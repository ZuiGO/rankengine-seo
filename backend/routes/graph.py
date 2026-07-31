from fastapi import APIRouter, Query

from backend.services.graph_service import get_graph_data, get_graph_summary
from backend.services.user_flow import get_user_flows, get_top_flows

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


@router.get("/{job_id}/flows")
async def user_flows(job_id: str, limit: int = Query(200, le=1000)):
    data = await get_user_flows(job_id, limit)
    return data


@router.get("/{job_id}/flows/top")
async def top_user_flows(job_id: str, limit: int = Query(10, le=50)):
    data = await get_top_flows(job_id, limit)
    return {"flows": data}
