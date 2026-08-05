from fastapi import APIRouter, HTTPException

from backend.db.mongo import get_db
from backend.services.exec_summary import compute_exec_summary, get_exec_summary

router = APIRouter(prefix="/api/exec", tags=["exec-summary"])


@router.get("/{job_id}")
async def exec_summary(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id}, {"_id": 1})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    doc = await get_exec_summary(job_id)
    if not doc:
        raise HTTPException(status_code=404, detail="No summary for this job")
    return doc


@router.post("/{job_id}")
async def regenerate_exec_summary(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id}, {"_id": 1})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    doc = await compute_exec_summary(job_id)
    return {"status": "ok", **doc}