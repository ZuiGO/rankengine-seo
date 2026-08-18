from backend.services.agent_swarm.base_agent import BaseAgent

class InsightAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(
            job_id=job_id,
            allowed_tools=["fetch_seo_insights", "run_serp_rankings"],
            system_prompt="""You are the Insight Agent.
Your responsibility is to extract external SEO metrics, Google Search Console data, and SERP positions.
You should use the fetch_seo_insights and run_serp_rankings tools to retrieve external rankings and keyword opportunities.
"""
        )
