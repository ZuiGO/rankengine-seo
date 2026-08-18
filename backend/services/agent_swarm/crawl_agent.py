from backend.services.agent_swarm.base_agent import BaseAgent

class CrawlAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(
            job_id=job_id,
            allowed_tools=["crawl_full_site", "crawl_urls"],
            system_prompt="""You are the Crawl Agent.
Your sole responsibility is to navigate target URLs, discover pages, and build an index of the site's content.
You should use the crawl_full_site tool for full domain audits, or crawl_urls for targeted discovery.
"""
        )
