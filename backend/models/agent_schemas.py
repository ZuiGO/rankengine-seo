from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentGoal(BaseModel):
    id: str
    job_id: str | None = None
    scope: Literal["single_page", "whole_site"] = "single_page"
    urls: list[str]
    goal: str
    budget_credits: float = 100.0
    max_steps: int = 15
    checkpoint_policy: Literal["every_apply", "budget_threshold", "never"] = "budget_threshold"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentStep(BaseModel):
    step_num: int
    tool: str
    args: dict = {}
    reasoning: str = ""
    result: dict | None = None
    error: str | None = None
    duration_ms: int = 0
    tokens_used: int = 0
    ok: bool = True
    ts: datetime = Field(default_factory=datetime.utcnow)


class AgentRun(BaseModel):
    id: str
    goal: str
    domain: str = ""
    agent_type: str = "coordinator"
    job_id: str | None = None
    scope: str = "single_page"
    urls: list[str] = []
    status: Literal["queued", "running", "waiting_approval", "complete", "failed", "stopped"] = "queued"
    steps: list[AgentStep] = []
    facts: dict[str, Any] = {}
    budget_credits: float = 100.0
    credits_spent: float = 0.0
    max_steps: int = 15
    checkpoint_policy: str = "budget_threshold"
    pending_payload: dict | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


class AgentDecision(BaseModel):
    reasoning: str = ""
    tool: str
    args: dict = {}


class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: dict
    requires_checkpoint: bool = False
    credit_cost: float = 0.0
