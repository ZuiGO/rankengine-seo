import pytest
from backend.services.agent_tools.domain_tools import (
    _crawl_full_site_tool,
    _run_full_analysis_tool,
    _fetch_seo_insights_tool
)

@pytest.mark.asyncio
async def test_crawl_full_site_tool_success(monkeypatch):
    async def mock_crawl(*args, **kwargs):
        return {"total_pages": 10}
    monkeypatch.setattr("backend.services.crawler.crawl_site", mock_crawl)
    result = await _crawl_full_site_tool("job1", "https://example.com", 10)
    assert result["ok"] is True
    assert result["summary"]["total_pages"] == 10

@pytest.mark.asyncio
async def test_crawl_full_site_tool_error(monkeypatch):
    async def mock_crawl(*args, **kwargs):
        raise Exception("Crawler error")
    monkeypatch.setattr("backend.services.crawler.crawl_site", mock_crawl)
    result = await _crawl_full_site_tool("job1", "https://example.com", 10)
    assert result["ok"] is False
    assert "Crawler error" in result["error"]

@pytest.mark.asyncio
async def test_run_full_analysis_tool_success(monkeypatch):
    import sys
    from unittest.mock import MagicMock
    mock_module = MagicMock()
    async def mock_run(*args, **kwargs):
        return None
    mock_module.run_analysis_pipeline = mock_run
    monkeypatch.setitem(sys.modules, "backend.routes.analysis", mock_module)
    
    result = await _run_full_analysis_tool("job1", "https://example.com", 50)
    assert result["ok"] is True
    assert "completed successfully" in result["message"]

@pytest.mark.asyncio
async def test_fetch_seo_insights_tool_success(monkeypatch):
    async def mock_fetch(*args, **kwargs):
        return {"keyword": "test"}
    monkeypatch.setattr("backend.services.external_insights.fetch_all_insights", mock_fetch)
    result = await _fetch_seo_insights_tool("example.com", "job1")
    assert result["ok"] is True
    assert result["insights"]["keyword"] == "test"


from backend.services.agent_tools.domain_tools import (
    _run_competitor_audit_tool,
    _audit_programmatic_tool,
    _audit_ai_visibility_tool,
    _apply_approved_changes_tool,
    _export_patch_tool,
    _github_pr_tool,
    _generate_pdf_report_tool,
    _send_report_email_tool,
    _create_schedule_tool,
    _list_schedules_tool
)

@pytest.mark.asyncio
async def test_run_competitor_audit_tool(monkeypatch):
    async def mock_audit(*args, **kwargs):
        return {"competitors_analyzed": 2}
    monkeypatch.setattr("backend.services.competitor_audit.audit_competitors", mock_audit)
    result = await _run_competitor_audit_tool("job1", ["a.com", "b.com"])
    assert result["ok"] is True
    assert result["results"]["competitors_analyzed"] == 2

@pytest.mark.asyncio
async def test_audit_programmatic_tool(monkeypatch):
    async def mock_audit(*args, **kwargs):
        return {"templates_found": 3}
    monkeypatch.setattr("backend.services.programmatic_seo.audit_programmatic_seo", mock_audit)
    result = await _audit_programmatic_tool("job1")
    assert result["ok"] is True
    assert result["results"]["templates_found"] == 3

@pytest.mark.asyncio
async def test_apply_approved_changes_tool(monkeypatch):
    async def mock_apply(*args, **kwargs):
        return None
    monkeypatch.setattr("backend.routes.actions.apply_approved_changes", mock_apply)
    result = await _apply_approved_changes_tool("job1")
    assert result["ok"] is True

@pytest.mark.asyncio
async def test_export_patch_tool(monkeypatch):
    async def mock_export(*args, **kwargs):
        return {"changes": []}
    monkeypatch.setattr("backend.routes.actions.export_patch", mock_export)
    result = await _export_patch_tool("job1")
    assert result["ok"] is True
    assert "patch" in result

@pytest.mark.asyncio
async def test_github_pr_tool(monkeypatch):
    async def mock_pr(*args, **kwargs):
        return {"pr_url": "https://github.com/pulls/1"}
    monkeypatch.setattr("backend.services.notifications.create_github_pr", mock_pr)
    result = await _github_pr_tool("job1", "example.com", [{"test": 1}], "token123")
    assert result["ok"] is True
    assert result["pr_info"]["pr_url"] == "https://github.com/pulls/1"

@pytest.mark.asyncio
async def test_send_report_email_tool(monkeypatch):
    async def mock_email(*args, **kwargs):
        return True, None
    monkeypatch.setattr("backend.services.notifications.email_report", mock_email)
    result = await _send_report_email_tool("job1", "admin@example.com")
    assert result["ok"] is True

@pytest.mark.asyncio
async def test_create_schedule_tool(monkeypatch):
    import sys
    from unittest.mock import MagicMock
    mock_module = MagicMock()
    async def mock_create(req, **kwargs):
        return {"id": "sched_123"}
    mock_module.create = mock_create
    monkeypatch.setitem(sys.modules, "backend.routes.scheduler", mock_module)
    
    result = await _create_schedule_tool("job1", "https://example.com", 24, 50, "crawl")
    assert result["ok"] is True
    assert result["schedule_id"] == "sched_123"


@pytest.mark.asyncio
async def test_list_schedules_tool(monkeypatch):
    import sys
    from unittest.mock import MagicMock
    mock_module = MagicMock()
    async def mock_list():
        return [{"id": "sched_123"}]
    mock_module.list_all = mock_list
    monkeypatch.setitem(sys.modules, "backend.routes.scheduler", mock_module)
    
    result = await _list_schedules_tool("job1")
    assert result["ok"] is True
    assert len(result["schedules"]) == 1


@pytest.mark.asyncio
async def test_delegate_to_domain_agent(monkeypatch):
    import sys
    from unittest.mock import MagicMock
    from backend.models.agent_schemas import AgentRun
    
    # Mock get_agent_for_domain
    mock_agent_cls = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_cls.return_value = mock_agent_instance
    
    # Needs to be an async mock for start()
    async def mock_start(sub_run_id):
        pass
    mock_agent_instance.start = mock_start
    
    def mock_get_agent(domain):
        if domain == "crawl": return mock_agent_cls
        return None
        
    monkeypatch.setattr("backend.services.agent_swarm.get_agent_for_domain", mock_get_agent)
    
    # Mock DB
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.agent_runs = mock_collection
    
    async def mock_insert(doc):
        pass
    mock_collection.insert_one = mock_insert
    
    async def mock_find_one(query):
        return {"id": query["id"], "status": "complete", "facts": {"test": True}}
    mock_collection.find_one = mock_find_one
    
    monkeypatch.setattr("backend.db.mongo.get_db", lambda: mock_db)
    
    # Run
    from backend.services.agent_tools.domain_tools import _delegate_to_domain_agent
    result = await _delegate_to_domain_agent("job1", "crawl", "Crawl it", ["https://example.com"], "single_page")
    
    assert result["ok"] is True
    assert result["status"] == "complete"
    assert result["facts"] == {"test": True}
    assert "sub_run_id" in result

