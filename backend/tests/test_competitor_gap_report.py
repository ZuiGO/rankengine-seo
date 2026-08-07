"""Tests for the SE Ranking powered competitor gap report (se_rich block):

-_se_rich_gap assembles target (cached) vs competitor (live) metrics and
  degrades gracefully per-key when SE Ranking calls fail;
- _opportunity_score / _build_recommendations turn that data into a score and
  a prioritized recommendation list."""

import pytest

from backend.services.competitor_audit import (
    _build_recommendations,
    _opportunity_score,
    _se_rich_gap,
)
from backend.services.competitor_audit import build_competitor_report


class FakeCollection:
    def __init__(self, store):
        self._store = store

    async def find_one(self, q):
        for v in self._store.values():
            if all(v.get(fk) == fv for fk, fv in q.items()):
                return dict(v)
        return None


class FakeDb:
    def __init__(self, cache_doc=None):
        self._stores = {"seo_insights_cache": {}}
        if cache_doc:
            self._stores["seo_insights_cache"]["c1"] = cache_doc

    def __getattr__(self, name):
        if name in self._stores:
            return FakeCollection(self._stores[name])
        raise AttributeError(name)


def _kw(name, volume=100, cpc=1.5, difficulty=40):
    return {
        "keyword": name,
        "keyword_data": {
            "keyword_info": {"search_volume": volume, "cpc": cpc},
            "keyword_properties": {"keyword_difficulty": difficulty},
        },
    }


def _ranked(name, rank=3):
    return {"keyword": name, "rank": rank}


def _cache_doc():
    import copy
    return copy.deepcopy({
        "job_id": "target-job",
        "data": {
            "overview": {"estimated_organic_traffic": 100, "organic_keywords_count": 10},
            "keywords": [_kw("foundation", 60, 0.8, 30), _kw("target-only word", volume=300, difficulty=12)],
            "backlinks": {"backlinks": 50, "referring_domains": 10, "domain_rank": 20, "page_rank": 15},
            "overview_history": [{"date": "2026-01", "value": 90}],
            "overview_source": "se-ranking",
        },
    })


@pytest.mark.asyncio
async def test_se_rich_gap_assembles_and_reuses_cache(monkeypatch):
    from backend.services import competitor_audit as mod
    from backend.services import se_ranking as ser

    db = FakeDb(_cache_doc())
    monkeypatch.setattr(mod, "get_db", lambda: db)

    async def fake_overview(domain):
        return {"estimated_organic_traffic": 940, "organic_keywords_count": 120}

    async def fake_keywords(domain, limit=50):
        return [_kw("foundation"), _kw("valve types", 500, 2.1, 55), _kw("valve word", 800, 3.0, 70)]

    async def fake_ranked(domain, limit=50):
        return [_ranked("foundation", 0), _ranked("valve types", 5)]

    async def fake_backlinks(domain):
        return {"backlinks": 300, "referring_domains": 60, "domain_rank": 42, "page_rank": 38}

    async def fake_history(domain):
        return [{"date": "2026-01", "value": 800}]

    async def fake_backlink_list(domain, limit=50):
        return [{"source_domain": "authority.net", "domain_inlink_rank": 8}]

    async def fake_gap(primary, compare, limit=50):
        return []

    monkeypatch.setattr(ser, "domain_overview", fake_overview)
    monkeypatch.setattr(ser, "domain_keywords", fake_keywords)
    monkeypatch.setattr(ser, "ranked_keywords", fake_ranked)
    monkeypatch.setattr(ser, "backlink_summary", fake_backlinks)
    monkeypatch.setattr(ser, "domain_overview_history", fake_history)
    monkeypatch.setattr(ser, "backlink_list", fake_backlink_list)
    monkeypatch.setattr(ser, "keyword_gap", fake_gap)

    out = await _se_rich_gap("me.com", "comp.com", "target-job")

    assert out["target"]["overview"]["estimated_organic_traffic"] == 100
    assert out["competitor"]["overview"]["estimated_organic_traffic"] == 940
    assert out["target"]["source"] == "se-ranking"
    assert out["traffic_analysis"]["competitor_traffic"] == 940
    assert out["traffic_analysis"]["traffic_value_estimate"] == 3600.0
    assert out["authority_analysis"]["comp_domain_rank"] == 42
    assert out["authority_analysis"]["delta"] == 22
    assert out["backlink_analysis"]["high_authority_sources"][0]["source_domain"] == "authority.net"
    assert out["errors"] == []

    ka = out["keyword_analysis"]
    assert "valve types" in ka["missing_from_target"]
    assert "target-only word" in ka["unique_target"]
    assert ka["top_opportunities"] and ka["top_opportunities"][0]["keyword"] == "valve word"
    assert ka["top_opportunities"][0]["volume"] == 800
    assert any(s["keyword"] == "foundation" and s["comp"]["volume"] == 100 for s in ka["shared_detail"])


@pytest.mark.asyncio
async def test_se_rich_gap_degrades_on_api_failures(monkeypatch):
    from backend.services import competitor_audit as mod
    from backend.services import se_ranking as ser

    db = FakeDb(_cache_doc())
    monkeypatch.setattr(mod, "get_db", lambda: db)

    async def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(ser, "domain_overview", boom)
    monkeypatch.setattr(ser, "domain_keywords", boom)
    monkeypatch.setattr(ser, "ranked_keywords", boom)
    monkeypatch.setattr(ser, "backlink_summary", boom)
    monkeypatch.setattr(ser, "domain_overview_history", boom)
    monkeypatch.setattr(ser, "backlink_list", boom)
    monkeypatch.setattr(ser, "keyword_gap", boom)

    out = await _se_rich_gap("me.com", "comp.com", "target-job")
    assert out["competitor"] == {}
    assert out["keyword_analysis"]["missing_detail"] == []
    assert len(out["errors"]) == 7


def test_opportunity_score_and_recommendations():
    se_rich = {
        "keyword_analysis": {
            "missing_detail": [{"keyword": "a"} for _ in range(20)],
            "shared_detail": [{"keyword": "b"} for _ in range(5)],
        },
        "traffic_analysis": {"competitor_traffic": 1000, "target_traffic": 100},
        "backlink_analysis": {"backlinks_delta": 500, "referring_domains_delta": 40},
        "authority_analysis": {"comp_domain_rank": 50, "target_domain_rank": 20},
    }
    score = _opportunity_score(se_rich)
    assert isinstance(score, int)
    assert 0 <= score <= 100

    recs = _build_recommendations(se_rich)
    assert any(r["priority"] == "high" for r in recs)
    assert any("keyword" in r["title"].lower() for r in recs)
    assert any("backlink" in r["title"].lower() for r in recs)
    assert any("authority" in r["title"].lower() for r in recs)


def test_opportunity_score_none_when_no_comparable_data():
    assert _opportunity_score({}) is None
    assert _opportunity_score({"keyword_analysis": {}, "traffic_analysis": {}, "backlink_analysis": {}}) is None


def test_build_competitor_report_assembles_sections():
    row = {
        "competitor": "comp.com",
        "url": "https://comp.com",
        "pages_crawled": 25,
        "gap_count": 4,
        "status": "completed",
        "generated_at": "2026-08-07T10:00:00Z",
        "errors": [],
        "keyword_gap": {"gaps": ["serp word"], "errors": []},
        "content_gap": {"missing": [{"url": "https://comp.com/page", "title": "Page"}], "missing_count": 1, "comp_pages": 25},
        "technical_gap": {"broken_link_rate": {"target": 1.0, "competitor": 2.0, "delta": 1.0}},
        "schema_gap": {"missing_from_target": ["Offer"]},
        "serp_features_gap": {"comp_only": {"faq": ["What is a valve?"]}, "errors": []},
        "se_rich": {
            "opportunity_score": 74,
            "recommendations": [
                {"priority": "high", "title": "Target high-opportunity keywords you don't rank for",
                 "detail": "x", "count": 10}
            ],
            "comp_keywords_count": 120,
            "keyword_analysis": {
                "missing_from_target": ["valve"], "missing_detail": [], "shared_detail": [],
                "unique_target": [], "top_opportunities": [],
            },
            "traffic_analysis": {"target_traffic": 100, "competitor_traffic": 940},
            "backlink_analysis": {"referring_domains_delta": 40, "backlinks_delta": 500},
            "authority_analysis": {"target_domain_rank": 20, "comp_domain_rank": 42, "delta": 22},
        },
    }
    rep = build_competitor_report(row)

    assert rep["executive_overview"]["opportunity_score"] == 74
    assert rep["keyword"]["missing_from_target"] == ["valve"]
    assert rep["traffic"]["competitor_estimated"] == 940
    assert rep["content"]["missing_count"] == 1
    assert rep["authority"]["comp_domain_rank"] == 42
    assert rep["technical"]["broken_link_rate"]["competitor"] == 2.0
    assert rep["serp"]["features"] == {"faq": ["What is a valve?"]}
    assert len(rep["insights"]["recommendations"]) == 1


def test_build_competitor_report_handles_empty_row():
    report = build_competitor_report({"competitor": "comp.com", "status": "completed"})
    assert report["executive_overview"]["opportunity_score"] is None
    assert report["keyword"]["missing_detail"] == []
    assert report["content"]["missing_count"] is None
    assert report["insights"]["recommendations"] == []