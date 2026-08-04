"""Unit tests for Phase 5 additions (GEO readiness, trends helpers, chat prompt)."""

from backend.services.geo_readiness import check_robots_text
from backend.routes.trends import _domain_of
from backend.services.chat_service import FULL_SITE_PROMPT, SYSTEM_PROMPT


class TestGeoReadiness:
    def test_blocked_ai_bots(self):
        robots = """User-agent: *
Disallow: /private/
User-agent: GPTBot
Disallow: /
User-agent: PerplexityBot
Disallow: /
"""
        r = check_robots_text(robots)
        assert r["status"] == "blocked"
        assert r["score"] == 0
        assert "GPTBot" in r["blocked_ai_crawlers"]
        assert "PerplexityBot" in r["blocked_ai_crawlers"]

    def test_allowed_ai_bots(self):
        robots = """User-agent: *
Allow: /
User-agent: GPTBot
Allow: /
"""
        r = check_robots_text(robots)
        assert r["status"] == "allowed"
        assert r["score"] == 100
        assert r["blocked_ai_crawlers"] == []

    def test_no_rules_defaults_to_allowed(self):
        r = check_robots_text("# empty ruleset\nUser-agent: *\n")
        assert r["status"] == "allowed-by-default"
        assert r["score"] == 80

    def test_empty_robots(self):
        r = check_robots_text("")
        assert r["status"] == "allowed-by-default"

    def test_google_extended_detected(self):
        robots = "User-agent: Google-Extended\nDisallow: /"
        r = check_robots_text(robots)
        assert "Google-Extended" in r["blocked_ai_crawlers"]


class TestTrendsHelpers:
    def test_domain_of(self):
        assert _domain_of("https://www.example.com/path/page") == "www.example.com"
        assert _domain_of("") == ""
        assert _domain_of("example.com") == "example.com"


class TestChatFullSite:
    def test_full_site_prompt_covers_all_sections(self):
        for section in ("overview", "pages", "content", "links", "actions", "insights", "health"):
            assert section in FULL_SITE_PROMPT.lower()

    def test_system_prompt_composes_with_full_site(self):
        combined = SYSTEM_PROMPT + "\n\n" + FULL_SITE_PROMPT
        assert "ENTIRE site analysis" in combined
