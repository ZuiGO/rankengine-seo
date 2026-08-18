"""Agent runtime Phase 1 tests:

- fallback planner follows crawl -> analyze -> suggest -> apply -> verify -> complete
- full flow runs to a checkpoint (apply pauses), approve resumes, run completes
- checkpoint_policy "never" applies without a pause
- loop guard kills a repeated identical tool call
- max_steps termination
- budget exhaustion
- cooperative stop
- memory store upserts episodes + facts
- planner decision validation rejects unknown tools / invalid apply args
"""

import asyncio

import pytest

from backend.models.agent_schemas import AgentDecision, AgentRun
from backend.services.agent_planner import _fallback_decision, _validate_decision
from backend.services.agent_memory import get_facts, get_episode, record_fact, save_episode
from backend.services.agent_tools import TOOL_REGISTRY


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for d in self._docs:
            yield d

    async def to_list(self, length=None):
        out = self._docs
        if length is not None:
            out = out[:length]
        return out


def _matches(doc, q):
    for k, val in q.items():
        if k == "_id":
            continue
        if isinstance(val, dict):
            if "$in" in val and doc.get(k) not in val["$in"]:
                return False
            if "$ne" in val and doc.get(k) == val["$ne"]:
                return False
            continue
        if doc.get(k) != val:
            return False
    return True


class Coll:
    def __init__(self, store, name):
        self._store = store
        self.name = name

    async def find_one(self, q, projection=None):
        for v in self._store.values():
            if v.get("_coll") != self.name:
                continue
            if _matches(v, q):
                return {k: vv for k, vv in v.items() if k != "_coll"}
        return None

    def find(self, q, projection=None):
        return FakeCursor(
            [{k: vv for k, vv in v.items() if k != "_coll"} for v in self._store.values() if v.get("_coll") == self.name and _matches(v, q)]
        )

    async def insert_one(self, doc):
        key = f"{self.name}:{len(self._store)}"
        self._store[key] = {**doc, "_coll": self.name}
        return type("R", (), {"inserted_id": key})()

    async def replace_one(self, q, doc):
        for k, v in self._store.items():
            if v.get("_coll") != self.name:
                continue
            if _matches(v, q):
                self._store[k] = {**doc, "_id": v.get("_id"), "_coll": self.name}
                return
        self._store[f"{self.name}:gen-{len(self._store)}"] = {**doc, "_coll": self.name}

    async def update_one(self, q, update, upsert=False):
        for v in self._store.values():
            if v.get("_coll") != self.name:
                continue
            if _matches(v, q):
                if update.get("$set"):
                    v.update(update["$set"])
                if update.get("$pull"):
                    for k, val in update["$pull"].items():
                        if isinstance(v.get(k), list) and val in v[k]:
                            v[k].remove(val)
                return
        if upsert:
            doc = dict(update.get("$set", {}))
            doc["_coll"] = self.name
            for k, val in q.items():
                if not isinstance(val, dict):
                    doc[k] = val
            self._store[f"{self.name}:gen-{len(self._store)}"] = doc


class FakeDb:
    def __init__(self):
        self._store = {}

    def __getitem__(self, name):
        return Coll(self._store, name)

    def __getattr__(self, name):
        return Coll(self._store, name)


def _install_fake_db(monkeypatch, db):
    import backend.db.mongo as mongo
    import backend.services.agent_memory as am
    import backend.services.agent_runtime as ar
    import backend.services.agent_tools as at

    for mod in (mongo, am, ar, at):
        monkeypatch.setattr(mod, "get_db", lambda: db)


def _seed_run(db, **kw):
    return AgentRun(
        id=kw.get("id", "r1"),
        goal=kw.get("goal", "Improve meta tags on the railways page in the sandbox"),
        domain=kw.get("domain", "fluidcontrols.com"),
        job_id=kw.get("job_id", "j1"),
        urls=kw.get("urls", ["https://fluidcontrols.com/products/railways/"]),
        budget_credits=kw.get("budget_credits", 100.0),
        max_steps=kw.get("max_steps", 15),
        checkpoint_policy=kw.get("checkpoint_policy", "every_apply"),
    )


import backend.services.agent_runtime as _runtime_mod
from backend.services.agent_planner import _fallback_decision

_ORIGINAL_DECIDE = _runtime_mod.decide


def _force_fallback_planner(monkeypatch):
    if _runtime_mod.decide is _ORIGINAL_DECIDE:
        async def _fallback_decide(state):
            return _fallback_decision(state)

        monkeypatch.setattr(_runtime_mod, "decide", _fallback_decide)


async def _seed_and_run(monkeypatch, runtime, **kw):
    db = FakeDb()
    _install_fake_db(monkeypatch, db)
    _force_fallback_planner(monkeypatch)
    run = _seed_run(db, **kw)
    await db.agent_runs.insert_one(run.model_dump())
    await runtime.start(run.id)
    return db, run.id


async def _install_stub_tools(monkeypatch):
    async def fake_crawl(**kw):
        return {
            "ok": True,
            "target_url": kw.get("urls", ["u"])[0],
            "summary": {"total_pages": 1, "total_links": 2},
            "page_facts": [{
                "url": "https://fluidcontrols.com/products/railways/",
                "title": "Old Title", "title_length": 55,
                "meta_description_present": False, "meta_description_length": 0,
                "h1_count": 1, "word_count": 400, "image_count": 2,
                "images_missing_alt": 1, "has_structured_data": False,
                "is_indexable": True, "status_code": 200,
            }],
        }

    async def fake_analyze(**kw):
        return {"ok": True, "completed": ["page_facts"], "page_facts": []}

    async def fake_suggest(**kw):
        return {"ok": True, "count": 2, "created": [
            {"id": "s1", "page_url": "https://fluidcontrols.com/products/railways/", "field_type": "title", "current_value": "Old", "suggested_value": "New Title", "rationale": "t"},
            {"id": "s2", "page_url": "https://fluidcontrols.com/products/railways/", "field_type": "meta_description", "current_value": "", "suggested_value": "New meta", "rationale": "t"},
        ]}

    async def fake_apply(**kw):
        return {"ok": True, "applied": [
            {"id": i, "page_url": "https://fluidcontrols.com/products/railways/", "field_type": "title", "staging_page_id": "sp1"}
            for i in kw.get("suggestion_ids", [])
        ], "failed": [], "staging_page_ids": ["sp1"]}

    stubs = {
        "crawl_urls": fake_crawl,
        "run_analyzers": fake_analyze,
        "generate_suggestions": fake_suggest,
        "apply_changes": fake_apply,
    }
    for name, handler in stubs.items():
        monkeypatch.setattr(TOOL_REGISTRY[name], "handler", handler)


# ---------- planner ----------

def test_fallback_sequence():
    urls = ["https://x.com/p"]
    d = _fallback_decision({"facts": {}, "urls": urls})
    assert d.tool == "crawl_urls"
    assert d.args["urls"] == urls

    d = _fallback_decision({"facts": {"pages_crawled": 1}, "urls": urls})
    assert d.tool == "run_analyzers"

    d = _fallback_decision({"facts": {"pages_crawled": 1, "analyze_done": True}, "urls": urls})
    assert d.tool == "generate_suggestions"

    d = _fallback_decision({"facts": {"pages_crawled": 1, "analyze_done": True, "suggestions_attempted": True, "suggestions_pending": 2, "suggestion_ids_pending": ["s1", "s2"]}})
    assert d.tool == "apply_changes"
    assert d.args["suggestion_ids"] == ["s1", "s2"]

    d = _fallback_decision({"facts": {"pages_crawled": 1, "analyze_done": True, "suggestions_attempted": True, "apply_attempted": True}})
    assert d.tool == "complete"


def test_validate_decision_rejects_bad_inputs():
    assert _validate_decision({"tool": "nope", "args": {}}, {}) is None
    assert _validate_decision({"tool": "crawl_urls", "args": "not-a-dict"}, {}) is None
    assert _validate_decision({"tool": "apply_changes", "args": {"suggestion_ids": ["z"]}}, {"facts": {}}) is None
    ok = _validate_decision(
        {"tool": "apply_changes", "args": {"suggestion_ids": ["s1"]}},
        {"facts": {"suggestion_ids_pending": ["s1"]}},
    )
    assert ok is not None and ok.tool == "apply_changes"
    complete = _validate_decision({"tool": "complete", "args": {}}, {})
    assert complete is not None and complete.tool == "complete"


# ---------- runtime flow ----------

@pytest.mark.asyncio
async def test_flow_checkpoint_then_approve(monkeypatch):
    from backend.services.agent_runtime import AgentRuntime

    await _install_stub_tools(monkeypatch)
    db, run_id = await _seed_and_run(monkeypatch, AgentRuntime())
    doc = await db.agent_runs.find_one({"id": run_id})
    assert doc["status"] == "waiting_approval"
    tools = [s["tool"] for s in doc["steps"]]
    assert tools == ["crawl_urls", "run_analyzers", "generate_suggestions"]
    assert doc["pending_payload"]["tool"] == "apply_changes"
    assert doc["facts"]["suggestions_pending"] == 2

    ok = await AgentRuntime().approve(run_id)
    assert ok
    doc = await db.agent_runs.find_one({"id": run_id})
    assert doc["status"] == "complete"
    tools = [s["tool"] for s in doc["steps"]]
    assert tools == ["crawl_urls", "run_analyzers", "generate_suggestions", "apply_changes"]
    assert doc["completed_at"] is not None

    episode = await get_episode(run_id)
    assert episode is not None
    assert episode["outcome"] == "complete"


@pytest.mark.asyncio
async def test_policy_never_skips_checkpoint(monkeypatch):
    from backend.services.agent_runtime import AgentRuntime

    await _install_stub_tools(monkeypatch)
    db, run_id = await _seed_and_run(monkeypatch, AgentRuntime(), checkpoint_policy="never")
    doc = await db.agent_runs.find_one({"id": run_id})
    assert doc["status"] == "complete"
    tools = [s["tool"] for s in doc["steps"]]
    assert tools == ["crawl_urls", "run_analyzers", "generate_suggestions", "apply_changes"]


@pytest.mark.asyncio
async def test_loop_detected(monkeypatch):
    from backend.services import agent_runtime as runtime_mod

    async def always_analyze(state):
        return AgentDecision(reasoning="again", tool="run_analyzers", args={"analyzers": ["page_facts"]})

    monkeypatch.setattr(runtime_mod, "decide", always_analyze)
    db, run_id = await _seed_and_run(monkeypatch, runtime_mod.AgentRuntime())
    doc = await db.agent_runs.find_one({"id": run_id})
    assert doc["status"] == "failed"
    assert "loop detected" in doc["error"]


@pytest.mark.asyncio
async def test_max_steps_termination(monkeypatch):
    from backend.services import agent_runtime as runtime_mod

    calls = {"n": 0}

    async def fake_decide(state):
        calls["n"] += 1
        if calls["n"] == 1:
            return AgentDecision(reasoning="a", tool="crawl_urls", args={"urls": state["urls"], "max_pages": 1, "mobile": True})
        return AgentDecision(reasoning="b", tool="run_analyzers", args={"analyzers": ["page_facts"]})

    monkeypatch.setattr(runtime_mod, "decide", fake_decide)
    monkeypatch.setattr(TOOL_REGISTRY["crawl_urls"], "handler", _ok_handler({"summary": {"total_pages": 1}, "page_facts": []}))
    monkeypatch.setattr(TOOL_REGISTRY["run_analyzers"], "handler", _ok_handler({"completed": []}))
    db, run_id = await _seed_and_run(monkeypatch, runtime_mod.AgentRuntime(), max_steps=2)
    doc = await db.agent_runs.find_one({"id": run_id})
    assert doc["status"] == "failed"
    assert "max_steps" in doc["error"]


@pytest.mark.asyncio
async def test_budget_exhaustion(monkeypatch):
    from backend.services import agent_runtime as runtime_mod

    monkeypatch.setattr(TOOL_REGISTRY["crawl_urls"], "credit_cost", 1.0)
    monkeypatch.setattr(TOOL_REGISTRY["crawl_urls"], "handler", _ok_handler({"summary": {"total_pages": 1}, "page_facts": []}))
    db, run_id = await _seed_and_run(monkeypatch, runtime_mod.AgentRuntime(), budget_credits=1.0)
    doc = await db.agent_runs.find_one({"id": run_id})
    assert doc["status"] == "failed"
    assert doc["error"] == "budget exhausted"


@pytest.mark.asyncio
async def test_cooperative_stop(monkeypatch):
    from backend.services.agent_runtime import AgentRuntime

    db = FakeDb()
    _install_fake_db(monkeypatch, db)
    run = _seed_run(db, id="r-stop")
    await db.agent_runs.insert_one(run.model_dump())
    await AgentRuntime().stop("r-stop")
    doc = await db.agent_runs.find_one({"id": "r-stop"})
    assert doc["status"] == "stopped"
    episode = await get_episode("r-stop")
    assert episode["outcome"] == "stopped"

    await AgentRuntime().start("r-stop")
    doc = await db.agent_runs.find_one({"id": "r-stop"})
    assert doc["status"] == "stopped"
    assert len(doc["steps"]) == 0


def _ok_handler(result):
    async def handler(**kw):
        return {"ok": True, **result}

    return handler


# ---------- memory ----------

@pytest.mark.asyncio
async def test_memory_facts(monkeypatch):
    db = FakeDb()
    _install_fake_db(monkeypatch, db)
    await record_fact("x.com", "page_title_length:https://x.com/p", 60, source_run="r1")
    await record_fact("x.com", "page_title_length:https://x.com/p", 62, source_run="r1")
    await record_fact("y.com", "other", 1)
    facts = await get_facts("x.com")
    assert facts["page_title_length:https://x.com/p"] == 62
    assert await get_facts("y.com") == {"other": 1}
    assert await get_facts("") == {}


@pytest.mark.asyncio
async def test_memory_episode_upsert(monkeypatch):
    db = FakeDb()
    _install_fake_db(monkeypatch, db)
    run = _seed_run(db)
    run_doc = run.model_dump()
    await save_episode(run_doc)
    run_doc["status"] = "complete"
    await save_episode(run_doc)
    episode = await get_episode("r1")
    assert episode["outcome"] == "complete"
    n = sum(1 for v in db._store.values() if v.get("_coll") == "agent_episodes")
    assert n == 1