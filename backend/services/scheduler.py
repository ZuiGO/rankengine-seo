import asyncio
import uuid
from datetime import datetime, timedelta

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.routes.analysis import run_analysis_pipeline

logger = get_logger("scheduler")

POLL_INTERVAL_SECONDS = 30
MIN_INTERVAL_HOURS = 0.1


async def create_schedule(url: str, interval_hours: float, max_pages: int = 50, kind: str = "crawl") -> dict:
    db = get_db()
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    if interval_hours < MIN_INTERVAL_HOURS:
        raise ValueError(f"interval_hours must be >= {MIN_INTERVAL_HOURS}")
    if kind not in ("crawl", "keyword_check"):
        raise ValueError("kind must be 'crawl' or 'keyword_check'")

    domain = url.split("//")[-1].split("/")[0]
    schedule_id = str(uuid.uuid4())
    now = datetime.utcnow()
    doc = {
        "_id": schedule_id,
        "url": url,
        "domain": domain,
        "kind": kind,
        "interval_hours": interval_hours,
        "max_pages": max_pages,
        "enabled": True,
        "created_at": now,
        "last_run_at": None,
        "next_run_at": now + timedelta(hours=interval_hours),
        "history": [],
    }
    await db.crawl_schedules.insert_one(doc)
    logger.info("Schedule created id=%s url=%s kind=%s interval=%sh", schedule_id, url, kind, interval_hours)
    return doc


async def list_schedules() -> list[dict]:
    db = get_db()
    cursor = db.crawl_schedules.find({}).sort("created_at", -1)
    schedules = await cursor.to_list(length=100)
    for s in schedules:
        s["id"] = s.pop("_id")
    return schedules


async def delete_schedule(schedule_id: str) -> bool:
    db = get_db()
    result = await db.crawl_schedules.delete_one({"_id": schedule_id})
    if result.deleted_count:
        logger.info("Schedule deleted id=%s", schedule_id)
    return result.deleted_count > 0


async def _run_due_crawls():
    db = get_db()
    now = datetime.utcnow()
    cursor = db.crawl_schedules.find({
        "enabled": True,
        "next_run_at": {"$lte": now},
    })
    due = await cursor.to_list(length=50)
    for schedule in due:
        if schedule.get("kind") == "keyword_check":
            await _run_keyword_check(schedule, now)
            continue
        job_id = str(uuid.uuid4())
        await db.analysis_jobs.insert_one({
            "_id": job_id,
            "url": schedule["url"],
            "status": "queued",
            "progress": 0,
            "progress_message": "Queued (scheduled)...",
            "created_at": now,
            "completed_at": None,
            "error_message": None,
            "summary": None,
            "scheduled": True,
            "schedule_id": schedule["_id"],
        })
        await db.crawl_schedules.update_one(
            {"_id": schedule["_id"]},
            {"$set": {
                "last_run_at": now,
                "next_run_at": now + timedelta(hours=schedule["interval_hours"]),
            }, "$push": {"history": job_id}},
        )
        from backend.services.queue import run_or_fallback
        await run_or_fallback("analyze_job", run_analysis_pipeline, job_id, schedule["url"], schedule["max_pages"])
        logger.info("Scheduled crawl triggered id=%s job=%s url=%s", schedule["_id"], job_id, schedule["url"])


async def _run_keyword_check(schedule: dict, now: datetime):
    db = get_db()
    try:
        from backend.services.queue import run_or_fallback
        from backend.services.keyword_tracking import check_keywords
        latest = await db.analysis_jobs.find_one(
            {"url": schedule["url"], "status": "completed"},
            sort=[("completed_at", -1)],
        )
        if not latest:
            logger.warning("Keyword check skipped: no completed job for %s", schedule["url"])
            return
        await run_or_fallback("keyword_check", check_keywords, str(latest["_id"]))
        logger.info("Scheduled keyword check enqueued id=%s job=%s", schedule["_id"], latest["_id"])
    except Exception as e:
        logger.error("Scheduled keyword check failed id=%s: %s", schedule["_id"], e)
    await db.crawl_schedules.update_one(
        {"_id": schedule["_id"]},
        {"$set": {
            "last_run_at": now,
            "next_run_at": now + timedelta(hours=schedule["interval_hours"]),
        }},
    )


async def scheduler_loop():
    logger.info("Scheduler loop started (poll=%ss)", POLL_INTERVAL_SECONDS)
    while True:
        try:
            await _run_due_crawls()
        except Exception as e:
            logger.error("Scheduler tick error: %s", e)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
