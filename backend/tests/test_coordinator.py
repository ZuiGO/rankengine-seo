import pytest
from backend.services.agent_swarm.coordinator_agent import CoordinatorAgent

class TestCoordinatorAgent:
    def test_coordinator_init(self):
        agent = CoordinatorAgent(job_id="j1")
        assert agent.job_id == "j1"
        assert "delegate_to_domain_agent" in agent.allowed_tools
        assert "read_current_state" in agent.allowed_tools
        
    def test_coordinator_prompt(self):
        agent = CoordinatorAgent(job_id="j1")
        prompt = agent.system_prompt
        assert "Coordinator Orchestrator Agent" in prompt
        assert "crawl" in prompt
        assert "analysis" in prompt
        assert "delegate_to_domain_agent" in prompt
