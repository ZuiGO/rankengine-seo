"""Tests for auto-generated 'after' content on approval: issue-key field
mapping, suggestion/template fallbacks, grouped+paged action listing, and
the regenerate endpoint."""

import asyncio

import pytest

import backend.routes.actions as actions_module
from backend.services import change_applier


def run(coro):
    return asyncio.run(coro)


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)
        self._skip = 0
        self._limit = None

    def sort(self, *args, **kwargs):
        return self

    def skip(self, n):
        self._skip = n
        return self

    def limit(self, n):
        self._limit = n
        return self

    async def to_list(self, length=None):
        out = self.docs[self._skip:]
        if self._limit is not None:
            out = out[: self._limit]
        if length is not None:
            out = out[:length]
        return out


class FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, q, projection=None):
        return FakeCursor(self.docs)

    async def find_one(self, q):
        for d in self.docs:
            if all(str(d.get(k)) == str(v) for k, v in q.items()):
                return d
        return None

    async def count_documents(self, q):
        return sum(1 for d in self.docs if all(d.get(k) == v for k, v in q.items()))

    async def delete_many(self, q):
        self.docs = [d for d in self.docs if not all(d.get(k) == v for k, v in q.items())]

    async def update_one(self, q, update, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(update.get("$set", {}))
                return None
        if upsert:
            self.docs.append({**q, **update.get("$set", {})})

    async def insert_one(self, doc):
        self.docs.append(doc)

    def aggregate(self, pipeline):
        return FakeAggregate(self.docs, pipeline)


class FakeAggregate:
    def __init__(self, docs):
        self.docs = list(docs)
        self._it = iter(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeAggregateColl(FakeColl):
    def __init__(self, docs):
        super().__init__(docs)
        self._aggs = []

    def aggregate(self, pipeline):
        group_stage = next((s for s in pipeline if isinstance(s, dict) and s.get("$group")), {})
        group = group_stage.get("$group", {})
        key = str(group.get("_id", "")).lstrip("$")
        counts = {}
        for d in self.docs:
            k = d.get(key)
            counts[k] = counts.get(k, 0) + 1
        self._aggs = [{"_id": k, "count": c} for k, c in counts.items()]
        return FakeAggregate(self._aggs)


class FakeDb:
    def __init__(self, actions=None, versions=None, pages=None):
        self.action_items = FakeDb._coll(actions)
        self.content_versions = FakeDb._coll(versions)
        self.pages = FakeDb._coll(pages)
        self.action_feedback = FakeDb._coll([])
        self.analysis_jobs = FakeDb._coll([{"_id": "job1", "url": "https://example.com"}])

    @staticmethod
    def _coll(docs):
        return FakeAggregateColl(list(docs or []))


def make_item(oid="a" * 24, issue_key="meta_description_missing", ctype="page",
              suggestions=None, page_url="https://example.com/page"):
    return {
        "_id": oid,
        "job_id": "job1",
        "content_type": ctype,
        "page_url": page_url,
        "source_url": "https://example.com/img/photo.png",
        "impact_on_ranking": "high",
        "status": "pending",
        "issue_key": issue_key,
        "identified_issues": ["Meta description missing"],
        "improvement_suggestions": suggestions or ["Write a compelling meta description"],
        "evidence": {},
    }


class TestFieldMapping:
    def test_page_meta_issue_maps_to_meta_description(self):
        item = make_item(issue_key="meta_description_missing")
        assert change_applier._field_for(item) == "meta_description"

    def test_page_structured_data_issue_maps(self):
        item = make_item(issue_key="no_structured_data")
        assert change_applier._field_for(item) == "structured_data"

    def test_page_eaat_maps(self):
        item = make_item(issue_key="eaat_signals_missing")
        assert change_applier._field_for(item) == "eaat"

    def test_image_type_maps_to_alt_text(self):
        item = make_item(issue_key="image_alt_missing", ctype="image")
        assert change_applier._field_for(item) == "alt_text"

    def test_unknown_issue_defaults_to_text(self):
        item = make_item(issue_key="site_issue", ctype="page")
        assert change_applier._field_for(item) == "text"

    def test_unknown_type_defaults_to_text(self):
        item = {"content_type": "xlsx", "issue_key": "pdf_link_missing"}
        assert change_applier._field_for(item) == "link_text"

    def test_prompt_exists_for_new_fields(self):
        for field in ("structured_data", "eaat", "text"):
            assert change_applier.PROMPT_BY_FIELD.get(field), f"missing prompt {field}"
        for field in ("structured_data", "eaat", "text"):
            assert change_applier.FALLBACK_AFTER.get(field), f"missing fallback {field}"


class TestFallbackAfter:
    def test_suggestion_fallback_uses_first_suggestion(self, monkeypatch):
        async def _page(job_id, url):
            return {"title": "Example Product Page"}
        db = FakeDb()
        monkeypatch.setattr(change_applier, "get_db", lambda: db)
        item = make_item(suggestions=["Add author byline and last-updated date"])
        out = run(change_applier._fallback_after(item, "eaat"))
        assert out == "Add author byline and last-updated date"

    def test_meta_fallback_uses_suggestion(self, monkeypatch):
        monkeypatch.setattr(change_applier, "get_db", lambda: FakeDb())
        item = make_item(suggestions=["A fresh 150-character meta description"])
        out = run(change_applier._fallback_after(item, "meta_description"))
        assert out == "A fresh 150-character meta description"

    def test_title_fallback_uses_page_title(self, monkeypatch):
        db = FakeDb(pages=[{"job_id": "job1", "url": "https://example.com/products", "title": "Stainless Fittings"}])
        monkeypatch.setattr(change_applier, "get_db", lambda: db)
        item = make_item(issue_key="title_missing", page_url="https://example.com/products")
        out = run(change_applier._fallback_after(item, "title"))
        assert "Stainless Fittings" in out


class TestCreateVersionSuggestionFallback:
    def test_approved_with_no_groq_uses_suggestion_and_qa(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(change_applier, "get_db", lambda: db)

        async def _no_groq(item, field):
            return None

        monkeypatch.setattr(change_applier, "_groq_generate", _no_groq)
        monkeypatch.setattr(change_applier, "settings", type("S", (), {"groq_api_key": "x"})())
        item = make_item(suggestions=["Add last-updated date"])
        v = run(change_applier.create_version_for_action(item, "approved"))
        assert v["status"] == "approved"
        assert v["after"] == "Add last-updated date"
        assert v["qa"] == "suggestion"
        assert v["field"] == "meta_description"

    def test_rejected_after_stays_none(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(change_applier, "get_db", lambda: db)
        item = make_item()
        v = run(change_applier.create_version_for_action(item, "rejected"))
        assert v["status"] == "rejected"
        assert v["after"] is None


class TestGroupedListAndRegenerate:
    def test_list_groups_and_paginates(self, monkeypatch):
        db = FakeDb(actions=[
            make_item("a" * 24, ctype="image", issue_key="image_alt_missing"),
            make_item("b" * 24, ctype="page", issue_key="meta_description_missing", suggestions=["x"]),
            make_item("c" * 24, ctype="pdf", issue_key="link_text_generic"),
        ])
        monkeypatch.setattr(actions_module, "get_db", lambda: db)
        out = run(actions_module.list_actions("job1", grouped=True, limit=2, offset=0))
        assert out["total"] == 3
        assert len(out["actions"]) == 2
        assert out["summary"]["pending"] == 3
        assert out["summary"]["by_type"]["image"] == 1
        assert out["summary"]["by_type"]["page"] == 1

    def test_list_pagination_offset(self, monkeypatch):
        db = FakeDb(actions=[make_item(f"{i:024x}", ctype="page", issue_key="weird") for i in range(1, 6)])
        monkeypatch.setattr(actions_module, "get_db", lambda: db)
        out = run(actions_module.list_actions("job1", limit=3, offset=3))
        assert out["total"] == 5
        assert len(out["actions"]) == 2

    def test_regenerate_replaces_version(self, monkeypatch):
        db = FakeDb(actions=[make_item("a" * 24, issue_key="meta_desc_missing_long")])
        db.content_versions = FakeColl([{"job_id": "job1", "action_id": "a" * 24, "after": "old"}])
        monkeypatch.setattr(actions_module, "get_db", lambda: db)
        monkeypatch.setattr(actions_module, "create_version_for_action",
                            lambda item, status: _fake_new_version(db, item, status))
        out = run(actions_module.regenerate_version("a" * 24))
        assert out["version"]["after"] == "freshly generated"
        assert db.content_versions.docs  # new version stored
        assert not any(v.get("after") == "old" for v in db.content_versions.docs)

    def test_regenerate_missing_action(self, monkeypatch):
        db = FakeDb(actions=[])
        monkeypatch.setattr(actions_module, "get_db", lambda: db)
        with pytest.raises(Exception):
            run(actions_module.regenerate_version("a" * 24))


async def _fake_new_version(db, item, status):
    version = {"job_id": "job1", "action_id": str(item["_id"]), "status": status,
               "field": "meta_description", "before": "x", "after": "freshly generated",
               "qa": "passed", "generated_by": "groq:test"}
    await db.content_versions.insert_one(version)
    return version