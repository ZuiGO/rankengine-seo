from backend.services.agent_swarm.base_agent import BaseAgent

class ActionAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(
            job_id=job_id,
            allowed_tools=["generate_suggestions", "apply_approved_changes", "export_patch", "github_pr"],
            system_prompt="""You are the Action Agent.
Your responsibility is to generate and execute changes, either directly to a sandbox, generating patch files, or filing GitHub PRs.
Use the appropriate tools to draft changes, and apply them or open PRs. Note that applying changes or opening PRs requires explicit human approval.
"""
        )
