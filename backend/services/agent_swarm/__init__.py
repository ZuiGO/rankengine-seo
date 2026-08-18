from backend.services.agent_swarm.base_agent import BaseAgent
from backend.services.agent_swarm.crawl_agent import CrawlAgent
from backend.services.agent_swarm.analysis_agent import AnalysisAgent
from backend.services.agent_swarm.insight_agent import InsightAgent
from backend.services.agent_swarm.competitor_agent import CompetitorAgent
from backend.services.agent_swarm.technical_agent import TechnicalAgent
from backend.services.agent_swarm.action_agent import ActionAgent
from backend.services.agent_swarm.report_agent import ReportAgent
from backend.services.agent_swarm.schedule_agent import ScheduleAgent
from backend.services.agent_swarm.coordinator_agent import CoordinatorAgent

__all__ = [
    "BaseAgent",
    "CrawlAgent",
    "AnalysisAgent",
    "InsightAgent",
    "CompetitorAgent",
    "TechnicalAgent",
    "ActionAgent",
    "ReportAgent",
    "ScheduleAgent",
    "CoordinatorAgent",
    "get_agent_for_domain",
]

def get_agent_for_domain(domain: str) -> type[BaseAgent] | None:
    """Returns the correct agent class for a given domain string."""
    mapping = {
        "crawl": CrawlAgent,
        "analysis": AnalysisAgent,
        "insight": InsightAgent,
        "competitor": CompetitorAgent,
        "technical": TechnicalAgent,
        "action": ActionAgent,
        "report": ReportAgent,
        "schedule": ScheduleAgent,
        "coordinator": CoordinatorAgent,
    }
    return mapping.get(domain)
