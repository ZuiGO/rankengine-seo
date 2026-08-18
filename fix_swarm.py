import re

with open("backend/tests/test_agent_swarm.py", "r") as f:
    c = f.read()

c = re.sub(r'agent = ([a-zA-Z]+Agent)\(\)', r'agent = \1(job_id="j1")', c)

with open("backend/tests/test_agent_swarm.py", "w") as f:
    f.write(c)
