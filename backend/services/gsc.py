"""Google Search Console integration: OAuth2 connect + Search Analytics data.

One-time setup (user): create a Google Cloud OAuth client (Desktop app),
enable the Search Console API, and put GSC_CLIENT_ID / GSC_CLIENT_SECRET in
.env (redirect URI defaults to http://localhost:8001/api/gsc/callback).
The analyzed domain must be a verified property in Search Console.
"""

from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

import httpx

from backend.config import settings
from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("gsc")

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
SEARCH_ANALYTICS_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"


def configured() -> bool:
    return bool(settings.gsc_client_id and settings.gsc_client_secret)


def build_auth_url(job_id: str) -> str:
    params = {
        "client_id": settings.gsc_client_id,
        "redirect_uri": settings.gsc_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": job_id,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _domain_from_url(url: str) -> str:
    if "//" in url:
        return url.split("//")[-1].split("/")[0]
    return url


def _match_property(sites: list[str], domain: str) -> str | None:
    d = (domain or "").lower()
    if not d:
        return None
    exact = f"sc-domain:{d}"
    if exact in sites:
        return exact
    normalized = {s.rstrip("/"): s for s in sites}
    for pref in ("https://www.", "https://", "http://www.", "http://"):
        if pref + d in normalized:
            return normalized[pref + d]
    return None


async def _get_credentials(domain: str) -> dict | None:
    db = get_db()
    return await db.gsc_credentials.find_one({"domain": domain})


async def _save_credentials(domain: str, creds: dict):
    db = get_db()
    await db.gsc_credentials.update_one(
        {"domain": domain},
        {"$set": {**creds, "domain": domain, "connected_at": creds.get("connected_at", datetime.utcnow())}},
        upsert=True,
    )


async def _token_post(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(TOKEN_URL, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"GSC OAuth failed (HTTP {resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def exchange_code(code: str, job_id: str) -> dict:
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise RuntimeError("Job not found")
    domain = _domain_from_url(job.get("url", ""))
    data = await _token_post({
        "code": code,
        "client_id": settings.gsc_client_id,
        "client_secret": settings.gsc_client_secret,
        "redirect_uri": settings.gsc_redirect_uri,
        "grant_type": "authorization_code",
    })
    if not data.get("refresh_token"):
        raise RuntimeError("OAuth response missing refresh_token (grant_type must be 'offline')")
    await _save_credentials(domain, {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_at": datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600)),
        "scope": data.get("scope", SCOPE),
    })
    return {"domain": domain, "ok": True}


async def _valid_access_token(domain: str) -> str | None:
    creds = await _get_credentials(domain)
    if not creds:
        return None
    expires = creds.get("expires_at")
    if expires and expires > datetime.utcnow() + timedelta(minutes=5):
        return creds.get("access_token")
    try:
        data = await _token_post({
            "client_id": settings.gsc_client_id,
            "client_secret": settings.gsc_client_secret,
            "refresh_token": creds.get("refresh_token"),
            "grant_type": "refresh_token",
        })
        updated = {**creds,
                   "access_token": data.get("access_token"),
                   "expires_at": datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))}
        await _save_credentials(domain, updated)
        return updated.get("access_token")
    except Exception as e:
        logger.warning("GSC token refresh failed domain=%s: %s", domain, e)
        return None


async def list_sites(domain: str) -> list[str]:
    token = await _valid_access_token(domain)
    if not token:
        raise RuntimeError("GSC not connected for this domain")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(SITES_URL, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 400:
        raise RuntimeError(f"GSC sites list failed (HTTP {resp.status_code}): {resp.text[:200]}")
    return [s.get("siteUrl") for s in resp.json().get("siteEntry", [])]


async def _analytics_query(site: str, domain: str, dimensions: list[str], days: int = 28) -> list[dict]:
    token = await _valid_access_token(domain)
    if not token:
        raise RuntimeError("GSC not connected for this domain")
    start = (datetime.utcnow() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    end = datetime.utcnow().strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            SEARCH_ANALYTICS_URL.format(site=quote(site, safe="")),
            headers={"Authorization": f"Bearer {token}"},
            json={"startDate": start, "endDate": end, "dimensions": dimensions, "rowLimit": 25},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"GSC search analytics failed (HTTP {resp.status_code}): {resp.text[:200]}")
    return resp.json().get("rows") or []


def _summarize(rows: list[dict]) -> dict:
    clicks = sum(r.get("clicks", 0) for r in rows)
    impressions = sum(r.get("impressions", 0) for r in rows)
    weighted_position = sum((r.get("position") or 0) * (r.get("impressions") or 0) for r in rows)
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 4) if impressions else 0.0,
        "position": round(weighted_position / impressions, 1) if impressions else None,
    }


async def fetch_gsc(domain: str, days: int = 28) -> dict | None:
    creds = await _get_credentials(domain)
    if not creds:
        return None
    sites = await list_sites(domain)
    site = _match_property(sites, domain)
    if not site:
        raise RuntimeError(
            f"Domain {domain} is not a verified Search Console property. "
            "Verify it in Search Console first (found: " + (", ".join(sites[:5]) or "none") + ")."
        )
    q_rows = await _analytics_query(site, domain, ["query"], days)
    p_rows = await _analytics_query(site, domain, ["page"], days)
    totals = _summarize(q_rows)
    await _save_credentials(domain, {**creds, "property": site})
    return {
        "property": site,
        "days": days,
        "fetched_at": datetime.utcnow(),
        **totals,
        "queries": [
            {"query": r["keys"][0], "clicks": r.get("clicks", 0),
             "impressions": r.get("impressions", 0),
             "ctr": round(r.get("clicks", 0) / r.get("impressions", 1), 4) if r.get("impressions") else 0,
             "position": r.get("position")}
            for r in q_rows
        ],
        "pages": [
            {"page": r["keys"][0], "clicks": r.get("clicks", 0),
             "impressions": r.get("impressions", 0),
             "ctr": round(r.get("clicks", 0) / r.get("impressions", 1), 4) if r.get("impressions") else 0,
             "position": r.get("position")}
            for r in p_rows
        ],
    }


async def gsc_status(domain: str) -> dict:
    creds = await _get_credentials(domain)
    if not creds:
        return {"connected": False, "configured": configured(), "domain": domain, "property": None}
    return {
        "connected": True,
        "configured": configured(),
        "domain": domain,
        "property": creds.get("property"),
        "token_expires_at": creds.get("expires_at"),
        "connected_at": creds.get("connected_at"),
    }


async def disconnect(domain: str) -> None:
    db = get_db()
    await db.gsc_credentials.delete_many({"domain": domain})
