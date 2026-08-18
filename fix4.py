import re

with open("backend/tests/conftest.py", "r") as f:
    c = f.read()

c = c.replace('monkeypatch.setattr(jc, "get_db", lambda: fake_db)', 'if hasattr(jc, "get_db"): monkeypatch.setattr(jc, "get_db", lambda: fake_db)')
c = c.replace('monkeypatch.setattr(jl, "get_db", lambda: fake_db)', 'if hasattr(jl, "get_db"): monkeypatch.setattr(jl, "get_db", lambda: fake_db)')
c = c.replace('monkeypatch.setattr(ran, "get_db", lambda: fake_db)', 'if hasattr(ran, "get_db"): monkeypatch.setattr(ran, "get_db", lambda: fake_db)')
c = c.replace('monkeypatch.setattr(at, "get_db", lambda: fake_db)', 'if hasattr(at, "get_db"): monkeypatch.setattr(at, "get_db", lambda: fake_db)')
c = c.replace('monkeypatch.setattr(ar, "get_db", lambda: fake_db)', 'if hasattr(ar, "get_db"): monkeypatch.setattr(ar, "get_db", lambda: fake_db)')
c = c.replace('monkeypatch.setattr(am, "get_db", lambda: fake_db)', 'if hasattr(am, "get_db"): monkeypatch.setattr(am, "get_db", lambda: fake_db)')
c = c.replace('monkeypatch.setattr(mongo, "get_db", lambda: fake_db)', 'if hasattr(mongo, "get_db"): monkeypatch.setattr(mongo, "get_db", lambda: fake_db)')

with open("backend/tests/conftest.py", "w") as f:
    f.write(c)
