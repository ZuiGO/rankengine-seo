import re

with open("backend/tests/test_agent_runtime.py", "r") as f:
    c = f.read()

c = re.sub(r'async def _seed_and_run\(monkeypatch, runtime, \*\*kw\):\n\s*db = fake_db', 'async def _seed_and_run(monkeypatch, runtime, fake_db, **kw):\n    db = fake_db', c)
c = re.sub(r'await _seed_and_run\(monkeypatch, runtime', 'await _seed_and_run(monkeypatch, runtime, fake_db', c)

with open("backend/tests/test_agent_runtime.py", "w") as f:
    f.write(c)
