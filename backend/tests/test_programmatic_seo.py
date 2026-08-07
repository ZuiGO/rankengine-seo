"""Tests for the programmatic-SEO skill integration: template-cluster URL
pattern detection, thin/duplicate/unlinked template grading, sitemap-coverage
indexation, and the audit's stored shape (+ exec_summary mapping)."""

import pytest

from backend.services import programmatic_seo as ps
from backend.services.exec_summary import issue_key_from_message


class FakeCollection:
    def __init__(self, store):
        self._store = store

    def find(self, q, projection=None):
        return self

    async def to_list(self, length=None):
        items = list(self._store.values())
        return [dict(x) for x in items][:length] if length is not None else [dict(x) for x in items]

    async def find_one(self, q):
        for v in self._store.values():
            if all(v.get(k) == fv for k, fv in q.items()):
                return dict(v)
        return None

    async def update_one(self, q, update, upsert=False):
        key = next(iter(q.values()))
        self._store[key] = {**(self._store.get(key) or {}), **update.get("$set", {})}


class FakeDb:
    def __init__(self):
        self._stores = {
            "pages": {},
            "duplicate_content": {},
            "orphan_pages": {},
            "sitemap_audits": {},
            "programmatic_seo_audits": {},
        }

    def __getattr__(self, name):
        if name in self._stores:
            return FakeCollection(self._stores[name])
        raise AttributeError(name)


def _page(url, word_count=200, title="T", indexable=True):
    return {
        "job_id": "j1", "url": url, "title": f"{title} {url.split('/')[-2]}",
        "word_count": word_count, "is_indexable": indexable, "internal_links": 1,
    }


class TestUrlPattern:
    def test_leaf_slug_collapsed(self):
        assert ps.url_pattern("https://x.com/locations/austin/") == "/locations/{slug}/"
        assert ps.url_pattern("https://x.com/locations/dallas/") == "/locations/{slug}/"

    def test_numeric_segments_become_slug(self):
        assert ps.url_pattern("https://x.com/products/2024/widget") == "/products/{slug}/{slug}/"

    def test_root_and_shallow_return_none(self):
        assert ps.url_pattern("https://x.com/") is None
        assert ps.url_pattern("https://x.com/about") is None

    def test_extension_stripped(self):
        assert ps.url_pattern("https://x.com/blog/post-one.html") == "/blog/{slug}/"


class TestDetectClusters:
    def test_groups_three_leaf_pages(self):
        pages = [_page(f"https://x.com/locations/{c}/") for c in ("austin", "dallas", "houston")]
        clusters = ps.detect_clusters(pages)
        assert len(clusters) == 1
        assert clusters[0]["pattern"] == "/locations/{slug}/"
        assert len(clusters[0]["pages"]) == 3

    def test_ignores_fewer_than_three(self):
        pages = [_page(f"https://x.com/blog/p{i}") for i in range(2)]
        assert ps.detect_clusters(pages) == []


class TestAuditProgrammaticSeo:
    @pytest.mark.asyncio
    async def test_cluster_and_thin_grading(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(ps, "get_db", lambda: db)
        for c in ("austin", "dallas", "houston", "miami"):
            db._stores["pages"][c] = _page(f"https://x.com/locations/{c}/", word_count=45)
        summary = await ps.audit_programmatic_seo("j1")
        assert summary["clusters_count"] == 1
        assert summary["template_pages"] == 4
        assert summary["thin_template_pages"] == 4
        assert summary["template_page_share"] == 100.0
        assert summary["subscores"]["structure"] == 25
        assert summary["subscores"]["content_uniqueness"] < 25
        assert summary["score"] == sum(summary["subscores"].values())
        assert any(not c["passed"] for c in summary["checks"])
        assert db._stores["programmatic_seo_audits"]["j1"]["clusters"][0]["pattern"] == "/locations/{slug}/"

    @pytest.mark.asyncio
    async def test_duplicate_pages_from_existing_groups(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(ps, "get_db", lambda: db)
        for i, city in enumerate(("austin", "dallas", "houston")):
            db._stores["pages"][city] = _page(f"https://x.com/locations/{city}/")
        db._stores["duplicate_content"]["j1"] = {
            "job_id": "j1",
            "duplicate_groups": [
                {"urls": ["https://x.com/locations/austin/", "https://x.com/locations/dallas/"]},
            ],
            "canonical_flags": [],
        }
        summary = await ps.audit_programmatic_seo("j1")
        assert summary["duplicate_template_pages"] == 2
        assert any(not c.get("passed") and "near-duplicate" in c["label"] for c in summary["checks"])

    @pytest.mark.asyncio
    async def test_unlinked_from_orphans(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(ps, "get_db", lambda: db)
        for city in ("austin", "dallas", "houston"):
            db._stores["pages"][city] = _page(f"https://x.com/tools/{city}/")
        db._stores["orphan_pages"]["j1"] = {"job_id": "j1", "pages": [{"page_url": "https://x.com/tools/austin/"}]}
        summary = await ps.audit_programmatic_seo("j1")
        assert summary["unlinked_template_pages"] == 1

    @pytest.mark.asyncio
    async def test_no_sitemap_uses_hundred_percent(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(ps, "get_db", lambda: db)
        for city in ("austin", "dallas", "houston"):
            db._stores["pages"][city] = _page(f"https://x.com/tools/{city}/")
        summary = await ps.audit_programmatic_seo("j1")
        assert summary["sitemap_coverage"] == 100.0
        assert summary["subscores"]["indexation"] > 0


class TestExecMapping:
    def test_programmatic_message_keys(self):
        assert issue_key_from_message("3 programmatic thin pages") == "programmatic_thin"
        assert issue_key_from_message("2 programmatic pages are near-duplicates of other template pages") == "programmatic_duplicates"
        assert issue_key_from_message("orphan spokes") == "programmatic_linking"
        assert issue_key_from_message("No /pricing.md machine-readable file") == "ai_pricing_md"
        assert issue_key_from_message("No author attribution on scanned pages") == "ai_eaat_signals"