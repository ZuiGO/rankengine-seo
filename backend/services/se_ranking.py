"""SE Ranking Data API provider: domain overview, ranked keywords, backlinks.

Auth is `Authorization: Token <key>`. The key is read from the MongoDB
`app_settings` doc keyed `se_ranking` (set via the Settings page) with
`settings.se_ranking_api_key` (.env) as fallback, mirroring GSC config.

Used as a provider in the insights chain (dataforseo.py) so SEO providers
with an SE Ranking key still get keyword / overview / backlink data when
DataForSEO is not configured, out of credits, or the endpoint is not on
plan (404).
"""

import asyncio
import time

import httpx

from backend.config import settings
from backend.services.service_errors import ServiceError

SE_BASE_URL = "https://api.seranking.com/v1"
SERVICE = "se_ranking"

HINT = "Add your SE Ranking API key in Settings (app_settings['se_ranking']), or set se_ranking_api_key in .env."

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MIN_INTERVAL_SECONDS = 0.2
REGION = "us"
LIMIT = 20

_rate_lock = asyncio.Lock()
_last_request_at = 0.0


def _body_message(body: dict | list) -> str:
    b = body if isinstance(body, dict) else {}
    err = b.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("detail") or err.get("description")
        if msg:
            return str(msg)
    if isinstance(err, str) and err:
        return err
    msg = b.get("message") or b.get("detail") or b.get("description")
    if isinstance(msg, str) and msg:
        return msg
    return ""


def _hint_for_status(status_code: int, body_text: str) -> str:
    lowered = body_text.lower()
    if status_code in (401, 403) or "api key" in lowered or "no token" in lowered:
        return HINT
    if "license" in lowered or "expired" in lowered:
        return "SE Ranking subscription looks expired or restricted. Renew it, or use the local crawl fallback."
    if "insufficient funds" in lowered or "no credits" in lowered or "payment" in lowered:
        return "SE Ranking account has no credits left. Top up SE Ranking credits, or use the local crawl fallback."
    return None


def _raise_for_http(resp: httpx.Response, endpoint: str) -> None:
    if resp.status_code < 400:
        return
    body: dict | list = {}
    try:
        body = resp.json()
    except Exception:
        body = {}
    message = _body_message(body)
    detail = f": {message}" if message else ""
    raise ServiceError(
        SERVICE,
        f"SE Ranking {endpoint} failed (HTTP {resp.status_code}){detail}",
        status_code=resp.status_code,
        hint=_hint_for_status(resp.status_code, str(body)),
    )


async def get_se_ranking_config() -> dict:
    """SE Ranking API key + region: MongoDB app_settings first, .env as fallback."""
    try:
        from backend.db.mongo import get_db
        db = get_db()
        doc = await db.app_settings.find_one({"key": "se_ranking"}) or {}
    except Exception:
        doc = {}
    return {
        "api_key": doc.get("api_key") or settings.se_ranking_api_key,
        "region": doc.get("region") or REGION,
    }


async def _api_key() -> str:
    cfg = await get_se_ranking_config()
    return (cfg.get("api_key") or "").strip()


async def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 5.0)
        except ValueError:
            pass
    return 1.0 * (attempt + 1)


async def _throttled_request(client: httpx.AsyncClient, endpoint: str, params: dict, key: str):
    """Rate-limited GET: one request per ~MIN_INTERVAL_SECONDS."""
    global _last_request_at
    async with _rate_lock:
        now = time.monotonic()
        elapsed = now - _last_request_at
        if elapsed < MIN_INTERVAL_SECONDS:
            await asyncio.sleep(MIN_INTERVAL_SECONDS - elapsed)
        _last_request_at = time.monotonic()
    return await client.get(
        f"{SE_BASE_URL}/{endpoint}",
        params=params,
        headers={"Authorization": f"Token {key}"},
        timeout=90,
    )


async def _get(endpoint: str, params: dict, region_params: bool = True) -> dict:
    key = await _api_key()
    if not key:
        raise ServiceError(SERVICE, "SE Ranking API key not configured", hint=HINT)
    cfg = await get_se_ranking_config()
    query = {**params}
    if region_params and "source" not in query:
        query["source"] = (cfg.get("region") or REGION).strip() or REGION
    last_error: ServiceError | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            async with httpx.AsyncClient() as client:
                resp = await _throttled_request(client, endpoint, query, key)
        except Exception as e:
            last_error = ServiceError(SERVICE, f"SE Ranking {endpoint} request failed: {e}", hint=HINT)
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            raise last_error from e
        if resp.status_code in RETRYABLE_STATUSES:
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(await _retry_delay(resp, attempt))
                continue
            _raise_for_http(resp, endpoint)
        if resp.status_code >= 400:
            _raise_for_http(resp, endpoint)
        try:
            return resp.json()
        except Exception as e:
            raise ServiceError(SERVICE, f"SE Ranking {endpoint}: invalid JSON response", hint=HINT) from e
    raise last_error or ServiceError(SERVICE, f"SE Ranking {endpoint}: retries exhausted", hint=HINT)


async def _record_usage(endpoint: str) -> None:
    try:
        from backend.services.spend_tracker import record_usage
        await record_usage(SERVICE, "", endpoint[:40], requests=1)
    except Exception:
        pass


def _normalize_keyword(item: dict) -> dict:
    return {
        "keyword": item.get("keyword") or "",
        "keyword_data": {
            "keyword_info": {
                "search_volume": item.get("volume"),
                "cpc": item.get("cpc"),
            },
            "keyword_properties": {
                "keyword_difficulty": item.get("difficulty"),
            },
        },
    }


async def domain_overview(domain: str) -> dict:
    """Regional organic/paid overview -> renderer shape."""
    data = await _get("domain/overview/db", {"domain": domain, "with_subdomains": 1})
    await _record_usage("domain/overview/db")
    if not isinstance(data, dict) or not data.get("organic"):
        raise ServiceError(SERVICE, "SE Ranking domain overview returned no organic data")
    organic = data["organic"]
    adv = data.get("adv") or {}
    return {
        "domain": domain,
        "estimated_organic_traffic": organic.get("traffic_sum"),
        "organic_keywords_count": organic.get("keywords_count"),
        "paid_keywords_count": adv.get("keywords_count"),
        "sample_n": None,
        "source": "se-ranking",
    }


async def domain_keywords(domain: str, limit: int = LIMIT) -> list[dict]:
    """Ranked organic keywords for a domain -> renderer keyword shape."""
    data = await _get("domain/keywords", {
        "domain": domain,
        "with_subdomains": 1,
        "type": "organic",
        "limit": limit,
        "order_field": "volume",
        "order_type": "desc",
    })
    await _record_usage("domain/keywords")
    items = data if isinstance(data, list) else (data.get("items") or data.get("results") or [])
    return [_normalize_keyword(item) for item in items]


async def ranked_keywords(domain: str, limit: int = LIMIT) -> list[dict]:
    """Keyword positions from SE Ranking (organic) in the SERP-rankings renderer shape."""
    data = await _get("domain/keywords", {
        "domain": domain,
        "with_subdomains": 1,
        "type": "organic",
        "limit": limit,
        "order_field": "position",
        "order_type": "asc",
    })
    await _record_usage("domain/keywords")
    items = data if isinstance(data, list) else (data.get("items") or data.get("results") or [])
    rankings = []
    for item in items:
        pos = item.get("position")
        if not pos or pos <= 0:
            continue
        rankings.append({
            "keyword": item.get("keyword") or "",
            "rank": pos,
            "total_results": item.get("total_sites"),
            "top_results": [{
                "position": pos,
                "title": item.get("url") or "",
                "url": item.get("url") or "",
            }],
        })
    return rankings


async def backlink_summary(target: str) -> dict:
    """Backlink summary for the target domain -> renderer shape (counts preserved)."""
    data = await _get("backlinks/summary", {"target": target, "mode": "domain"})
    await _record_usage("backlinks/summary")
    rows = data.get("summary") if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise ServiceError(SERVICE, "SE Ranking backlinks summary returned no data")
    row = rows[0]
    return {
        "target": row.get("target", target),
        "backlinks": row.get("backlinks"),
        "referring_domains": row.get("refdomains"),
        "referring_pages": row.get("pages_with_backlinks"),
        "referring_ips": row.get("ips"),
        "referring_subnets": row.get("subnets"),
        "dofollow_backlinks": row.get("dofollow_backlinks"),
        "nofollow_backlinks": row.get("nofollow_backlinks"),
        "domain_rank": row.get("domain_inlink_rank"),
        "rank": row.get("domain_inlink_rank"),
        "page_rank": row.get("inlink_rank"),
        "edu_backlinks": row.get("edu_backlinks"),
        "gov_backlinks": row.get("gov_backlinks"),
        "anchors": row.get("anchors"),
        "top_anchors": row.get("top_anchors_by_backlinks"),
        "top_pages": row.get("top_pages_by_backlinks"),
        "top_tlds": row.get("top_tlds"),
        "top_countries": row.get("top_countries"),
        "source": "se-ranking",
    }