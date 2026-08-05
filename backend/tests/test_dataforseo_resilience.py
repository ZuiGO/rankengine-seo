"""Resilience tests for DataForSEO (retry/backoff, 404 blacklist, 40200 hint,
keyword normalization, labs overview synthesis) and SERP API (429 retry,
24h per-keyword cache).

All tests are network-free (httpx clients are faked)."""

from datetime import datetime, timedelta

import pytest

from backend.config import settings
from backend.services import dataforseo, serp_api
from backend.services.service_errors import ServiceError


class FakeResp:
    def __init__(self, status, headers=None, json_body=None):
        self.status_code = status
        self.headers = headers or {}
        self._json = json_body

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

    async def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, json))
        return self._responses.pop(0)

    async def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self._responses.pop(0)


def ok_task_result(payload):
    return {"tasks": [{"result": [payload]}]}


@pytest.fixture(autouse=True)
def clear_blacklist():
    dataforseo._BLACKLISTED_ENDPOINTS.clear()
    yield
    dataforseo._BLACKLISTED_ENDPOINTS.clear()


class TestDataForSeoRetryAndBlacklist:
    @pytest.mark.asyncio
    async def test_post_retries_then_succeeds(self, monkeypatch):
        client = FakeClient([
            FakeResp(429),
            FakeResp(200, json_body=ok_task_result([{"keyword": "x"}])),
        ])
        monkeypatch.setattr(dataforseo.httpx, "AsyncClient", lambda: client)
        data = await dataforseo._post("keywords_data/google/keywords_for_site", [{}])
        assert data["tasks"][0]["result"][0] == [{"keyword": "x"}]
        assert len(client.calls) == 2

    @pytest.mark.asyncio
    async def test_post_raises_after_retries_exhausted(self, monkeypatch):
        client = FakeClient([FakeResp(429), FakeResp(429), FakeResp(429)])
        monkeypatch.setattr(dataforseo.httpx, "AsyncClient", lambda: client)
        with pytest.raises(ServiceError) as exc:
            await dataforseo._post("keywords_data/google/keywords_for_site", [{}])
        assert exc.value.status_code == 429
        assert len(client.calls) == 3

    @pytest.mark.asyncio
    async def test_404_blacklists_endpoint(self, monkeypatch):
        client = FakeClient([FakeResp(404, json_body={"status_message": "nope"})])
        monkeypatch.setattr(dataforseo.httpx, "AsyncClient", lambda: client)
        with pytest.raises(ServiceError) as exc:
            await dataforseo._post("domain_analytics/google/overview", [{}])
        assert exc.value.status_code == 404
        assert "not enabled" in (exc.value.hint or "")
        with pytest.raises(ServiceError) as exc2:
            await dataforseo._post("domain_analytics/google/overview", [{}])
        assert "not enabled on this plan" in exc2.value.message
        assert len(client.calls) == 1

    @pytest.mark.asyncio
    async def test_40200_task_error_maps_to_credits_hint(self, monkeypatch):
        body = {"tasks": [{"status_code": 40200, "error": {"code": 40200, "message": "Payment Required"}}]}
        client = FakeClient([FakeResp(200, json_body=body)])
        monkeypatch.setattr(dataforseo.httpx, "AsyncClient", lambda: client)
        with pytest.raises(ServiceError) as exc:
            await dataforseo._post("keywords_data/google/keywords_for_site", [{}])
        assert exc.value.hint == dataforseo.HINTS[402]


class TestDataForSeoTransformers:
    @pytest.mark.asyncio
    async def test_domain_keywords_normalizes_flat_items(self, monkeypatch):
        async def fake_post(endpoint, payload):
            assert endpoint == "keywords_data/google/keywords_for_site"
            return ok_task_result([
                {"keyword": "flow valves", "search_volume": 100, "cpc": 2.5},
            ])

        monkeypatch.setattr(dataforseo, "_post", fake_post)
        kws = await dataforseo.domain_keywords("fluidcontrols.com")
        item = kws[0]
        assert item["keyword"] == "flow valves"
        assert item["keyword_data"]["keyword_info"]["search_volume"] == 100
        assert item["keyword_data"]["keyword_info"]["cpc"] == 2.5
        assert item["keyword_data"]["keyword_properties"]["keyword_difficulty"] is None

    @pytest.mark.asyncio
    async def test_domain_keywords_passes_through_nested_items(self, monkeypatch):
        async def fake_post(endpoint, payload):
            return ok_task_result([{
                "keyword": "valves",
                "keyword_data": {
                    "keyword_info": {"search_volume": 7, "cpc": 0.9},
                    "keyword_properties": {"keyword_difficulty": 44},
                },
            }])

        monkeypatch.setattr(dataforseo, "_post", fake_post)
        kws = await dataforseo.domain_keywords("fluidcontrols.com")
        assert kws[0]["keyword_data"]["keyword_info"]["search_volume"] == 7
        assert kws[0]["keyword_data"]["keyword_properties"]["keyword_difficulty"] == 44

    @pytest.mark.asyncio
    async def test_domain_overview_labs_sums_sampled_clicks(self, monkeypatch):
        async def fake_post(endpoint, payload):
            assert endpoint == "dataforseo_labs/google/ranked_keywords"
            return ok_task_result({
                "total_count": 500,
                "items": [
                    {"metrics": {"organic": {"clicks": 10}}},
                    {"metrics": {"organic": {"clicks": 5}}},
                ],
            })

        monkeypatch.setattr(dataforseo, "_post", fake_post)
        ov = await dataforseo.domain_overview_labs("fluidcontrols.com")
        assert ov["estimated_organic_traffic"] == 15
        assert ov["organic_keywords_count"] == 500
        assert ov["sample_n"] == 2
        assert ov["source"] == "dataforseo-labs"


class FakeCollection:
    def __init__(self, db, name):
        self._db = db
        self._name = name

    def _store(self):
        return self._db._stores[self._name]

    async def find_one(self, q):
        for v in self._store().values():
            if all(v.get(fk) == fv for fk, fv in q.items()):
                return dict(v)
        return None

    async def update_one(self, q, update, upsert=False):
        store = self._store()
        key = next(iter(q.values()))
        store[key] = {**(store.get(key) or {}), **update.get("$set", {})}


class FakeDb:
    def __init__(self):
        self._stores = {"serp_cache": {}}

    def __getattr__(self, name):
        if name in self._stores:
            return FakeCollection(self, name)
        raise AttributeError(name)


class TestSerpResilience:
    @pytest.mark.asyncio
    async def test_search_keyword_retries_429_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(settings, "serp_api_key", "k")
        client = FakeClient([
            FakeResp(429, headers={"Retry-After": "1"}),
            FakeResp(200, json_body={
                "search_information": {"total_results": 100},
                "organic_results": [{"position": 1, "title": "T", "link": "https://fluidcontrols.com/x"}],
            }),
        ])
        monkeypatch.setattr(serp_api.httpx, "AsyncClient", lambda: client)
        result = await serp_api.search_keyword("flow valves", "fluidcontrols.com")
        assert result["rank"] == 1
        assert len(client.calls) == 2

    @pytest.mark.asyncio
    async def test_run_serp_rankings_uses_cache(self, monkeypatch):
        monkeypatch.setattr(settings, "serp_api_key", "k")
        db = FakeDb()
        from backend.db import mongo
        monkeypatch.setattr(mongo, "get_db", lambda: db)

        async def fake_extract(job_id):
            return ["widgets", "valves"]

        calls = []

        async def fake_search(kw, domain=None):
            calls.append(kw)
            return {"keyword": kw, "rank": 1, "total_results": 10, "organic_count": 1, "top_results": []}

        monkeypatch.setattr(serp_api, "extract_keywords_from_content", fake_extract)
        monkeypatch.setattr(serp_api, "search_keyword", fake_search)

        results, errors = await serp_api.run_serp_rankings("example.com", "job-1")
        assert len(results) == 2
        assert errors == []
        assert len(calls) == 2

        results2, errors2 = await serp_api.run_serp_rankings("example.com", "job-1")
        assert len(results2) == 2
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_run_serp_rankings_without_db_still_searches(self, monkeypatch):
        from backend.db import mongo

        def raise_db():
            raise AttributeError("no mongo client")

        monkeypatch.setattr(mongo, "get_db", raise_db)

        async def fake_extract(job_id):
            return ["widgets"]

        async def fake_search(kw, domain=None):
            return {"keyword": kw, "rank": 2}

        monkeypatch.setattr(serp_api, "extract_keywords_from_content", fake_extract)
        monkeypatch.setattr(serp_api, "search_keyword", fake_search)

        results, errors = await serp_api.run_serp_rankings("example.com", "job-1")
        assert len(results) == 1
        assert errors == []

    @pytest.mark.asyncio
    async def test_run_serp_rankings_skips_expired_cache(self, monkeypatch):
        db = FakeDb()
        from backend.db import mongo
        monkeypatch.setattr(mongo, "get_db", lambda: db)
        await db.serp_cache.update_one(
            {"cache_key": "example.com|widgets"},
            {"$set": {"cache_key": "example.com|widgets", "data": {"keyword": "widgets"},
                      "fetched_at": datetime.utcnow() - timedelta(days=2)}},
            upsert=True,
        )

        async def fake_extract(job_id):
            return ["widgets"]

        calls = []

        async def fake_search(kw, domain=None):
            calls.append(kw)
            return {"keyword": kw, "rank": 3}

        monkeypatch.setattr(serp_api, "extract_keywords_from_content", fake_extract)
        monkeypatch.setattr(serp_api, "search_keyword", fake_search)

        results, errors = await serp_api.run_serp_rankings("example.com", "job-1")
        assert len(results) == 1
        assert len(calls) == 1
