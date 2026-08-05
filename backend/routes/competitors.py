"""Free-tools competitor gap analysis endpoints.

Replaces the DataForSEO-backed implementation (endpoints not on plan -> 404).
Analysis runs on the queue; results persist in `competitor_gap_analyses`
keyed by (target_job_id, competitor).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime

from backend.db.mongo import get_db

router = APIRouter(prefix="/api/competitors", tags=["competitors"])


class GapRequest(BaseModel):
    job_id: str
    competitors: list[str] = []


@router.post("/{target_job_id}/analyze")
async def competitor_analyze(target_job_id: str, req: GapRequest):
    if not req.competitors:
        raise HTTPException(400, "Provide at least one competitor domain")

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": target_job_id})
    if not job:
        raise HTTPException(404, "Job not found")

    competitors = [c.strip() for c in req.competitors if c.strip()]

    for comp in competitors:
        existing = await db.competitor_gap_analyses.find_one(
            {"target_job_id": target_job_id, "competitor": comp}
        )
        if existing and existing.get("status") == "running":
            continue
        await db.competitor_gap_analyses.update_one(
            {"target_job_id": target_job_id, "competitor": comp},
            {
                "$set": {
                    "competitor": comp,
                    "target_job_id": target_job_id,
                    "status": "queued",
                    "updated_at": datetime.utcnow(),
                },
                "$setOnInsert": {"created_at": datetime.utcnow()},
            },
            upsert=True,
        )

    from backend.services.queue import run_or_fallback
    from backend.routes.analysis import run_competitor_pipeline

    await run_or_fallback(
        "competitor_audit",
        run_competitor_pipeline,
        target_job_id,
        competitors,
    )
    return {"status": "queued", "job_id": target_job_id, "competitors": competitors}


@router.get("/{target_job_id}")
async def competitor_list(target_job_id: str):
    db = get_db()
    rows = await db.competitor_gap_analyses.find(
        {"target_job_id": target_job_id}
    ).sort("competitor", 1).to_list(length=100)
    cleaned = []
    for row in rows:
        row.pop("_id", None)
        cleaned.append(row)
    return {"results": cleaned, "total": len(cleaned)}


@router.get("/{target_job_id}/{competitor}")
async def competitor_detail(target_job_id: str, competitor: str):
    db = get_db()
    row = await db.competitor_gap_analyses.find_one(
        {"target_job_id": target_job_id, "competitor": competitor}
    )
    if not row:
        raise HTTPException(404, "Competitor analysis not found")
    row.pop("_id", None)
    return row


@router.post("/gap")
async def competitor_gap_analysis(req: GapRequest):
    return await competitor_analyze(req.job_id, req)