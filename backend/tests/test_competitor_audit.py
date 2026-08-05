"""Tests for the free-tools competitor gap analysis round."""

import pytest

from backend.services.competitor_audit import (
    _avg,
    _content_gap,
    _domain,
    _jaccard,
    _onpage_gap,
    _rate,
    _schema_gap,
    _technical_gap,
    _token_set,
    _ux_gap,
)


def _target(health_metrics=None, pages=None, sd_types=None):
    pages = pages or []
    return {
        "health": {"metrics": health_metrics or {}},
        "sd_types": set(sd_types or []),
        "pages": pages,
        "titles": {p.get("url", ""): p.get("title", "") for p in pages},
        "word_counts": [p.get("word_count") or 0 for p in pages],
        "mobile_friendly": sum(1 for p in pages if p.get("mobile_friendly", True)),
    }


class TestHelpers:
    def test_domain_strips_scheme_and_path(self):
        assert _domain("https://shop.example.com/path/page") == "shop.example.com"

    def test_rate(self):
        assert _rate(2, 4) == 50.0
        assert _rate(0, 0) is None

    def test_token_set_and_jaccard(self):
        assert _token_set("SEO Guide for 2026") == {"seo", "guide", "for", "2026"}
        assert _jaccard({"a", "b"}, {"a", "c"}) == 1 / 3
        assert _jaccard(set(), {"a"}) == 0.0

    def test_avg(self):
        assert _avg([1, 2, 3]) == 2.0
        assert _avg([None, 4]) == 4.0
        assert _avg([]) is None


class TestContentGap:
    @pytest.mark.asyncio
    async def test_missing_page_flagged(self):
        comp = [{"url": "https://comp.com/faq", "title": "Complete FAQ list", "h1_count": 1}]
        target = _target(pages=[{"url": "https://me.com/home", "title": "Welcome home page", "word_count": 500}])
        gap = await _content_gap(comp, target)
        assert gap["missing_count"] == 1
        assert gap["missing"][0]["url"].endswith("/faq")

    @pytest.mark.asyncio
    async def test_near_duplicate_not_flagged(self):
        comp = [{"url": "https://comp.com/seo", "title": "SEO Guide 2026 tools", "h1_count": 1}]
        target = _target(pages=[{"url": "https://me.com/seo-guide", "title": "SEO Guide 2026 tools explained", "word_count": 900}])
        gap = await _content_gap(comp, target)
        assert gap["missing_count"] == 0

    @pytest.mark.asyncio
    async def test_empty_comp_titles(self):
        gap = await _content_gap([{"url": "u", "title": "", "h1_count": 0}], _target())
        assert gap["missing_count"] == 0


class TestSchemaGap:
    @pytest.mark.asyncio
    async def test_missing_type_detected(self):
        comp_sd = {"type_counts": {"Product 3": 3, "FAQPage 1": 1}}
        target = _target(sd_types=["Product"])
        gap = await _schema_gap(comp_sd, target)
        assert "FAQPage" in gap["missing_from_target"]
        assert "Product" not in gap["missing_from_target"]

    @pytest.mark.asyncio
    async def test_no_gap(self):
        comp_sd = {"type_counts": {"Organization 1": 1}}
        target = _target(sd_types=["Organization"])
        assert (await _schema_gap(comp_sd, target))["missing_from_target"] == []

    @pytest.mark.asyncio
    async def test_no_comp_sd(self):
        gap = await _schema_gap(None, _target(sd_types=["Organization"]))
        assert gap["missing_from_target"] == []


class TestTechnicalGap:
    @pytest.mark.asyncio
    async def test_deltas(self):
        comp_health = {"metrics": {"broken_link_rate": 12.0}}
        comp_pages = [{"https_entry": True, "redirect_count": 0, "click_depth": 2}]
        target = _target(
            health_metrics={"broken_link_rate": 4.0},
            pages=[{"https_entry": True, "redirect_count": 1, "click_depth": 1}],
        )
        gap = await _technical_gap(comp_health, comp_pages, target)
        assert gap["broken_link_rate"]["delta"] == 8.0
        assert gap["redirected_pages"]["competitor"] == 0
        assert gap["https_pages_pct"]["competitor"] == 100.0

    @pytest.mark.asyncio
    async def test_missing_metric(self):
        gap = await _technical_gap(
            {"metrics": {}},
            [{"https_entry": False, "redirect_count": 0}],
            _target(pages=[{"https_entry": True}]),
        )
        assert gap["broken_link_rate"]["delta"] in (None, "n/a")


class TestOnpageGap:
    @pytest.mark.asyncio
    async def test_delta_and_word_count(self):
        comp_health = {"metrics": {"meta_description_coverage": 80.0, "h1_coverage": 90.0}}
        comp_pages = [{"word_count": 400}, {"word_count": 600}]
        target = _target(
            health_metrics={"meta_description_coverage": 50.0, "h1_coverage": 70.0},
            pages=[{"word_count": 300}],
        )
        gap = await _onpage_gap(comp_health, comp_pages, target)
        assert gap["meta_coverage_pct"]["delta"] == 30.0
        assert gap["avg_word_count"]["competitor"] == 500.0
        assert gap["avg_word_count"]["target"] == 300.0


class TestUxGap:
    @pytest.mark.asyncio
    async def test_deltas(self):
        comp_health = {"metrics": {"avg_cwv_score": 90.0}}
        comp_pages = [{"mobile_friendly": True}, {"mobile_friendly": True}]
        target = _target(
            health_metrics={"avg_cwv_score": 70.0},
            pages=[{"mobile_friendly": True}, {"mobile_friendly": False}],
        )
        gap = await _ux_gap(comp_health, comp_pages, target)
        assert gap["avg_cwv_score"]["delta"] == 20.0
        assert gap["mobile_friendly_pct"]["competitor"] == 100.0
        assert gap["mobile_friendly_pct"]["target"] == 50.0