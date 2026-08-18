"""Agent planner: picks the next tool via Groq structured JSON output.

Without a Groq key (or on LLM failure) a deterministic phase fallback keeps
the runtime functional and testable: crawl -> analyze -> suggest -> apply
-> verify -> complete.
"""

import json
from typing import Any

from backend.config import settings
from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.models.agent_schemas import AgentDecision
from backend.services.agent_tools import TOOL_REGISTRY

logger = get_logger("agent_planner")

SYSTEM_PROMPT = """You are the planning module of an SEO optimization agent for {domain}.

Goal: {goal}
Scope: {scope}
Budget remaining: {budget_remaining:.1f} credits
Steps used / max: {steps_used} / {max_steps}

Available tools:
{tools}

Constraints:
- NEVER claim ranking-position improvements; only report measured facts.
- The apply_changes tool is sandbox-only: it never touches the live site or Vercel.
- Prefer the smallest number of steps that achieves the goal.
- If facts.pages_crawled is missing or 0, your FIRST action MUST be crawl_urls.
- If a step produced no actionable output (e.g. 0 suggestions created), call complete
  after at most one clarifying read_current_state instead of repeating the same call.
- If the goal is already satisfied or cannot be satisfied, call "complete".
Output ONLY a JSON object: {{"reasoning": "...", "tool": "<tool name or complete>", "args": {{...}}}}"""


def _tools_json() -> str:
    return json.dumps(
        [
            {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
            for t in TOOL_REGISTRY.values()
        ],
        ensure_ascii=False,
        indent=2,
    )


def _state_json(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, default=str)[:6000]


async def decide(state: dict) -> AgentDecision:
    if not settings.groq_api_key:
        return _fallback_decision(state)
    return await _llm_decision(state)


async def _llm_decision(state: dict) -> AgentDecision:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=settings.groq_api_key)
    system = SYSTEM_PROMPT.format(
        domain=state.get("domain", ""),
        goal=state.get("goal", ""),
        scope=state.get("scope", "single_page"),
        budget_remaining=float(state.get("budget_remaining", 0)),
        steps_used=state.get("steps_used", 0),
        max_steps=state.get("max_steps", 15),
        tools=_tools_json(),
    )
    user = "Current state:\n" + _state_json(state)

    for attempt in range(2):
        try:
            completion = await client.chat.completions.create(
                model=settings.groq_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.2,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            raw = completion.choices[0].message.content or "{}"
            payload = json.loads(raw)
        except Exception as e:
            logger.warning("Planner LLM attempt %s failed: %s", attempt + 1, e)
            continue
        decision = _validate_decision(payload, state)
        if decision:
            return decision
    logger.warning("Planner LLM returned invalid decision; using fallback")
    return _fallback_decision(state)


def _validate_decision(payload: dict, state: dict) -> AgentDecision | None:
    try:
        decision = AgentDecision(
            reasoning=str(payload.get("reasoning", ""))[:1000],
            tool=str(payload.get("tool", "")),
            args=payload.get("args") or {},
        )
    except Exception:
        return None
    if not decision.tool or decision.tool == "complete":
        return decision
    spec = TOOL_REGISTRY.get(decision.tool)
    if not spec:
        return None
    if not isinstance(decision.args, dict):
        return None
    if decision.tool == "crawl_urls" and not decision.args.get("urls"):
        decision.args["urls"] = state.get("urls") or []
    if decision.tool == "apply_changes":
        pending_ids = (state.get("facts") or {}).get("suggestion_ids_pending") or []
        ids = decision.args.get("suggestion_ids") or []
        valid_ids = [i for i in ids if i in pending_ids]
        if not valid_ids:
            return None
        decision.args["suggestion_ids"] = valid_ids[:10]
        decision.args["staging_page_ids"] = (state.get("facts") or {}).get("staging_page_ids") or []
    if decision.tool == "query_knowledge" and not decision.args.get("domain"):
        decision.args["domain"] = state.get("domain", "")
    return decision


def _fallback_decision(state: dict) -> AgentDecision:
    facts = state.get("facts") or {}
    urls = state.get("urls") or []
    if not facts.get("pages_crawled"):
        return AgentDecision(
            reasoning="No pages crawled yet.",
            tool="crawl_urls",
            args={"urls": urls, "max_pages": 1, "mobile": True},
        )
    if facts.get("pages_crawled") and not facts.get("analyze_done"):
        return AgentDecision(
            reasoning="Pages are crawled; run the local analyzers.",
            tool="run_analyzers",
            args={"analyzers": ["page_facts", "content", "links"]},
        )
    if facts.get("suggestions_pending") and not facts.get("apply_attempted"):
        return AgentDecision(
            reasoning="Suggestions are pending; apply them to the sandbox (human approval checkpoint).",
            tool="apply_changes",
            args={"suggestion_ids": facts.get("suggestion_ids_pending") or []},
        )
    if not facts.get("suggestions_attempted") and facts.get("pages_crawled"):
        return AgentDecision(
            reasoning="Pages are analyzed; generate evidence-anchored suggestions.",
            tool="generate_suggestions",
            args={"focus_areas": ["meta", "headings"]},
        )
    return AgentDecision(reasoning="Goal satisfied or no further tool is appropriate.", tool="complete")
