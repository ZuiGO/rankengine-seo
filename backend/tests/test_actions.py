"""Unit tests for actions batch/severity endpoints (faked DB, no network)."""

import asyncio

import pytest
from bson.objectid import ObjectId
from fastapi import HTTPException

import backend.routes.actions as actions_module


def run(coro):
    return asyncio.run(coro)


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *args, **kwargs):
        return self

    def skip(self, offset):
        if offset:
            self.docs = self.docs[offset:]
        return self

    def limit(self, limit):
        return self

    async def to_list(self, length):
        return self.docs[:length]


class FakeActionItems:
    def __init__(self, docs):
        self.docs = list(docs)
        self.updated = []

    def find(self, query):
        return FakeCursor([d for d in self.docs if self._matches(d, query)])

    def _matches(self, doc, query):
        for k, v in query.items():
            if isinstance(v, dict):
                if "$in" in v:
                    if doc.get(k) not in v["$in"]:
                        return False
                elif "$ne" in v and doc.get(k) == v["$ne"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    async def update_many(self, query, update):
        for d in self.docs:
            if self._matches(d, query):
                self.updated.append(("many", d["_id"], update))

    async def update_one(self, query, update):
        for d in self.docs:
            if self._matches(d, query):
                self.updated.append(("one", d["_id"], update))

    async def count_documents(self, query):
        return len([d for d in self.docs if self._matches(d, query)])


class FakeFeedback:
    def __init__(self):
        self.rows = []

    async def insert_one(self, doc):
        self.rows.append(doc)


class FakeDb:
    def __init__(self, actions):
        self.action_items = FakeActionItems(actions)
        self.action_feedback = FakeFeedback()


def make_action(oid, impact="high", status="pending"):
    return {
        "_id": ObjectId(oid),
        "job_id": "job1",
        "content_type": "image",
        "page_url": f"https://example.com/{oid[:4]}.jpg",
        "impact_on_ranking": impact,
        "status": status,
        "issue_key": "image_alt_missing",
    }


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDb([])
    monkeypatch.setattr(actions_module, "get_db", lambda: db)

    async def _noop_audit(event, job_id=None, details=None):
        pass

    monkeypatch.setattr(actions_module, "log_audit", _noop_audit)
    return db


class TestListActionsFilter:
    def test_severity_filter(self, fake_db):
        fake_db.action_items.docs = [make_action("a" * 24, "high"), make_action("b" * 24, "low")]
        result = run(actions_module.list_actions("job1", severity="low"))
        assert result["total"] == 1
        assert result["actions"][0]["impact_on_ranking"] == "low"

    def test_status_filter(self, fake_db):
        fake_db.action_items.docs = [
            make_action("a" * 24, "high", "pending"),
            make_action("b" * 24, "high", "approved"),
        ]
        result = run(actions_module.list_actions("job1", status_filter="approved"))
        assert result["total"] == 1
        assert result["actions"][0]["status"] == "approved"

    def test_status_plus_severity(self, fake_db):
        fake_db.action_items.docs = [
            make_action("a" * 24, "high", "pending"),
            make_action("b" * 24, "low", "pending"),
        ]
        result = run(actions_module.list_actions("job1", status_filter="pending", severity="high"))
        assert result["total"] == 1


class TestBatchReject:
    def test_rejects_pending_only(self, fake_db):
        fake_db.action_items.docs = [make_action("a" * 24), make_action("b" * 24, status="approved")]
        result = run(actions_module.batch_update_actions("job1", actions_module.BatchRequest(status="rejected")))
        assert result["updated"] == 1
        assert len(fake_db.action_feedback.rows) == 1
        assert fake_db.action_feedback.rows[0]["status"] == "rejected"

    def test_reject_severity_scoped(self, fake_db):
        fake_db.action_items.docs = [make_action("a" * 24, "high"), make_action("b" * 24, "low")]
        result = run(actions_module.batch_update_actions(
            "job1", actions_module.BatchRequest(status="rejected", severity="low")))
        assert result["updated"] == 1
        assert fake_db.action_feedback.rows[0]["page_url"].endswith("b.jpg")

    def test_reject_by_ids(self, fake_db):
        fake_db.action_items.docs = [make_action("a" * 24), make_action("b" * 24)]
        result = run(actions_module.batch_update_actions(
            "job1", actions_module.BatchRequest(status="rejected", ids=["b" * 24])))
        assert result["updated"] == 1
        assert fake_db.action_feedback.rows[0]["page_url"].endswith("b.jpg")

    def test_empty_set_noop(self, fake_db):
        result = run(actions_module.batch_update_actions(
            "job1", actions_module.BatchRequest(status="rejected")))
        assert result["updated"] == 0
        assert fake_db.action_feedback.rows == []

    def test_invalid_status_raises_400(self, fake_db):
        with pytest.raises(HTTPException) as exc:
            run(actions_module.batch_update_actions("job1", actions_module.BatchRequest(status="bogus")))
        assert exc.value.status_code == 400
