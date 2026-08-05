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
    try:
        from backend.services.spend_tracker import record_usage
        await record_usage("serp", "", f"search_{keyword[:40]}", requests=1)
    except Exception:
        pass
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


async def search_keyword_full(keyword: str) -> dict:
    """Google SERP with feature extraction (answer box, FAQ, reviews, images, AI overview).

    Used by competitor SERP-features gap: returns which search features rendered and the
    domains each feature attributed to, so we can diff target vs competitor presence.
    """
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
    try:
        from backend.services.spend_tracker import record_usage
        await record_usage("serp", "", f"search_{keyword[:40]}", requests=1)
    except Exception:
        pass

    organic = data.get("organic_results", [])
    features = {}

    def _domain_set(items: list | None) -> list[str]:
        out = []
        for it in items or []:
            link = it.get("link") or it.get("url") or ""
            host = link.split("//")[-1].split("/")[0]
            if host and host not in out:
                out.append(host)
        return out

    ab = data.get("answer_box") or {}
    if ab:
        features["answer_box"] = {
            "present": True,
            "title": ab.get("title") or "",
            "domains": _domain_set([ab] if ab.get("link") else []),
            "text": (ab.get("snippet") or "")[:300] if isinstance(ab, dict) else "",
        }

    rq = data.get("related_questions") or []
    if rq:
        features["faq"] = {
            "present": True,
            "count": len(rq),
            "questions": [q.get("question", "") for q in rq[:5]],
            "domains": _domain_set(rq),
        }

    kg = data.get("knowledge_graph") or {}
    if kg:
        kg_title = kg.get("title") or ""
        if not kg_title:
            kg_title = (kg.get("description") or "")[:80]
        features["knowledge_graph"] = {
            "present": True,
            "title": kg_title,
            "domains": _domain_set([kg] if kg.get("image_url") or kg.get("heading") else []),
        }

    ts = data.get("top_stories") or []
    if ts:
        features["top_stories"] = {"present": True, "count": len(ts), "domains": _domain_set(ts)}

    imgs = data.get("images_results") or []
    if imgs:
        features["images"] = {"present": True, "count": len(imgs), "domains": _domain_set(imgs)}

    reviews = []
    for r in organic:
        rating = r.get("rating") or r.get("reviews")
        if rating:
            reviews.append({"title": r.get("title", ""), "url": r.get("link", ""), "rating": rating})
    if reviews:
        features["reviews"] = {
            "present": True,
            "count": len(reviews),
            "domains": _domain_set(organic),
            "ratings": reviews[:5],
        }

    ai = data.get("ai_overview")
    if not isinstance(ai, dict):
        ai = data.get("ai_overviews") or {}
    if ai:
        ai_items = ai.get("items") or ([ai.get("snippet", "")] if ai.get("snippet") else [])
        features["ai_overview"] = {
            "present": True,
            "text": (ai.get("snippet") or ai.get("summary_text") or "")[:400] if isinstance(ai, dict) else "",
            "items": [str(x)[:200] for x in ai_items[:5]],
        }

    return {
        "keyword": keyword,
        "total_results": data.get("search_information", {}).get("total_results"),
        "organic_count": len(organic),
        "top_results": [
            {"position": r.get("position"), "title": r.get("title"), "url": r.get("link")}
            for r in organic[:10]
        ],
        "organic_domains": _domain_set(organic),
        "features": features,
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
    """Real corpus keywords (TF-IDF over crawled pages + extracted text)."""
    from backend.services.keyword_extractor import extract_keywords_from_content as _extract
    return await _extract(job_id, top_k=10)
