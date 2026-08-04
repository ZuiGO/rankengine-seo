"""Unit tests for webhook notifications and GitHub PR gating (no real network)."""

import asyncio

import backend.services.notifications as notif


def run(coro):
    return asyncio.run(coro)


class FakeSettings:
    action_webhook_url = ""
    github_token = ""


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, timeout=None):
        self.requests = []
        self.status_code = 200
        self.user_login = "octocat"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return FakeResponse(self.status_code, {"html_url": f"https://github.com/pull/{len(self.requests)}"})

    async def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return FakeResponse(200, {"login": self.user_login})


class TestSendWebhook:
    def test_noop_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(notif, "settings", FakeSettings())
        assert run(notif.send_webhook({"event": "action_approved"})) is False

    def test_posts_when_configured(self, monkeypatch):
        settings = FakeSettings()
        settings.action_webhook_url = "https://hooks.example.com/push"
        monkeypatch.setattr(notif, "settings", settings)
        client = FakeClient()
        monkeypatch.setattr(notif.httpx, "AsyncClient", lambda timeout=None: client)
        result = run(notif.send_webhook({"event": "action_approved", "action_id": "abc"}))
        assert result is True
        assert len(client.requests) == 1
        method, url, kwargs = client.requests[0]
        assert url == "https://hooks.example.com/push"
        assert kwargs["json"]["event"] == "action_approved"

    def test_non2xx_returns_false(self, monkeypatch):
        settings = FakeSettings()
        settings.action_webhook_url = "https://hooks.example.com/push"
        monkeypatch.setattr(notif, "settings", settings)
        client = FakeClient()
        client.status_code = 500
        monkeypatch.setattr(notif.httpx, "AsyncClient", lambda timeout=None: client)
        assert run(notif.send_webhook({"event": "action_rejected"})) is False


class TestCreateGithubPr:
    def _changes(self):
        return [{
            "content_type": "image",
            "page_url": "https://example.com/a",
            "identified_issues": ["Image has no alt text"],
            "improvement_suggestions": ["Add descriptive alt text"],
        }]

    def test_noop_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(notif, "settings", FakeSettings())
        assert run(notif.create_github_pr("example.com", self._changes())) is None

    def test_pr_created(self, monkeypatch):
        settings = FakeSettings()
        settings.github_token = "ghp_test"
        monkeypatch.setattr(notif, "settings", settings)
        client = FakeClient()
        monkeypatch.setattr(notif.httpx, "AsyncClient", lambda timeout=None: client)
        result = run(notif.create_github_pr("example.com", self._changes()))
        assert result["ok"] is True
        assert "/user" in client.requests[0][1]
        pr_url = client.requests[1][1]
        assert "repos/octocat/example-com/pulls" in pr_url
        assert client.requests[1][2]["json"]["base"] == "main"

    def test_pr_fails_on_non2xx(self, monkeypatch):
        settings = FakeSettings()
        settings.github_token = "ghp_test"
        monkeypatch.setattr(notif, "settings", settings)
        client = FakeClient()
        client.status_code = 404
        monkeypatch.setattr(notif.httpx, "AsyncClient", lambda timeout=None: client)
        result = run(notif.create_github_pr("example.com", self._changes()))
        assert result["ok"] is False