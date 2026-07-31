from typing import Optional
import httpx

from backend.config import settings
from backend.services.service_errors import ServiceError

SERP_BASE_URL = "https://serpapi.com/search"

SERVICE = "serp"

HINT = "Add a valid SERP API key to .env (serp_api_key) or top up your SERP API credits."


def _raise_api_error(data: dict, query: str) -> None:
    err = data.get("error")
    if not err:
        return
    raise ServiceError(SERVICE, f"SERP API ({query}): {err}", hint=HINT)


async def search_keyword(keyword: str, domain: Optional[str] = None) -> dict:
    if not settings.serp_api_key:
        raise ServiceError(SERVICE, "SERP API key not configured", hint=HINT)
    params = {
        "api_key": settings.serp_api_key,
        "q": keyword,
        "engine": "google",
        "google_domain": "google.com",
        "gl": "us",
        "hl": "en",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(SERP_BASE_URL, params=params, timeout=30)
    except Exception as e:
        raise ServiceError(SERVICE, f"SERP API request failed: {e}", hint=HINT) from e
    if resp.status_code >= 400:
        raise ServiceError(
            SERVICE,
            f"SERP API ({keyword}) failed (HTTP {resp.status_code})",
            status_code=resp.status_code,
            hint=HINT,
        )
    data = resp.json()
    _raise_api_error(data, keyword)
    organic = data.get("organic_results", [])
    if domain:
        rank = next(
            (i + 1 for i, r in enumerate(organic) if domain in r.get("link", "")),
            None,
        )
        return {
            "keyword": keyword,
            "rank": rank,
            "total_results": data.get("search_information", {}).get("total_results"),
            "organic_count": len(organic),
            "top_results": [
                {"position": r.get("position"), "title": r.get("title"), "url": r.get("link")}
                for r in organic[:5]
            ],
        }
    return {
        "keyword": keyword,
        "total_results": data.get("search_information", {}).get("total_results"),
        "organic_count": len(organic),
        "top_results": [
            {"position": r.get("position"), "title": r.get("title"), "url": r.get("link")}
            for r in organic[:5]
        ],
    }


async def bulk_keyword_search(keywords: list[str], domain: str) -> list[dict]:
    results = []
    for kw in keywords:
        try:
            result = await search_keyword(kw, domain)
            results.append(result)
        except Exception as e:
            results.append({"keyword": kw, "error": str(e)})
    return results


async def serp_link_search(domain: str, max_pages: int = 3) -> list[dict]:
    """Harvest backlink source pages via Google `link:` / `inanchor:` operators."""
    if not settings.serp_api_key:
        raise ServiceError(SERVICE, "SERP API key not configured", hint=HINT)

    sources = []
    seen = set()
    queries = [f"link:{domain}", f"inanchor:{domain}"]

    async with httpx.AsyncClient() as client:
        for query in queries:
            for page in range(max_pages):
                params = {
                    "api_key": settings.serp_api_key,
                    "q": query,
                    "engine": "google",
                    "google_domain": "google.com",
                    "gl": "us",
                    "hl": "en",
                    "start": page * 10,
                }
                try:
                    resp = await client.get(SERP_BASE_URL, params=params, timeout=30)
                except Exception as e:
                    raise ServiceError(SERVICE, f"SERP API request failed: {e}", hint=HINT) from e
                if resp.status_code >= 400:
                    raise ServiceError(
                        SERVICE,
                        f"SERP API ({query}) failed (HTTP {resp.status_code})",
                        status_code=resp.status_code,
                        hint=HINT,
                    )
                data = resp.json()
                _raise_api_error(data, query)
                organic = data.get("organic_results", [])
                if not organic:
                    break
                for r in organic:
                    url = r.get("link")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    sources.append({
                        "source_url": url,
                        "source_domain": url.split("//")[-1].split("/")[0],
                        "anchor": r.get("title", ""),
                        "backlinks_count": None,
                        "page_from_rank": r.get("position"),
                        "query": query,
                    })

    return sources


async def run_serp_rankings(domain: str, job_id: str | None, max_keywords: int = 5) -> tuple[list[dict], list[str]]:
    """Check SERP ranking for a handful of job keywords. Returns (results, per-keyword errors)."""
    keywords = []
    if job_id:
        keywords = await extract_keywords_from_content(job_id)
    keywords = keywords[:max_keywords]
    results = []
    errors = []
    for kw in keywords:
        try:
            results.append(await search_keyword(kw, domain))
        except Exception as e:
            errors.append(f"{kw}: {e}")
    return results, errors


async def extract_keywords_from_content(job_id: str) -> list[str]:
    from backend.db.mongo import get_db
    db = get_db()
    pipeline = [
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$content_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    keywords = []
    async for row in db.content_items.aggregate(pipeline):
        keywords.append(row["_id"])
    pages_pipeline = [
        {"$match": {"job_id": job_id}},
        {"$project": {"_id": 0, "title": 1}},
        {"$match": {"title": {"$ne": ""}}},
        {"$limit": 3},
    ]
    async for row in db.pages.aggregate(pages_pipeline):
        words = row.get("title", "").split()[:3]
        keywords.extend(words)
    return list(set(kw.lower().rstrip("s") for kw in keywords if kw))[:10]
