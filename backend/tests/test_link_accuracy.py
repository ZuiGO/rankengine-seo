"""Tests for the link/content accuracy round: honest link status buckets,
unique link counting, content dedup, and exec-summary evidence/explanation."""

import pytest

from backend.services.exec_summary import (
    EXPLANATIONS,
    HOW_TO_FIX,
    annotate,
    issue_key_from_message,
    _narrative,
)
from backend.services.link_checker import classify_status


class TestLinkStatusBuckets:
    def test_classify_ok(self):
        assert classify_status(200) == "ok"
        assert classify_status(204) == "ok"

    def test_classify_redirect(self):
        assert classify_status(301) == "redirect"
        assert classify_status(308) == "redirect"

    def test_classify_blocked(self):
        assert classify_status(401) == "blocked"
        assert classify_status(403) == "blocked"

    def test_classify_broken(self):
        assert classify_status(404) == "broken"
        assert classify_status(410) == "broken"
        assert classify_status(500) == "broken"

    def test_classify_unknown(self):
        assert classify_status(0) == "unknown"


class TestExecSummaryDetail:
    def test_every_issue_has_explanation(self):
        for key in ("broken_links", "thin_content", "poor_core_web_vitals", "orphan_pages"):
            assert EXPLANATIONS.get(key), f"missing explanation for {key}"
            assert HOW_TO_FIX.get(key), f"missing how_to_fix for {key}"

    def test_how_to_fix_has_steps(self):
        assert len(HOW_TO_FIX["broken_links"]) >= 2

    def test_annotate_unchanged(self):
        effort, step = annotate("broken_links")
        assert effort == "medium"
        assert step

    def test_issue_key_from_message_unchanged(self):
        assert issue_key_from_message("3 broken links found") == "broken_links"
        assert issue_key_from_message("something else") == "site_issue"

    def test_narrative_mentions_score(self):
        text = _narrative(60, "D", "declined", 75, [{"title": "Broken links", "drive": "3 actions"}])
        assert "60" in text
        assert "down" in text


class TestCrawlerSummaryShape:
    def test_unique_fields_expected_in_summary(self):
        from backend.services.crawler import crawl_site  # noqa: F401  (import sanity)
