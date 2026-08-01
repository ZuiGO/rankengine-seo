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
        return True
    except Exception as e:
        logger.warning("Slack webhook error: %s", e)
        return False
