import asyncio
import base64
from datetime import datetime
from typing import Optional
import httpx

from backend.config import settings
from backend.services.service_errors import ServiceError

BASE_URL = "https://api.dataforseo.com"

SERVICE = "dataforseo"

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 1.0

HINTS = {
    401: "Check your DataForSEO login and password in .env (dataforseo_login / dataforseo_password).",
    402: "DataForSEO subscription has no credits left. Top up credits, or use SE Ranking / the built-in SERP / local crawl fallbacks.",
    403: "DataForSEO access is restricted for this account.",
    404: "This DataForSEO endpoint is not enabled on your subscription plan. SE Ranking / local crawl data is shown instead.",
}

_BLACKLISTED_ENDPOINTS: set[str] = set()


def _auth_header() -> dict:
    if not settings.dataforseo_login or not settings.dataforseo_password:
        raise ServiceError(
            SERVICE,
            "DataForSEO credentials not configured in .env",
            hint="Add dataforseo_login and dataforseo_password to .env",
        )
    token = base64.b64encode(
        f"{settings.dataforseo_login}:{settings.dataforseo_password}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


def _hint_for_code(status_code: int) -> str | None:
    return HINTS.get(status_code)


def _raise_for_http(resp: httpx.Response, endpoint: str) -> None:
    if resp.status_code < 400:
        return
    if resp.status_code in (403, 404):
        _BLACKLISTED_ENDPOINTS.add(endpoint)
    message = f"DataForSEO {endpoint} failed (HTTP {resp.status_code})"
    try:
        body = resp.json()
        if body.get("status_message"):
            message += f": {body['status_message']}"
    except Exception:
        pass
    raise ServiceError(
        SERVICE,
        message,
        status_code=resp.status_code,
        hint=_hint_for_code(resp.status_code),
    )


def _raise_for_task(data: dict, endpoint: str) -> None:
    tasks = data.get("tasks") or []
    if not tasks:
        raise ServiceError(SERVICE, f"DataForSEO {endpoint}: empty response")
    task = tasks[0]
    if task.get("result"):
        return
    err = task.get("error") or {}
    code = err.get("code") or task.get("status_code")
    msg = err.get("message") or task.get("status_message") or "Unknown task error"
    lowered = f"{code} {msg}".lower()
    hint = None
    if code in (40200, 40202, 40203, 40204) or "fund" in lowered or "payment" in lowered:
        hint = _hint_for_code(402)
    elif code == 40101 or "login" in lowered:
        hint = _hint_for_code(401)
    raise ServiceError(SERVICE, f"DataForSEO {endpoint}: {msg} (code {code})", status_code=code, hint=hint)


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 5.0)
        except ValueError:
            pass
    return RETRY_BASE_SECONDS * (attempt + 1)


async def _post(endpoint: str, payload: list) -> dict:
    if endpoint in _BLACKLISTED_ENDPOINTS:
        raise ServiceError(
            SERVICE,
            f"DataForSEO {endpoint} not enabled on this plan",
            status_code=404,
            hint=_hint_for_code(404),
        )
    last_error: ServiceError | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{BASE_URL}/v3/{endpoint}/live",
                    headers=_auth_header(),
                    json=payload,
                    timeout=90,
                )
        except ServiceError:
            raise
        except Exception as e:
            last_error = ServiceError(SERVICE, f"DataForSEO {endpoint}: {e}")
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BASE_SECONDS * (attempt + 1))
                continue
            raise last_error
        if resp.status_code in RETRYABLE_STATUSES:
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(_retry_delay(resp, attempt))
                continue
        _raise_for_http(resp, endpoint)
        data = resp.json()
        _raise_for_task(data, endpoint)
        return data
    raise last_error or ServiceError(SERVICE, f"DataForSEO {endpoint}: retries exhausted")


def _normalize_keyword_item(item: dict) -> dict:
    kd = item.get("keyword_data") or {}
    ki = kd.get("keyword_info") or {}
    kp = kd.get("keyword_properties") or {}
    return {
        "keyword": item.get("keyword") or kd.get("keyword") or "",
        "keyword_data": {
            "keyword_info": {
                "search_volume": ki.get("search_volume", item.get("search_volume")),
                "cpc": ki.get("cpc", item.get("cpc")),
            },
            "keyword_properties": {
                "keyword_difficulty": kp.get("keyword_difficulty"),
            },
        },
    }


async def domain_keywords(domain: str, limit: int = 20) -> list[dict]:
    data = await _post("keywords_data/google/keywords_for_site", [{
        "target": domain,
        "limit": limit,
        "location_name": "United States",
        "language_name": "English",
    }])
    result = data["tasks"][0]["result"][0]
    items = result if isinstance(result, list) else result.get("items", [])
    return [_normalize_keyword_item(it) for it in items]


async def backlink_summary(target: str) -> Optional[dict]:
    data = await _post("backlinks/summary", [{"target": target}])
    return data["tasks"][0]["result"][0]


async def backlink_referring_pages(target: str, limit: int = 100) -> list[dict]:
    data = await _post("backlinks/referring_pages", [{"target": target, "limit": limit}])
    return data["tasks"][0]["result"][0].get("items", [])


async def backlink_referring_domains(target: str, limit: int = 100) -> list[dict]:
    data = await _post("backlinks/referring_domains", [{"target": target, "limit": limit}])
    return data["tasks"][0]["result"][0].get("items", [])


async def onpage_summary(url: str) -> Optional[dict]:
    data = await _post("on_page/summary", [{"url": url}])
    return data["tasks"][0]["result"][0]


async def domain_overview(domain: str) -> Optional[dict]:
    data = await _post("domain_analytics/google/overview", [{"target": domain}])
    return data["tasks"][0]["result"][0]


async def domain_overview_labs(domain: str, limit: int = 100) -> Optional[dict]:
    """DataForSEO Labs ranked-keywords synthesis for the domain overview.

    Not a full domain_analytics overview (that endpoint is plan-gated), so the
    traffic figure is the summed organic clicks of the top `limit` ranked
    keywords; `sample_n` flags that the sum is a lower bound.
    """
    data = await _post("dataforseo_labs/google/ranked_keywords", [{
        "target": domain,
        "location_name": "United States",
        "language_name": "English",
        "limit": limit,
        "include_subdomains": True,
    }])
    res = (data["tasks"][0].get("result") or [{}])[0]
    items = res.get("items") or []
    if not items:
        return None
    total = res.get("total_count") or len(items)
    organic_clicks = sum(
        ((it.get("metrics") or {}).get("organic") or {}).get("clicks", 0) for it in items
    )
    return {
        "domain": domain,
        "estimated_organic_traffic": round(organic_clicks),
        "organic_keywords_count": total,
        "paid_keywords_count": None,
        "sample_n": len(items),
        "source": "dataforseo-labs",
    }


async def rank_tracking_keywords(domain: str, keywords: list[str]) -> list[dict]:
    data = await _post("rank_tracking/keywords", [{
        "domain": domain,
        "keywords": keywords,
        "location_name": "United States",
        "language_name": "English",
    }])
    return data["tasks"][0]["result"][0].get("items", [])


async def fetch_all_insights(domain: str, job_id: str | None = None) -> dict:
    """Fetch external SEO insights with per-section structured errors and local fallbacks."""
    from backend.services.local_insights import local_keywords, local_onpage, local_backlinks
    from backend.services import se_ranking

    insights = {"domain": domain}

    try:
        kws = await domain_keywords(domain)
        if not kws:
            raise ServiceError(SERVICE, "no keyword data returned for this domain")
        insights["keywords"] = kws
        insights["keywords_source"] = "dataforseo"
        insights["keywords_error"] = None
    except Exception as e:
        insights["keywords_error"] = str(e)
        try:
            insights["keywords"] = await se_ranking.domain_keywords(domain)
            if not insights["keywords"]:
                raise ServiceError(SERVICE, "no keyword data returned (se-ranking)")
            insights["keywords_source"] = "se-ranking"
            insights["keywords_error"] = None
        except Exception as e2:
            insights["keywords_error"] = f"{e} | {e2}"
            insights["keywords"] = await local_keywords(job_id) if job_id else []
            insights["keywords_source"] = "local" if insights["keywords"] else "none"

    try:
        insights["backlinks"] = await backlink_summary(domain)
        insights["backlinks_source"] = "dataforseo"
        insights["backlinks_error"] = None
    except Exception as e:
        insights["backlinks_error"] = str(e)
        try:
            insights["backlinks"] = await se_ranking.backlink_summary(domain)
            if not insights["backlinks"]:
                raise ServiceError(SERVICE, "no backlink data returned (se-ranking)")
            insights["backlinks_source"] = "se-ranking"
            insights["backlinks_error"] = None
        except Exception as e2:
            insights["backlinks_error"] = f"{e} | {e2}"
            insights["backlinks"] = await local_backlinks(job_id) if job_id else None
            insights["backlinks_source"] = "local" if insights["backlinks"] else "none"

    try:
        insights["overview"] = await domain_overview(domain)
        insights["overview_source"] = "dataforseo"
        insights["overview_error"] = None
    except Exception as first_e:
        try:
            labs = await domain_overview_labs(domain)
            if not labs:
                raise ServiceError(SERVICE, "no overview data returned (labs)")
            insights["overview"] = labs
            insights["overview_source"] = "dataforseo-labs"
            insights["overview_error"] = None
        except Exception as e:
            insights["overview_error"] = f"{first_e} | {e}"
            try:
                insights["overview"] = await se_ranking.domain_overview(domain)
                if not insights["overview"]:
                    raise ServiceError(SERVICE, "no overview data returned (se-ranking)")
                insights["overview_source"] = "se-ranking"
                insights["overview_error"] = None
            except Exception as e2:
                insights["overview_error"] = f"{insights['overview_error']} | {e2}"
                from backend.services.local_insights import local_overview
                insights["overview"] = await local_overview(job_id) if job_id else None
                insights["overview_source"] = "local" if insights["overview"] else "none"

    try:
        insights["onpage"] = await onpage_summary(f"https://{domain}")
        insights["onpage_source"] = "dataforseo"
        insights["onpage_error"] = None
    except Exception as e:
        insights["onpage_error"] = str(e)
        insights["onpage"] = await local_onpage(job_id) if job_id else None
        insights["onpage_source"] = "local" if insights["onpage"] else "none"

    try:
        from backend.services.gsc import fetch_gsc
        gsc_data = await fetch_gsc(domain)
        if gsc_data:
            insights["gsc"] = gsc_data
            insights["gsc_error"] = None
            ov = dict(insights.get("overview") or {})
            ov.update({
                "estimated_organic_traffic": gsc_data.get("clicks"),
                "organic_keywords_count": len(gsc_data.get("queries") or []),
                "source": "gsc",
            })
            insights["overview"] = ov
            insights["overview_source"] = "gsc"
            insights["overview_error"] = None
        else:
            insights["gsc"] = None
            insights["gsc_error"] = None
    except Exception as e:
        insights["gsc"] = None
        insights["gsc_error"] = str(e)

    try:
        from backend.services.serp_api import run_serp_rankings
        insights["serp_rankings"], failed = await run_serp_rankings(domain, job_id)
        insights["serp_source"] = "serp"
        insights["serp_error"] = None
        if failed:
            insights["serp_error"] = f"{len(failed)} keyword check(s) failed: " + "; ".join(failed[:2])
    except Exception as e:
        insights["serp_rankings"] = []
        insights["serp_source"] = "none"
        insights["serp_error"] = str(e)
    if not insights["serp_rankings"]:
        try:
            from backend.services.se_ranking import ranked_keywords
            rankings = await ranked_keywords(domain)
            if rankings:
                insights["serp_rankings"] = rankings
                insights["serp_source"] = "se-ranking"
                insights["serp_error"] = None
        except Exception:
            pass

    return insights


async def merge_gsc_into_insights(db, job_id: str, domain: str, gsc_data: dict, cache_version: int) -> bool:
    """Merge a fresh GSC snapshot into the stored insights cache without refetching other sections."""
    cached = await db.seo_insights_cache.find_one({"job_id": job_id})
    if not cached:
        return False
    data = dict(cached.get("data") or {})
    data["gsc"] = gsc_data
    data["gsc_error"] = None
    ov = dict(data.get("overview") or {})
    ov.update({
        "estimated_organic_traffic": gsc_data.get("clicks"),
        "organic_keywords_count": len(gsc_data.get("queries") or []),
        "source": "gsc",
    })
    data["overview"] = ov
    data["overview_source"] = "gsc"
    data["overview_error"] = None
    await db.seo_insights_cache.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, "data": data, "fetched_at": datetime.utcnow(), "v": cache_version}},
        upsert=True,
    )
    return True
