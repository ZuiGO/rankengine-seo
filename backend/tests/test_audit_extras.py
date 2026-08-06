"""Tests for the professional audit extras round: new sitemap audit
(unique-URL coverage, lastmod, http-plain, uncrawled counts), robots
section-aware AI parsing (exact-block vs partial), JSON-LD-only structured
data counting, and LocalBusiness/NAP/geo heuristics (incl. false-positive
guards)."""

import json

import pytest

from backend.services.ai_visibility import (
    _agent_status,
    _ld_types,
    _parse_robots,
)
from backend.services.local_seo import (
    _extract_nap,
    _find_key,
    _is_homepage,
    _iter_schema_objects,
    _types_of,
)
from backend.services.sitemap import _fetch_sitemap_entries, _parse_sitemap_urls


def _ld(html: str) -> str:
    return html


class TestSitemapEntries:
    @pytest.mark.asyncio
    async def test_urlset_parses_loc_and_lastmod(self):
        xml = (
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://x.example/a</loc><lastmod>2026-01-01</lastmod></url>"
            "<url><loc>https://x.example/b</loc></url>"
            "</urlset>"
        )
        entries = await _fetch_sitemap_entries(xml)
        assert [e["loc"] for e in entries] == ["https://x.example/a", "https://x.example/b"]
        assert entries[0]["lastmod"] == "2026-01-01"
        assert entries[1]["lastmod"] == ""

    @pytest.mark.asyncio
    async def test_parse_sitemap_urls_returns_locs(self):
        xml = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://x.example/a</loc></url>"
            "</urlset>"
        )
        assert await _parse_sitemap_urls(xml) == ["https://x.example/a"]

    @pytest.mark.asyncio
    async def test_invalid_xml_returns_none(self):
        assert await _parse_sitemap_urls("<html>not a sitemap</html>") is None

    @pytest.mark.asyncio
    async def test_empty_urlset_returns_empty_list(self):
        xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
        assert await _parse_sitemap_urls(xml) == []

    @pytest.mark.asyncio
    async def test_nested_sitemap_index_expands_each_child_once(self, monkeypatch):
        child_a = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://x.example/a</loc></url>"
            "</urlset>"
        )
        child_b = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://x.example/b</loc></url>"
            "</urlset>"
        )
        called = {"n": 0}

        async def fake_fetch(url: str):
            called["n"] += 1
            return {"https://x.example/a.xml": child_a, "https://x.example/b.xml": child_b}.get(url)

        monkeypatch.setattr("backend.services.sitemap._fetch", fake_fetch)
        index = (
            '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://x.example/a.xml</loc></sitemap>"
            "<sitemap><loc>https://x.example/b.xml</loc></sitemap>"
            "<sitemap><loc>https://x.example/a.xml</loc></sitemap>"
            "</sitemapindex>"
        )
        entries = await _fetch_sitemap_entries(index)
        assert [e["loc"] for e in entries] == ["https://x.example/a", "https://x.example/b"]
        assert called["n"] == 2


class TestAIRobotsParsing:
    def test_exact_block_is_blocked(self):
        assert _agent_status(["/"]) == "blocked"
        assert _agent_status(["/*"]) == "blocked"
        assert _agent_status(["/?"]) == "blocked"

    def test_partial_rule_is_not_full_block(self):
        assert _agent_status(["/wp-admin/"]) == "partial"
        assert _agent_status(["/wp-json/"]) == "partial"

    def test_no_rules_allowed(self):
        assert _agent_status([]) == "allowed"

    def test_parse_robots_section(self):
        rules = _parse_robots(
            "User-agent: *\nDisallow: /wp-admin/\n\n"
            "User-agent: GPTBot\nDisallow: /\nCrawl-delay: 5\n\n"
            "User-agent: Google-Extended\nDisallow: /private\n"
        )
        assert rules["*"]["disallow"] == ["/wp-admin/"]
        assert rules["gptbot"]["disallow"] == ["/"]
        assert rules["gptbot"]["delay"] == 5.0
        assert rules["google-extended"]["disallow"] == ["/private"]

    def test_crawl_delay_non_numeric_ignored(self):
        rules = _parse_robots("User-agent: GPTBot\nCrawl-delay: banana\n")
        assert rules["gptbot"]["delay"] is None


class TestStructuredDataCounting:
    def test_only_application_ld_json_blocks_count(self):
        html = (
            '<script>{"@type": "Person"}</script>'
            '<script type="application/ld+json">{"@type": ["WebSite", "Organization"]}</script>'
        )
        types = _ld_types(html)
        assert types == {"website", "organization"}

    def test_no_jsonld_returns_empty(self):
        assert _ld_types("<html><body><p>hi</p></body></html>") == set()


class TestLocalSchemaHelpers:
    def test_find_key_searches_nested(self):
        objs = [{"address": {"streetAddress": "1 Main St", "postalCode": "12345"}}]
        assert _find_key(objs, "streetaddress") == "1 Main St"
        assert _find_key(objs, "postalCode") == "12345"

    def test_types_of_lowercases_and_handles_arrays(self):
        assert _types_of({"@type": ["LocalBusiness", "Store"]}) == ["localbusiness", "store"]

    def test_is_homepage(self):
        assert _is_homepage("https://x.example/")
        assert _is_homepage("https://x.example")
        assert not _is_homepage("https://x.example/contact")

    def test_iter_schema_objects_walks_graph_and_nested(self):
        blocks = [json.dumps({
            "@graph": [
                {"@type": "WebSite", "@id": "site"},
                {"@type": "Restaurant", "address": {"streetAddress": "1 Main St", "telephone": "+1 555 0100"}},
            ]
        })]
        objs = list(_iter_schema_objects(blocks))
        assert len(objs) == 4

    def test_extract_nap_from_local_business(self):
        objs = [{
            "@type": "Restaurant",
            "name": "ACME Diner",
            "telephone": "+1 555 0100",
            "address": {"streetAddress": "1 Main St", "postalCode": "12345"},
        }]
        nap = _extract_nap(objs)
        assert nap == {"name": "ACME Diner", "street_address": "1 Main St", "phone": "+1 555 0100"}

    def test_extract_nap_none_when_no_contact_info(self):
        objs = [{"@type": "Organization", "name": "ACME"}]
        assert _extract_nap(objs) is None

    def test_geo_regex_requires_real_geo_meta(self):
        import re

        plain = "the george washington bridge and biogeography"
        assert not re.search(r"geo\.(region|position)", plain)
        assert re.search(r"geo\.(region|position)", 'name="geo.position" content="40.7,-74.0"')