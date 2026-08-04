"""Longitudinal trends across repeated analyses of the same domain.

Each scheduled/manual re-crawl creates a new job; this endpoint aggregates the
per-job summary + site health + CWV + keyword tracking into a time series so
the UI can show progress over time.
"""

from datetime import datetime
import re

from fastapi import APIRouter, HTTPException

from backend.db.mongo import get_db

router = APIRouter(prefix="/api/trends", tags=["trends"])


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_deltas(prev: dict, cur: dict) -> dict:
    """Period-over-period diffs for numeric series; None when a value is absent."""
    deltas = {}
    for key in ("health_score", "broken_link_count", "total_pages", "avg_cwv_score", "keyword_ranked"):
        cur_v = _num(cur.get(key))
        prev_v = _num(prev.get(key)) if prev else None
        deltas[key] = round(cur_v - prev_v, 2) if (cur_v is not None and prev_v is not None) else None
    return deltas


def _domain_of(url: str) -> str:
    if not url:
        return ""
    return url.split("//")[-1].split("/")[0].lower()


@router.get("/{domain}")
async def domain_trends(domain: str, limit: int = 20):
    if limit > 100:
        limit = 100
    db = get_db()
    jobs = await db.analysis_jobs.find(
        {"url": {"$regex": re.escape(domain), "$options": "i"}},
        {"_id": 1, "url": 1, "status": 1, "completed_at": 1, "summary": 1},
    ).sort("completed_at", 1).to_list(length=limit)

    points = []
    for job in jobs:
        if job.get("status") != "completed":
            continue
        summary = job.get("summary") or {}
        health = await db.site_health.find_one({"job_id": job["_id"]})
        perf = await db.page_performance_summaries.find_one({"job_id": job["_id"]})
        kt = await db.keyword_tracking_summaries.find_one({"job_id": job["_id"]})
        kt_summary = kt or {}
        try:
            from backend.config import settings
            serp_configured = bool(getattr(settings, "serp_api_key", ""))
        except Exception:
            serp_configured = False
        points.append({
            "job_id": job["_id"],
            "url": job.get("url", ""),
            "completed_at": (job.get("completed_at") or datetime.utcnow()).isoformat(),
            "health_grade": summary.get("health_grade"),
            "health_score": (health or {}).get("score"),
            "avg_cwv_score": (perf or {}).get("avg_cwv_score"),
            "cwv_pages": summary.get("cwv_pages"),
            "broken_links": summary.get("broken_links"),
            "broken_link_count": summary.get("broken_link_count"),
            "total_links_scanned": summary.get("total_links_scanned"),
            "total_pages": summary.get("total_pages"),
            "keyword_ranked": kt_summary.get("ranked"),
            "keyword_integration": kt_summary.get("integration") or ("configured" if serp_configured else "unconfigured"),
            "deltas": compute_deltas(points[-1] if points else None, {
                "health_score": (health or {}).get("score"),
                "broken_link_count": summary.get("broken_link_count"),
                "total_pages": summary.get("total_pages"),
                "avg_cwv_score": (perf or {}).get("avg_cwv_score"),
                "keyword_ranked": kt_summary.get("ranked"),
            }),
        })

    if not points:
        raise HTTPException(404, f"No completed analyses found for domain '{domain}'")

    return {"domain": domain, "points": points}
