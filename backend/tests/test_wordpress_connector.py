import pytest
import httpx
from backend.services.connectors.wordpress_connector import WordPressConnector

# We use httpx.MockTransport to mock the WordPress REST API responses for testing
# so we don't need a real WordPress container running to pass unit tests.

def mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    
    # Mock finding page by slug
    if "slug=railways" in url:
        return httpx.Response(200, json=[{"id": 4}])
    
    # Mock updating the page (POST)
    if "pages/4" in url and request.method == "POST":
        # Simulate success
        return httpx.Response(200, json={"id": 4, "status": "updated"})
    
    # Mock reading the page (GET)
    if "pages/4" in url and request.method == "GET":
        return httpx.Response(200, json={
            "id": 4, 
            "title": {"rendered": "New Optimized Title"},
            "meta": {"_yoast_wpseo_metadesc": "New Meta Desc"}
        })

    return httpx.Response(404, json={"message": "Not Found"})

original_client = httpx.AsyncClient

@pytest.fixture
def mock_client_factory():
    transport = httpx.MockTransport(mock_handler)
    def factory(*args, **kwargs):
        kwargs['transport'] = transport
        return original_client(*args, **kwargs)
    return factory

@pytest.mark.asyncio
async def test_apply_title_change(monkeypatch, mock_client_factory):
    connector = WordPressConnector(wp_app_pass="testpass")
    
    # Mock httpx.AsyncClient to return a new client using our factory
    monkeypatch.setattr(httpx, "AsyncClient", mock_client_factory)

    suggestion = {
        "field_type": "title_tag",
        "suggested_value": "New Optimized Title",
        "page_url": "/railways/"
    }
    
    success, error = await connector.apply_field(suggestion)
    assert success
    
    # Verify the value was actually updated (our mock returns the new value)
    new_value = await connector.read_field("/railways/", "title_tag", "title")
    assert new_value == "New Optimized Title"

@pytest.mark.asyncio
async def test_apply_meta_description(monkeypatch, mock_client_factory):
    connector = WordPressConnector(wp_app_pass="testpass")
    monkeypatch.setattr(httpx, "AsyncClient", mock_client_factory)

    suggestion = {
        "field_type": "meta_description",
        "suggested_value": "New Meta Desc",
        "page_url": "/railways/"
    }
    
    success, error = await connector.apply_field(suggestion)
    assert success
    
    new_value = await connector.read_field("/railways/", "meta_description", "meta")
    assert new_value == "New Meta Desc"

@pytest.mark.asyncio
async def test_apply_failure_on_invalid_field(monkeypatch, mock_client_factory):
    connector = WordPressConnector(wp_app_pass="testpass")
    monkeypatch.setattr(httpx, "AsyncClient", mock_client_factory)

    suggestion = {
        "field_type": "invalid_field_type",
        "suggested_value": "New Value",
        "page_url": "/railways/"
    }
    
    success, error = await connector.apply_field(suggestion)
    assert not success
    assert "Unsupported field_type" in error

@pytest.mark.asyncio
async def test_rollback_suggestion(monkeypatch, mock_client_factory):
    connector = WordPressConnector(wp_app_pass="testpass")
    monkeypatch.setattr(httpx, "AsyncClient", mock_client_factory)

    suggestion = {
        "field_type": "title_tag",
        "suggested_value": "New Optimized Title",
        "rollback_value": "Old Title",
        "page_url": "/railways/"
    }
    
    # Rollback should succeed if the underlying apply succeeds
    success, error = await connector.rollback_field(suggestion)
    assert success
