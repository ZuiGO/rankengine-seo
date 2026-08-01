from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.scheduler import create_schedule, list_schedules, delete_schedule
from backend.db.mongo import get_db

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


class CreateScheduleRequest(BaseModel):
    url: str
    interval_hours: float = 24
    max_pages: int = 50
    kind: str = "crawl"


@router.post("")
async def create(req: CreateScheduleRequest):
    try:
        schedule = await create_schedule(req.url, req.interval_hours, req.max_pages, req.kind)
    except ValueError as e:
        raise HTTPException(400, str(e))
    schedule["id"] = schedule.pop("_id")
    return schedule


@router.get("")
async def list_all():
    schedules = await list_schedules()
    return {"schedules": schedules, "total": len(schedules)}


@router.get("/{schedule_id}/history")
async def get_history(schedule_id: str):
    db = get_db()
    schedule = await db.crawl_schedules.find_one({"_id": schedule_id})
    if not schedule:
        raise HTTPException(404, "Schedule not found")

    history = []
    for job_id in schedule.get("history", []):
        job = await db.analysis_jobs.find_one({"_id": job_id})
        if job:
            history.append({
                "job_id": job_id,
                "status": job.get("status"),
                "progress": job.get("progress"),
                "created_at": job.get("created_at"),
                "completed_at": job.get("completed_at"),
                "summary": job.get("summary"),
            })
    return {"schedule_id": schedule_id, "history": history}


@router.delete("/{schedule_id}")
async def remove(schedule_id: str):
    deleted = await delete_schedule(schedule_id)
    if not deleted:
        raise HTTPException(404, "Schedule not found")
    return {"status": "ok"}
