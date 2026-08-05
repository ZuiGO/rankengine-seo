"""Truthfulness tests: health scoring must not fabricate deductions or counts
when data is missing, coverage denominators count evaluated pages only, and
CWV source labels distinguish field vs lab data.

Uses an in-memory fake DB, no network."""

import pytest

from backend.services import site_health
from backend.services.performance_service import (
    _classify_source,
    _cwv_score,
    GOOD,
    CWV_WEIGHTS,
)


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs)


class FakeCollection:
    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, q=None, projection=None):
        return FakeCursor(self._docs)

    async def find_one(self, q=None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in (q or {}).items()):
                return dict(d)
        return None

    async def count_documents(self, q=None):
        return len(self._docs)

    async def update_one(self, q, update, upsert=False):
        return None


class FakeDb:
    def __init__(self, **collections):
        self._cols = collections

    def __getattr__(self, name):
        if name in self._cols:
            return FakeCollection(self._cols[name])
        return FakeCollection([])


def _page(**kw):
    base = {
        "job_id": "j1",
        "url": "https://x.test/",
        "is_indexable": True,
        "h1_count": 1,
        "meta_description": "desc",
        "word_count": 800,
        "image_count": 0,
        "images_missing_alt": 0,
        "https_entry": True,
        "mobile_friendly": True,
        "click_depth": 1,
        "redirect_count": 0,
    }
    base.update(kw)
    return base


@pytest.mark.asyncio
class TestHealthNoFabrication:
    @pytest.fixture(autouse=True)
    def _patch_db(self, monkeypatch):
        self.db = FakeDb()
        monkeypatch.setattr(site_health, "get_db", lambda: self.db)

    async def test_no_images_means_no_alt_deduction(self):
        self.db._cols["pages"] = [_page()]
        health = await site_health.compute_site_health("j1")
        assert health["score"] == 100
        assert health["metrics"]["alt_text_coverage"] is None
        assert not any("alt" in i["message"].lower() for i in health["issues"])

    async def test_missing_mobile_data_does_not_pretend_friendly(self):
        self.db._cols["pages"] = [_page(mobile_friendly=None), _page(mobile_friendly=True)]
        health = await site_health.compute_site_health("j1")
        assert health["metrics"]["mobile_friendly_pages"] == 1
        assert health["metrics"]["mobile_friendly_evaluated"] == 1
        assert not any("mobile" in i["message"].lower() for i in health["issues"])

    async def test_unevaluated_pages_not_counted_as_thin(self):
        self.db._cols["pages"] = [
            _page(url="https://x.test/pdf", word_count=None),
            _page(url="https://x.test/ok", word_count=50),
        ]
        health = await site_health.compute_site_health("j1")
        assert health["metrics"]["thin_pages"] == 1
        assert health["metrics"]["pages_evaluated_word_count"] == 1

    async def test_coverage_denominators_are_evaluated_pages(self):
        self.db._cols["pages"] = [
            _page(url="https://x.test/a", meta_description=None, h1_count=None),
            _page(url="https://x.test/b", meta_description="d", h1_count=1),
        ]
        health = await site_health.compute_site_health("j1")
        assert health["metrics"]["meta_description_coverage"] == 100
        assert health["metrics"]["h1_coverage"] == 100
        assert not any("meta description" in i["message"].lower() for i in health["issues"])

    async def test_legacy_link_summary_is_labeled(self):
        self.db._cols["pages"] = [_page()]
        self.db._cols["link_health_summaries"] = [{
            "job_id": "j1",
            "counts": {"checked": 10, "broken": 2, "timeout": 1, "error": 0, "blocked": 1},
        }]
        health = await site_health.compute_site_health("j1")
        assert health["metrics"]["broken_links"] == 4
        assert health["metrics"]["broken_links_legacy_bucket"] is True
        assert health["metrics"]["broken_link_rate"] == 40.0
        assert any("broken or unreachable" in i["message"] for i in health["issues"])

    async def test_new_bucket_summary_not_legacy(self):
        self.db._cols["pages"] = [_page()]
        self.db._cols["link_health_summaries"] = [{
            "job_id": "j1",
            "counts": {"checked": 20, "broken_link_count": 1, "blocked": 1, "unreachable": 1},
        }]
        health = await site_health.compute_site_health("j1")
        assert health["metrics"]["broken_links"] == 1
        assert "broken_links_legacy_bucket" not in health["metrics"]
        assert health["metrics"]["broken_link_rate"] == 5.0
        assert not any("unreachable" in i["message"] for i in health["issues"])
        assert any("1 broken links" in i["message"] for i in health["issues"])


class TestCwvSourceLabels:
    def test_classify_all_field(self):
        cwv = {k: 100 for k in CWV_WEIGHTS}
        assert _classify_source({k: 100 for k in CWV_WEIGHTS}, cwv) == "field"

    def test_classify_all_lab(self):
        cwv = {k: 100 for k in CWV_WEIGHTS}
        assert _classify_source({}, cwv) == "lab"

    def test_classify_mixed(self):
        field = {"lcp": 1000}
        cwv = {"lcp": 1000, "inp": 150, "cls": 0.05}
        assert _classify_source(field, cwv) == "mixed"

    def test_classify_partial(self):
        cwv = {"lcp": 1000, "inp": 150, "cls": None}
        assert _classify_source({"lcp": 1000}, cwv) == "partial"

    def test_cwv_score_uses_weights(self):
        good = GOOD
        cwv = {"lcp": good["lcp"], "inp": good["inp"], "cls": good["cls"]}
        assert _cwv_score(cwv) == 100
        cwv = {"lcp": good["lcp"] * 3, "inp": good["inp"], "cls": good["cls"]}
        assert _cwv_score(cwv) < 100

    def test_cwv_score_none_when_no_metrics(self):
        assert _cwv_score({}) is None
