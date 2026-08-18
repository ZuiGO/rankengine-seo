import asyncio
from backend.logging_setup import get_logger
from backend.services.agent_tools_legacy import _compact
from backend.services.agent_tools.tool_registry import ToolSpec, registry

logger = get_logger("domain_tools")

# ----------------- CRAWL DOMAIN -----------------

async def _crawl_full_site_tool(job_id: str, target_url: str, max_pages: int = 50) -> dict:
    from backend.services.crawler import crawl_site
    try:
        summary = await crawl_site(job_id, target_url, max_pages=max_pages, seed_sitemap=True, unlimited=False, mobile=True)
        return {"ok": True, "summary": summary}
    except Exception as e:
        logger.error("crawl_full_site_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="crawl_full_site",
    description="Crawl an entire website starting from a target URL up to max_pages. Discovers and indexes pages.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "target_url": {"type": "string"},
            "max_pages": {"type": "integer", "default": 50}
        },
        "required": ["job_id", "target_url"]
    },
    handler=_crawl_full_site_tool
))

# ----------------- ANALYSIS DOMAIN -----------------

async def _run_full_analysis_tool(job_id: str, url: str, max_pages: int = 50) -> dict:
    from backend.routes.analysis import run_analysis_pipeline
    try:
        # Note: this blocks the agent while the 12-wave pipeline completes.
        await run_analysis_pipeline(job_id, url, max_pages)
        return {"ok": True, "message": "Analysis pipeline completed successfully."}
    except Exception as e:
        logger.error("run_full_analysis_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="run_full_analysis",
    description="Run the full 12-wave SEO analysis pipeline for a job. Note: This takes several minutes to complete.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "url": {"type": "string"},
            "max_pages": {"type": "integer", "default": 50}
        },
        "required": ["job_id", "url"]
    },
    handler=_run_full_analysis_tool
))

async def _run_single_page_analysis_tool(url: str, job_id: str) -> dict:
    from backend.services.single_page_service import run_single_page_analysis
    try:
        await run_single_page_analysis(url, job_id)
        return {"ok": True, "message": "Single page analysis completed."}
    except Exception as e:
        logger.error("run_single_page_analysis_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="run_single_page_analysis",
    description="Run the single page analysis (generates AI suggestions and builds visual comparison).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "job_id": {"type": "string"}
        },
        "required": ["url", "job_id"]
    },
    handler=_run_single_page_analysis_tool
))

# ----------------- INSIGHTS DOMAIN -----------------

async def _fetch_seo_insights_tool(domain: str, job_id: str) -> dict:
    from backend.services.external_insights import fetch_all_insights
    try:
        insights = await fetch_all_insights(domain, job_id)
        return _compact({"ok": True, "insights": insights})
    except Exception as e:
        logger.error("fetch_seo_insights_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="fetch_seo_insights",
    description="Fetch external SEO insights (SE Ranking, Google Search Console) for a domain.",
    parameters={
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "job_id": {"type": "string"}
        },
        "required": ["domain", "job_id"]
    },
    handler=_fetch_seo_insights_tool
))

async def _run_serp_rankings_tool(domain: str, job_id: str, max_keywords: int = 10) -> dict:
    from backend.services.serp_api import run_serp_rankings
    try:
        results, errors = await run_serp_rankings(domain, job_id, max_keywords)
        return _compact({"ok": True, "results": results, "errors": errors})
    except Exception as e:
        logger.error("run_serp_rankings_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="run_serp_rankings",
    description="Check SERP rankings for the top keywords identified for the job.",
    parameters={
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "job_id": {"type": "string"},
            "max_keywords": {"type": "integer", "default": 10}
        },
        "required": ["domain", "job_id"]
    },
    handler=_run_serp_rankings_tool
))

async def _audit_technical_tool(job_id: str) -> dict:
    from backend.services.site_health import compute_site_health
    try:
        health = await compute_site_health(job_id)
        return _compact({"ok": True, "health": health})
    except Exception as e:
        logger.error("audit_technical_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="audit_technical",
    description="Compute technical site health score and identify critical issues based on the crawl data.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"}
        },
        "required": ["job_id"]
    },
    handler=_audit_technical_tool
))

# ----------------- COMPETITOR DOMAIN -----------------

async def _run_competitor_audit_tool(job_id: str, competitors: list[str]) -> dict:
    from backend.services.competitor_audit import audit_competitors
    try:
        results = await audit_competitors(job_id, competitors)
        return _compact({"ok": True, "results": results})
    except Exception as e:
        logger.error("run_competitor_audit_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="run_competitor_audit",
    description="Run a deep analysis on a set of competitor URLs against a target job to identify gaps and opportunities.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "competitors": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["job_id", "competitors"]
    },
    handler=_run_competitor_audit_tool
))

# ----------------- TECHNICAL DOMAIN -----------------

async def _audit_programmatic_tool(job_id: str) -> dict:
    from backend.services.programmatic_seo import audit_programmatic_seo
    try:
        results = await audit_programmatic_seo(job_id)
        return _compact({"ok": True, "results": results})
    except Exception as e:
        logger.error("audit_programmatic_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="audit_programmatic",
    description="Detect and evaluate programmatic page templates across the crawled site.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"}
        },
        "required": ["job_id"]
    },
    handler=_audit_programmatic_tool
))

async def _audit_ai_visibility_tool(job_id: str, target_url: str) -> dict:
    from backend.services.ai_visibility import check_ai_visibility
    try:
        results = await check_ai_visibility(job_id, target_url)
        return _compact({"ok": True, "results": results})
    except Exception as e:
        logger.error("audit_ai_visibility_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="audit_ai_visibility",
    description="Check LLM and Search Generative Experience visibility for a given URL.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "target_url": {"type": "string"}
        },
        "required": ["job_id", "target_url"]
    },
    handler=_audit_ai_visibility_tool
))

# ----------------- ACTIONS DOMAIN -----------------

async def _apply_approved_changes_tool(job_id: str) -> dict:
    from backend.routes.actions import apply_approved_changes
    try:
        await apply_approved_changes(job_id)
        return {"ok": True, "message": "Changes applied successfully."}
    except Exception as e:
        logger.error("apply_approved_changes_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="apply_approved_changes",
    description="Execute all user-approved SEO changes natively.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"}
        },
        "required": ["job_id"]
    },
    handler=_apply_approved_changes_tool,
    requires_checkpoint=True
))

async def _export_patch_tool(job_id: str, format: str = "json") -> dict:
    from backend.routes.actions import export_patch
    try:
        patch = await export_patch(job_id, format)
        return _compact({"ok": True, "patch": patch})
    except Exception as e:
        logger.error("export_patch_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="export_patch",
    description="Generate JSON or Markdown patches of reviewed actions.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "format": {"type": "string", "default": "json"}
        },
        "required": ["job_id"]
    },
    handler=_export_patch_tool
))

async def _github_pr_tool(job_id: str, domain: str, changes: list[dict], token: str | None = None) -> dict:
    from backend.services.notifications import create_github_pr
    try:
        pr_info = await create_github_pr(domain, changes, token)
        return {"ok": True, "pr_info": pr_info}
    except Exception as e:
        logger.error("github_pr_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="github_pr",
    description="Automatically file a GitHub pull request with the approved SEO changes.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "domain": {"type": "string"},
            "changes": {"type": "array", "items": {"type": "object"}},
            "token": {"type": "string"}
        },
        "required": ["job_id", "domain", "changes"]
    },
    handler=_github_pr_tool,
    requires_checkpoint=True
))

# ----------------- REPORTS DOMAIN -----------------

async def _generate_pdf_report_tool(job_id: str) -> dict:
    from backend.routes.reports import download_report_pdf
    try:
        # Note: download_report_pdf returns a StreamingResponse or Response from fastapi
        # The agent probably just needs to trigger generation or know it succeeded.
        # We'll just call it and return success if it doesn't throw.
        # However, FastAPI's download_report_pdf returns a Response object containing the bytes.
        res = await download_report_pdf(job_id)
        if getattr(res, "status_code", 200) >= 400:
            return {"ok": False, "error": f"Failed to generate PDF, status {getattr(res, 'status_code')}"}
        return {"ok": True, "message": "PDF report generated successfully."}
    except Exception as e:
        logger.error("generate_pdf_report_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="generate_pdf_report",
    description="Compile SEO findings into a branded PDF report.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"}
        },
        "required": ["job_id"]
    },
    handler=_generate_pdf_report_tool
))

async def _send_report_email_tool(job_id: str, to: str) -> dict:
    from backend.services.notifications import email_report
    try:
        sent, error = await email_report(job_id, to)
        if not sent:
            return {"ok": False, "error": error}
        return {"ok": True, "message": f"Email report sent to {to}."}
    except Exception as e:
        logger.error("send_report_email_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="send_report_email",
    description="Distribute the generated PDF report to stakeholders via email.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "to": {"type": "string"}
        },
        "required": ["job_id", "to"]
    },
    handler=_send_report_email_tool,
    requires_checkpoint=True
))

# ----------------- SCHEDULING DOMAIN -----------------

async def _create_schedule_tool(job_id: str, url: str, interval_hours: float, max_pages: int = 50, kind: str = "crawl") -> dict:
    from backend.routes.scheduler import create, CreateScheduleRequest
    try:
        req = CreateScheduleRequest(url=url, interval_hours=interval_hours, max_pages=max_pages, kind=kind)
        res = await create(req)
        return {"ok": True, "schedule_id": res.get("id")}
    except Exception as e:
        logger.error("create_schedule_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="create_schedule",
    description="Set up recurring automated crawls/analysis on a schedule.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "url": {"type": "string"},
            "interval_hours": {"type": "number"},
            "max_pages": {"type": "integer", "default": 50},
            "kind": {"type": "string", "default": "crawl"}
        },
        "required": ["job_id", "url", "interval_hours"]
    },
    handler=_create_schedule_tool
))

async def _list_schedules_tool(job_id: str) -> dict:
    from backend.routes.scheduler import list_all
    try:
        schedules = await list_all()
        # Filter schedules by URL or job? Actually list_all returns all schedules.
        # But we can compact it.
        return _compact({"ok": True, "schedules": schedules})
    except Exception as e:
        logger.error("list_schedules_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="list_schedules",
    description="List all currently active cron schedules for recurring analysis.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"}
        },
        "required": ["job_id"]
    },
    handler=_list_schedules_tool
))


# ----------------- COORDINATOR DOMAIN -----------------

async def _delegate_to_domain_agent(job_id: str, agent_domain: str, goal: str, urls: list[str], scope: str = "single_page") -> dict:
    from backend.services.agent_swarm import get_agent_for_domain
    from backend.models.agent_schemas import AgentRun
    from backend.db.mongo import get_db
    import uuid
    
    agent_cls = get_agent_for_domain(agent_domain)
    if not agent_cls:
        return {"ok": False, "error": f"Unknown agent domain: {agent_domain}"}
    
    def _domain(url: str) -> str:
        if "//" in url:
            return url.split("//")[-1].split("/")[0].lower()
        return url
    
    sub_run_id = str(uuid.uuid4())
    sub_run = AgentRun(
        id=sub_run_id,
        goal=goal,
        domain=_domain(urls[0]) if urls else "",
        agent_type=agent_domain,
        job_id=job_id,
        scope=scope,
        urls=urls,
        budget_credits=100.0,
        max_steps=15,
        checkpoint_policy="never",  # prevent sub-agents from blocking the coordinator indefinitely
        status="queued"
    )
    
    db = get_db()
    await db.agent_runs.insert_one(sub_run.model_dump())
    
    try:
        agent_instance = agent_cls(job_id=job_id)
        await agent_instance.start(sub_run_id)
        
        # Read the completed run
        completed_run = await db.agent_runs.find_one({"id": sub_run_id})
        if not completed_run:
            return {"ok": False, "error": "Sub-run not found after execution"}
            
        return {
            "ok": True,
            "sub_run_id": sub_run_id,
            "status": completed_run.get("status"),
            "facts": completed_run.get("facts", {}),
            "error": completed_run.get("error")
        }
    except Exception as e:
        logger.error("Delegate to %s failed: %s", agent_domain, e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="delegate_to_domain_agent",
    description="Delegate a sub-goal to a specific domain agent (e.g., 'crawl', 'analysis', 'competitor', 'technical', 'action', 'report', 'schedule').",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "agent_domain": {"type": "string"},
            "goal": {"type": "string"},
            "urls": {"type": "array", "items": {"type": "string"}},
            "scope": {"type": "string", "default": "single_page"}
        },
        "required": ["job_id", "agent_domain", "goal", "urls"]
    },
    handler=_delegate_to_domain_agent
))

# ----------------- MEMORY DOMAIN -----------------

async def _store_memory_tool(job_id: str, domain: str, memory_type: str, key: str, value: str) -> dict:
    from backend.services.agent_memory import record_fact
    try:
        fact_key = f"{memory_type}:{key}"
        await record_fact(domain, fact_key, value)
        return {"ok": True, "message": f"Stored memory: {fact_key}"}
    except Exception as e:
        logger.error("store_memory_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="store_memory",
    description="Store persistent cross-session memory such as 'user_preference', 'domain_learning', or 'approval_pattern'.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "domain": {"type": "string", "description": "Use 'GLOBAL' for user preferences/patterns, or a specific domain for domain learnings"},
            "memory_type": {"type": "string", "enum": ["user_preference", "domain_learning", "approval_pattern"]},
            "key": {"type": "string"},
            "value": {"type": "string"}
        },
        "required": ["job_id", "domain", "memory_type", "key", "value"]
    },
    handler=_store_memory_tool
))
