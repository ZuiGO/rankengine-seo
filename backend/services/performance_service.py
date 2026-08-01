"""Core Web Vitals via the free Google PageSpeed Insights API (field + lab data).

Fetches mobile CWV for every page and desktop for the homepage, stores per-page results in
`page_performance`, and exposes a job-level summary consumed by site health scoring.
"""

import asyncio
from datetime import datetime

import httpx

from backend.config import settings
from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.service_errors import ServiceError

logger = get_logger("performance")

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
SERVICE = "pagespeed"
HINT = "Add a Google PageSpeed Insights API key to .env (pagespeed_api_key). Free tier: 100 queries/day by default, extendable to 25k/day."

CWV_WEIGHTS = {"lcp": 0.4, "inp": 0.4, "cls": 0.2}
GOOD = {"lcp": 2500, "inp": 200, "cls": 0.1}


def _metric_value(lh_audit: dict) -> float | None:
    if not lh_audit:
        return None
    return lh_audit.get("numericValue")


def _field_metrics(data: dict) -> dict:
    """CrUX field data from loadingExperience (ms; CLS is a ratio)."""
    exp = data.get("loadingExperience") or {}
    metrics = exp.get("metrics") or {}
    out = {}
    for key, m in metrics.items():
        percentiles = m.get("percentile") or {}
        value = percentiles.get("p75")
        if value is not None:
            out[key.lower()] = value / 1000.0 if key.lower() == "cls" else value
    return out


def _lab_metrics(lr: dict) -> dict:
    audits = lr.get("audits") or {}
    out = {
        "lcp": _metric_value(audits.get("largest-contentful-paint")),
        "inp": _metric_value(audits.get("interaction-to-next-paint")),
        "cls": _metric_value(audits.get("cumulative-layout-shift")),
        "fcp": _metric_value(audits.get("first-contentful-paint")),
        "ttfb": _metric_value(audits.get("server-response-time")),
        "tbt": _metric_value(audits.get("total-blocking-time")),
    }
    if out["inp"] is None:
        out["inp"] = _metric_value(audits.get("max-potential-fid"))
    return out


def _cwv_score(cwv: dict) -> int:
    values = []
    for key, weight in CWV_WEIGHTS.items():
        v = cwv.get(key)
        if v is None:
            continue
        good = GOOD[key]
        if v <= good:
            s = 100
        elif v <= good * 2:
            s = 50
        else:
            s = 0
        values.append((s, weight))
    if not values:
        return None
    total_w = sum(w for _, w in values)
    return round(sum(s * w for s, w in values) / total_w)


async def fetch_page_performance(url: str, strategy: str = "mobile") -> dict:
    if not settings.pagespeed_api_key:
        raise ServiceError(SERVICE, "PageSpeed Insights API key not configured", hint=HINT)
    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
        "key": settings.pagespeed_api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.get(PSI_URL, params=params)
    except Exception as e:
        raise ServiceError(SERVICE, f"PageSpeed request failed: {e}", hint=HINT) from e
    if resp.status_code >= 400:
        raise ServiceError(
            SERVICE,
            f"PageSpeed ({url}, {strategy}) failed (HTTP {resp.status_code})",
            status_code=resp.status_code,
            hint=HINT,
        )
    data = resp.json()
    field = _field_metrics(data)
    lab = _lab_metrics(data.get("lighthouseResult") or {})
    cwv = {k: (field.get(k) if field.get(k) is not None else lab.get(k)) for k in CWV_WEIGHTS}
    return {
        "url": url,
        "strategy": strategy,
        "cwv": cwv,
        "cwv_score": _cwv_score(cwv),
        "field": field,
        "lab": lab,
        "lighthouse_score": (data.get("lighthouseResult") or {}).get("categories", {}).get("performance", {}).get("score"),
        "fetched_at": datetime.utcnow(),
    }


async def fetch_performance(job_id: str, max_pages: int = 50) -> dict:
    """Mobile CWV for every page (cap max_pages), desktop for the homepage. Per-page error isolation."""
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 0, "html_mobile": 0}).to_list(length=None)
    if not pages:
        return {"status": "error", "message": "No pages for this job"}

    sem = asyncio.Semaphore(3)
    results = []
    errors = []

    async def fetch_one(page: dict):
        async with sem:
            url = page["url"]
            for strategy in (["mobile", "desktop"] if page.get("page_type") == "home" else ["mobile"]):
                try:
                    result = await fetch_page_performance(url, strategy)
                    results.append(result)
                    await db.page_performance.update_one(
                        {"job_id": job_id, "url": url, "strategy": strategy},
                        {"$set": {"job_id": job_id, **result}},
                        upsert=True,
                    )
                except Exception as e:
                    errors.append(f"{url} ({strategy}): {e}")

    await asyncio.gather(*[fetch_one(p) for p in pages[:max_pages]])

    summary = {
        "job_id": job_id,
        "checked": len(results),
        "pages": min(len(pages), max_pages),
        "failed": len(errors),
        "errors": errors[:10],
        "avg_cwv_score": round(sum(r["cwv_score"] for r in results if r.get("cwv_score") is not None) / max(1, sum(1 for r in results if r.get("cwv_score") is not None)), 1) if results else None,
    }
    await db.page_performance_summaries.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, **summary}},
        upsert=True,
    )
    return summary


async def get_performance_summary(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.page_performance_summaries.find_one({"job_id": job_id})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
