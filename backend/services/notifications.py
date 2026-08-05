"""Slack notifications via incoming webhook. No-op (with a log line) when no webhook is configured."""

import httpx

from backend.config import settings
from backend.logging_setup import get_logger

logger = get_logger("notifications")


async def send_slack(title: str, fields: dict, color: str = "good") -> bool:
    if not settings.slack_webhook_url:
        logger.debug("Slack webhook not configured; skipping notification: %s", title)
        return False
    try:
        attachments = [{
            "color": color,
            "title": title,
            "fields": [{"title": k, "value": str(v), "short": True} for k, v in fields.items()],
        }]
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.slack_webhook_url, json={"attachments": attachments})
        if resp.status_code >= 400:
            logger.warning("Slack webhook failed: HTTP %s", resp.status_code)
            return False
        logger.info("Slack notification sent: %s", title)
        return True
    except Exception as e:
        logger.warning("Slack webhook error: %s", e)
        return False


async def send_webhook(payload: dict) -> bool:
    """Generic action webhook (CMS/automation targets). No-op when unconfigured."""
    if not settings.action_webhook_url:
        logger.debug("Action webhook not configured; skipping: %s", payload.get("event", "event"))
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.action_webhook_url, json=payload)
        if resp.status_code >= 400:
            logger.warning("Action webhook failed: HTTP %s", resp.status_code)
            return False
        logger.info("Action webhook sent: %s %s", payload.get("event"), payload.get("action_id", ""))
        return True
    except Exception as e:
        logger.warning("Action webhook error: %s", e)
        return False


async def create_github_pr(domain: str, changes: list[dict]) -> dict | None:
    """Open a PR on a repo named after the domain when a GitHub token is configured."""
    if not settings.github_token:
        return None
    repo = domain.replace(".", "-").replace(":", "-")
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = "\n\n".join(
        f"## {c.get('content_type', '')} - {c.get('page_url', '')}\n\n"
        f"{chr(10).join(c.get('identified_issues') or [])}\n\n"
        f"Suggested: {'; '.join(c.get('improvement_suggestions') or [])}"
        for c in changes[:20]
    )
    payload = {
        "title": f"[ZuiGO Engine] SEO patch for {domain} ({len(changes)} actions)",
        "head": f"rankengine/{domain}",
        "base": "main",
        "body": body or "See attached patch for details.",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            me = await client.get("https://api.github.com/user", headers=headers)
            if me.status_code >= 400:
                logger.warning("GitHub auth failed: HTTP %s", me.status_code)
                return {"ok": False, "status_code": me.status_code}
            owner = (me.json() or {}).get("login", "")
            if not owner:
                return {"ok": False, "error": "GitHub user lookup returned no login"}
            resp = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers=headers,
                json=payload,
            )
        if resp.status_code >= 400:
            logger.warning("GitHub PR failed: HTTP %s", resp.status_code)
            return {"ok": False, "status_code": resp.status_code}
        logger.info("GitHub PR created: %s", resp.json().get("html_url", ""))
        return {"ok": True, "html_url": resp.json().get("html_url", "")}
    except Exception as e:
        logger.warning("GitHub PR error: %s", e)
        return {"ok": False, "error": str(e)}
