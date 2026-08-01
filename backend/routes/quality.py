from fastapi import APIRouter, HTTPException

from backend.db.mongo import get_db
from backend.services.duplicate_content import get_duplicate_content
from backend.services.performance_service import get_performance_summary
from backend.services.structured_data import get_structured_data
from backend.services.vector_service import get_embedding_report

router = APIRouter(prefix="/api/quality", tags=["quality"])


async def _ensure_job(job_id: str):
    db = get_db()
    if not await db.analysis_jobs.find_one({"_id": job_id}):
        raise HTTPException(404, "Job not found")


@router.get("/{job_id}/duplicates")
async def duplicates(job_id: str):
    await _ensure_job(job_id)
    doc = await get_duplicate_content(job_id)
    if not doc:
        raise HTTPException(404, "Duplicate analysis not run for this job")
    return doc


@router.get("/{job_id}/structured-data")
async def structured_data(job_id: str):
    await _ensure_job(job_id)
    doc = await get_structured_data(job_id)
    if not doc:
        raise HTTPException(404, "Structured data audit not run for this job")
    return doc


@router.get("/{job_id}/performance")
async def performance(job_id: str):
    await _ensure_job(job_id)
    doc = await get_performance_summary(job_id)
    if not doc:
        raise HTTPException(404, "Performance audit not run for this job")
    return doc


@router.get("/{job_id}/embeddings")
async def embeddings(job_id: str):
    await _ensure_job(job_id)
    return await get_embedding_report(job_id)
