"""M3: competitor reliability — domain key normalization, key migration,
status lifecycle on failure, and resource caps passed to the crawler."""

import asyncio
import pytest

from backend.routes import competitors as comp_route
from backend.routes import analysis as analysis_route
from backend.services import competitor_audit as ca_mod


class FakeColl:
    def __init__(self, store):
        self._store = store

    @staticmethod
    def _match(v, q):
        for fk, fv in q.items():
            if isinstance(fv, dict) and "$in" in fv:
                if v.get(fk) not in fv["$in"]:
                    return False
            elif v.get(fk) != fv:
                return False
        return True

    async def find_one(self, q):
        for v in self._store.values():
            if self._match(v, q):
                return dict(v)
        return None

    async def update_one(self, q, update, upsert=False):
        key = next(iter(q.values()), None)
        if key is None:
            return
        self._store[key] = {**(self._store.get(key) or {}), **update.get("$set", {})}

    async def update_many(self, q, update):
        for v in self._store.values():
            if self._match(v, q):
                v.update(update.get("$set", {}))

    async def insert_one(self, doc):
        key = doc.get("competitor") or doc.get("_id") or str(len(self._store))
        self._store[key] = dict(doc)

    async def delete_one(self, q):
        for k, v in list(self._store.items()):
            if self._match(v, q):
                del self._store[k]
                return

    async def delete_many(self, q):
        for k, v in list(self._store.items()):
            if self._match(v, q):
                del self._store[k]

    async def delete_many(self, q):
        for k, v in list(self._store.items()):
            if all(v.get(fk) == fv for fk, fv in q.items()):
                del self._store[k]


class FakeDb:
    def __init__(self):
        self._stores = {
            "analysis_jobs": {},
            "competitor_gap_analyses": {},
            "pages": {},
        }

    def __getattr__(self, name):
        if name in self._stores:
            return FakeColl(self._stores[name])
        raise AttributeError(name)


@pytest.mark.parametrize("raw,expected", [
    ("https://parkertorchology.com/", "parkertorchology.com"),
    ("  WWW.FluidControls.com  ", "fluidcontrols.com"),
    ("horsebrands.com", "horsebrands.com"),
    ("http://www.example.com:8080/x?y=1", "example.com:8080"),
    ("example.com/?q=1#frag", "example.com"),
])
def test_normalize_domain(raw, expected):
    assert comp_route._normalize_domain(raw) == expected


def test_migrate_stale_raw_key():
    db = FakeDb()
    db._stores["competitor_gap_analyses"] = {
        "raw": {
            "_id": "raw",
            "competitor": "https://parkertorchology.com/",
            "target_job_id": "t1", "status": "queued",
        }
    }
    asyncio.run(comp_route._migrate_stale_key(
        db, "t1", "parkertorchology.com", ["parkertorchology.com", "https://parkertorchology.com/"]))
    store = db._stores["competitor_gap_analyses"]
    assert "raw" not in store
    assert "parkertorchology.com" in store
    assert store["parkertorchology.com"]["competitor"] == "parkertorchology.com"


def test_migrate_does_not_clobber_live_row():
    db = FakeDb()
    db._stores["competitor_gap_analyses"] = {
        "live": {"_id": "live", "competitor": "parkertorchology.com", "target_job_id": "t1", "status": "running"},
        "raw": {"_id": "raw", "competitor": "https://parkertorchology.com/", "target_job_id": "t1", "status": "error"},
    }
    asyncio.run(comp_route._migrate_stale_key(
        db, "t1", "parkertorchology.com", ["parkertorchology.com", "https://parkertorchology.com/"]))
    store = db._stores["competitor_gap_analyses"]
    assert store["live"]["status"] == "running"
    assert "raw" not in store


async def _fake_crawl(comp_job, url, **kw):
    assert kw.get("mobile") is False
    assert kw.get("unlimited") is True
    return {"total_pages": 3}


def test_crawl_competitor_caps(monkeypatch):
    monkeypatch.setattr("backend.services.crawler.crawl_site", _fake_crawl)
    result = asyncio.run(ca_mod._crawl_competitor("c1", "https://competitor.example"))
    assert result["total_pages"] == 3


@pytest.mark.parametrize("exc", [
    RuntimeError("boom"),
    asyncio.TimeoutError(),
    asyncio.CancelledError(),
])
def test_pipeline_marks_rows_error(exc):
    async def _boom(*args, **kwargs):
        raise exc

    db = FakeDb()
    db._stores["competitor_gap_analyses"]["comp1.example"] = {
        "competitor": "comp1.example", "target_job_id": "t1", "status": "running",
    }

    async def _run():
        await analysis_route.run_competitor_pipeline("t1", ["comp1.example"])

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(analysis_route, "get_db", lambda: db)
    monkeypatch.setattr("backend.services.competitor_audit.audit_competitors", _boom)

    def _run_until():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()

    if isinstance(exc, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            _run_until()
    else:
        _run_until()

    row = db._stores["competitor_gap_analyses"]["comp1.example"]
    assert row["status"] == "error"
    assert row["errors"]