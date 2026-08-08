"""Free-tools competitor gap analysis endpoints.

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


def _normalize_domain(value: str) -> str:
    d = value.strip().lower()
    if "//" in d:
        d = d.split("//")[-1]
    d = d.split("/")[0].split("?")[0].split("#")[0]
    while d.startswith("www."):
        d = d[4:]
    return d


async def _migrate_stale_key(db, target_job_id: str, norm: str, raw_forms: list[str]):
    """Rename old rows stored under the raw input string to the normalized key."""
    for stale in raw_forms:
        if not stale or stale == norm:
            continue
        old = await db.competitor_gap_analyses.find_one(
            {"target_job_id": target_job_id, "competitor": stale}
        )
        if not old:
            continue
        old_id = old.get("_id")
        # never clobber a live row under the normalized key
        normalized = await db.competitor_gap_analyses.find_one(
            {"target_job_id": target_job_id, "competitor": norm}
        )
        if not normalized:
            old["competitor"] = norm
            old.pop("_id", None)
            await db.competitor_gap_analyses.insert_one(old)
        await db.competitor_gap_analyses.delete_one({"_id": old_id})


@router.post("/{target_job_id}/analyze")
async def competitor_analyze(target_job_id: str, req: GapRequest):
    if not req.competitors:
        raise HTTPException(400, "Provide at least one competitor domain")

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": target_job_id})
    if not job:
        raise HTTPException(404, "Job not found")

    competitors = []
    seen = set()
    raw_forms = []
    for c in req.competitors:
        norm = _normalize_domain(c)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        competitors.append(norm)
        raw_forms.append(c.strip().lower())

    for comp, raw in zip(competitors, raw_forms):
        await _migrate_stale_key(db, target_job_id, comp, [comp, raw])

    to_enqueue = []
    for comp in competitors:
        existing = await db.competitor_gap_analyses.find_one(
            {"target_job_id": target_job_id, "competitor": comp}
        )
        if existing and existing.get("status") in ("queued", "running"):
            continue
        to_enqueue.append(comp)
        await db.competitor_gap_analyses.update_one(
            {"target_job_id": target_job_id, "competitor": comp},
            {
                "$set": {
                    "competitor": comp,
                    "url": comp,
                    "target_job_id": target_job_id,
                    "status": "queued",
                    "errors": None,
                    "updated_at": datetime.utcnow(),
                },
                "$setOnInsert": {"created_at": datetime.utcnow()},
            },
            upsert=True,
        )

    if not to_enqueue:
        return {
            "status": "already_running",
            "job_id": target_job_id,
            "competitors": competitors,
            "detail": "All submitted competitors are already queued or running.",
        }

    from backend.services.queue import run_or_fallback
    from backend.routes.analysis import run_competitor_pipeline

    await run_or_fallback(
        "competitor_audit",
        run_competitor_pipeline,
        target_job_id,
        to_enqueue,
    )
    return {"status": "queued", "job_id": target_job_id, "competitors": to_enqueue}


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


@router.get("/{target_job_id}/report")
async def competitor_report(target_job_id: str):
    db = get_db()
    rows = await db.competitor_gap_analyses.find(
        {"target_job_id": target_job_id, "status": {"$in": ["completed", "blocked"]}}
    ).sort("competitor", 1).to_list(length=100)
    if not rows:
        raise HTTPException(404, "No completed analysis for this job")

    from backend.services.competitor_audit import build_competitor_report

    reports = [build_competitor_report(r) for r in rows]
    return {"job_id": target_job_id, "competitors": reports, "total": len(reports)}


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