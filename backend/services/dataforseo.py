import base64
from typing import Optional
import httpx

from backend.config import settings
from backend.services.service_errors import ServiceError

BASE_URL = "https://api.dataforseo.com"

SERVICE = "dataforseo"

HINTS = {
    401: "Check your DataForSEO login and password in .env (dataforseo_login / dataforseo_password).",
    402: "DataForSEO subscription has no credits left. Top up credits, or use the built-in SERP / local crawl fallbacks.",
    403: "DataForSEO access is restricted for this account.",
}


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
    if code in (40202, 40203, 40204) or "fund" in lowered or "payment" in lowered:
        hint = _hint_for_code(402)
    elif code == 40101 or "login" in lowered:
        hint = _hint_for_code(401)
    raise ServiceError(SERVICE, f"DataForSEO {endpoint}: {msg} (code {code})", status_code=code, hint=hint)


async def _post(endpoint: str, payload: list) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/v3/{endpoint}/live",
                headers=_auth_header(),
                json=payload,
                timeout=30,
            )
    except ServiceError:
        raise
    except Exception as e:
        raise ServiceError(SERVICE, f"DataForSEO {endpoint}: {e}") from e
    _raise_for_http(resp, endpoint)
    data = resp.json()
    _raise_for_task(data, endpoint)
    return data


async def domain_keywords(domain: str, limit: int = 20) -> list[dict]:
    data = await _post("keywords_data/google/keywords_for_site", [{
        "domain": domain,
        "limit": limit,
        "location_name": "United States",
        "language_name": "English",
    }])
    return data["tasks"][0]["result"][0].get("items", [])


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
    data = await _post("domain_analytics/google/overview", [{"domain": domain}])
    return data["tasks"][0]["result"][0]


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

    insights = {"domain": domain}

    try:
        insights["keywords"] = await domain_keywords(domain)
        insights["keywords_source"] = "dataforseo"
        insights["keywords_error"] = None
    except Exception as e:
        insights["keywords_error"] = str(e)
        insights["keywords"] = await local_keywords(job_id) if job_id else []
        insights["keywords_source"] = "local" if insights["keywords"] else "none"

    try:
        insights["backlinks"] = await backlink_summary(domain)
        insights["backlinks_source"] = "dataforseo"
        insights["backlinks_error"] = None
    except Exception as e:
        insights["backlinks_error"] = str(e)
        insights["backlinks"] = await local_backlinks(job_id) if job_id else None
        insights["backlinks_source"] = "local" if insights["backlinks"] else "none"

    try:
        insights["overview"] = await domain_overview(domain)
        insights["overview_source"] = "dataforseo"
        insights["overview_error"] = None
    except Exception as e:
        insights["overview_error"] = str(e)
        insights["overview"] = None
        insights["overview_source"] = "none"

    try:
        insights["onpage"] = await onpage_summary(f"https://{domain}")
        insights["onpage_source"] = "dataforseo"
        insights["onpage_error"] = None
    except Exception as e:
        insights["onpage_error"] = str(e)
        insights["onpage"] = await local_onpage(job_id) if job_id else None
        insights["onpage_source"] = "local" if insights["onpage"] else "none"

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

    return insights
