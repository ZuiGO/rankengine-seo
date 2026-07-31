from fastapi import APIRouter

from backend.db.mongo import get_db
from backend.services.backlinks import get_backlinks

router = APIRouter(prefix="/api/links", tags=["links"])


@router.get("/{job_id}")
async def get_link_summary(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}

    summary = job.get("summary", {})
    return {
        "total_links": summary.get("total_links", 0),
        "total_internal": summary.get("total_internal_links", 0),
        "total_external": summary.get("total_external_links", 0),
    }


@router.get("/{job_id}/backlinks")
async def list_backlinks(job_id: str):
    return await get_backlinks(job_id, limit=1000)
