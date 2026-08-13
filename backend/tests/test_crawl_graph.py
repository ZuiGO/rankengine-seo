import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

class FakeCursor:
    def __init__(self, items):
        self.items = items
    def __aiter__(self):
        return self._gen()
    async def _gen(self):
        for item in self.items:
            yield item
    async def to_list(self, length=None):
        return self.items

class FakeDb:
    def __init__(self):
        self.analysis_jobs = AsyncMock()
        self.pages = AsyncMock()
        self.link_health = AsyncMock()
        self.page_links = AsyncMock()

    def __getitem__(self, item):
        return getattr(self, item)


def test_get_crawl_graph_not_found():
    fake_db = FakeDb()
    fake_db.analysis_jobs.find_one = AsyncMock(return_value=None)
    with patch("backend.routes.links.get_db", return_value=fake_db):
        resp = client.get("/api/links/nonexistent/graph")
        assert resp.status_code == 200
        assert resp.json() == {"error": "Job not found"}


from unittest.mock import patch, AsyncMock, MagicMock

def test_get_crawl_graph_success():
    fake_db = FakeDb()
    fake_db.analysis_jobs.find_one = AsyncMock(return_value={"_id": "job123"})
    fake_db.pages.find = MagicMock(return_value=FakeCursor([
        {"url": "https://example.com/", "title": "Home", "status_code": 200, "word_count": 500, "page_type": "home"},
        {"url": "https://example.com/about", "title": "About", "status_code": 200, "word_count": 300, "page_type": "about"},
        {"url": "https://example.com/broken", "title": "Missing", "status_code": 404, "word_count": 0, "page_type": "other"},
    ]))
    fake_db.link_health.find = MagicMock(return_value=FakeCursor([
        {"url": "https://example.com/broken", "status": "broken", "status_code": 404, "external": False},
        {"url": "https://external.com", "status": "external", "status_code": 200, "external": True},
    ]))
    fake_db.page_links.find = MagicMock(return_value=FakeCursor([
        {"url": "https://example.com/", "internal_link_urls": ["https://example.com/about", "https://example.com/broken"], "external_link_urls": ["https://external.com"]},
        {"url": "https://example.com/about", "internal_link_urls": ["https://example.com/"], "external_link_urls": []},
    ]))

    with patch("backend.routes.links.get_db", return_value=fake_db):
        resp = client.get("/api/links/job123/graph?limit=100")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert data["total_nodes"] == 4
        assert data["broken_nodes_count"] == 1

        nodes_by_id = {n["id"]: n for n in data["nodes"]}
        assert nodes_by_id["https://example.com/"]["status"] == "ok"
        assert nodes_by_id["https://example.com/broken"]["status"] == "broken"
        assert nodes_by_id["https://external.com"]["status"] == "external"

        edges = data["edges"]
        assert len(edges) == 4
