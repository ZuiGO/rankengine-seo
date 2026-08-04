"""Unit tests for patch export, llms.txt builder and new AI-readable page checks."""

import asyncio

import backend.routes.actions as actions_module
from backend.services.dummy_site import build_llms_txt
from backend.services.seo_analyzer import run_page_checks
from backend.services.structured_data import validate_structured_data


def run(coro):
    return asyncio.run(coro)


def make_action(oid, ctype="image", status="pending", issue_key="image_alt_missing"):
    return {
        "_id": oid,
        "job_id": "job1",
        "content_type": ctype,
        "page_url": "https://example.com/page",
        "impact_on_ranking": "high",
        "status": status,
        "issue_key": issue_key,
        "identified_issues": ["Image has no alt text"],
        "improvement_suggestions": ["Add descriptive alt text"],
        "evidence": {"alt": ""},
    }


def make_version(action_id, status="approved"):
    return {
        "action_id": action_id,
        "field": "alt_text",
        "before": "",
        "after": "A red book cover",
        "diff": ["- ", "+ A red book cover"],
        "generated_by": "fallback",
        "qa": "template",
    }


class FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query, projection=None):
        return FakeCursor(self.docs)

    async def find_one(self, query, projection=None):
        for d in self.docs:
            if d.get("_id") == query.get("_id") or d.get("_id") == query:
                return d
        return None


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, length):
        return self.docs[:length]


class FakeDb:
    def __init__(self, actions, job=None):
        self.action_items = FakeCollection(actions)
        self.analysis_jobs = FakeCollection([job or {"_id": "job1", "url": "https://example.com"}])


class TestExportPatch:
    def _db(self, actions, versions):
        db = FakeDb(actions)
        return db, versions

    def test_json_patch_structure(self, monkeypatch):
        actions = [make_action("a" * 24, status="approved")]
        db, versions = self._db(actions, [make_version("a" * 24)])
        monkeypatch.setattr(actions_module, "get_db", lambda: db)
        async def _fake_versions(job_id, limit=500):
            return {"versions": versions, "total": 1, "applied": 1}
        monkeypatch.setattr(actions_module, "get_content_versions", _fake_versions)

        result = run(actions_module.export_patch("job1", "json"))
        assert result["patch_version"] == 1
        assert result["site"] == "https://example.com"
        assert result["summary"]["approved"] == 1
        change = result["changes"][0]
        assert change["issue_key"] == "image_alt_missing"
        assert change["version"]["after"] == "A red book cover"

    def test_markdown_patch(self, monkeypatch):
        actions = [make_action("a" * 24, status="approved")]
        db, versions = self._db(actions, [make_version("a" * 24)])
        monkeypatch.setattr(actions_module, "get_db", lambda: db)
        async def _fake_versions(job_id, limit=500):
            return {"versions": versions, "total": 1, "applied": 1}
        monkeypatch.setattr(actions_module, "get_content_versions", _fake_versions)

        resp = run(actions_module.export_patch("job1", "md"))
        assert resp.media_type.startswith("text/markdown")
        assert "# SEO Patch" in resp.body.decode()
        assert "A red book cover" in resp.body.decode()

    def test_version_missing_when_not_reviewed(self, monkeypatch):
        actions = [make_action("a" * 24, status="pending")]
        db, versions = self._db(actions, [])
        monkeypatch.setattr(actions_module, "get_db", lambda: db)
        async def _fake_versions(job_id, limit=500):
            return {"versions": [], "total": 0, "applied": 0}
        monkeypatch.setattr(actions_module, "get_content_versions", _fake_versions)

        result = run(actions_module.export_patch("job1", "json"))
        assert result["changes"][0]["version"] is None
        assert result["summary"]["pending"] == 1


class TestLlmsTxt:
    def test_llms_txt_lists_pages(self):
        pages = [
            {"url": "https://example.com/", "title": "Home", "meta_description": "Example homepage"},
            {"url": "https://example.com/about/", "title": "About Us"},
        ]
        text = build_llms_txt(pages, "https://example.com")
        assert text.startswith("# ZuiGO.ai Mirror")
        assert "example.com" in text
        assert "About Us" in text
        assert "Example homepage" in text
        assert text.count("- [") == 2


class TestAiReadableChecks:
    def test_no_structured_data_flagged(self):
        page = {"url": "https://example.com/a", "is_indexable": True, "page_type": "product"}
        checks = run_page_checks(page, {"sd": {"https://example.com/a": False}})
        keys = {c["issue_key"] for c in checks}
        assert "no_structured_data" in keys

    def test_structured_data_present_not_flagged(self):
        html = '<html><head><script type="application/ld+json">{"@type": "Product"}</script></head></html>'
        report = validate_structured_data("https://example.com/a", html)
        page = {"url": "https://example.com/a", "is_indexable": True}
        checks = run_page_checks(page, {"sd": {"https://example.com/a": report["has_structured_data"]}})
        assert not any(c["issue_key"] == "no_structured_data" for c in checks)

    def test_no_ctx_skips_sd_check(self):
        page = {"url": "https://example.com/a", "is_indexable": True}
        checks = run_page_checks(page, {})
        assert not any(c["issue_key"] == "no_structured_data" for c in checks)

    def test_entity_coverage_low_flagged(self):
        page = {"url": "https://example.com/a", "is_indexable": True,
                "title": "Random Topic", "meta_description": "Unrelated content"}
        checks = run_page_checks(page, {"corpus_keywords": ["books", "fiction"]})
        assert any(c["issue_key"] == "entity_coverage_low" for c in checks)

    def test_entity_coverage_match_not_flagged(self):
        page = {"url": "https://example.com/a", "is_indexable": True,
                "title": "Best Books of 2026", "meta_description": "Fiction picks"}
        checks = run_page_checks(page, {"corpus_keywords": ["books", "fiction"]})
        assert not any(c["issue_key"] == "entity_coverage_low" for c in checks)

    def test_no_corpus_skips_entity_check(self):
        page = {"url": "https://example.com/a", "is_indexable": True, "title": "Anything"}
        checks = run_page_checks(page, {})
        assert not any(c["issue_key"] == "entity_coverage_low" for c in checks)
