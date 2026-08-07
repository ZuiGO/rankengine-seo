"""SE Ranking Data API provider: domain overview, ranked keywords, backlinks.

Auth is `Authorization: Token <key>`. The key is read from the MongoDB
`app_settings` doc keyed `se_ranking` (set via the Settings page) with
`settings.se_ranking_api_key` (.env) as fallback, mirroring GSC config.

This is the sole paid external provider: keyword / overview / backlink /
competitor data, with local crawl-data fallbacks in external_insights.py.
"""

import asyncio
import time
from datetime import datetime, timedelta

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
    data = await _get("backlinks/summary", {"target": target, "mode": "domain"}, region_params=False)
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


def _rows(data: dict | list, key: str) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get(key) or []
        return rows if isinstance(rows, list) else []
    return []


def _days_ago(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")


async def domain_overview_history(domain: str, months: int = 12) -> list[dict]:
    """Monthly organic traffic / keyword history -> trend rows (newest first)."""
    data = await _get("domain/overview/history", {
        "domain": domain,
        "with_subdomains": 1,
        "type": "organic",
    })
    await _record_usage("domain/overview/history")
    rows = data if isinstance(data, list) else (data.get("results") or data.get("items") or [])
    trend = []
    for r in rows:
        year, month = r.get("year"), r.get("month")
        if not year or not month:
            continue
        trend.append({
            "month": f"{year:04d}-{month:02d}",
            "traffic_sum": r.get("traffic_sum"),
            "keywords_count": r.get("keywords_count"),
            "price_sum": r.get("price_sum"),
        })
    trend.sort(key=lambda t: t["month"], reverse=True)
    return trend[:months]


async def domain_competitors(domain: str, limit: int = 10) -> list[dict]:
    """Top organic competitors with keyword overlap and traffic estimates."""
    data = await _get("domain/competitors", {
        "domain": domain,
        "type": "organic",
        "limit": limit,
    })
    await _record_usage("domain/competitors")
    return [{
        "domain": c.get("domain") or "",
        "common_keywords": c.get("common_keywords"),
        "domain_relevance": c.get("domain_relevance"),
        "total_keywords": c.get("total_keywords"),
        "missing_keywords": c.get("missing_keywords"),
        "traffic_sum": c.get("traffic_sum"),
        "price_sum": c.get("price_sum"),
    } for c in _rows(data, "competitors")][:limit]


async def keyword_gap(primary: str, compare: str, limit: int = 50) -> list[dict]:
    """Keywords the primary domain ranks for that the compare domain does not (diff=1)."""
    data = await _get("domain/keywords/comparison", {
        "domain": primary,
        "compare": compare,
        "type": "organic",
        "diff": 1,
        "limit": limit,
        "order_field": "volume",
        "order_type": "desc",
    })
    await _record_usage("domain/keywords/comparison")
    return [{
        "keyword": k.get("keyword") or "",
        "volume": k.get("volume"),
        "cpc": k.get("cpc"),
        "difficulty": k.get("difficulty"),
        "position": k.get("position"),
        "url": k.get("url"),
    } for k in _rows(data, "keywords")][:limit]


async def backlink_list(target: str, limit: int = 50) -> list[dict]:
    """Backlink source pages -> renderer shape (one per referring domain, best rank first)."""
    data = await _get("backlinks/all", {
        "target": target,
        "mode": "domain",
        "limit": limit,
        "per_domain": 1,
        "order_by": "domain_inlink_rank",
        "order_type": "desc",
    }, region_params=False)
    await _record_usage("backlinks/all")
    return [{
        "source_url": b.get("url_from") or "",
        "url_to": b.get("url_to") or "",
        "title": b.get("title") or "",
        "anchor": b.get("anchor") or "",
        "nofollow": b.get("nofollow"),
        "page_from_rank": b.get("inlink_rank"),
        "domain_inlink_rank": b.get("domain_inlink_rank"),
        "first_seen": b.get("first_seen"),
        "last_visited": b.get("last_visited"),
    } for b in _rows(data, "backlinks")][:limit]


async def backlink_anchors(target: str, limit: int = 25) -> list[dict]:
    """Anchor-text distribution for inbound links (most-used first)."""
    data = await _get("backlinks/anchors", {
        "target": target,
        "mode": "domain",
        "limit": limit,
        "order_by": "backlinks",
    }, region_params=False)
    await _record_usage("backlinks/anchors")
    return [{
        "anchor": a.get("anchor") or "",
        "backlinks": a.get("backlinks"),
        "refdomains": a.get("refdomains"),
        "dofollow_backlinks": a.get("dofollow_backlinks"),
        "nofollow_backlinks": a.get("nofollow_backlinks"),
        "first_seen": a.get("first_seen"),
    } for a in _rows(data, "anchors")][:limit]


async def backlink_refdomains(target: str, limit: int = 25) -> list[dict]:
    """Referring domains sorted by authority."""
    data = await _get("backlinks/refdomains", {
        "target": target,
        "mode": "domain",
        "limit": limit,
        "order_by": "domain_inlink_rank",
        "order_type": "desc",
    }, region_params=False)
    await _record_usage("backlinks/refdomains")
    return [{
        "refdomain": r.get("refdomain") or "",
        "backlinks": r.get("backlinks"),
        "dofollow_backlinks": r.get("dofollow_backlinks"),
        "first_seen": r.get("first_seen"),
        "domain_inlink_rank": r.get("domain_inlink_rank"),
    } for r in _rows(data, "refdomains")][:limit]


async def backlink_top_pages(target: str, limit: int = 10) -> list[dict]:
    """Target pages with the most backlinks."""
    data = await _get("backlinks/indexed-pages", {
        "target": target,
        "mode": "domain",
        "limit": limit,
        "order_by": "backlinks",
    }, region_params=False)
    await _record_usage("backlinks/indexed-pages")
    return [{
        "url": p.get("url") or "",
        "backlinks": p.get("backlinks"),
        "refdomains": p.get("refdomains"),
        "dofollow_backlinks": p.get("dofollow_backlinks"),
        "first_seen": p.get("first_seen"),
    } for p in _rows(data, "pages")][:limit]


async def backlink_authority(target: str) -> dict | None:
    """Page + domain authority (InLink Rank / Domain InLink Rank) for the target."""
    data = await _get("backlinks/authority", {"target": target}, region_params=False)
    await _record_usage("backlinks/authority")
    pages = _rows(data, "pages")
    if not pages:
        raise ServiceError(SERVICE, "SE Ranking backlinks authority returned no data")
    first = pages[0]
    return {
        "url": first.get("url") or target,
        "page_rank": first.get("inlink_rank"),
        "domain_rank": first.get("domain_inlink_rank"),
        "source": "se-ranking",
    }


async def authority_history(target: str, months: int = 6) -> list[dict]:
    """Domain Authority (Domain InLink Rank) history, monthly, newest first."""
    data = await _get(
        "backlinks/authority/domain/history",
        {
            "target": target,
            "granularity": "by_month",
            "date_from": _days_ago(31 * months),
        },
        region_params=False,
    )
    await _record_usage("backlinks/authority/domain/history")
    ranks = []
    for r in _rows(data, "ranks"):
        date = r.get("date")
        if not date:
            continue
        ranks.append({"date": str(date)[:7], "domain_rank": r.get("domain_inlink_rank")})
    ranks.sort(key=lambda t: t["date"], reverse=True)
    return ranks


async def backlink_new_lost(target: str, days: int = 30, limit: int = 50) -> list[dict]:
    """Recently added and lost backlinks (both types, newest activity first)."""
    data = await _get("backlinks/history", {
        "target": target,
        "mode": "domain",
        "date_from": _days_ago(days),
        "limit": limit,
        "order_by": "new_lost_date",
        "order_type": "desc",
    }, region_params=False)
    await _record_usage("backlinks/history")
    return [{
        "date": b.get("new_lost_date"),
        "type": b.get("new_lost_type"),
        "url_from": b.get("url_from") or "",
        "url_to": b.get("url_to") or "",
        "anchor": b.get("anchor") or "",
        "reason_lost": b.get("reason_lost"),
        "domain_inlink_rank": b.get("domain_inlink_rank"),
    } for b in _rows(data, "new_lost_backlinks")][:limit]


async def backlink_new_lost_counts(target: str, days: int = 30) -> list[dict]:
    """Daily new/lost backlink counts -> trend rows (newest first)."""
    data = await _get("backlinks/history/count", {
        "target": target,
        "mode": "domain",
        "date_from": _days_ago(days),
    }, region_params=False)
    await _record_usage("backlinks/history/count")
    counts = []
    for r in _rows(data, "new_lost_backlinks_count"):
        date = r.get("date")
        if not date:
            continue
        counts.append({"date": date, "new": r.get("new"), "lost": r.get("lost")})
    counts.sort(key=lambda t: t["date"], reverse=True)
    return counts