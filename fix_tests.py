import re

with open("backend/tests/test_agent_runtime.py", "r") as f:
    content = f.read()

# Replace db = FakeDb() and _install_fake_db
content = re.sub(r'async def test_flow_checkpoint_then_approve\(monkeypatch\):', r'async def test_flow_checkpoint_then_approve(monkeypatch, fake_db, fake_mongo):', content)
content = re.sub(r'async def test_policy_never_skips_checkpoint\(monkeypatch\):', r'async def test_policy_never_skips_checkpoint(monkeypatch, fake_db, fake_mongo):', content)
content = re.sub(r'async def test_loop_detected\(monkeypatch\):', r'async def test_loop_detected(monkeypatch, fake_db, fake_mongo):', content)
content = re.sub(r'async def test_max_steps_termination\(monkeypatch\):', r'async def test_max_steps_termination(monkeypatch, fake_db, fake_mongo):', content)
content = re.sub(r'async def test_budget_exhaustion\(monkeypatch\):', r'async def test_budget_exhaustion(monkeypatch, fake_db, fake_mongo):', content)
content = re.sub(r'async def test_cooperative_stop\(monkeypatch\):', r'async def test_cooperative_stop(monkeypatch, fake_db, fake_mongo):', content)
content = re.sub(r'async def test_memory_facts\(monkeypatch\):', r'async def test_memory_facts(monkeypatch, fake_db, fake_mongo):', content)
content = re.sub(r'async def test_memory_episode_upsert\(monkeypatch\):', r'async def test_memory_episode_upsert(monkeypatch, fake_db, fake_mongo):', content)

content = re.sub(r'\s*db = FakeDb\(\)\n\s*_install_fake_db\(monkeypatch, db\)', '\n        db = fake_db', content)
content = re.sub(r'\s*db = FakeDb\(\)', '\n        db = fake_db', content)
content = re.sub(r'monkeypatch\.setitem\(TOOL_REGISTRY\["crawl_urls"\], "handler"', r'monkeypatch.setattr(TOOL_REGISTRY["crawl_urls"], "handler"', content)
content = re.sub(r'monkeypatch\.setitem\(TOOL_REGISTRY\["crawl_urls"\], "credit_cost"', r'monkeypatch.setattr(TOOL_REGISTRY["crawl_urls"], "credit_cost"', content)

with open("backend/tests/test_agent_runtime.py", "w") as f:
    f.write(content)

with open("backend/tests/test_cancel.py", "r") as f:
    c = f.read()
    
# Remove FakeCursor and FakeDb and _call_check's mongo patch from test_cancel.py
c = re.sub(r'class FakeCursor:.*?def _job\(status', 'def _job(status', c, flags=re.DOTALL)
c = re.sub(r'async def _call_check\(db, job_id="job-running"\):.*?return await check_cancelled\(job_id\).*?mongo.get_db = orig_mongo', 'async def _call_check(db, job_id="job-running"):\n    return await check_cancelled(job_id)', c, flags=re.DOTALL)

c = re.sub(r'def test_no_flag_is_noop\(self\):', r'def test_no_flag_is_noop(self, fake_mongo):', c)
c = re.sub(r'def test_flag_raises\(self\):', r'def test_flag_raises(self, fake_mongo):', c)
c = re.sub(r'def test_cancelled_status_raises\(self\):', r'def test_cancelled_status_raises(self, fake_mongo):', c)
c = re.sub(r'def test_stops_pipeline_before_crawling\(monkeypatch\):', r'def test_stops_pipeline_before_crawling(monkeypatch, fake_mongo):', c)
c = re.sub(r'def test_hard_delete_job_cascade\(monkeypatch\):', r'def test_hard_delete_job_cascade(monkeypatch, fake_mongo):', c)

c = re.sub(r'\s*db = FakeDb\(jobs=\[_job\("running"\)\]\)', '\n        db = fake_mongo\n        db._store["job:0"] = {"_coll": "analysis_jobs", **_job("running")}', c)
c = re.sub(r'\s*db = FakeDb\(jobs=\[_job\("running", cancelled=True\)\]\)', '\n        db = fake_mongo\n        db._store["job:0"] = {"_coll": "analysis_jobs", **_job("running", cancelled=True)}', c)
c = re.sub(r'\s*db = FakeDb\(jobs=\[_job\("cancelled"\)\]\)', '\n        db = fake_mongo\n        db._store["job:0"] = {"_coll": "analysis_jobs", **_job("cancelled")}', c)

with open("backend/tests/test_cancel.py", "w") as f:
    f.write(c)
