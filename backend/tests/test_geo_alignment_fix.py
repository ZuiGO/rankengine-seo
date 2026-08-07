"""Regression test for the geo_alignment `page_iter` NameError: the audit must
store a real report (not silently degrade to None) when pages exist."""

import pytest

from backend.services import geo_alignment


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
            if all(v.get(fk) == fv for fk, fv in q.items()):
                return dict(v)
        return None

    async def update_one(self, q, update, upsert=False):
        key = next(iter(q.values()))
        self._store[key] = {**(self._store.get(key) or {}), **update.get("$set", {})}


class FakeDb:
    def __init__(self):
        self._stores = {"pages": {}, "geo_alignment": {}, "content_items": {}}

    def __getattr__(self, name):
        if name in self._stores:
            return FakeCollection(self._stores[name])
        raise AttributeError(name)


def _page(url, page_type):
    return {
        "job_id": "j1",
        "url": url,
        "title": f"Title of {url}",
        "meta_description": "",
        "word_count": 300,
        "page_type": page_type,
    }


@pytest.mark.asyncio
async def test_audit_geo_alignment_runs_and_stores_report(monkeypatch):
    db = FakeDb()
    db._stores["pages"]["home"] = _page("https://example.com/", "home")
    db._stores["pages"]["a"] = _page("https://example.com/about", "")
    db._stores["pages"]["b"] = _page("https://example.com/contact", "")

    async def fake_embed(texts, job_id=None):
        dim = 4
        return [[float(i + j) for j in range(dim)] for i in range(len(texts))]

    monkeypatch.setattr(geo_alignment, "get_db", lambda: db)
    monkeypatch.setattr(geo_alignment, "embed_texts", fake_embed)

    report = await geo_alignment.audit_geo_alignment("j1")
    assert report is not None
    assert report["pages_analyzed"] == 2
    assert report["off_topic_pages"] >= 0
    assert all("alignment" in p and "off_topic" in p for p in report["pages"])
    stored = db._stores["geo_alignment"]["j1"]
    assert stored["pages_analyzed"] == 2


@pytest.mark.asyncio
async def test_audit_geo_alignment_degrades_without_pages(monkeypatch):
    db = FakeDb()

    async def fake_embed(texts, job_id=None):
        return [[0.1] * 4 for _ in range(len(texts))]

    monkeypatch.setattr(geo_alignment, "get_db", lambda: db)
    monkeypatch.setattr(geo_alignment, "embed_texts", fake_embed)

    report = await geo_alignment.audit_geo_alignment("j1")
    assert report is not None
    assert report.get("status") == "error"
