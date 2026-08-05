"""Tests for the Google Search Console integration: OAuth URL shape,
property matching, analytics parsing, and the insights-merge logic.

All tests are network-free (httpx and token endpoints are mocked)."""

import pytest

from backend.config import settings
from backend.services import gsc

SAMPLE_ROWS = [
    {"keys": ["green widgets"], "clicks": 120, "impressions": 900, "position": 4.2},
    {"keys": ["widget sizes"], "clicks": 40, "impressions": 300, "position": 7.1},
]


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

    async def delete_many(self, q):
        for k in list(self._store().keys()):
            if all(self._store()[k].get(fk) == fv for fk, fv in q.items()):
                del self._store()[k]


class FakeDb:
    def __init__(self):
        self._stores = {
            "analysis_jobs": {},
            "gsc_credentials": {},
            "seo_insights_cache": {},
        }

    def __getattr__(self, name):
        if name in self._stores:
            return FakeCollection(self, name)
        raise AttributeError(name)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(gsc, "get_db", lambda: db)
    return db


class TestAuthUrl:
    def test_build_auth_url_includes_required_params(self, monkeypatch):
        monkeypatch.setattr(settings, "gsc_client_id", "client-123")
        monkeypatch.setattr(settings, "gsc_redirect_uri", "http://localhost:8001/api/gsc/callback")
        url = gsc.build_auth_url("job-abc")
        assert "client_id=client-123" in url
        assert "redirect_uri=" in url
        assert "response_type=code" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert "state=job-abc" in url
        assert url.startswith(gsc.AUTH_URL)

    def test_configured_false_without_client_id(self):
        assert not gsc.configured()


class TestPropertyMatch:
    @pytest.mark.parametrize("site,domain", [
        ("sc-domain:example.com", "example.com"),
        ("https://www.example.com/", "example.com"),
        ("https://example.com/", "example.com"),
        ("http://example.com/", "example.com"),
    ])
    def test_matches_verified_properties(self, site, domain):
        assert gsc._match_property([site], domain) == site

    def test_no_match_returns_none(self):
        assert gsc._match_property(["sc-domain:other.com"], "example.com") is None

    def test_sc_domain_preferred(self):
        result = gsc._match_property(["https://www.example.com/", "sc-domain:example.com"], "example.com")
        assert result == "sc-domain:example.com"


@pytest.mark.asyncio
class TestExchangeCode:
    async def test_exchange_stores_credentials(self, fake_db, monkeypatch):
        monkeypatch.setattr(settings, "gsc_client_id", "client-123")
        monkeypatch.setattr(settings, "gsc_client_secret", "secret")
        monkeypatch.setattr(settings, "gsc_redirect_uri", "http://localhost:8001/api/gsc/callback")
        fake_db._stores["analysis_jobs"]["job-abc"] = {"_id": "job-abc", "url": "https://example.com/"}
        async def fake_token_post(payload):
            return {"access_token": "tok", "refresh_token": "ref", "expires_in": 3600}

        monkeypatch.setattr(gsc, "_token_post", fake_token_post)
        result = await gsc.exchange_code("code-1", "job-abc")
        assert result == {"domain": "example.com", "ok": True}
        creds = fake_db._stores["gsc_credentials"]["example.com"]
        assert creds["access_token"] == "tok"
        assert creds["refresh_token"] == "ref"

    async def test_exchange_rejects_missing_refresh(self, fake_db, monkeypatch):
        monkeypatch.setattr(settings, "gsc_client_id", "client-123")
        fake_db._stores["analysis_jobs"]["job-abc"] = {"_id": "job-abc", "url": "https://example.com/"}

        async def fake_token_post(payload):
            return {"access_token": "tok", "expires_in": 3600}

        monkeypatch.setattr(gsc, "_token_post", fake_token_post)
        with pytest.raises(RuntimeError, match="refresh_token"):
            await gsc.exchange_code("code-1", "job-abc")


@pytest.mark.asyncio
class TestFetchParsing:
    async def test_fetch_gsc_returns_sums_and_rows(self, monkeypatch):
        async def fake_save(domain, creds):
            return None

        async def fake_creds(domain):
            return {"domain": domain, "access_token": "tok", "expires_at": None}

        monkeypatch.setattr(gsc, "_get_credentials", fake_creds)
        monkeypatch.setattr(gsc, "_save_credentials", fake_save)

        async def fake_list(domain):
            return ["sc-domain:example.com"]

        async def fake_query(site, domain, dim, days):
            return SAMPLE_ROWS

        monkeypatch.setattr(gsc, "list_sites", fake_list)
        monkeypatch.setattr(gsc, "_analytics_query", fake_query)
        data = await gsc.fetch_gsc("example.com")
        assert data["property"] == "sc-domain:example.com"
        assert data["clicks"] == 160
        assert data["impressions"] == 1200
        assert data["ctr"] == round(160 / 1200, 4)
        assert data["position"] == round((4.2 * 900 + 7.1 * 300) / 1200, 1)
        assert len(data["queries"]) == 2
        assert data["queries"][0]["query"] == "green widgets"
        assert data["queries"][0]["clicks"] == 120

    async def test_fetch_gsc_returns_none_when_not_connected(self, monkeypatch):
        async def no_creds(domain):
            return None

        monkeypatch.setattr(gsc, "_get_credentials", no_creds)
        assert await gsc.fetch_gsc("example.com") is None


@pytest.mark.asyncio
class TestInsightsMerge:
    def _gsc(self):
        return {"property": "sc-domain:example.com", "clicks": 160,
                "impressions": 1200, "ctr": 0.13, "position": 4.9,
                "queries": [{"query": "green widgets", "clicks": 120}], "pages": []}

    async def test_merge_overrides_overview(self, fake_db):
        fake_db._stores["seo_insights_cache"]["job-abc"] = {
            "job_id": "job-abc",
            "data": {"overview": {"estimated_organic_traffic": None, "source": "local"}},
        }
        from backend.services.dataforseo import merge_gsc_into_insights

        await merge_gsc_into_insights(fake_db, "job-abc", "example.com", self._gsc(), 3)
        doc = fake_db._stores["seo_insights_cache"]["job-abc"]
        assert doc["data"]["gsc"]["clicks"] == 160
        assert doc["data"]["overview"]["estimated_organic_traffic"] == 160
        assert doc["data"]["overview"]["organic_keywords_count"] == 1
        assert doc["data"]["overview"]["source"] == "gsc"
        assert doc["data"]["overview_source"] == "gsc"
        assert doc["v"] == 3

    async def test_merge_skips_when_no_cache(self, fake_db):
        from backend.services.dataforseo import merge_gsc_into_insights

        ok = await merge_gsc_into_insights(fake_db, "job-missing", "example.com", self._gsc(), 3)
        assert not ok
        assert "job-missing" not in fake_db._stores["seo_insights_cache"]

    async def test_status_reports_disconnected(self, fake_db):
        status = await gsc.gsc_status("example.com")
        assert status["connected"] is False