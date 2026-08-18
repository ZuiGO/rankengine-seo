import re

with open("backend/tests/test_agent_runtime.py", "r") as f:
    c = f.read()

# remove FakeCursor, _matches, Coll, FakeDb, _install_fake_db
c = re.sub(r'class FakeCursor:.*?\ndef _seed_run\(db', 'def _seed_run(db', c, flags=re.DOTALL)

# add fake_db fixture to all tests
tests = [
    "test_flow_checkpoint_then_approve",
    "test_policy_never_skips_checkpoint",
    "test_loop_detected",
    "test_max_steps_termination",
    "test_budget_exhaustion",
    "test_cooperative_stop",
    "test_memory_facts",
    "test_memory_episode_upsert"
]
for t in tests:
    c = re.sub(f'def {t}\\(monkeypatch\\):', f'def {t}(monkeypatch, fake_db, fake_mongo):', c)

# replace monkeypatch calls
c = c.replace('monkeypatch.setitem(TOOL_REGISTRY["crawl_urls"], "handler", _ok_handler({"summary": {"total_pages": 1}, "page_facts": []}))', 'monkeypatch.setattr(TOOL_REGISTRY["crawl_urls"], "handler", _ok_handler({"summary": {"total_pages": 1}, "page_facts": []}))')
c = c.replace('monkeypatch.setitem(TOOL_REGISTRY["crawl_urls"], "credit_cost", 1.0)', 'monkeypatch.setattr(TOOL_REGISTRY["crawl_urls"], "credit_cost", 1.0)')

# replace db initialization
c = re.sub(r'\s*db = FakeDb\(\)\n\s*_install_fake_db\(monkeypatch, db\)', '\n    db = fake_db', c)
c = re.sub(r'\s*db = FakeDb\(\)', '\n        db = fake_db', c)

c = c.replace('async def _seed_and_run(monkeypatch, runtime, **kw):\n    db = fake_db', 'async def _seed_and_run(monkeypatch, runtime, fake_db, **kw):\n    db = fake_db')

with open("backend/tests/test_agent_runtime.py", "w") as f:
    f.write(c)
