import pytest
from backend.models.agent_schemas import AgentRun, AgentDecision
from backend.services.agent_swarm.action_agent import ActionAgent
from backend.services.agent_swarm.analysis_agent import AnalysisAgent
from backend.services.agent_swarm.competitor_agent import CompetitorAgent
from backend.services.agent_swarm.crawl_agent import CrawlAgent
from backend.services.agent_swarm.insight_agent import InsightAgent
from backend.services.agent_swarm.report_agent import ReportAgent
from backend.services.agent_swarm.schedule_agent import ScheduleAgent
from backend.services.agent_swarm.technical_agent import TechnicalAgent

@pytest.fixture
def mock_run():
    return AgentRun(id="r1", goal="improve", domain="x.com", job_id="j1", urls=["https://x.com"])

class TestDomainAgents:
    def test_action_agent_init(self):
        agent = ActionAgent(job_id="j1")
        assert "Action" in agent.system_prompt
        assert "apply_approved_changes" in agent.allowed_tools

    def test_analysis_agent_init(self):
        agent = AnalysisAgent(job_id="j1")
        assert "Analysis" in agent.system_prompt
        assert "run_analyzers" in agent.allowed_tools
        assert "run_single_page_analysis" in agent.allowed_tools

    def test_competitor_agent_init(self):
        agent = CompetitorAgent(job_id="j1")
        assert "Competitor" in agent.system_prompt
        assert "run_competitor_audit" in agent.allowed_tools

    def test_crawl_agent_init(self):
        agent = CrawlAgent(job_id="j1")
        assert "Crawl" in agent.system_prompt
        assert "crawl_urls" in agent.allowed_tools

    def test_insight_agent_init(self):
        agent = InsightAgent(job_id="j1")
        assert "Insight" in agent.system_prompt
        assert "fetch_seo_insights" in agent.allowed_tools

    def test_report_agent_init(self):
        agent = ReportAgent(job_id="j1")
        assert "Report" in agent.system_prompt
        assert "generate_pdf_report" in agent.allowed_tools

    def test_schedule_agent_init(self):
        agent = ScheduleAgent(job_id="j1")
        assert "Schedule" in agent.system_prompt
        assert "create_schedule" in agent.allowed_tools

    def test_technical_agent_init(self):
        agent = TechnicalAgent(job_id="j1")
        assert "Technical" in agent.system_prompt
        assert "audit_technical" in agent.allowed_tools
