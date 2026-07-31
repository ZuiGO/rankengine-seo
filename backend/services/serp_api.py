from typing import Optional
import httpx

from backend.config import settings

SERP_BASE_URL = "https://serpapi.com/search"


async def search_keyword(keyword: str, domain: Optional[str] = None) -> dict:
    if not settings.serp_api_key:
        raise ValueError("SERP API key not configured")
    params = {
        "api_key": settings.serp_api_key,
        "q": keyword,
        "engine": "google",
        "google_domain": "google.com",
        "gl": "us",
        "hl": "en",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(SERP_BASE_URL, params=params, timeout=30)
        data = resp.json()
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
        raise ValueError("SERP API key not configured")

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
                resp = await client.get(SERP_BASE_URL, params=params, timeout=30)
                data = resp.json()
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
