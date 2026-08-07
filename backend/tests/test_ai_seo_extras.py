"""Tests for the ai-seo skill integration: extractability/authority scan
helpers, machine-readable-file probes, chat guidance wiring, and exec-summary
mapping of AI-citation issues."""

import pytest

from backend.services.ai_visibility import (
    _ai_extractability,
    _is_fresh,
    _parse_date,
    _parse_robots,
    _word_count,
)
from backend.services import ai_visibility as ai_mod, exec_summary, chat_service


class FakeCollection:
    def __init__(self, store):
        self._store = store

    def find(self, q, projection=None):
        return self

    async def to_list(self, length=None):
        items = list(self._store.values())
        return [dict(x) for x in items][:length] if length is not None else [dict(x) for x in items]

    async def find_one(self, q):
        for v in self._store.values():
            if all(v.get(k) == fv for k, fv in q.items()):
                return dict(v)
        return None

    async def update_one(self, q, update, upsert=False):
        key = next(iter(q.values()))
        self._store[key] = {**(self._store.get(key) or {}), **update.get("$set", {})}


class FakeDb:
    def __init__(self):
        self._stores = {
            "pages": {}, "sitemap_audits": {}, "ai_visibility_summaries": {},
            "programmatic_seo_audits": {},
        }

    def __getattr__(self, name):
        if name in self._stores:
            return FakeCollection(self._stores[name])
        raise AttributeError(name)


class TestHelpers:
    def test_word_count(self):
        assert _word_count("one two three") == 3

    def test_parse_date(self):
        assert _parse_date("2026-07-01") == _parse_date("2026-07-01T00:00:00")
        assert _parse_date("garbage") is None

    def test_is_fresh(self):
        assert _is_fresh("2026-07-01")
        assert not _is_fresh("2020-01-01")

    def test_extractability_core_block(self):
        html = (
            "<html><head><meta name='author' content='Jane'>"
            "<meta property='article:modified_time' content='2026-07-01'></head><body>"
            "<p>This is a forty word standalone answer paragraph that nicely falls inside "
            "the optimal range for generative engines to extract the substance of the page.</p>"
            "<h2>Is it any good?</h2><table><tr><td>x</td></tr></table>"
            "<p>According to our data 42%% of users saw gains <a href='/r'>source</a></p>"
            "<main><article>hi</article><nav>n</nav></main></body></html>"
        )
        ex = _ai_extractability(html)
        assert ex["author"] is True
        assert ex["fresh"] is True
        assert ex["faq_heading"] >= 1
        assert ex["comparison_table"] >= 1
        assert ex["stat_cited"] >= 1
        assert ex["semantic_landmark"] is True


class TestAuditAiVisibility:
    @pytest.mark.asyncio
    async def test_ai_files_and_scan_counts(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(ai_mod, "get_db", lambda: db)
        html = (
            "<html><head><meta name='author' content='Jane'>"
            "<meta property='article:modified_time' content='2026-07-01'></head><body>"
            "<p>This is a forty word standalone paragraph that is a perfect little answer "
            "block for generative engines to lift out of the page and cite directly.</p>"
            "<table><tr><td>x</td></tr></table></body></html>"
        )
        for i in range(3):
            db._stores["pages"][f"https://x.com/p{i}.html"] = {
                "job_id": "j1", "url": f"https://x.com/p{i}.html", "html": html,
            }
        db._stores["sitemap_audits"]["s1"] = {"job_id": "j1", "sitemap_valid": True}

        async def fake_fetch(url, ua):
            if "pricing.md" in url:
                return ("# Pricing\n\nPro $29/month", 200)
            if "okf" in url:
                return ("okf bundle index", 200)
            return None, 404

        monkeypatch.setattr(ai_mod, "_fetch_plain", fake_fetch)
        summary = await ai_mod.check_ai_visibility("j1", "https://x.com")
        assert summary["pricing_md_present"] is True
        assert summary["okf_present"] is True
        assert summary["scanned_pages"] == 3
        assert summary["author_pages"] == 3
        assert summary["fresh_pages"] == 3
        labels = [c.get("label", "") for c in summary["checks"]]
        assert any("pricing" in l for l in labels)
        assert any("author" in l.lower() for l in labels)
        assert db._stores["ai_visibility_summaries"]["j1"]["score"] == summary["score"]

    @pytest.mark.asyncio
    async def test_blocked_training_agents_reported(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(ai_mod, "get_db", lambda: db)
        async def fake_fetch(url, ua):
            return (None, 404) if "robots" not in url else ("User-agent: CCBot\nDisallow: /\n", 200)

        monkeypatch.setattr(ai_mod, "_fetch_plain", fake_fetch)
        monkeypatch.setattr(
            ai_mod,
            "_ld_types",
            lambda html: set(),
        )
        db._stores["pages"]["h"] = {"job_id": "j1", "url": "https://x.com/", "html": "<html></html>"}
        summary = await ai_mod.check_ai_visibility("j1", "https://x.com")
        assert summary["blocked_training_agents"] == ["ccbot"]
        assert any("training-only" in c.get("label", "") for c in summary["checks"])


class TestChatAndSummaryWiring:
    def test_guidance_vendored_into_prompts(self):
        assert "Programmatic-SEO guidance" in chat_service.SYSTEM_PROMPT
        assert "AI-search (AEO/GEO) guidance" in chat_service.SYSTEM_PROMPT
        assert "programmatic-SEO" in chat_service.FULL_SITE_PROMPT
        assert "programmatic-seo skill" in chat_service.PROGRAMMATIC_SEO_GUIDANCE
        assert "ai-seo skill" in chat_service.AI_SEO_GUIDANCE
        assert "programmatic" in chat_service.GENERAL_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_context_builders(self, monkeypatch):
        db = FakeDb()
        db._stores["programmatic_seo_audits"]["j1"] = {
            "job_id": "j1", "score": 70, "clusters_count": 2, "template_pages": 8,
            "total_pages": 10, "template_page_share": 80.0, "thin_template_pages": 1,
            "duplicate_template_pages": 0, "unlinked_template_pages": 0,
            "duplicate_title_template_pages": 0, "not_indexable_template_pages": 0,
            "clusters": [{"pattern": "/locations/{slug}/", "page_count": 5, "thin_pages": 1,
                          "duplicate_pages": 0, "unlinked_pages": 0}],
        }
        db._stores["ai_visibility_summaries"]["j1"] = {
            "job_id": "j1", "score": 50, "llms_txt_present": True, "pricing_md_present": True,
            "pricing_txt_present": False, "okf_present": False, "blocked_ai_agents": [],
            "blocked_training_agents": [], "scanned_pages": 3, "answer_block_pages": 2,
            "author_pages": 1, "fresh_pages": 1, "faq_heading_pages": 1, "comparison_table_pages": 1,
        }
        monkeypatch.setattr(chat_service, "get_db", lambda: db)
        pctx = await chat_service._programmatic_seo_context("j1")
        assert "70/100" in pctx and "/locations/{slug}/" in pctx
        aictx = await chat_service._ai_seo_context("j1")
        assert "50/100" in aictx and "pricing.md=True" in aictx

    def test_exec_keys_exist(self):
        for key, val in exec_summary.EFFORT.items():
            assert key in exec_summary.TITLES
            assert key in exec_summary.EXPLANATIONS
            assert key in exec_summary.HOW_TO_FIX
        for k in ("programmatic_thin", "programmatic_duplicates", "programmatic_linking", "ai_pricing_md", "ai_eaat_signals"):
            assert k in exec_summary.EFFORT
        assert exec_summary.issue_key_from_message("No /pricing.md machine-readable file") == "ai_pricing_md"
        assert exec_summary.issue_key_from_message("No author attribution detected") == "ai_eaat_signals"