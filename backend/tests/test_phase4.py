"""Unit tests for Phase 4 changes (pure logic + faked DB, no network)."""

import asyncio

from bs4 import BeautifulSoup

from backend.services.dummy_site import _apply_changes, _normalize_page_url
from backend.services.change_applier import FIELD_BY_TYPE, FALLBACK_AFTER

class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, **kwargs):
        return FakeCursor(self.docs, query)


class FakeCursor:
    def __init__(self, docs, query):
        self.docs = [d for d in docs if self._matches(d, query)]

    def _matches(self, doc, query):
        for k, v in query.items():
            if isinstance(v, dict):
                if "$ne" in v and doc.get(k) == v["$ne"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    async def to_list(self, length):
        return self.docs[:length]


class FakeDb:
    def __init__(self, versions, actions):
        self.content_versions = FakeCollection(versions)
        self.action_items = FakeCollection(actions)


class TestNormalizePageUrl:
    def test_strips_www_and_slash(self):
        assert _normalize_page_url("https://www.Example.com/About/") == "https://www.example.com/about"

    def test_removes_index_html(self):
        assert _normalize_page_url("https://x.com/index.html") == "https://x.com"

    def test_removes_utm_query(self):
        assert _normalize_page_url("https://x.com/a?utm_source=x") == "https://x.com/a"


class TestFieldRegistry:
    def test_known_fields_covered(self):
        for f in ("image", "text", "pdf", "doc", "video", "audio"):
            assert f in FIELD_BY_TYPE
        assert FIELD_BY_TYPE["text"] == "meta_description"

    def test_fallback_after_known(self):
        for f in ("title", "meta_description", "alt_text", "link_text"):
            assert f in FALLBACK_AFTER


class TestApplyChanges:
    def _run(self, versions, actions, html):
        db = FakeDb(versions, actions)
        soup = BeautifulSoup(
            f"""<html><head><title>T</title><meta name="description" content="d"></head>
            <body><h1>H</h1><p>{html}</p></body></html>""",
            "lxml",
        )
        import backend.services.dummy_site as ds
        original = ds.get_db
        ds.get_db = lambda: db
        try:
            return asyncio.run(_apply_changes(soup, "job1", "https://example.com/"))
        finally:
            ds.get_db = original

    def test_approved_version_applied(self):
        versions = [{
            "job_id": "job1", "status": "approved", "after": "New title",
            "page_url": "https://example.com/", "field": "title",
            "action_id": "act1", "source_url": "https://example.com/",
        }]
        applied, suggested, remaining = self._run(versions, [], "x")
        assert applied == 1
        assert suggested == 0

    def test_pending_suggestion_generated(self):
        actions = [{
            "job_id": "job1", "status": "pending", "content_type": "text",
            "page_url": "https://example.com/",
            "source_url": "https://example.com/old.html",
        }]
        applied, suggested, remaining = self._run([], actions, "x")
        assert suggested == 1
        assert applied == 0

    def test_approved_action_not_double_counted(self):
        versions = [{
            "job_id": "job1", "status": "approved", "after": "New title",
            "page_url": "https://example.com/", "field": "title",
            "action_id": "act1", "source_url": "https://example.com/",
        }]
        actions = [{
            "job_id": "job1", "status": "pending", "content_type": "text",
            "page_url": "https://example.com/",
            "source_url": "https://example.com/old.html", "_id": "act1",
        }]
        applied, suggested, remaining = self._run(versions, actions, "x")
        assert applied == 1
        assert suggested == 0

    def test_other_pages_untouched(self):
        versions = [{
            "job_id": "job1", "status": "approved", "after": "Other title",
            "page_url": "https://other.com/", "field": "title",
            "action_id": "act1", "source_url": "https://other.com/",
        }]
        applied, suggested, remaining = self._run(versions, [], "x")
        assert applied == 0
        assert suggested == 0
