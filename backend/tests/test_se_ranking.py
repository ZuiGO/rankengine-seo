"""Tests for the SE Ranking Data API provider (normalization, retry, error hints)
and its position in the insights provider chain (dataforseo -> se-ranking -> local).

Network-free: httpx clients and mongo access are faked/patched."""

import pytest

from backend.services import dataforseo, se_ranking
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
            "top_anchors_by_backlinks": [{"anchor": "SE Ranking", "backlinks": 1853}],
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


class TestSeRankingNoKey:
    @pytest.mark.asyncio
    async def test_missing_key_raises(self, monkeypatch):
        async def _no_key():
            return ""
        monkeypatch.setattr(se_ranking, "_api_key", _no_key)
        with pytest.raises(ServiceError) as exc:
            await se_ranking._get("domain/overview/db", {})
        assert "not configured" in exc.value.message


class TestInsightsChainFallback:
    def _patch_chain_helpers(self, monkeypatch):
        from backend.services import local_insights, serp_api

        async def _no_serp(domain, job_id):
            return [], []

        async def _local_onpage(job_id):
            return None

        async def _local_kw(job_id):
            return []

        async def _local_bl(job_id):
            return None

        async def _local_ov(job_id):
            return None

        monkeypatch.setattr(serp_api, "run_serp_rankings", _no_serp)
        monkeypatch.setattr(serp_api, "extract_keywords_from_content", lambda job_id: [])
        monkeypatch.setattr(local_insights, "local_keywords", _local_kw)
        monkeypatch.setattr(local_insights, "local_backlinks", _local_bl)
        monkeypatch.setattr(local_insights, "local_overview", _local_ov)
        monkeypatch.setattr(local_insights, "local_onpage", _local_onpage)
        monkeypatch.setattr(dataforseo, "onpage_summary", _always_raised)

    @pytest.mark.asyncio
    async def test_keywords_fall_back_to_se_ranking(self, monkeypatch):
        async def _sr_keywords(domain, **kw):
            return [{"keyword": "flow valves",
                     "keyword_data": {"keyword_info": {"search_volume": 100}}}]
        self._patch_chain_helpers(monkeypatch)
        monkeypatch.setattr(se_ranking, "domain_keywords", _sr_keywords)
        monkeypatch.setattr(dataforseo, "domain_keywords", _always_raised)
        monkeypatch.setattr(dataforseo, "backlink_summary", _always_raised)
        monkeypatch.setattr(dataforseo, "domain_overview", _always_raised)
        insights = await dataforseo.fetch_all_insights("example.com", None)
        assert insights["keywords_source"] == "se-ranking"
        assert insights["keywords"][0]["keyword"] == "flow valves"
        assert insights["keywords_error"] is None

    @pytest.mark.asyncio
    async def test_backlinks_fall_back_and_full_failure_local(self, monkeypatch):
        async def _sr_summary(d):
            return {"backlinks": 9, "referring_domains": 3, "rank": 2, "source": "se-ranking"}

        async def _empty_keywords(d, **kw):
            return []

        async def _sr_overview_zero(d):
            return {"estimated_organic_traffic": 0}

        self._patch_chain_helpers(monkeypatch)
        monkeypatch.setattr(se_ranking, "backlink_summary", _sr_summary)
        monkeypatch.setattr(dataforseo, "domain_keywords", _always_raised)
        monkeypatch.setattr(dataforseo, "backlink_summary", _always_raised)
        monkeypatch.setattr(dataforseo, "domain_overview", _always_raised)

        from backend.services import local_insights
        monkeypatch.setattr(local_insights, "local_backlinks", _local_links)
        monkeypatch.setattr(se_ranking, "domain_keywords", _empty_keywords)
        monkeypatch.setattr(se_ranking, "domain_overview", _sr_overview_zero)

        insights = await dataforseo.fetch_all_insights("example.com", "job-1")
        assert insights["backlinks_source"] == "se-ranking"
        assert insights["backlinks"]["backlinks"] == 9

        monkeypatch.setattr(se_ranking, "backlink_summary", _always_raised)
        insights2 = await dataforseo.fetch_all_insights("example.com", "job-1")
        assert insights2["backlinks_source"] == "local"
        assert insights2["backlinks"]["backlinks"] == 3

    @pytest.mark.asyncio
    async def test_overview_chain_prefers_labs_then_se_ranking(self, monkeypatch):
        async def _empty_keywords(d, **kw):
            return []

        async def _sr_overview(d):
            return {"estimated_organic_traffic": 50, "organic_keywords_count": 5, "source": "se-ranking"}

        self._patch_chain_helpers(monkeypatch)
        monkeypatch.setattr(se_ranking, "domain_keywords", _empty_keywords)
        monkeypatch.setattr(dataforseo, "domain_keywords", _always_raised)
        monkeypatch.setattr(dataforseo, "backlink_summary", _always_raised)
        monkeypatch.setattr(dataforseo, "domain_overview_labs", _always_raised)
        monkeypatch.setattr(se_ranking, "domain_overview", _sr_overview)
        insights = await dataforseo.fetch_all_insights("example.com", None)
        assert insights["overview_source"] == "se-ranking"
        assert insights["overview"]["estimated_organic_traffic"] == 50


async def _always_raised(*args, **kwargs):
    raise ServiceError("dataforseo", "the mock always fails")


async def _local_links(job_id=None):
    return {"backlinks": 3, "referring_domains": 1, "rank": None}