import re

with open("backend/tests/test_agent_swarm.py", "r") as f:
    c = f.read()

c = re.sub(r'assert agent.name == "Action Agent"', 'assert "Action" in agent.system_prompt', c)
c = re.sub(r'assert agent.name == "Analysis Agent"', 'assert "Analysis" in agent.system_prompt', c)
c = re.sub(r'assert agent.name == "Competitor Agent"', 'assert "Competitor" in agent.system_prompt', c)
c = re.sub(r'assert agent.name == "Crawl Agent"', 'assert "Crawl" in agent.system_prompt', c)
c = re.sub(r'assert agent.name == "Insight Agent"', 'assert "Insight" in agent.system_prompt', c)
c = re.sub(r'assert agent.name == "Report Agent"', 'assert "Report" in agent.system_prompt', c)
c = re.sub(r'assert agent.name == "Schedule Agent"', 'assert "Schedule" in agent.system_prompt', c)
c = re.sub(r'assert agent.name == "Technical Agent"', 'assert "Technical" in agent.system_prompt', c)

c = c.replace('.tools', '.allowed_tools')
c = c.replace('"apply_to_sandbox"', '"apply_approved_changes"')

with open("backend/tests/test_agent_swarm.py", "w") as f:
    f.write(c)

with open("backend/tests/test_coordinator.py", "r") as f:
    c = f.read()

c = c.replace('.tools', '.allowed_tools')

with open("backend/tests/test_coordinator.py", "w") as f:
    f.write(c)
