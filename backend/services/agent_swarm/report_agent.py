from backend.services.agent_swarm.base_agent import BaseAgent

class ReportAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(
            job_id=job_id,
            allowed_tools=["generate_pdf_report", "send_report_email"],
            system_prompt="""You are the Report Agent.
Your responsibility is to aggregate the finalized data and distribute beautiful PDF reports to stakeholders.
Use the generate_pdf_report and send_report_email tools to build and share findings. Sending emails requires human approval.
"""
        )
