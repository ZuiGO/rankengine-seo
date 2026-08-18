from typing import Optional
from backend.services.agent_runtime import AgentRuntime
from backend.services.agent_tools import TOOL_REGISTRY
from backend.logging_setup import get_logger

logger = get_logger("base_agent")

class BaseAgent(AgentRuntime):
    """
    A specialized agent that extends AgentRuntime.
    It has a specific domain-level planner prompt and a restricted set of tools.
    """
    def __init__(self, job_id: str, allowed_tools: list[str], system_prompt: str):
        super().__init__()
        self.job_id = job_id
        self.allowed_tools = allowed_tools
        self.system_prompt = system_prompt

    async def _plan_next_step(self, run: dict, current_facts: list[dict], steps: list[dict]):
        # We need to override the planner or pass the system_prompt to it.
        # For this PoC, we will inject our specific system prompt and allowed tools into the Groq call.
        from backend.services.agent_planner import _generate_prompt, _call_groq, _fallback_decision, _validate_decision
        
        # Filter TOOL_REGISTRY to only allowed_tools
        available_tools = [TOOL_REGISTRY[t] for t in self.allowed_tools if t in TOOL_REGISTRY]
        
        prompt = _generate_prompt(
            goal=run.get("goal") or "Execute domain tasks",
            scope=run.get("scope") or {},
            facts=current_facts,
            steps=steps,
            tools=available_tools
        )
        
        # Prepend our domain system prompt
        prompt = self.system_prompt + "\n\n" + prompt

        try:
            raw_response = await _call_groq(prompt)
            return _validate_decision(raw_response)
        except Exception as e:
            logger.error("Domain agent planner failed: %s", e)
            return _fallback_decision(f"Planner error: {e}")
