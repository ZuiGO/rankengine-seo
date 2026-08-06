"""Tests for the M6 apply-actions flow: GitHub PR apply, in-repo guide,
GitHub settings endpoints, and DB-first GitHub config."""

import asyncio

import backend.routes.actions as actions_module
import backend.routes.app_settings as settings_route
import backend.services.notifications as notif

from backend.tests.test_patch import FakeDb, make_action, make_version


def run(coro):
    return asyncio.run(coro)


def _patch_actions_deps(monkeypatch, db, versions):
    monkeypatch.setattr(actions_module, "get_db", lambda: db)

    async def _fake_versions(job_id, limit=500):
        return {"versions": versions, "total": len(versions), "applied": len(versions)}

    monkeypatch.setattr(actions_module, "get_content_versions", _fake_versions)

    async def _noop_audit(event, job_id=None, details=None):
        pass

    monkeypatch.setattr(actions_module, "log_audit", _noop_audit)


class TestBuildApplyGuide:
    def test_lists_approved_changes(self):
        changes = [
            {
                "status": "approved",
                "content_type": "image",
                "page_url": "https://example.com/page",
                "issue_key": "image_alt_missing",
                "impact_on_ranking": "high",
                "identified_issues": ["Image has no alt text"],
                "improvement_suggestions": ["Add descriptive alt text"],
                "version": {"field": "alt_text", "before": "", "after": "A red book cover"},
            },
            {"status": "rejected", "content_type": "text", "page_url": "", "version": None},
        ]
        guide = actions_module.build_apply_guide("https://example.com", changes)
        assert "How to apply in your repository" in guide
        assert "git checkout -b" in guide
        assert "image_alt_missing" in guide
        assert "A red book cover" in guide
        assert "rejected" not in guide.split("## Approved changes")[1].lower() or "rejected" not in guide

    def test_empty_guide(self):
        guide = actions_module.build_apply_guide("https://example.com", [])
        assert "0" in guide.split("change(s)")[0]


class TestApplyEndpoint:
    def test_no_approved_changes(self, monkeypatch):
        db = FakeDb([make_action("a" * 24, status="pending")])
        _patch_actions_deps(monkeypatch, db, [])
        result = run(actions_module.apply_approved_changes("job1"))
        assert result["ok"] is False
        assert result["reason"] == "no_approved"

    def test_no_token_returns_guide(self, monkeypatch):
        db = FakeDb([make_action("a" * 24, status="approved")])
        _patch_actions_deps(monkeypatch, db, [make_version("a" * 24)])

        async def _no_token():
            return {"token": ""}

        monkeypatch.setattr(notif, "get_github_config", _no_token)
        result = run(actions_module.apply_approved_changes("job1"))
        assert result["ok"] is False
        assert result["reason"] == "no_token"
        assert "git checkout -b" in result["guide"]
        assert result["approved"] == 1

    def test_pr_created(self, monkeypatch):
        db = FakeDb([make_action("a" * 24, status="approved")])
        _patch_actions_deps(monkeypatch, db, [make_version("a" * 24)])

        async def _cfg():
            return {"token": "ghp_test"}

        async def _pr(domain, changes, token=None):
            assert token == "ghp_test"
            return {"ok": True, "html_url": "https://github.com/zui/example-com/pull/7"}

        monkeypatch.setattr(notif, "get_github_config", _cfg)
        monkeypatch.setattr(notif, "create_github_pr", _pr)
        result = run(actions_module.apply_approved_changes("job1"))
        assert result["ok"] is True
        assert result["reason"] == "github_pr"
        assert result["html_url"].endswith("/pull/7")

    def test_pr_failure_returns_error_and_guide(self, monkeypatch):
        db = FakeDb([make_action("a" * 24, status="approved")])
        _patch_actions_deps(monkeypatch, db, [make_version("a" * 24)])

        async def _cfg():
            return {"token": "ghp_test"}

        async def _pr(domain, changes, token=None):
            return {"ok": False, "status_code": 404}

        monkeypatch.setattr(notif, "get_github_config", _cfg)
        monkeypatch.setattr(notif, "create_github_pr", _pr)
        result = run(actions_module.apply_approved_changes("job1"))
        assert result["ok"] is False
        assert result["reason"] == "pr_failed"
        assert result["error"] == "HTTP 404"
        assert "git checkout -b" in result["guide"]


class TestGithubSettingsRoute:
    class _Store(dict):
        async def find_one(self, q):
            v = self.get(q.get("key"))
            return dict(v) if v else None

        async def update_one(self, q, update, upsert=False):
            self[q["key"]] = {**(self.get(q["key"]) or {}), **update["$set"]}

    class _Db:
        def __init__(self):
            self.app_settings = TestGithubSettingsRoute._Store()

    def _seed(self, fake_db, token="ghp_1234567890"):
        fake_db.app_settings["github"] = {"key": "github", "token": token}

    def test_read_masks_token(self, monkeypatch):
        db = self._Db()
        monkeypatch.setattr(settings_route, "get_db", lambda: db)
        self._seed(db)
        out = run(settings_route.read_github_settings())
        assert out["token_set"] is True
        assert out["token"] != "ghp_1234567890"

    def test_put_stores_token(self, monkeypatch):
        db = self._Db()
        monkeypatch.setattr(settings_route, "get_db", lambda: db)
        req = settings_route.GithubSettingsRequest(token="ghp_abcdef")
        out = run(settings_route.write_github_settings(req))
        assert out["token_set"] is True
        stored = db.app_settings["github"]
        assert stored["token"] == "ghp_abcdef"

    def test_put_empty_is_noop(self, monkeypatch):
        db = self._Db()
        monkeypatch.setattr(settings_route, "get_db", lambda: db)
        req = settings_route.GithubSettingsRequest(token="   ")
        out = run(settings_route.write_github_settings(req))
        assert out["token_set"] is False


class TestGetGithubConfig:
    def test_db_first(self, monkeypatch):
        from backend.db import mongo

        class FakeColl:
            async def find_one(self, q):
                return {"key": "github", "token": "ghp_from_db"}

        class FakeDb:
            app_settings = FakeColl()

        monkeypatch.setattr(mongo, "get_db", lambda: FakeDb())
        assert run(notif.get_github_config()) == {"token": "ghp_from_db"}

    def test_env_fallback(self, monkeypatch):
        from backend.db import mongo

        class FakeColl:
            async def find_one(self, q):
                return None

        class FakeDb:
            app_settings = FakeColl()

        monkeypatch.setattr(mongo, "get_db", lambda: FakeDb())

        class FakeSettings:
            github_token = "ghp_env"

        monkeypatch.setattr(notif, "settings", FakeSettings())
        assert run(notif.get_github_config()) == {"token": "ghp_env"}


class TestCreateGithubPrTokenParam:
    def _changes(self):
        return [{"content_type": "image", "page_url": "https://example.com/a"}]

    class FakeResponse:
        def __init__(self, status_code=200, json_data=None):
            self.status_code = status_code
            self._json = json_data or {}

        def json(self):
            return self._json

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            self.requests.append(("POST", url, kwargs))
            return TestCreateGithubPrTokenParam.FakeResponse(
                200, {"html_url": f"https://github.com/pull/{len(self.requests)}"}
            )

        async def get(self, url, **kwargs):
            self.requests.append(("GET", url, kwargs))
            return TestCreateGithubPrTokenParam.FakeResponse(200, {"login": "octocat"})

    def test_explicit_token_used(self, monkeypatch):
        monkeypatch.setattr(notif, "settings", type("S", (), {"github_token": "", "action_webhook_url": ""})())
        client = self.FakeClient()
        monkeypatch.setattr(notif.httpx, "AsyncClient", lambda timeout=None: client)
        result = run(notif.create_github_pr("example.com", self._changes(), token="ghp_explicit"))
        assert result["ok"] is True
        auth = client.requests[0][2]["headers"]["Authorization"]
        assert auth == "Bearer ghp_explicit"
        assert "ghp_explicit" in client.requests[1][2]["headers"]["Authorization"]

    def test_no_token_no_pr(self, monkeypatch):
        monkeypatch.setattr(notif, "settings", type("S", (), {"github_token": "", "action_webhook_url": ""})())
        assert run(notif.create_github_pr("example.com", self._changes())) is None
