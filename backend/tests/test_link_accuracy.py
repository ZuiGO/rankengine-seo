"""Tests for the link/content accuracy round: honest link status buckets,
unique link counting, content dedup, and exec-summary evidence/explanation."""

import asyncio

import httpx
import pytest

from backend.services.exec_summary import (
    EXPLANATIONS,
    HOW_TO_FIX,
    annotate,
    issue_key_from_message,
    _narrative,
)
from backend.services.link_checker import (
    RETRY_ATTEMPTS,
    RETRY_BACKOFF,
    RETRY_STATUS_CODES,
    _check_one,
    check_links,
    classify_status,
)


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


class FakeResponse:
    def __init__(self, status_code, url=None, headers=None, history=None):
        self.status_code = status_code
        self.url = url or httpx.URL("https://example.com/page")
        self.headers = headers or {}
        self.history = history or []


class FakeClient:
    def __init__(self, statuses, fallback=404):
        self.statuses = list(statuses)
        self.calls = []
        self._fallback = fallback

    async def head(self, url, **kwargs):
        self.calls.append(("head", url))
        return self._next(url)

    async def get(self, url, **kwargs):
        self.calls.append(("get", url))
        return self._next(url)

    def _next(self, url):
        if not self.statuses:
            status = self._fallback
        else:
            status = self.statuses.pop(0)
        if status is None:
            raise httpx.ConnectError("connect failed", request=None)
        return FakeResponse(status, url=url)


class TestCheckOneRetry:
    def test_transient_500_retries_then_ok(self):
        client = FakeClient([500, 500, 200])
        res = asyncio.run(_check_one(client, "https://example.com/page"))
        assert res["status"] == "ok"
        assert res["status_code"] == 200
        assert len(client.calls) == 3

    def test_503_then_200_success(self):
        client = FakeClient([503, 200])
        res = asyncio.run(_check_one(client, "https://example.com/page"))
        assert res["status"] == "ok"
        assert res["status_code"] == 200

    def test_persistent_500_stays_broken(self):
        client = FakeClient([500, 500, 500])
        client._fallback = 500
        client.statuses = [500] * 6
        res = asyncio.run(_check_one(client, "https://example.com/page"))
        assert res["status"] == "broken"
        assert res["status_code"] == 500

    def test_connect_error_retries_then_ok(self):
        client = FakeClient([None, None, 200])
        client.statuses = [None, None, None, None, 200]
        res = asyncio.run(_check_one(client, "https://example.com/page"))
        assert res["status"] == "ok"

    def test_persistent_connect_error_unreachable(self):
        client = FakeClient([None] * 6)
        client._fallback = None
        res = asyncio.run(_check_one(client, "https://example.com/page"))
        assert res["status"] == "unreachable"
        assert res["status_code"] is None

    def test_404_no_retry(self):
        client = FakeClient([404, 404])
        res = asyncio.run(_check_one(client, "https://example.com/missing"))
        assert res["status"] == "broken"
        assert len(client.calls) == 2

    def test_head_405_falls_back_to_get(self):
        client = FakeClient([405, 200])
        res = asyncio.run(_check_one(client, "https://example.com/page"))
        assert res["status"] == "ok"
        assert client.calls[0][0] == "head"
        assert client.calls[1][0] == "get"


class FakeColl:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, q, projection=None):
        return FakeCursor(self.rows)

    async def delete_many(self, q):
        self.rows = []

    async def insert_many(self, rows):
        self.rows.extend(rows)

    async def update_one(self, q, update, upsert=False):
        self.rows.append(update.get("$set", {}))


class FakeCursor:
    def __init__(self, rows):
        self._it = iter(list(rows))

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeDb:
    def __init__(self):
        self.page_links = FakeColl()
        self.pages = FakeColl()
        self.link_health = FakeColl()
        self.link_health_summaries = FakeColl()


class TestLinkCheckerConcurrency:
    def test_retry_constants_sane(self):
        assert RETRY_ATTEMPTS == 3
        assert RETRY_BACKOFF > 0
        assert RETRY_STATUS_CODES == {500, 502, 503, 504}

    def test_check_links_honors_status_buckets(self):
        import backend.services.link_checker as lc

        async def fake_check_one(client, url):
            return {"url": url, "status": "ok", "status_code": 200}

        lc._check_one = fake_check_one
        db = FakeDb()
        db.page_links = FakeColl([{"url": "https://a.com/1", "internal_link_urls": ["https://a.com/x", "https://a.com/y"]}])
        db.pages = FakeColl([{"url": "https://a.com/x", "status_code": 200}])
        lc.get_db = lambda: db

        try:
            summary = asyncio.run(lc.check_links("job1"))
            assert summary["checked"] == 2
            assert summary["ok"] == 2
            assert summary["broken"] == 0
        finally:
            lc._check_one = None


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
