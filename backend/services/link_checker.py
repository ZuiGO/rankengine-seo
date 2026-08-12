import asyncio
from datetime import datetime
from urllib.parse import urlparse

import httpx

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.url_normalizer import normalize_url

logger = get_logger("link_checker")

CHECK_CONCURRENCY = 10
REQUEST_TIMEOUT = 7
USER_AGENT = "ZuiGO-Engine/1.0 link-checker (+https://zuigo.ai)"
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 0.5
RETRY_STATUS_CODES = frozenset({500, 502, 503, 504})


def classify_status(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ok"
    if status_code in (301, 302, 303, 307, 308):
        return "redirect"
    if status_code in (401, 403):
        return "blocked"
    if status_code >= 400:
        return "broken"
    return "unknown"


async def _check_one(client: httpx.AsyncClient, url: str) -> dict:
    result = {
        "url": url,
        "status": "unreachable",
        "status_code": None,
        "final_url": url,
        "error": None,
        "length_chars": len(url),
        "checked_at": datetime.utcnow(),
        "redirect_count": 0,
        "redirect_chain": [],
    }
    resp = None
    err = None
    for attempt in range(RETRY_ATTEMPTS):
        resp = None
        err = None
        try:
            resp = await client.head(url, follow_redirects=True, timeout=REQUEST_TIMEOUT)
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            err = e
        if resp is None or resp.status_code >= 400:
            try:
                resp = await client.get(url, follow_redirects=True, timeout=REQUEST_TIMEOUT)
                err = None
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                err = e
        if resp is None:
            await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
            continue
        if resp.status_code in RETRY_STATUS_CODES and attempt < RETRY_ATTEMPTS - 1:
            await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
            continue
        break
    if resp is None:
        result["error"] = str(err)[:200] if err else "Request failed"
        result["status"] = "unreachable"
        return result
    result["status_code"] = resp.status_code
    result["final_url"] = str(resp.url)
    result["status"] = classify_status(resp.status_code)
    result["content_length"] = resp.headers.get("content-length")
    result["redirect_count"] = len(resp.history) if resp.history else 0
    result["redirect_chain"] = [str(h.url) for h in resp.history] if resp.history else []
    return result


async def check_links(job_id: str) -> dict:
    """Check every unique internal link URL and store health in the link_health collection."""
    db = get_db()
    unique_urls = set()
    external_urls = set()
    page_map = {}
    cursor = db.page_links.find({"job_id": job_id})
    async for doc in cursor:
        page_url = doc["url"]
        for target in doc.get("internal_link_urls", []):
            norm = normalize_url(target)
            if not norm:
                continue
            unique_urls.add(norm)
            page_map.setdefault(norm, set()).add(page_url)
        for target in doc.get("external_link_urls", []):
            norm = normalize_url(target)
            if not norm:
                continue
            external_urls.add(norm)
            page_map.setdefault(norm, set()).add(page_url)

    # External targets join the check (capped) and are flagged `external: true`.
    MAX_EXTERNAL_CHECK = 300
    external_urls = sorted(external_urls)[:MAX_EXTERNAL_CHECK]
    unique_urls = unique_urls | set(external_urls)
    unique_urls = sorted(unique_urls)
    if not unique_urls:
        return {"checked": 0, "status": "no_links"}

    crawled_status: dict[str, int] = {}
    pages_cursor = db.pages.find({"job_id": job_id}, {"url": 1, "status_code": 1})
    async for p in pages_cursor:
        nurl = normalize_url(p.get("url") or "")
        if nurl and p.get("status_code"):
            crawled_status.setdefault(nurl, p["status_code"])

    results = []
    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)

    def _from_crawled(url: str) -> dict | None:
        status_code = crawled_status.get(url)
        if status_code is None:
            return None
        return {
            "url": url,
            "status": classify_status(status_code),
            "status_code": status_code,
            "final_url": url,
            "error": None,
            "length_chars": len(url),
            "checked_at": datetime.utcnow(),
            "redirect_count": 0,
            "redirect_chain": [],
            "from_crawled": True,
        }

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=REQUEST_TIMEOUT,
        limits=httpx.Limits(max_connections=CHECK_CONCURRENCY, max_keepalive_connections=CHECK_CONCURRENCY),
    ) as client:
        async def limited(url: str):
            cached = _from_crawled(url)
            if cached is not None:
                return cached
            async with semaphore:
                return await _check_one(client, url)

        tasks = [limited(u) for u in unique_urls]
        for i, outcome in enumerate(asyncio.as_completed(tasks)):
            if i % 20 == 0:
                from backend.services.job_cancel import check_cancelled
                await check_cancelled(job_id)
            try:
                res = await outcome
            except Exception as e:
                res = {"url": unique_urls[i], "status": "unreachable", "error": str(e)[:200],
                       "status_code": None, "final_url": unique_urls[i],
                       "length_chars": len(unique_urls[i]), "checked_at": datetime.utcnow(),
                       "redirect_count": 0, "redirect_chain": []}
            res["job_id"] = job_id
            res["pages"] = sorted(page_map.get(res["url"], []))
            res["external"] = res["url"] in external_urls
            results.append(res)

    await db.link_health.delete_many({"job_id": job_id})
    await db.link_health.insert_many(results)

    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    broken_link_count = counts.get("broken", 0)
    chain_lengths = [len(r.get("redirect_chain", [])) for r in results if r.get("redirect_count")]
    summary = {
        "checked": len(results),
        "total_links_scanned": len(results),
        "ok": counts.get("ok", 0),
        "redirect": counts.get("redirect", 0),
        "broken": counts.get("broken", 0),
        "blocked": counts.get("blocked", 0),
        "unreachable": counts.get("unreachable", 0),
        "broken_link_count": broken_link_count,
        "redirected_links": sum(1 for r in results if r.get("redirect_count")),
        "max_redirect_chain": max(chain_lengths) if chain_lengths else 0,
    }
    await db.link_health_summaries.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, **summary, "checked_at": datetime.utcnow()}},
        upsert=True,
    )
    logger.info("Link health check job=%s checked=%s broken=%s", job_id, len(results), broken_link_count)
    return summary


async def get_link_health(job_id: str, limit: int = 100, offset: int = 0) -> dict:
    db = get_db()
    summary = await db.link_health_summaries.find_one({"job_id": job_id})
    if not summary:
        summary = {"checked": 0, "ok": 0, "redirect": 0, "broken": 0,
                   "blocked": 0, "unreachable": 0, "status": "not_checked"}

    issues = []
    cursor = (
        db.link_health.find({"job_id": job_id, "status": {"$ne": "ok"}})
        .skip(offset).limit(limit).sort("length_chars", -1)
    )
    rows = await cursor.to_list(length=limit)
    for r in rows:
        r["id"] = str(r.pop("_id"))
        issues.append(r)

    length_stats = {"avg": 0, "max": 0, "min": 0, "longest": []}
    length_pipeline = [
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": None, "avg": {"$avg": "$length_chars"}, "max": {"$max": "$length_chars"}, "min": {"$min": "$length_chars"}}},
    ]
    async for row in db.link_health.aggregate(length_pipeline):
        length_stats["avg"] = round(row["avg"], 1)
        length_stats["max"] = row["max"]
        length_stats["min"] = row["min"]

    long_cursor = db.link_health.find({"job_id": job_id}).sort("length_chars", -1).limit(5)
    length_stats["longest"] = [
        {"url": r["url"], "length": r["length_chars"]} for r in await long_cursor.to_list(length=5)
    ]

    return {"summary": {k: v for k, v in summary.items() if k != "_id"}, "issues": issues, "length_stats": length_stats}
