from fastapi import APIRouter, HTTPException

from backend.db.mongo import get_db
from backend.services.keyword_tracking import check_keywords, get_tracking

router = APIRouter(prefix="/api/tracking", tags=["tracking"])


async def _ensure_job(job_id: str):
    db = get_db()
    if not await db.analysis_jobs.find_one({"_id": job_id}):
        raise HTTPException(404, "Job not found")


@router.get("/{job_id}")
async def tracking_history(job_id: str):
    await _ensure_job(job_id)
    return await get_tracking(job_id)


@router.post("/{job_id}/check")
async def run_tracking(job_id: str):
    await _ensure_job(job_id)
    return await check_keywords(job_id)
