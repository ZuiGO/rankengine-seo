from backend.services.agent_swarm.base_agent import BaseAgent

class TechnicalAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(
            job_id=job_id,
            allowed_tools=["audit_technical", "audit_programmatic", "audit_ai_visibility"],
            system_prompt="""You are the Technical Agent.
Your responsibility is to deeply analyze technical SEO issues, programmatic template scaling, and modern AI-search readiness.
You should use audit_technical, audit_programmatic, and audit_ai_visibility tools to uncover and report technical insights.
"""
        )
