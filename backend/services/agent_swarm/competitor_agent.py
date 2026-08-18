from backend.services.agent_swarm.base_agent import BaseAgent

class CompetitorAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(
            job_id=job_id,
            allowed_tools=["run_competitor_audit"],
            system_prompt="""You are the Competitor Agent.
Your responsibility is to analyze competitors, identify content gaps, and reverse-engineer their strategy.
You should use the run_competitor_audit tool to audit rival sites and find opportunities.
"""
        )
