"""Keyword-position tracking: re-check target keyword ranks over time and correlate moves with
approved SEO changes so the tool learns which action types actually move the needle."""

from datetime import datetime

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.serp_api import search_keyword, extract_keywords_from_content

logger = get_logger("tracking")

DEFAULT_MAX_KEYWORDS = 5


async def _approved_action_types(db, job_id: str, page_url: str) -> list[str]:
    actions = await db.action_items.find({
        "job_id": job_id,
        "status": "approved",
        "page_url": page_url,
    }).to_list(length=100)
    return sorted({a.get("content_type", "") for a in actions if a.get("content_type")})


async def check_keywords(job_id: str, max_keywords: int = DEFAULT_MAX_KEYWORDS) -> dict:
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"status": "error", "message": "Job not found"}

    domain = job.get("url", "").split("//")[-1].split("/")[0]
    keywords = await extract_keywords_from_content(job_id)
    keywords = [k for k in keywords if k][:max_keywords]
    if not keywords:
        return {"status": "error", "message": "No keywords available for this job"}

    results = []
    errors = []
    for kw in keywords:
        try:
            data = await search_keyword(kw, domain)
            rank = data.get("rank")
            page_url = None
            if rank is None:
                page_url = data.get("top_results", [{}])[0].get("url") if data.get("top_results") else None
            results.append({
                "keyword": kw,
                "rank": rank,
                "total_results": data.get("total_results"),
                "organic_count": data.get("organic_count"),
                "top_url": data.get("top_results", [{}])[0].get("url") if data.get("top_results") else None,
                "page_url": page_url,
                "approved_action_types": await _approved_action_types(db, job_id, page_url) if page_url else [],
            })
        except Exception as e:
            errors.append(f"{kw}: {e}")
            logger.warning("Keyword check failed job=%s kw=%s: %s", job_id, kw, e)

    doc = {
        "job_id": job_id,
        "domain": domain,
        "checked_at": datetime.utcnow(),
        "results": results,
        "failed": errors,
    }
    await db.keyword_tracking.insert_one(doc)

    previous = await db.keyword_tracking.find({"job_id": job_id}).sort("checked_at", -1).skip(1).limit(1).to_list(length=1)
    prev_map = {r["keyword"]: r.get("rank") for r in (previous[0].get("results") if previous else [])}
    for r in results:
        old = prev_map.get(r["keyword"])
        r["previous_rank"] = old
        r["delta"] = (old - r["rank"]) if (old is not None and r.get("rank") is not None) else None

    summary = {
        "job_id": job_id,
        "domain": domain,
        "last_checked_at": doc["checked_at"],
        "keyword_count": len(results),
        "moved_up": sum(1 for r in results if (r.get("delta") or 0) > 0),
        "moved_down": sum(1 for r in results if (r.get("delta") or 0) < 0),
        "ranked": sum(1 for r in results if r.get("rank") is not None),
    }
    await db.keyword_tracking_summaries.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    return {"status": "ok", **summary, "results": results, "failed": errors}


async def get_tracking(job_id: str, limit: int = 10) -> dict:
    db = get_db()
    cursor = db.keyword_tracking.find({"job_id": job_id}).sort("checked_at", -1).limit(limit)
    history = await cursor.to_list(length=limit)
    for h in history:
        h["id"] = str(h.pop("_id"))
    summary = await db.keyword_tracking_summaries.find_one({"job_id": job_id})
    if summary:
        summary["id"] = str(summary.pop("_id"))
    latest = history[0] if history else None
    return {
        "job_id": job_id,
        "summary": summary,
        "history": history,
        "latest": latest,
    }
