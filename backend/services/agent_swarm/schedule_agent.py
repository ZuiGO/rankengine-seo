from backend.services.agent_swarm.base_agent import BaseAgent

class ScheduleAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(
            job_id=job_id,
            allowed_tools=["create_schedule", "list_schedules"],
            system_prompt="""You are the Schedule Agent.
Your responsibility is to maintain a continuous monitoring state by setting up automated recurring crawls.
Use the create_schedule and list_schedules tools to manage cron-like background jobs.
"""
        )
