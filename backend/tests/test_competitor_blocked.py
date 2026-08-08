"""Tests for competitor `blocked` status and stale-error clearing:

- _analyze_one marks a competitor `blocked` (not `completed`) when the crawl
  only reaches the homepage (robots.txt/sitemap.xml 403 bot-blocking);
- a rerun clears stale `errors` when it sets `status: running`;
- real crawls (2+ pages) still complete normally."""

import asyncio

import pytest

from backend.services import competitor_audit as ca_mod


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    async def to_list(self, length=None):
        out = self._docs
        if length is not None:
            out = out[:length]
        return out


class FakeColl:
    def __init__(self, store):
        self._store = store
        self.updates = []

    async def find_one(self, q):
        for v in self._store.values():
            if all(v.get(k) == val for k, val in q.items()):
                return dict(v)
        return None

    def find(self, q, projection=None):
        docs = []
        for v in self._store.values():
            ok = True
            for k, val in q.items():
                if isinstance(val, dict) and "$in" in val:
                    if v.get(k) not in val["$in"]:
                        ok = False
                        break
                elif v.get(k) != val:
                    ok = False
                    break
            if ok:
                docs.append(dict(v))
        return FakeCursor(docs)

    async def update_one(self, q, update, upsert=False):
        self.updates.append(update)
        key = q.get("competitor") or q.get("_id") or next(iter(q.values()), None)
        if key is None:
            return
        doc = dict(self._store.get(key) or {})
        doc.update(update.get("$set", {}))
        if update.get("$unset"):
            for k in update["$unset"]:
                doc.pop(k, None)
        self._store[key] = doc

    async def insert_one(self, doc):
        key = doc.get("_id") or doc.get("competitor") or str(len(self._store))
        self._store[key] = dict(doc)

    async def delete_one(self, q):
        key = next(iter(q.values()), None)
        self._store.pop(key, None)

    async def delete_many(self, q):
        for k, v in list(self._store.items()):
            if all(v.get(fk) == fv for fk, fv in q.items()):
                del self._store[k]


class FakeDb:
    def __init__(self, pages=(), gap_row=None):
        self._stores = {
            "analysis_jobs": {},
            "competitor_gap_analyses": {},
            "pages": {},
        }
        for i, p in enumerate(pages):
            self._stores["pages"][f"p{i}"] = p
        if gap_row:
            self._stores["competitor_gap_analyses"][gap_row["competitor"]] = gap_row

    def __getattr__(self, name):
        if name in self._stores:
            return FakeColl(self._stores[name])
        raise AttributeError(name)


def _page(url, job_id="compjob1"):
    return {"job_id": job_id, "url": url, "title": "x", "word_count": 300}


@pytest.fixture
def patched(monkeypatch):
    async def _fake_crawl(comp_job, url, **kw):
        return {"total_pages": 1}

    async def _fake_create(target_job_id, url):
        return "compjob1"

    async def _fake_delete(comp_job):
        pass

    monkeypatch.setattr(ca_mod, "_crawl_competitor", _fake_crawl)
    monkeypatch.setattr(ca_mod, "_create_competitor_job", _fake_create)
    monkeypatch.setattr(ca_mod, "_delete_competitor_job", _fake_delete)

    async def _fake_serp_gap(*a, **k):
        return {"gaps": ["flow valve"], "errors": []}

    async def _fake_features_gap(*a, **k):
        return {"comp_only": {"faq": 2}, "errors": []}

    async def _fake_backlink_gap(*a, **k):
        return {"gaps": ["www.parker.com"], "errors": []}

    async def _fake_se_rich(*a, **k):
        return {"opportunity_score": 42, "keyword_analysis": {"top_opportunities": []}}

    async def _fake_baseline(*a, **k):
        return {"titles": {}, "health": None, "sd": None, "perf": None, "lh": None}

    monkeypatch.setattr(ca_mod, "_target_baseline", _fake_baseline)
    monkeypatch.setattr(ca_mod, "_serp_keyword_gaps", _fake_serp_gap)
    monkeypatch.setattr(ca_mod, "_serp_features_gap", _fake_features_gap)
    monkeypatch.setattr(ca_mod, "_backlink_gap", _fake_backlink_gap)
    monkeypatch.setattr(ca_mod, "_se_rich_gap", _fake_se_rich)
    monkeypatch.setattr(ca_mod, "_build_recommendations", lambda d: [{"title": "Fix", "detail": "d", "priority": "high"}])
    monkeypatch.setattr(ca_mod, "_opportunity_score", lambda d: 42)
    import backend.config as config

    monkeypatch.setattr(config.settings, "serp_api_key", "test-key")
    import backend.services.keyword_extractor as kw_mod

    async def _fake_kw(job_id, top_k=50):
        return [{"keyword": "ball valve"}]

    monkeypatch.setattr(kw_mod, "extract_keywords_from_content", _fake_kw)


@pytest.mark.asyncio
async def test_blocked_when_only_homepage_crawled(monkeypatch, patched):
    db = FakeDb(pages=[_page("https://www.parker.com/")])
    monkeypatch.setattr(ca_mod, "get_db", lambda: db)
    result = await ca_mod._analyze_one("t1", "https://fluidcontrols.com", "parker.com")
    assert result["status"] == "blocked"
    assert result["pages_crawled"] == 1
    assert any("blocks automated access" in e for e in result["errors"])
    assert result["se_rich"]["opportunity_score"] == 42
    assert result["se_rich"]["keyword_analysis"] == {"top_opportunities": []}
    assert result["keyword_gap"]["gaps"] == ["flow valve"]
    assert result["backlink_gap"]["gaps"] == ["www.parker.com"]
    assert "Crawl blocked" in result["technical_gap"]["errors"][0]
    stored = db._stores["competitor_gap_analyses"]["parker.com"]
    assert stored["status"] == "blocked"
    assert "blocks automated access" in stored["errors"][0]
    assert stored["se_rich"]["opportunity_score"] == 42


@pytest.mark.asyncio
async def test_rerun_clears_stale_cancel_error(monkeypatch, patched):
    db = FakeDb(
        pages=[_page("https://www.parker.com/")],
        gap_row={
            "competitor": "parker.com",
            "target_job_id": "t1",
            "status": "error",
            "errors": ["Audit cancelled (worker restart or timeout)"],
        },
    )
    monkeypatch.setattr(ca_mod, "get_db", lambda: db)
    result = await ca_mod._analyze_one("t1", "https://fluidcontrols.com", "parker.com")
    assert result["status"] == "blocked"
    assert "Audit cancelled" not in db._stores["competitor_gap_analyses"]["parker.com"]["errors"][0]
    running_update = db._stores["competitor_gap_analyses"]["parker.com"]
    assert "Audit cancelled" not in running_update.get("errors", [""])[0]


@pytest.mark.asyncio
async def test_multi_page_crawl_completes_normally(monkeypatch):
    async def _fake_crawl(comp_job, url, **kw):
        return {"total_pages": 3}

    async def _fake_create(target_job_id, url):
        return "compjob1"

    async def _fake_delete(comp_job):
        pass

    async def _noop(*a, **k):
        return {}

    async def _noop_pages(*a, **k):
        return {"pages": []}

    monkeypatch.setattr(ca_mod, "_crawl_competitor", _fake_crawl)
    monkeypatch.setattr(ca_mod, "_create_competitor_job", _fake_create)
    monkeypatch.setattr(ca_mod, "_delete_competitor_job", _fake_delete)
    monkeypatch.setattr(ca_mod, "_target_baseline", _noop)
    monkeypatch.setattr(ca_mod, "_content_gap", _noop)
    monkeypatch.setattr(ca_mod, "_technical_gap", _noop)
    monkeypatch.setattr(ca_mod, "_schema_gap", _noop)
    monkeypatch.setattr(ca_mod, "_onpage_gap", _noop)
    monkeypatch.setattr(ca_mod, "_ux_gap", _noop)
    monkeypatch.setattr(ca_mod, "_se_rich_gap", _noop)

    for mod_name, fn in [
        ("backend.services.seo_analyzer", "analyze_pages"),
        ("backend.services.link_checker", "check_links"),
        ("backend.services.site_health", "compute_site_health"),
        ("backend.services.performance_service", "fetch_performance"),
        ("backend.services.structured_data", "audit_structured_data"),
        ("backend.services.keyword_extractor", "extract_keywords_from_content"),
    ]:
        monkeypatch.setattr(f"{mod_name}.{fn}", _noop)

    import backend.config as config

    monkeypatch.setattr(config.settings, "serp_api_key", "")

    db = FakeDb(pages=[_page(f"https://comp.example/p{i}") for i in range(3)])
    monkeypatch.setattr(ca_mod, "get_db", lambda: db)

    result = await ca_mod._analyze_one("t1", "https://fluidcontrols.com", "comp.example")
    assert result["status"] == "completed"
    assert result["pages_crawled"] == 3


@pytest.mark.asyncio
async def test_report_route_includes_blocked_rows(monkeypatch):
    from backend.routes import competitors as comp_route
    from fastapi import HTTPException

    db = FakeDb()
    db._stores["competitor_gap_analyses"]["parker.com"] = {
        "competitor": "parker.com",
        "target_job_id": "t1",
        "status": "blocked",
        "pages_crawled": 1,
        "se_rich": {"opportunity_score": 42},
        "errors": ["Site blocks automated access (robots.txt/sitemap.xml returned 403; only the homepage could be crawled)"],
    }
    monkeypatch.setattr(comp_route, "get_db", lambda: db)

    import backend.services.competitor_audit as mod
    original = mod.build_competitor_report
    try:
        mod.build_competitor_report = lambda row: {"executive_overview": {"status": row["status"], "errors": row["errors"]}}
        out = await comp_route.competitor_report("t1")
        assert out["total"] == 1
        assert out["competitors"][0]["executive_overview"]["status"] == "blocked"
        assert "blocks automated access" in out["competitors"][0]["executive_overview"]["errors"][0]
    finally:
        mod.build_competitor_report = original
