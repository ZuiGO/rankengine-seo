from fastapi import APIRouter

from backend.services.spend_tracker import get_global_spend, get_spend_summary

router = APIRouter(prefix="/api/spend", tags=["spend"])


@router.get("/{job_id}")
async def job_spend(job_id: str):
    return await get_spend_summary(job_id)


@router.get("")
async def global_spend():
    return await get_global_spend()
