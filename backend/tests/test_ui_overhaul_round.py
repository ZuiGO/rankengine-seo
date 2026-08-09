"""Tests for the UI + reliability overhaul round:

- keyword_engine smart keyword generation (slugs, ngrams, modifiers, LLM off)
- image audit missing-alt counting + external_insights onpage sync + tracked merge
- competitor `partial` status on crawl timeout, staleness recovery, report route
- links /all external filter
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from backend.services import competitor_audit as ca_mod
from backend.services import keyword_engine as ke


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        out = self._docs
        if length is not None:
            out = out[:length]
        return out

    async def __aiter__(self):
        for d in self._docs:
            yield d


def _matches(doc, q):
    for k, val in q.items():
        if isinstance(val, dict):
            if "$in" in val and doc.get(k) not in val["$in"]:
                return False
            if "$ne" in val and doc.get(k) == val["$ne"]:
                return False
            if "$lt" in val and not (doc.get(k) is not None and doc[k] < val["$lt"]):
                return False
            if "$exists" in val and (k in doc) != val["$exists"]:
                return False
            if isinstance(val, int) and not isinstance(val, bool) and False:
                pass
            continue
        if doc.get(k) != val:
            return False
    return True


class FakeColl:
    def __init__(self, store, name):
        self._store = store
        self.name = name

    async def find_one(self, q, projection=None):
        for v in self._store.values():
            if _matches(v, q):
                row = dict(v)
                if projection:
                    row = {k: vv for k, vv in row.items() if k in projection or k == "_id"}
                return row
        return None

    def find(self, q, projection=None):
        rows = []
        for v in self._store.values():
            if _matches(v, q):
                row = dict(v)
                if projection:
                    row = {k: vv for k, vv in row.items() if k in projection or k == "_id"}
                rows.append(row)
        return FakeCursor(rows)

    async def count_documents(self, q):
        return sum(1 for v in self._store.values() if _matches(v, q))

    async def distinct(self, field, q=None):
        out = set()
        for v in self._store.values():
            if q is None or _matches(v, q):
                val = v.get(field)
                if val is not None:
                    out.add(val)
        return list(out)

    async def update_one(self, q, update, upsert=False):
        for v in self._store.values():
            if _matches(v, q):
                if update.get("$set"):
                    v.update(update["$set"])
                if update.get("$unset"):
                    for k in update["$unset"]:
                        v.pop(k, None)
                return
        if upsert:
            doc = dict(update.get("$set", {}))
            key = q.get("_id") or q.get("competitor") or f"gen-{len(self._store)}"
            for k, val in q.items():
                if k != "_id" and not isinstance(val, dict):
                    doc[k] = val
            doc.update(update.get("$setOnInsert", {}))
            self._store[key] = doc

    async def update_many(self, q, update):
        for v in self._store.values():
            if _matches(v, q):
                if update.get("$set"):
                    v.update(update["$set"])

    async def insert_one(self, doc):
        key = doc.get("_id") or str(len(self._store))
        self._store[key] = dict(doc)

    async def delete_one(self, q):
        for k, v in list(self._store.items()):
            if _matches(v, q):
                del self._store[k]
                return

    def aggregate(self, pipeline):
        docs = [dict(v) for v in self._store.values()]
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if _matches(d, stage["$match"])]
            elif "$group" in stage:
                spec = stage["$group"]
                acc = []
                seen = {}
                for d in docs:
                    key = tuple(
                        (kk, d.get(vv.lstrip("$")))
                        for kk, vv in spec["_id"].items()
                    ) if isinstance(spec["_id"], dict) else d.get(str(spec["_id"]).lstrip("$"))
                    if key not in seen:
                        if isinstance(spec["_id"], dict):
                            seen[key] = {"_id": {kk: vv2 for kk, vv2 in key}}
                        else:
                            seen[key] = {"_id": key}
                    row = seen[key]
                    for field, val in spec.items():
                        if field == "_id":
                            continue
                        if isinstance(val, dict) and "$addToSet" in val:
                            expr = val["$addToSet"]
                            val_expr = None
                            if isinstance(expr, dict) and "$cond" in expr:
                                cond, then_v, else_v = expr["$cond"]
                                eq = cond.get("$eq", [])
                                if len(eq) == 2:
                                    use_then = str(d.get(str(eq[0]).lstrip("$"))) == str(eq[1]) if eq[1] is not None else False
                                else:
                                    use_then = False
                                branch = then_v if use_then else else_v
                                if isinstance(branch, dict) and "$ifNull" in branch:
                                    f1, f2 = branch["$ifNull"]
                                    s_val = d.get(str(f1).lstrip("$"))
                                    s_val = s_val if s_val is not None else d.get(str(f2).lstrip("$"))
                                elif isinstance(branch, str):
                                    s_val = d.get(branch.lstrip("$"))
                                else:
                                    s_val = None
                            elif isinstance(expr, str):
                                s_val = d.get(expr.lstrip("$"))
                            else:
                                s_val = None
                            row.setdefault(field, set()).add(s_val)
                docs = []
                for row in self._seen_set_rows(seen):
                    docs.append(row)
            elif "$project" in stage:
                proj = stage["$project"]
                new_docs = []
                for d in docs:
                    out = {"_id": d["_id"]}
                    for field, val in proj.items():
                        if field == "_id":
                            continue
                        if isinstance(val, dict) and "$size" in val:
                            set_val = d.get(val["$size"].lstrip("$"))
                            out[field] = len(set_val) if set_val is not None else 0
                        else:
                            out[field] = d.get(field)
                    new_docs.append(out)
                docs = new_docs
            elif "$sort" in stage:
                for field, direction in reversed(list(stage["$sort"].items())):
                    docs.sort(key=lambda d: d.get(field) or 0, reverse=(direction < 0))
            elif "$limit" in stage:
                docs = docs[: stage["$limit"]]
        return FakeCursor(docs)

    def _seen_set_rows(self, seen):
        for _id, row in seen.items():
            row = dict(row)
            for field in tuple(row):
                if isinstance(row[field], set):
                    row[field] = list(row[field])
            yield row


class FakeDb:
    def __init__(self, pages=(), gap_rows=(), links=(), cache_rows=()):
        self._stores = {
            "analysis_jobs": {},
            "pages": {},
            "competitor_gap_analyses": {},
            "link_health": {},
            "seo_insights_cache": {},
            "image_optimization_audits": {},
            "content_extractions": {},
            "backlinks": {},
        }
        for i, p in enumerate(pages):
            self._stores["pages"][f"p{i}"] = dict(p)
        for row in gap_rows:
            self._stores["competitor_gap_analyses"][row["competitor"]] = dict(row)
        for i, r in enumerate(links):
            self._stores["link_health"][f"l{i}"] = dict(r)
        for i, r in enumerate(cache_rows):
            self._stores["seo_insights_cache"][f"c{i}"] = dict(r)

    def __getattr__(self, name):
        if name in self._stores:
            return FakeColl(self._stores[name], name)
        raise AttributeError(name)


class TestKeywordEngine:
    def test_slug_phrases_extracts_product_terms(self):
        urls = [
            "https://fluidcontrols.com/products/fittings-and-connectors/double-ferrule-fittings/",
            "https://fluidcontrols.com/products/valves/ball-valves/",
            "https://fluidcontrols.com/",
        ]
        phrases = ke.slug_phrases(urls)
        assert "double ferrule fittings" in phrases
        assert "ball valves" in phrases
        assert len({p.lower() for p in phrases}) == len(phrases)

    def test_slug_phrases_skips_greedy_and_numbers(self):
        assert ke.slug_phrases(["https://x.com/products/", "https://x.com/page/2/"]) == []

    def test_corpus_ngrams_requires_repeats(self):
        texts = [
            "double ferrule fittings manufacturer india pune",
            "double ferrule fittings supplier india mumbai",
            "double ferrule fittings price list",
        ]
        out = ke.corpus_ngrams(texts, min_freq=2)
        assert "double ferrule fittings" in out
        assert "supplier india mumbai" not in out

    def test_apply_modifiers_appends_purchase_terms(self):
        out = ke.apply_modifiers(["double ferrule fittings"], max_total=40)
        assert out[0] == "double ferrule fittings"
        assert any("manufacturer" in k for k in out)
        assert any("india" in k for k in out)

    def test_apply_modifiers_dedupes(self):
        out = ke.apply_modifiers(["a b", "a b", "a b manufacturer"], max_total=40)
        assert out.count("a b") == 1

    def test_domain_from_urls(self):
        assert ke.domain_from_urls(["https://fluidcontrols.com/x"]) == "fluidcontrols.com"

    def test_llm_polish_returns_empty_without_key(self, monkeypatch):
        import backend.config as config

        class _S:
            groq_api_key = ""
            groq_model = "openai/gpt-oss-120b"

        monkeypatch.setattr(config, "settings", _S())
        assert asyncio.run(ke.llm_polish(["ball valve"], "fluidcontrols.com")) == []

    @pytest.mark.asyncio
    async def test_smart_keywords_fallback_from_slugs(self, monkeypatch):
        db = FakeDb(pages=[
            {"job_id": "j1", "url": "https://fluidcontrols.com/double-ferrule-fittings/", "title": "Double Ferrule Fittings", "meta_description": "quality fittings"},
            {"job_id": "j1", "url": "https://fluidcontrols.com/ball-valves/", "title": "Ball Valves", "meta_description": "industrial ball valves"},
        ])
        monkeypatch.setattr("backend.db.mongo.get_db", lambda: db)

        async def no_keywords(domain, limit=0):
            raise RuntimeError("no key")

        import backend.services.se_ranking as sr
        monkeypatch.setattr(sr, "domain_keywords", no_keywords)

        out = await ke.get_smart_keywords("j1", max_total=20, use_llm=False)
        assert "double ferrule fittings" in out
        assert any("manufacturer" in k for k in out)


class TestImageAltCounting:
    @pytest.mark.asyncio
    async def test_missing_alt_counts_unique_images(self, monkeypatch):
        from backend.services import image_optimization as iopt
        pages = [
            {"job_id": "j1", "url": "https://x.com/a", "html": '<img src="/a.png" alt=""><img src="/b.png" alt="ok">'},
            {"job_id": "j1", "url": "https://x.com/b", "html": '<img src="/a.png">'},
        ]
        db = FakeDb(pages=pages)
        monkeypatch.setattr(iopt, "get_db", lambda: db)
        out = await iopt.audit_image_optimization("j1")
        assert out["total_images"] == 2
        assert out["missing_alt"] == 1
        assert out["alt_share"] == 0.5
        assert out["pages_with_images"] == 2
        assert out["checks"][-1]["label"] == "Descriptive alt text on images"


class TestExternalInsightsSync:
    @pytest.mark.asyncio
    async def test_onpage_image_counts_aligned_with_image_audit(self, monkeypatch):
        from backend.services import external_insights as ei
        from backend.services import local_insights as li
        from backend.services import image_optimization as iopt

        db = FakeDb()
        monkeypatch.setattr("backend.db.mongo.get_db", lambda: db)
        monkeypatch.setattr(li, "get_db", lambda: db)
        monkeypatch.setattr(iopt, "get_db", lambda: db)

        async def fake_local_onpage(job_id):
            return {"score": 80, "pages_analyzed": 1, "images_total": 5, "images_missing_alt": 0, "source": "local-crawl"}

        monkeypatch.setattr(li, "local_onpage", fake_local_onpage)
        async def _none(*a, **k):
            return None
        monkeypatch.setattr(li, "local_keywords", _none)
        monkeypatch.setattr(li, "local_backlinks", _none)
        monkeypatch.setattr(li, "local_overview", _none)

        async def fake_img(job_id):
            return {"total_images": 12, "missing_alt": 3, "pages_with_images": 1, "image_occurrences": 30}

        monkeypatch.setattr(iopt, "audit_image_optimization", fake_img)

        from backend.services import se_ranking
        async def _boom(*a, **k):
            raise RuntimeError("nope")
        monkeypatch.setattr(se_ranking, "domain_keywords", _boom)
        monkeypatch.setattr(se_ranking, "backlink_summary", _boom)
        monkeypatch.setattr(se_ranking, "domain_overview", _boom)
        monkeypatch.setattr(se_ranking, "domain_overview_history", _boom)
        monkeypatch.setattr(se_ranking, "domain_competitors", _boom)
        monkeypatch.setattr(se_ranking, "backlink_anchors", _boom)
        monkeypatch.setattr(se_ranking, "backlink_authority", _boom)
        monkeypatch.setattr(se_ranking, "backlink_refdomains", _boom)
        monkeypatch.setattr(se_ranking, "backlink_top_pages", _boom)
        monkeypatch.setattr(se_ranking, "authority_history", _boom)
        monkeypatch.setattr(se_ranking, "backlink_new_lost", _boom)
        monkeypatch.setattr(se_ranking, "backlink_new_lost_counts", _boom)
        monkeypatch.setattr(se_ranking, "ranked_keywords", _boom)

        async def fake_serp(*a, **k):
            return [], []

        monkeypatch.setattr("backend.services.serp_api.run_serp_rankings", fake_serp)

        async def fake_gsc(domain):
            from backend.services.service_errors import ServiceError
            raise ServiceError("gsc", "not connected")

        monkeypatch.setattr("backend.services.gsc.fetch_gsc", fake_gsc)

        out = await ei.fetch_all_insights("x.com", "j1")
        assert out["onpage"]["images_total"] == 12
        assert out["onpage"]["images_missing_alt"] == 3
        assert out["onpage"]["pages_with_images"] == 1

    @pytest.mark.asyncio
    async def test_tracked_competitors_merged_in(self, monkeypatch):
        from backend.services import external_insights as ei
        from backend.services import se_ranking
        from backend.services import local_insights as li

        db = FakeDb(gap_rows=[
            {"competitor": "swagelok.com", "target_job_id": "j1", "status": "completed",
             "se_rich": {"keyword_analysis": {"shared": ["tube fittings", "ferrule"]}}},
            {"competitor": "parker.com", "target_job_id": "j1", "status": "blocked",
             "se_rich": {"keyword_analysis": {"shared": []}}},
        ])
        monkeypatch.setattr("backend.db.mongo.get_db", lambda: db)
        monkeypatch.setattr(li, "get_db", lambda: db)

        async def _none(*a, **k):
            return None
        monkeypatch.setattr(li, "local_keywords", _none)
        monkeypatch.setattr(li, "local_backlinks", _none)
        monkeypatch.setattr(li, "local_overview", _none)

        async def _se_domain_competitors(domain):
            return [{"domain": "fluidcontrolsystem.com", "common_keywords": 4, "traffic_sum": 100}]

        async def _boom(*a, **k):
            raise RuntimeError("nope")

        monkeypatch.setattr(se_ranking, "domain_competitors", _se_domain_competitors)
        for fn in ("domain_keywords", "backlink_summary", "domain_overview", "domain_overview_history",
                   "backlink_authority", "backlink_anchors", "backlink_refdomains", "backlink_top_pages",
                   "authority_history", "backlink_new_lost", "backlink_new_lost_counts", "ranked_keywords"):
            monkeypatch.setattr(se_ranking, fn, _boom)

        async def fake_serp(*a, **k):
            return [], []

        monkeypatch.setattr("backend.services.serp_api.run_serp_rankings", fake_serp)

        async def fake_gsc(domain):
            from backend.services.service_errors import ServiceError
            raise ServiceError("gsc", "not connected")

        monkeypatch.setattr("backend.services.gsc.fetch_gsc", fake_gsc)

        out = await ei.fetch_all_insights("us.com", "j1")
        comps = {c["domain"]: c for c in out["competitors"]}
        assert "swagelok.com" in comps
        assert comps["swagelok.com"]["tracked"] is True
        assert comps["swagelok.com"]["common_keywords"] == 2
        assert comps["swagelok.com"]["shared_keywords"] == ["tube fittings", "ferrule"]
        assert comps["fluidcontrolsystem.com"].get("tracked") is not True
        assert comps["fluidcontrolsystem.com"]["common_keywords"] == 4
        assert "parker.com" in comps
        assert comps["parker.com"]["status"] == "blocked"


class TestCompetitorPartial:
    @pytest.mark.asyncio
    async def test_crawl_timeout_marks_partial(self, monkeypatch):
        async def fake_crawl(comp_job, url, **kw):
            raise asyncio.TimeoutError()

        async def fake_create(target_job_id, url):
            return "compj"

        async def fake_delete(comp_job):
            pass

        async def fake_gap(*a, **k):
            return {"gaps": [], "missing": [], "missing_count": 0, "comp_pages": 0}

        async def fake_noop(*a, **k):
            return None

        import backend.config as config

        monkeypatch.setattr(ca_mod, "_crawl_competitor", fake_crawl)
        monkeypatch.setattr(ca_mod, "_create_competitor_job", fake_create)
        monkeypatch.setattr(ca_mod, "_delete_competitor_job", fake_delete)
        monkeypatch.setattr(ca_mod, "_target_baseline", fake_gap)
        monkeypatch.setattr(ca_mod, "_content_gap", fake_gap)
        monkeypatch.setattr(ca_mod, "_technical_gap", fake_gap)
        monkeypatch.setattr(ca_mod, "_schema_gap", fake_gap)
        monkeypatch.setattr(ca_mod, "_onpage_gap", fake_gap)
        monkeypatch.setattr(ca_mod, "_ux_gap", fake_gap)
        monkeypatch.setattr(ca_mod, "_se_rich_gap", fake_gap)
        monkeypatch.setattr(ca_mod, "_build_recommendations", lambda d: [])
        monkeypatch.setattr(ca_mod, "_opportunity_score", lambda d: None)
        monkeypatch.setattr(config.settings, "serp_api_key", "")

        for mod_path in (
            "backend.services.seo_analyzer.analyze_pages",
            "backend.services.link_checker.check_links",
            "backend.services.site_health.compute_site_health",
            "backend.services.performance_service.fetch_performance",
            "backend.services.structured_data.audit_structured_data",
            "backend.services.keyword_extractor.extract_keywords_from_content",
        ):
            monkeypatch.setattr(mod_path, fake_noop)

        db = FakeDb(pages=[
            {"job_id": "compj", "url": "https://www.big.com/p1", "title": "x", "word_count": 300},
            {"job_id": "compj", "url": "https://www.big.com/p2", "title": "x", "word_count": 300},
        ])
        monkeypatch.setattr(ca_mod, "get_db", lambda: db)

        result = await ca_mod._analyze_one("t1", "https://fluidcontrols.com", "www.big.com")
        assert result["status"] == "partial"
        assert result["pages_crawled"] == 2
        assert any("timed out" in e and "partial data" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_stale_running_row_recovered_by_list(self, monkeypatch):
        from backend.routes import competitors as comp_route

        stale = datetime.utcnow() - timedelta(minutes=90)
        db = FakeDb(gap_rows=[
            {"competitor": "a.com", "target_job_id": "t1", "status": "running", "updated_at": stale},
            {"competitor": "b.com", "target_job_id": "t1", "status": "queued", "updated_at": datetime.utcnow()},
        ])
        monkeypatch.setattr(comp_route, "get_db", lambda: db)

        out = await comp_route.competitor_list("t1")
        rows = {r["competitor"]: r for r in out["results"]}
        assert rows["b.com"]["status"] == "queued"
        assert rows["a.com"]["status"] == "error"
        assert "stale run" in rows["a.com"]["errors"][0]

    @pytest.mark.asyncio
    async def test_report_route_includes_partial_rows(self, monkeypatch):
        from backend.routes import competitors as comp_route

        db = FakeDb(gap_rows=[
            {"competitor": "big.com", "target_job_id": "t1", "status": "partial",
             "pages_crawled": 120, "errors": ["Competitor crawl timed out after 1200s"]},
            {"competitor": "ok.com", "target_job_id": "t1", "status": "completed", "pages_crawled": 50, "errors": []},
        ])
        monkeypatch.setattr(comp_route, "get_db", lambda: db)

        import backend.services.competitor_audit as mod
        original = mod.build_competitor_report
        try:
            mod.build_competitor_report = lambda row: {"executive_overview": {"status": row["status"], "errors": row.get("errors", [])}}
            out = await comp_route.competitor_report("t1")
            assert out["total"] == 2
            statuses = {c["executive_overview"]["status"] for c in out["competitors"]}
            assert statuses == {"partial", "completed"}
        finally:
            mod.build_competitor_report = original


class TestLinksExternalFilter:
    @pytest.mark.asyncio
    async def test_all_links_external_filter(self, monkeypatch):
        from backend.routes import links

        db = FakeDb(links=[
            {"job_id": "j1", "url": "https://ext.example.com/x", "status": "ok", "external": True, "_id": "id0"},
            {"job_id": "j1", "url": "https://internal.example.com/y", "status": "ok", "external": False, "_id": "id1"},
            {"job_id": "j1", "url": "https://broken.example.com/z", "status": "broken", "external": False, "_id": "id2"},
        ])
        monkeypatch.setattr(links, "get_db", lambda: db)
        db._stores["analysis_jobs"]["j1"] = {"_id": "j1"}

        out = await links.all_links("j1", external=True, limit=200, offset=0)
        assert out["total"] == 1
        assert out["links"][0]["url"] == "https://ext.example.com/x"
        assert out["links"][0]["id"] == "id0"

        out_all = await links.all_links("j1", limit=200, offset=0)
        assert out_all["total"] == 3

        out_broken = await links.all_links("j1", status="broken", limit=200, offset=0)
        assert out_broken["total"] == 1
        assert out_broken["links"][0]["external"] is False

    @pytest.mark.asyncio
    async def test_all_links_external_fallback_for_unflagged_rows(self, monkeypatch):
        from backend.routes import links

        db = FakeDb(links=[
            {"job_id": "j1", "url": "https://ext.example.com/x", "status": "ok", "_id": "id0"},
            {"job_id": "j1", "url": "https://internal.example.com/y", "status": "ok", "_id": "id1"},
        ])
        db._stores["page_links"] = {
            "p0": {"job_id": "j1", "url": "https://internal.example.com/y",
                   "external_link_urls": ["https://ext.example.com/x/", "https://cdn.example.net/img.png"]},
        }
        monkeypatch.setattr(links, "get_db", lambda: db)
        db._stores["analysis_jobs"]["j1"] = {"_id": "j1"}

        out = await links.all_links("j1", external=True, limit=200, offset=0)
        assert out["total"] == 1
        assert out["links"][0]["url"] == "https://ext.example.com/x"
        assert out["links"][0]["external"] is True

        out_all = await links.all_links("j1", limit=200, offset=0)
        assert out_all["total"] == 2
        flagged = [r["external"] for r in out_all["links"]]
        assert sorted(flagged) == [False, True]


class TestUserFlows:
    def test_top_flows_counts_distinct_funnel_pages(self, monkeypatch):
        from backend.services import user_flow as uf

        db = FakeDb()
        db._stores["user_flows"] = {
            f"f{i}": {
                "job_id": "j1",
                "target_url": "https://site.com/contact",
                "target_type": "action",
                "depth": 2,
                "start_url": f"https://site.com/start{i}",
                "intermediate_url": "https://site.com/browse" if i % 2 == 0 else "https://site.com/other",
            }
            for i in range(6)
        }
        db._stores["user_flows"]["f9"] = {
            "job_id": "j1",
            "target_url": "https://site.com/contact",
            "target_type": "action",
            "depth": 1,
            "start_url": "https://site.com/entry9",
        }
        monkeypatch.setattr(uf, "get_db", lambda: db)

        top = asyncio.run(uf.get_top_flows("j1", limit=10))
        assert len(top) == 2
        depth2 = next(f for f in top if f["depth"] == 2)
        depth1 = next(f for f in top if f["depth"] == 1)
        assert depth2["flow_count"] == 2
        assert depth1["flow_count"] == 1
        assert depth2["target_url"] == "https://site.com/contact"