with open("backend/services/agent_swarm/base_agent.py", "r") as f:
    c = f.read()
    
c = c.replace("super().__init__(job_id)", "super().__init__()\n        self.job_id = job_id")

with open("backend/services/agent_swarm/base_agent.py", "w") as f:
    f.write(c)
