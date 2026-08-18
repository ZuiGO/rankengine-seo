from backend.services.agent_swarm.base_agent import BaseAgent

class AnalysisAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(
            job_id=job_id,
            allowed_tools=["run_full_analysis", "run_analyzers", "run_single_page_analysis"],
            system_prompt="""You are the Analysis Agent.
Your responsibility is to analyze crawled content, compute SEO metrics, and extract insights.
You should use the run_full_analysis tool to run the complete 12-wave pipeline over crawled data.
"""
        )
