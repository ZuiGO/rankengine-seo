"""Keyword relevance round tests:

- canonicalization merges near-duplicate surface forms into one stem key
- intent gates reject stopword/modifier boundaries, unit tokens, nav-only
- corpus_ngrams ranks by count x IDF prior (sitewide nav phrase loses)
- apply_modifiers skips modifier-word cores ("india india" dies)
- weighted TF-IDF: title/meta/slug beats body; 2-3 gram phrases scored
- job_keywords cache: build -> write -> read; no SE Ranking spend on hit;
  version mismatch and rebuild=True force a rebuild
- llm_polish fact-anchoring rejects hallucinated terms (mocked Groq)
"""

import asyncio
import json

import pytest

from backend.services import keyword_engine as ke
from backend.services import keyword_extractor as kx


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


def _matches(doc, q):
    for k, val in q.items():
        if isinstance(val, dict):
            if "$in" in val and doc.get(k) not in val["$in"]:
                return False
            if "$ne" in val and doc.get(k) == val["$ne"]:
                return False
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

    async def update_one(self, q, update, upsert=False):
        for v in self._store.values():
            if _matches(v, q):
                if update.get("$set"):
                    v.update(update["$set"])
                return
        if upsert:
            doc = dict(update.get("$set", {}))
            for k, val in q.items():
                if k != "_id" and not isinstance(val, dict):
                    doc[k] = val
            self._store[f"gen-{len(self._store)}"] = doc


class FakeDb:
    def __init__(self, pages=None, extracts=None, job_keywords=None):
        self._store = {}
        self.pages = FakeColl(self._store, "pages")
        self.content_extractions = FakeColl(self._store, "content_extractions")
        self.job_keywords = FakeColl(self._store, "job_keywords")
        for i, p in enumerate(pages or []):
            self._store[f"p{i}"] = dict(p)
        for i, e in enumerate(extracts or []):
            self._store[f"e{i}"] = dict(e)
        for i, k in enumerate(job_keywords or []):
            self._store[f"k{i}"] = dict(k)


class TestCanonicalize:
    def test_merges_near_duplicate_surface_forms(self):
        assert ke.canonicalize("Double Ferrule Fittings") == ke.canonicalize("double ferrule fitting")
        assert ke.canonicalize("double-ferrule-fittings") == ke.canonicalize("double ferrule fittings")
        assert ke.canonicalize("double ferrule fittings") != ke.canonicalize("ball valves")
        assert ke.canonicalize("") == ""

    def test_slug_dedupe_by_canonical(self):
        urls = [
            "https://x.com/double-ferrule-fittings/",
            "https://x.com/double-ferrule-fitting/",
        ]
        out = ke.slug_phrases(urls)
        assert len(out) == 1


class TestIntentGate:
    def test_rejects_boundary_stopwords_and_modifiers(self):
        assert not ke._passes_intent("of india")
        assert not ke._passes_intent("fittings manufacturer")
        assert not ke._passes_intent("fittings india")
        assert not ke._passes_intent("the fittings")

    def test_rejects_unit_and_nav_only(self):
        assert not ke._passes_intent("10mm fittings")
        assert not ke._passes_intent("40bar valves")
        assert not ke._passes_intent("product catalog")

    def test_accepts_product_phrases(self):
        assert ke._passes_intent("double ferrule fittings")
        assert ke._passes_intent("stainless steel 316")
        assert ke._passes_intent("316l valves")


class TestCoreRanking:
    @pytest.mark.asyncio
    async def test_multiword_phrases_rank_above_single_word_cores(self, monkeypatch):
        db = FakeDb(pages=[
            {"job_id": "j1", "url": "https://x.com/union/", "title": "Union", "meta_description": "union"},
            {"job_id": "j1", "url": "https://x.com/double-ferrule-fittings/",
             "title": "Double Ferrule Fittings", "meta_description": "fittings"},
            {"job_id": "j1", "url": "https://x.com/services/", "title": "Services", "meta_description": "services"},
        ])
        monkeypatch.setattr("backend.db.mongo.get_db", lambda: db)
        import backend.services.se_ranking as sr

        async def no_keywords(domain, limit=0):
            raise RuntimeError("no key")

        monkeypatch.setattr(sr, "domain_keywords", no_keywords)

        out = await ke.get_smart_keywords("j1", max_total=30, use_llm=False, rebuild=True)
        idx_phrase = out.index("double ferrule fittings")
        idx_union = out.index("union")
        assert idx_phrase < idx_union
        assert not any(k == "services" or k.startswith("services ") for k in out)


class TestCorpusNgrams:
    def test_idf_prior_demotes_sitewide_nav_phrase(self):
        texts = [
            "industrial fittings valves gauges stock",
            "industrial fittings valves gauges stock",
            "industrial fittings valves gauges stock",
            "industrial fittings valves gauges stock",
            "industrial fittings valves gauges stock",
            "industrial fittings valves gauges stock",
            "industrial fittings valves gauges stock",
            "double ferrule fittings product page",
            "double ferrule fittings product page",
            "double ferrule fittings product page",
        ]
        out = ke.corpus_ngrams(texts, min_freq=2, max_total=10)
        assert "industrial fittings" not in out[:3]
        assert "double ferrule fittings" in out[:3]

    def test_rejects_modifier_boundary(self):
        out = ke.corpus_ngrams(["fittings supplier india", "fittings supplier india"], min_freq=2)
        assert "fittings supplier india" not in out


class TestApplyModifiers:
    def test_modifier_core_gets_no_variants(self):
        out = ke.apply_modifiers(["india", "union"], max_total=40)
        assert "india" in out
        assert "india manufacturer" not in out
        assert "union manufacturer" in out

    def test_originals_kept_and_deduped(self):
        out = ke.apply_modifiers(["a b", "a b", "a b manufacturer"], max_total=40)
        assert out.count("a b") == 1
        assert out[0] == "a b"


class TestWeightedExtraction:
    def test_title_beats_body(self):
        docs = [
            ("double ferrule fittings manufacturers union india", 3.0),
            ("double ferrule fittings double ferrule fittings double ferrule fittings", 1.0),
        ]
        out = kx.extract_keywords_from_docs(docs, top_k=5)
        assert "double ferrule fittings" in out

    def test_phrase_scoring_present(self):
        docs = [
            "double ferrule fittings double ferrule fittings",
            "double ferrule fittings valves",
            "double ferrule fittings valves",
        ]
        out = kx.extract_keywords_from_docs(docs, top_k=10)
        assert any(" " in k for k in out)

    def test_weights_argument(self):
        docs = ["aa bb cc", "aa bb cc", "aa bb cc"]
        out = kx.extract_keywords_from_docs(docs, top_k=3, weights=[1.0, 1.0, 1.0])
        assert len(out) <= 3


class TestSmartKeywordCache:
    @pytest.mark.asyncio
    async def test_build_writes_then_reads_without_se_spend(self, monkeypatch):
        db = FakeDb(pages=[
            {"job_id": "j1", "url": "https://x.com/double-ferrule-fittings/",
             "title": "Double Ferrule Fittings", "meta_description": "industrial fittings"},
        ])
        monkeypatch.setattr("backend.db.mongo.get_db", lambda: db)

        calls = {"n": 0}
        import backend.services.se_ranking as sr

        async def fake_domain_keywords(domain, limit=0):
            calls["n"] += 1
            return [{"keyword": "double ferrule fittings"}, {"keyword": "ball valve supplier"}]

        monkeypatch.setattr(sr, "domain_keywords", fake_domain_keywords)

        out1 = await ke.get_smart_keywords("j1", max_total=20, use_llm=False)
        assert out1
        assert calls["n"] == 1
        cached = [v for v in db._store.values() if v.get("version") == ke.KEYWORD_CACHE_VERSION]
        assert cached and cached[0]["keywords"] == out1

        out2 = await ke.get_smart_keywords("j1", max_total=20, use_llm=False)
        assert out2 == out1
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_version_mismatch_rebuilds(self, monkeypatch):
        db = FakeDb(pages=[
            {"job_id": "j1", "url": "https://x.com/ball-valves/", "title": "Ball Valves", "meta_description": "valves"},
        ], job_keywords=[
            {"job_id": "j1", "version": 1, "keywords": ["stale keyword"]},
        ])
        monkeypatch.setattr("backend.db.mongo.get_db", lambda: db)
        import backend.services.se_ranking as sr

        async def no_keywords(domain, limit=0):
            raise RuntimeError("no key")

        monkeypatch.setattr(sr, "domain_keywords", no_keywords)

        out = await ke.get_smart_keywords("j1", max_total=20, use_llm=False)
        assert "stale keyword" not in out
        assert "ball valves" in out

    @pytest.mark.asyncio
    async def test_rebuild_true_forces_refresh(self, monkeypatch):
        db = FakeDb(pages=[
            {"job_id": "j1", "url": "https://x.com/ball-valves/", "title": "Ball Valves", "meta_description": "valves"},
        ], job_keywords=[
            {"job_id": "j1", "version": ke.KEYWORD_CACHE_VERSION, "keywords": ["cached old"]},
        ])
        monkeypatch.setattr("backend.db.mongo.get_db", lambda: db)
        import backend.services.se_ranking as sr

        async def no_keywords(domain, limit=0):
            raise RuntimeError("no key")

        monkeypatch.setattr(sr, "domain_keywords", no_keywords)

        out = await ke.get_smart_keywords("j1", max_total=20, use_llm=False, rebuild=True)
        assert "cached old" not in out
        assert "ball valves" in out


class FakeGroqResult:
    def __init__(self, arr):
        self._arr = arr

    @property
    def choices(self):
        return [type("C", (), {"message": type("M", (), {"content": json.dumps(self._arr)})})()]


def _fake_groq(monkeypatch, arr):
    import backend.config as config

    class _S:
        groq_api_key = "k"
        groq_model = "openai/gpt-oss-120b"

    monkeypatch.setattr(config, "settings", _S())

    class _Completions:
        async def create(self, **kw):
            return FakeGroqResult(arr)

    class _Chat:
        completions = _Completions()

    monkeypatch.setattr("groq.AsyncGroq", lambda api_key=None: type("FC", (), {"chat": _Chat()})())

    async def no_budget(est_tokens=0):
        return None

    monkeypatch.setattr("backend.services.groq_limiter.acquire_token_budget", no_budget)


class TestLLMPolishFactAnchor:
    @pytest.mark.asyncio
    async def test_accepts_anchored_and_rejects_hallucinated(self, monkeypatch):
        _fake_groq(monkeypatch, [
            "double ferrule fittings manufacturer india",
            "pizza delivery new york",
        ])
        out = await ke.llm_polish(["double ferrule fittings"], "x.com")
        assert "double ferrule fittings manufacturer india" in out
        assert "pizza delivery new york" not in out

    @pytest.mark.asyncio
    async def test_corpus_verbatim_acceptance(self, monkeypatch):
        _fake_groq(monkeypatch, ["high pressure ball valves"])
        out = await ke.llm_polish(["ball valves"], "x.com", corpus_texts=["High pressure ball valves in stock"])
        assert out == ["high pressure ball valves"]

    @pytest.mark.asyncio
    async def test_no_anchor_no_corpus_rejects(self, monkeypatch):
        _fake_groq(monkeypatch, ["pizza delivery new york"])
        out = await ke.llm_polish(["ball valves"], "x.com")
        assert out == []