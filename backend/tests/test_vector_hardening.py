"""Unit tests for the embedding/index hardening: quota fallback, mixed-dim re-embed,
doc cap, and query-side dimension guard. Pure logic, no DB/network."""

import asyncio

import pytest

from backend.services.embeddings import VECTOR_DIM, QuotaExceeded, embed_text_hash
from backend.services import embeddings as emb_mod
from backend.services import vector_service


def _vec(dim: int) -> list[float]:
    v = [0.0] * dim
    v[0] = 1.0
    return v


class _FakeCollection:
    def __init__(self):
        self.adds = []

    def count(self):
        return sum(len(a["ids"]) for a in self.adds)

    def add(self, **kwargs):
        self.adds.append(kwargs)

    def get(self, *args, **kwargs):
        return {"embeddings": [_vec(768)]}


@pytest.fixture
def fake_indexed(monkeypatch):
    collection = _FakeCollection()
    docs = [(str(i), f"doc {i}", {"doc_type": "page", "url": f"https://x.com/{i}"}) for i in range(150)]
    monkeypatch.setattr(vector_service, "get_db", lambda: None)
    monkeypatch.setattr(vector_service, "_collect_docs", _noop_collect(docs))
    monkeypatch.setattr(vector_service, "delete_collection", lambda name: None)
    monkeypatch.setattr(vector_service, "get_or_create_collection", lambda name: collection)
    return collection, docs


def _noop_collect(docs):
    async def collect(db, job_id):
        return docs
    return collect


class TestIndexDims:
    @pytest.mark.asyncio
    async def test_mixed_dims_reembed_with_hash(self, fake_indexed, monkeypatch):
        collection, docs = fake_indexed

        async def mixed_embed(texts, job_id=None):
            dim = 768 if len(texts) == vector_service.BATCH_SIZE else 256
            return [_vec(dim) for _ in texts]

        monkeypatch.setattr(vector_service, "embed_texts", mixed_embed)
        count = await vector_service.index_job_vectors("job1")
        assert count == 150
        assert len(collection.adds) == 2
        assert all(len(e) == VECTOR_DIM for a in collection.adds for e in a["embeddings"])

    @pytest.mark.asyncio
    async def test_doc_cap_limits_embeds(self, fake_indexed, monkeypatch):
        monkeypatch.setattr(vector_service, "_collect_docs", _noop_collect([(str(i), f"doc {i}", {}) for i in range(600)]))

        async def hash_embed(texts, job_id=None):
            return [embed_text_hash(t) for t in texts]

        monkeypatch.setattr(vector_service, "embed_texts", hash_embed)
        count = await vector_service.index_job_vectors("job1")
        assert count == vector_service.MAX_INDEX_DOCS == 500

    @pytest.mark.asyncio
    async def test_consistent_gemini_dims_kept(self, fake_indexed, monkeypatch):
        collection, _ = fake_indexed

        async def gemini_embed(texts, job_id=None):
            return [_vec(768) for _ in texts]

        monkeypatch.setattr(vector_service, "embed_texts", gemini_embed)
        await vector_service.index_job_vectors("job1")
        assert all(len(e) == 768 for a in collection.adds for e in a["embeddings"])


class TestQuotaFallback:
    @pytest.mark.asyncio
    async def test_quota_exceeded_returns_hash(self, monkeypatch):
        monkeypatch.setattr(emb_mod.settings, "gemini_api_key", "test-key")

        async def quota_embed(texts):
            raise QuotaExceeded("quota")

        monkeypatch.setattr(emb_mod, "_gemini_embed", quota_embed)
        out = await emb_mod.embed_texts(["hello world"])
        assert len(out) == 1
        assert len(out[0]) == VECTOR_DIM

    @pytest.mark.asyncio
    async def test_transient_error_retries_then_hash(self, monkeypatch):
        monkeypatch.setattr(emb_mod.settings, "gemini_api_key", "test-key")
        calls = {"n": 0}

        async def flaky_embed(texts):
            calls["n"] += 1
            raise RuntimeError("boom")

        monkeypatch.setattr(emb_mod, "_gemini_embed", flaky_embed)
        out = await emb_mod.embed_texts(["hello"])
        assert calls["n"] == 2
        assert len(out[0]) == VECTOR_DIM


class TestSearchDimGuard:
    @pytest.mark.asyncio
    async def test_query_guard_matches_collection_dim(self, monkeypatch):
        queried = {"vec": None}

        class _Coll:
            def count(self):
                return 1

            def get(self, *args, **kwargs):
                return {"embeddings": [_vec(768)]}

            def query(self, **kw):
                queried["vec"] = kw["query_embeddings"][0]
                return {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

        monkeypatch.setattr(vector_service, "get_or_create_collection", lambda name: _Coll())
        monkeypatch.setattr(vector_service, "embed_texts", _noop_embed([_vec(VECTOR_DIM)]))
        monkeypatch.setattr(vector_service, "embed_text_hash", lambda t: _vec(768))
        out = await vector_service.search_similar("job1", "query")
        assert out == []
        assert queried["vec"] == _vec(768)

    @pytest.mark.asyncio
    async def test_consistent_dim_skips_reembed(self, monkeypatch):
        queried = {"vec": None}

        class _Coll:
            def count(self):
                return 1

            def get(self, *args, **kwargs):
                return {"embeddings": [_vec(VECTOR_DIM)]}

            def query(self, **kw):
                queried["vec"] = kw["query_embeddings"][0]
                return {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

        monkeypatch.setattr(vector_service, "get_or_create_collection", lambda name: _Coll())
        monkeypatch.setattr(vector_service, "embed_texts", _noop_embed([_vec(VECTOR_DIM)]))
        monkeypatch.setattr(vector_service, "embed_text_hash", lambda t: _vec(999))
        out = await vector_service.search_similar("job1", "query")
        assert queried["vec"] == _vec(VECTOR_DIM)

    @pytest.mark.asyncio
    async def test_empty_collection_returns_empty(self, monkeypatch):
        class _Empty:
            def count(self):
                return 0

        monkeypatch.setattr(vector_service, "get_or_create_collection", lambda name: _Empty())
        out = await vector_service.search_similar("job1", "query")
        assert out == []


def _noop_embed(vectors):
    async def embed(texts, job_id=None):
        return vectors
    return embed
