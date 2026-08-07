"""Tests for the SE Ranking Data API provider (normalization, retry, error hints,
new endpoint transformers) and the external_insights chain (se-ranking -> local).

Network-free: httpx clients and mongo access are faked/patched."""

import pytest

from backend.services import se_ranking
from backend.services.external_insights import fetch_all_insights
from backend.services.service_errors import ServiceError


class FakeResp:
    def __init__(self, status, json_body=None, headers=None):
        self.status_code = status
        self._json = json_body
        self.headers = headers or {}

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    async def _key():
        return "fake-key"
    monkeypatch.setattr(se_ranking, "_api_key", _key)


class TestSeRankingRetry:
    @pytest.mark.asyncio
    async def test_retries_429_then_succeeds(self, monkeypatch):
        client = FakeClient([
            FakeResp(429, headers={"Retry-After": "1"}),
            FakeResp(200, json_body={"organic": {"traffic_sum": 40000, "keywords_count": 115000}}),
        ])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        ov = await se_ranking.domain_overview("example.com")
        assert ov["estimated_organic_traffic"] == 40000
        assert ov["organic_keywords_count"] == 115000
        assert len(client.calls) == 2

    @pytest.mark.asyncio
    async def test_raises_after_retries_exhausted(self, monkeypatch):
        client = FakeClient([FakeResp(429), FakeResp(429), FakeResp(429)])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        with pytest.raises(ServiceError) as exc:
            await se_ranking.domain_overview("example.com")
        assert exc.value.status_code == 429
        assert len(client.calls) == 3

    @pytest.mark.asyncio
    async def test_401_maps_to_key_hint(self, monkeypatch):
        client = FakeClient([FakeResp(401, json_body={"error": {"message": "No token"}})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        with pytest.raises(ServiceError) as exc:
            await se_ranking.domain_overview("example.com")
        assert "API key" in (exc.value.hint or "")

    @pytest.mark.asyncio
    async def test_credits_error_maps_to_credits_hint(self, monkeypatch):
        client = FakeClient([FakeResp(400, json_body={"error": "Insufficient funds"})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        with pytest.raises(ServiceError) as exc:
            await se_ranking.domain_overview("example.com")
        assert "credits" in (exc.value.hint or "")


class TestSeRankingTransformers:
    @pytest.mark.asyncio
    async def test_domain_overview_maps_fields(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={
            "organic": {"traffic_sum": 273150, "keywords_count": 823967},
            "adv": {"keywords_count": 4947},
        })])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        ov = await se_ranking.domain_overview("example.com")
        assert ov["estimated_organic_traffic"] == 273150
        assert ov["organic_keywords_count"] == 823967
        assert ov["paid_keywords_count"] == 4947

    @pytest.mark.asyncio
    async def test_domain_keywords_normalizes_rows(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body=[
            {"keyword": "flow valves", "volume": 1200, "cpc": 2.1, "difficulty": 55},
            {"keyword": "control valves", "volume": 300, "cpc": 1.0},
        ])])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        kws = await se_ranking.domain_keywords("example.com")
        assert kws[0]["keyword"] == "flow valves"
        assert kws[0]["keyword_data"]["keyword_info"]["search_volume"] == 1200
        assert kws[0]["keyword_data"]["keyword_info"]["cpc"] == 2.1
        assert kws[0]["keyword_data"]["keyword_properties"]["keyword_difficulty"] == 55
        assert kws[1]["keyword_data"]["keyword_properties"]["keyword_difficulty"] is None

    @pytest.mark.asyncio
    async def test_ranked_keywords_filters_unranked(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body=[
            {"keyword": "alpha", "position": 3, "selected": "https://x/", "url": "https://x/"},
            {"keyword": "beta", "position": 0, "url": "https://x/"},
            {"keyword": "gamma", "position": None, "url": "https://x/"},
        ])])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        rankings = await se_ranking.ranked_keywords("example.com")
        assert len(rankings) == 1
        assert rankings[0]["keyword"] == "alpha"
        assert rankings[0]["rank"] == 3
        assert rankings[0]["top_results"][0]["url"] == "https://x/"

    @pytest.mark.asyncio
    async def test_backlink_summary_maps_row(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"summary": [{
            "target": "example.com",
            "backlinks": 22407,
            "refdomains": 2329,
            "ips": 1961,
            "pages_with_backlinks": 87,
            "domain_inlink_rank": 68,
            "inlink_rank": 24,
            "dofollow_backlinks": 18689,
            "nofollow_backlinks": 3718,
            "edu_backlinks": 40,
            "gov_backlinks": 0,
            "anchors": 720,
        }]})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        bl = await se_ranking.backlink_summary("example.com")
        assert bl["backlinks"] == 22407
        assert bl["referring_domains"] == 2329
        assert bl["referring_ips"] == 1961
        assert bl["rank"] == 68
        assert bl["dofollow_backlinks"] == 18689

    @pytest.mark.asyncio
    async def test_region_param_added(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"organic": {}})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)

        async def _cfg():
            return {"api_key": "k", "region": "uk"}
        monkeypatch.setattr(se_ranking, "get_se_ranking_config", _cfg)
        with pytest.raises(ServiceError):
            await se_ranking.domain_overview("example.com")
        assert client.calls[0][1].get("source") == "uk"

    @pytest.mark.asyncio
    async def test_backlinks_omit_region_param(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"summary": [{"target": "x.com", "backlinks": 1}]})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        await se_ranking.backlink_summary("example.com")
        assert "source" not in client.calls[0][1]
        assert client.calls[0][1]["mode"] == "domain"


class TestSeRankingCompetitors:
    @pytest.mark.asyncio
    async def test_domain_competitors_maps_rows(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body=[
            {"domain": "seoreviewtools.com", "common_keywords": 29926,
             "domain_relevance": 10.98, "total_keywords": 49437,
             "missing_keywords": 19511, "traffic_sum": 40619, "price_sum": 68705.61},
            {"domain": "keyword-tools.org", "common_keywords": 10110,
             "total_keywords": 11183, "missing_keywords": 1073, "traffic_sum": 19544},
        ])])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        comps = await se_ranking.domain_competitors("example.com", limit=5)
        assert comps[0]["domain"] == "seoreviewtools.com"
        assert comps[0]["common_keywords"] == 29926
        assert comps[0]["traffic_sum"] == 40619
        assert client.calls[0][1]["type"] == "organic"
        assert client.calls[0][1]["limit"] == 5

    @pytest.mark.asyncio
    async def test_domain_competitors_dedupes_limit(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body=[
            {"domain": f"c{i}.com", "total_keywords": 1} for i in range(3)
        ])])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        comps = await se_ranking.domain_competitors("example.com", limit=2)
        assert len(comps) == 2

    @pytest.mark.asyncio
    async def test_keyword_gap_swaps_domains(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body=[
            {"keyword": "auto valves", "volume": 400, "position": 2, "url": "https://p.com/"},
        ])])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        gaps = await se_ranking.keyword_gap("a.com", "b.com")
        assert gaps[0]["keyword"] == "auto valves"
        assert gaps[0]["volume"] == 400
        assert client.calls[0][1]["compare"] == "b.com"
        assert str(client.calls[0][1]["diff"]) == "1"


class TestSeRankingBacklinksDetail:
    @pytest.mark.asyncio
    async def test_backlink_list_maps_rows(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"backlinks": [{
            "url_from": "https://src.io/", "url_to": "https://tgt.com/",
            "anchor": "click here", "inlink_rank": 66, "domain_inlink_rank": 77,
            "nofollow": False, "first_seen": "2021-11-05",
        }]})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        rows = await se_ranking.backlink_list("tgt.com")
        assert rows[0]["source_url"] == "https://src.io/"
        assert rows[0]["page_from_rank"] == 66
        assert rows[0]["domain_inlink_rank"] == 77
        assert client.calls[0][1]["per_domain"] == 1

    @pytest.mark.asyncio
    async def test_backlink_anchors_maps(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"anchors": [
            {"anchor": "SEO tools", "backlinks": 120, "refdomains": 45, "dofollow_backlinks": 110},
        ]})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        rows = await se_ranking.backlink_anchors("tgt.com")
        assert rows[0]["anchor"] == "SEO tools"
        assert rows[0]["backlinks"] == 120
        assert rows[0]["refdomains"] == 45

    @pytest.mark.asyncio
    async def test_backlink_refdomains_maps(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"refdomains": [
            {"refdomain": "good.example", "backlinks": 12, "domain_inlink_rank": 91, "first_seen": "2023-01-01"},
        ]})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        rows = await se_ranking.backlink_refdomains("tgt.com")
        assert rows[0]["refdomain"] == "good.example"
        assert rows[0]["domain_inlink_rank"] == 91

    @pytest.mark.asyncio
    async def test_backlink_top_pages_maps(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"pages": [
            {"url": "https://tgt.com/", "backlinks": 500, "refdomains": 120},
        ]})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        rows = await se_ranking.backlink_top_pages("tgt.com")
        assert rows[0]["url"] == "https://tgt.com/"
        assert rows[0]["backlinks"] == 500

    @pytest.mark.asyncio
    async def test_backlink_authority_maps(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"pages": [
            {"url": "https://tgt.com/", "inlink_rank": 40, "domain_inlink_rank": 72},
        ]})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        res = await se_ranking.backlink_authority("tgt.com")
        assert res["page_rank"] == 40
        assert res["domain_rank"] == 72

    @pytest.mark.asyncio
    async def test_authority_history_sorts_desc(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"ranks": [
            {"date": "2026-05-01", "domain_inlink_rank": 70},
            {"date": "2026-06-01", "domain_inlink_rank": 72},
        ]})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        rows = await se_ranking.authority_history("tgt.com")
        assert rows[0]["date"] == "2026-06"
        assert rows[0]["domain_rank"] == 72
        assert client.calls[0][1]["granularity"] == "by_month"

    @pytest.mark.asyncio
    async def test_backlink_new_lost_maps(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"new_lost_backlinks": [
            {"new_lost_date": "2026-06-01", "new_lost_type": "new",
             "url_from": "https://s.io/", "url_to": "https://t.com/",
             "anchor": "x", "domain_inlink_rank": 44},
            {"new_lost_date": "2026-05-28", "new_lost_type": "lost",
             "url_from": "https://gone.io/", "reason_lost": "link_removed"},
        ]})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        rows = await se_ranking.backlink_new_lost("tgt.com")
        assert rows[0]["type"] == "new"
        assert rows[1]["type"] == "lost"
        assert rows[1]["reason_lost"] == "link_removed"
        assert "date_from" in client.calls[0][1]

    @pytest.mark.asyncio
    async def test_backlink_new_lost_counts(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body={"new_lost_backlinks_count": [
            {"date": "2026-06-01", "new": 5, "lost": 1},
        ]})])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        rows = await se_ranking.backlink_new_lost_counts("tgt.com")
        assert rows[0]["new"] == 5
        assert rows[0]["lost"] == 1


class TestOverviewHistory:
    @pytest.mark.asyncio
    async def test_maps_and_sorts(self, monkeypatch):
        client = FakeClient([FakeResp(200, json_body=[
            {"year": 2026, "month": 5, "traffic_sum": 34402, "keywords_count": 103538},
            {"year": 2026, "month": 4, "traffic_sum": 35838, "keywords_count": 104199},
        ])])
        monkeypatch.setattr(se_ranking.httpx, "AsyncClient", lambda: client)
        rows = await se_ranking.domain_overview_history("example.com")
        assert rows[0]["month"] == "2026-05"
        assert rows[0]["traffic_sum"] == 34402
        assert client.calls[0][1]["type"] == "organic"


class TestSeRankingNoKey:
    @pytest.mark.asyncio
    async def test_missing_key_raises(self, monkeypatch):
        async def _no_key():
            return ""
        monkeypatch.setattr(se_ranking, "_api_key", _no_key)
        with pytest.raises(ServiceError) as exc:
            await se_ranking._get("domain/overview/db", {})
        assert "not configured" in exc.value.message


class TestInsightsChain:
    def _patch_chain_helpers(self, monkeypatch):
        from backend.services import local_insights, serp_api, gsc

        async def _no_serp(domain, job_id, max_keywords=5):
            return [], []

        async def _local_onpage(job_id):
            return None

        async def _local_kw(job_id):
            return []

        async def _local_bl(job_id):
            return None

        async def _local_ov(job_id):
            return None

        async def _empty_list(d, **kw):
            return []

        async def _none(d, **kw):
            return None

        async def _no_gsc(domain, days=28):
            return None

        monkeypatch.setattr(serp_api, "run_serp_rankings", _no_serp)
        monkeypatch.setattr(local_insights, "local_keywords", _local_kw)
        monkeypatch.setattr(local_insights, "local_backlinks", _local_bl)
        monkeypatch.setattr(local_insights, "local_overview", _local_ov)
        monkeypatch.setattr(local_insights, "local_onpage", _local_onpage)
        monkeypatch.setattr(gsc, "fetch_gsc", _no_gsc)
        for name in ("domain_overview_history", "domain_competitors", "backlink_anchors",
                     "backlink_refdomains", "backlink_top_pages", "backlink_new_lost",
                     "backlink_new_lost_counts", "authority_history", "ranked_keywords"):
            monkeypatch.setattr(se_ranking, name, _empty_list)
        monkeypatch.setattr(se_ranking, "backlink_authority", _none)

    @pytest.mark.asyncio
    async def test_keywords_fall_back_keeps_se_ranking(self, monkeypatch):
        async def _sr_keywords(domain, **kw):
            return [{"keyword": "flow valves",
                     "keyword_data": {"keyword_info": {"search_volume": 100}}}]

        async def _fail(*args, **kwargs):
            raise ServiceError("se_ranking", "boom")

        self._patch_chain_helpers(monkeypatch)
        monkeypatch.setattr(se_ranking, "domain_keywords", _sr_keywords)
        monkeypatch.setattr(se_ranking, "backlink_summary", _fail)
        monkeypatch.setattr(se_ranking, "domain_overview", _fail)
        insights = await fetch_all_insights("example.com", None)
        assert insights["keywords_source"] == "se-ranking"
        assert insights["keywords"][0]["keyword"] == "flow valves"
        assert insights["keywords_error"] is None

    @pytest.mark.asyncio
    async def test_provider_failures_fall_back_to_local(self, monkeypatch):
        from backend.services import local_insights

        async def _fail(*args, **kwargs):
            raise ServiceError("se_ranking", "boom")

        async def _local_links(job_id=None):
            return {"backlinks": 3, "referring_domains": 1}

        async def _local_ov(job_id=None):
            return {"estimated_organic_traffic": 12, "organic_keywords_count": 2, "source": "local-crawl"}

        self._patch_chain_helpers(monkeypatch)
        monkeypatch.setattr(se_ranking, "domain_keywords", _fail)
        monkeypatch.setattr(se_ranking, "backlink_summary", _fail)
        monkeypatch.setattr(se_ranking, "domain_overview", _fail)
        monkeypatch.setattr(local_insights, "local_backlinks", _local_links)
        monkeypatch.setattr(local_insights, "local_overview", _local_ov)

        insights = await fetch_all_insights("example.com", "job-1")
        assert insights["keywords_source"] == "none"
        assert insights["backlinks_source"] == "local"
        assert insights["backlinks"]["backlinks"] == 3
        assert insights["overview_source"] == "local"
        assert insights["overview"]["estimated_organic_traffic"] == 12
        assert insights["onpage_source"] == "none"

    @pytest.mark.asyncio
    async def test_competitors_and_backlink_extra_sections(self, monkeypatch):
        async def _sr_keywords(domain, **kw):
            return [{"keyword": "flow valves",
                     "keyword_data": {"keyword_info": {"search_volume": 100}}}]

        async def _sr_summary(domain):
            return {"backlinks": 9, "referring_domains": 3, "rank": 2, "source": "se-ranking"}

        async def _sr_overview(domain):
            return {"estimated_organic_traffic": 50, "organic_keywords_count": 5,
                    "paid_keywords_count": 1, "source": "se-ranking"}

        async def _comps(domain, limit=10):
            return [{"domain": "comp.com", "common_keywords": 10, "total_keywords": 20,
                     "missing_keywords": 10, "traffic_sum": 100}]

        async def _anchors(domain, limit=25):
            return [{"anchor": "SEO", "backlinks": 5}]

        self._patch_chain_helpers(monkeypatch)
        monkeypatch.setattr(se_ranking, "domain_keywords", _sr_keywords)
        monkeypatch.setattr(se_ranking, "backlink_summary", _sr_summary)
        monkeypatch.setattr(se_ranking, "domain_overview", _sr_overview)
        monkeypatch.setattr(se_ranking, "domain_competitors", _comps)
        monkeypatch.setattr(se_ranking, "backlink_anchors", _anchors)

        insights = await fetch_all_insights("example.com", None)
        assert insights["overview_source"] == "se-ranking"
        assert insights["overview"]["paid_keywords_count"] == 1
        assert insights["competitors"][0]["domain"] == "comp.com"
        assert insights["backlink_anchors"][0]["anchor"] == "SEO"
        assert insights["backlink_anchors_error"] is None