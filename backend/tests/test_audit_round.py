"""Tests for the complete-audit round: exec summary, sitemap parsing, E-E-A-T /
extractability signals, AI visibility, and local-SEO heuristics."""

import pytest

from backend.services.content_signals import compute_page_signals
from backend.services.exec_summary import annotate, issue_key_from_message
from backend.services.link_checker import classify_status

RICH_HTML = """
<html><head>
<meta name="author" content="Jane Doe">
<meta property="article:published_time" content="2026-01-01">
<meta property="og:site_name" content="ZuiGO">
<script type="application/ld+json">{"@type": "Organization"}</script>
</head><body>
<h1>Title</h1><h2>FAQ</h2>
<ul><li>a</li></ul><ul><li>b</li></ul><ul><li>c</li></ul>
<table><tr><td>x</td></tr></table>
</body></html>
"""


class TestExecSummary:
    def test_annotate_known_issue(self):
        effort, step = annotate("broken_links")
        assert effort == "medium"
        assert "broken" in step.lower()

    def test_annotate_unknown_issue_falls_back(self):
        effort, step = annotate("totally_new_key")
        assert effort == "medium"

    def test_issue_key_from_message_matches(self):
        assert issue_key_from_message("3 broken links found") == "broken_links"
        assert issue_key_from_message("Sitemap could not be parsed") == "sitemap_issues"
        assert issue_key_from_message("AI crawlers blocked") == "ai_visibility_low"

    def test_issue_key_unknown_defaults_site_issue(self):
        assert issue_key_from_message("something else") == "site_issue"


class TestContentSignals:
    def test_rich_page_has_signals(self):
        sig = compute_page_signals(RICH_HTML)
        assert "author" in sig["present"]
        assert "publisher" in sig["present"]
        assert sig["extractable_format"] is True
        assert sig["faq_sections"] == 1

    def test_bare_page_missing_signals(self):
        sig = compute_page_signals("<html><body><h1>hi</h1></body></html>")
        assert "author" in sig["missing_signals"]
        assert sig["extractable_format"] is False

    def test_empty_html_no_crash(self):
        sig = compute_page_signals("")
        assert sig["extractable_format"] is False


class TestLinkClassifier:
    def test_redirect_chain_status(self):
        assert classify_status(301) == "redirect"
        assert classify_status(200) == "ok"
        assert classify_status(404) == "broken"
        assert classify_status(403) == "blocked"