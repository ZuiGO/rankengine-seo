from fastapi import APIRouter

from backend.services.graph_service import get_graph_data, get_graph_summary

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/{job_id}")
async def graph_data(job_id: str):
    data = await get_graph_data(job_id)
    return data


@router.get("/{job_id}/summary")
async def graph_summary(job_id: str):
    summary = await get_graph_summary(job_id)
    if not summary:
        return {"note": "Graph not yet built for this job"}
    return summary
