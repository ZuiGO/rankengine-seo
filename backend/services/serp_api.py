from datetime import datetime, timedelta
from typing import Optional
import asyncio
import httpx

from backend.config import settings
from backend.services.service_errors import ServiceError

SERP_BASE_URL = "https://serpapi.com/search"

SERVICE = "serp"

HINT = "Add a valid SERP API key to .env (serp_api_key) or top up your SERP API credits."

SERP_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
SERP_MAX_ATTEMPTS = 3
SERP_CACHE_TTL_SECONDS = 24 * 3600

def _raise_api_error(data: dict, query: str) -> None:
    err = data.get("error")
    if not err:
        return
    raise ServiceError(SERVICE, f"SERP API ({query}): {err}", hint=HINT)


async def _get_with_retry(client: httpx.AsyncClient, params: dict, query: str) -> httpx.Response:
    last_error: ServiceError | None = None
    for attempt in range(SERP_MAX_ATTEMPTS):
        try:
            resp = await client.get(SERP_BASE_URL, params=params, timeout=30)
        except Exception as e:
            last_error = ServiceError(SERVICE, f"SERP API request failed: {e}", hint=HINT)
            if attempt < SERP_MAX_ATTEMPTS - 1:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            raise last_error from e
        if resp.status_code in SERP_RETRYABLE_STATUSES:
            if attempt < SERP_MAX_ATTEMPTS - 1:
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = min(float(retry_after), 5.0) if retry_after else 1.0 * (attempt + 1)
                except ValueError:
                    delay = 1.0 * (attempt + 1)
                await asyncio.sleep(delay)
                continue
            raise ServiceError(
                SERVICE,
                f"SERP API ({query}) failed (HTTP {resp.status_code})",
                status_code=resp.status_code,
                hint=HINT,
            )
        return resp
    raise last_error or ServiceError(SERVICE, f"SERP API ({query}): retries exhausted", hint=HINT)


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
            resp = await _get_with_retry(client, params, keyword)
    except ServiceError:
        raise
    except Exception as e:
        raise ServiceError(SERVICE, f"SERP API request failed: {e}", hint=HINT) from e
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
            resp = await _get_with_retry(client, params, keyword)
    except ServiceError:
        raise
    except Exception as e:
        raise ServiceError(SERVICE, f"SERP API request failed: {e}", hint=HINT) from e
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


async def _serp_cache_get(db, cache_key: str) -> Optional[dict]:
    try:
        row = await db.serp_cache.find_one({"cache_key": cache_key})
    except Exception:
        return None
    if not row:
        return None
    fetched = row.get("fetched_at")
    if not fetched:
        return None
    if isinstance(fetched, dict) and "$date" in fetched:
        fetched = fetched["$date"]
    if isinstance(fetched, datetime):
        if datetime.utcnow() - fetched > timedelta(seconds=SERP_CACHE_TTL_SECONDS):
            return None
    return row.get("data")


async def _serp_cache_put(db, cache_key: str, data: dict) -> None:
    try:
        await db.serp_cache.update_one(
            {"cache_key": cache_key},
            {"$set": {"cache_key": cache_key, "data": data, "fetched_at": datetime.utcnow()}},
            upsert=True,
        )
    except Exception:
        pass


async def run_serp_rankings(domain: str, job_id: str | None, max_keywords: int = 10) -> tuple[list[dict], list[str]]:
    """Check SERP ranking for a handful of job keywords. Returns (results, per-keyword errors).

    Per-keyword results are cached for 24h (with the rank stamped at crawl time)
    so a transient SERP 429 doesn't blank the section on every insights refresh.
    """
    keywords = []
    if job_id:
        try:
            from backend.services.keyword_engine import get_smart_keywords
            keywords = await get_smart_keywords(job_id, max_total=max_keywords, use_llm=False)
        except Exception:
            keywords = await extract_keywords_from_content(job_id)
    keywords = keywords[:max_keywords]
    results = []
    errors = []
    db = None
    for kw in keywords:
        cache_key = f"{domain}|{kw}".lower()
        if db is None:
            try:
                from backend.db.mongo import get_db
                db = get_db()
            except Exception:
                db = False
        use_cache = db is not None and db is not False
        if use_cache:
            cached = await _serp_cache_get(db, cache_key)
            if cached is not None:
                results.append(cached)
                continue
        try:
            result = await search_keyword(kw, domain)
            if use_cache:
                await _serp_cache_put(db, cache_key, result)
            results.append(result)
        except Exception as e:
            errors.append(f"{kw}: {e}")
    return results, errors


async def extract_keywords_from_content(job_id: str) -> list[str]:
    """Real corpus keywords (TF-IDF over crawled pages + extracted text)."""
    from backend.services.keyword_extractor import extract_keywords_from_content as _extract
    return await _extract(job_id, top_k=10)
