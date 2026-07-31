from fastapi import APIRouter

from backend.db.mongo import get_db

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
    db = get_db()
    cursor = db.backlinks.find({"job_id": job_id})
    backlinks = await cursor.to_list(length=1000)
    for b in backlinks:
        b["id"] = str(b.pop("_id"))
    return {"backlinks": backlinks, "total": len(backlinks)}
