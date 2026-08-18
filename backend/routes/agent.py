import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import settings
from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.models.agent_schemas import AgentRun
from backend.services.agent_memory import get_episode

router = APIRouter(prefix="/api/agent", tags=["agent"])

logger = get_logger("agent_routes")


class CreateRunRequest(BaseModel):
    goal: str
    scope: str = "single_page"
    urls: list[str] = []
    budget_credits: float = Field(default=settings.agent_default_budget, ge=1)
    max_steps: int = Field(default=settings.agent_max_steps, ge=2, le=50)
    checkpoint_policy: str = "every_apply"


def _domain(url: str) -> str:
    if "//" in url:
        return url.split("//")[-1].split("/")[0].lower()
    return url


@router.post("/runs")
async def create_run(payload: CreateRunRequest):
    db = get_db()
    urls = [u for u in payload.urls if u]
    if not urls:
        raise HTTPException(status_code=400, detail="At least one URL is required")
    if payload.scope not in ("single_page", "whole_site"):
        raise HTTPException(status_code=400, detail="scope must be single_page or whole_site")
    if payload.checkpoint_policy not in ("every_apply", "budget_threshold", "never"):
        raise HTTPException(status_code=400, detail="invalid checkpoint_policy")

    run = AgentRun(
        id=str(uuid.uuid4()),
        goal=payload.goal,
        domain=_domain(urls[0]),
        job_id=str(uuid.uuid4()),
        scope=payload.scope,
        urls=urls,
        budget_credits=payload.budget_credits,
        max_steps=payload.max_steps,
        checkpoint_policy=payload.checkpoint_policy,
        status="queued",
    )
    run_doc = run.model_dump()
    await db.agent_runs.insert_one(run_doc)

    from backend.services.queue import run_or_fallback
    from backend.services.agent_runtime import AgentRuntime

    await run_or_fallback(
        "agent_run",
        AgentRuntime().start,
        run.id,
    )
    return {"run_id": run.id, "status": run.status}


@router.get("/runs")
async def list_runs(limit: int = 50):
    db = get_db()
    cursor = db.agent_runs.find().sort("created_at", -1).limit(min(limit, 100))
    runs = await cursor.to_list(length=min(limit, 100))
    out = []
    for r in runs:
        r.pop("_id", None)
        r.pop("steps", None)
        out.append(r)
    return {"runs": out}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    db = get_db()
    doc = await db.agent_runs.find_one({"id": run_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Run not found")
    doc.pop("_id", None)
    return doc


@router.post("/runs/{run_id}/approve")
async def approve_run(run_id: str):
    from backend.services.agent_runtime import AgentRuntime

    db = get_db()
    doc = await db.agent_runs.find_one({"id": run_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Run not found")
    if doc.get("status") != "waiting_approval":
        raise HTTPException(status_code=409, detail="Run is not waiting for approval")
    ok = await AgentRuntime().approve(run_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Run is not waiting for approval")
    return {"status": "resumed"}


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str):
    from backend.services.agent_runtime import AgentRuntime

    db = get_db()
    doc = await db.agent_runs.find_one({"id": run_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Run not found")
    ok = await AgentRuntime().stop(run_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Run is not stoppable")
    return {"status": "stopped"}


@router.get("/runs/{run_id}/log")
async def get_run_log(run_id: str):
    db = get_db()
    doc = await db.agent_runs.find_one({"id": run_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Run not found")
    doc.pop("_id", None)
    episode = await get_episode(run_id)
    return {"run": doc, "episode": episode}
