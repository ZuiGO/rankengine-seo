from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, HTTPException

from backend.db.mongo import get_db
from backend.config import settings

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _tail_file(path: str, n: int) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        chunk = min(size, 64 * 1024)
        f.seek(size - chunk)
        data = f.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        return lines[-n:]


@router.get("/app")
async def get_app_logs(limit: int = 100, level: str | None = None):
    if limit > 1000:
        limit = 1000
    log_path = str(Path(settings.log_dir) / "app.log")
    lines = _tail_file(log_path, limit)
    if level:
        level = level.upper()
        lines = [l for l in lines if f" | {level} " in l]
    return {"lines": lines, "total": len(lines), "path": log_path}


@router.get("/audit")
async def get_audit_logs(limit: int = 100, event: str | None = None, job_id: str | None = None):
    if limit > 1000:
        limit = 1000
    db = get_db()
    query = {}
    if event:
        query["event"] = event
    if job_id:
        query["job_id"] = job_id
    cursor = db.audit_logs.find(query).sort("timestamp", -1).limit(limit)
    entries = await cursor.to_list(length=limit)
    for e in entries:
        e["id"] = str(e.pop("_id"))
        if isinstance(e.get("timestamp"), datetime):
            e["timestamp"] = e["timestamp"].isoformat()
    return {"entries": entries, "total": len(entries)}


@router.get("/alerts")
async def get_alerts(hours: int = 24):
    db = get_db()
    since = datetime.utcnow() - timedelta(hours=hours)

    failed = []
    cursor = db.audit_logs.find({
        "event": "analysis_failed",
        "timestamp": {"$gte": since},
    }).sort("timestamp", -1)
    async for e in cursor:
        job = await db.analysis_jobs.find_one({"_id": e.get("job_id")})
        failed.append({
            "job_id": e.get("job_id"),
            "url": job.get("url", "") if job else "",
            "scheduled": job.get("scheduled", False) if job else False,
            "error": (e.get("details") or {}).get("error", ""),
            "timestamp": e["timestamp"].isoformat(),
        })

    broken = []
    cursor = db.crawl_schedules.find({"enabled": True})
    async for s in cursor:
        history = s.get("history", [])
        if history:
            last_job = await db.analysis_jobs.find_one({"_id": history[-1]})
            if last_job and last_job.get("status") == "failed":
                broken.append({
                    "schedule_id": s["_id"],
                    "domain": s.get("domain"),
                    "last_error": last_job.get("error_message", ""),
                    "last_run_at": (s.get("last_run_at") or datetime.utcnow()).isoformat(),
                })

    return {
        "failed_analyses": failed,
        "broken_schedules": broken,
        "period_hours": hours,
    }
