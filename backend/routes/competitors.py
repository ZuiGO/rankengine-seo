"""Competitor gap analysis endpoint (DataForSEO-backed, graceful 402)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db.mongo import get_db

router = APIRouter(prefix="/api/competitors", tags=["competitors"])


class GapRequest(BaseModel):
    job_id: str
    competitors: list[str] = []


@router.post("/gap")
async def competitor_gap_analysis(req: GapRequest):
    if not req.competitors:
        raise HTTPException(400, "Provide at least one competitor domain")

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": req.job_id})
    if not job:
        raise HTTPException(404, "Job not found")
    target = (job.get("url", "").split("//")[-1]).split("/")[0]
    if not target:
        raise HTTPException(400, "Job has no URL")

    from backend.services.competitor_gap import competitor_gap

    try:
        result = await competitor_gap(target, [c.strip() for c in req.competitors if c.strip()])
    except Exception as e:
        from backend.services.service_errors import ServiceError
        if isinstance(e, ServiceError):
            return {"error": str(e), "hint": e.hint, "source": "dataforseo"}
        return {"error": str(e), "source": "dataforseo"}
    return result
