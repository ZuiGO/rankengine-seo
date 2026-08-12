"""Slack notifications via incoming webhook + SMTP email. No-op (with a log line) when not configured."""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from backend.config import settings
from backend.logging_setup import get_logger

logger = get_logger("notifications")


async def get_smtp_config() -> dict:
    """SMTP: MongoDB app_settings first, .env as fallback (mirrors GitHub config)."""
    try:
        from backend.db.mongo import get_db
        db = get_db()
        doc = await db.app_settings.find_one({"key": "smtp"}) or {}
    except Exception:
        doc = {}
    return {
        "host": doc.get("host") or settings.smtp_host,
        "port": doc.get("port") or settings.smtp_port,
        "user": doc.get("user") or settings.smtp_user,
        "password": doc.get("password") or settings.smtp_password,
        "from_email": doc.get("from_email") or settings.smtp_from,
        "use_tls": doc.get("use_tls", settings.smtp_use_tls),
    }


def _send_sync(cfg: dict, to: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None) -> None:
    if not cfg.get("host"):
        raise ValueError("SMTP host not configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("from_email") or cfg.get("user") or "no-reply@zuigo.ai"
    msg["To"] = to
    msg.set_content(body)
    if attachment:
        filename, payload = attachment
        msg.add_attachment(payload, maintype="application", subtype="pdf", filename=filename)
    port = int(cfg.get("port") or 587)
    if port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], port, timeout=20, context=context) as server:
            if cfg.get("user") and cfg.get("password"):
                server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
    elif cfg.get("use_tls", True):
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], port, timeout=20) as server:
            server.starttls(context=context)
            if cfg.get("user") and cfg.get("password"):
                server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], port, timeout=20) as server:
            if cfg.get("user") and cfg.get("password"):
                server.login(cfg["user"], cfg["password"])
            server.send_message(msg)


async def send_email(to: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None) -> bool:
    """Send an email via the configured SMTP server (DB settings first, .env fallback)."""
    cfg = await get_smtp_config()
    if not cfg.get("host"):
        logger.debug("SMTP not configured; skipping email: %s", subject)
        return False
    try:
        await asyncio.to_thread(_send_sync, cfg, to, subject, body, attachment)
        logger.info("Email sent to=%s subject=%s", to, subject)
        return True
    except Exception as e:
        logger.warning("Email send failed to=%s: %s", to, e)
        return False


async def try_send_email(to: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None) -> tuple[bool, str | None]:
    """Like send_email but returns (sent, error_message) with the real failure reason."""
    cfg = await get_smtp_config()
    if not cfg.get("host"):
        return False, "SMTP host not configured. Add it in Settings → Email."
    try:
        await asyncio.to_thread(_send_sync, cfg, to, subject, body, attachment)
        logger.info("Email sent to=%s subject=%s", to, subject)
        return True, None
    except Exception as e:
        logger.warning("Email send failed to=%s: %s", to, e)
        return False, str(e)


async def email_report(job_id: str, to: str) -> tuple[bool, str | None]:
    """Render the branded PDF report for a job and email it. Returns (sent, error_message)."""
    from backend.routes.reports import _report_html, _render_pdf
    from backend.db.mongo import get_db

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return False, "Job not found"
    html = await _report_html(job_id)
    if isinstance(html, dict):
        return False, "Report rendering failed"
    pdf = await _render_pdf(html)
    if pdf is None:
        return False, "PDF rendering failed"
    domain = (job.get("url") or "").split("//")[-1].split("/")[0]
    return await try_send_email(
        to,
        f"[ZuiGO Engine] SEO report for {domain}",
        f"Hi,\n\nYour SEO report for {job.get('url')} is ready.\n\nThe PDF report is attached.\n\n— ZuiGO Engine",
        (f"seo-report-{job_id}.pdf", pdf),
    )


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


async def get_github_config() -> dict:
    """GitHub token: MongoDB app_settings first, .env as fallback."""
    try:
        from backend.db.mongo import get_db
        db = get_db()
        doc = await db.app_settings.find_one({"key": "github"}) or {}
    except Exception:
        doc = {}
    return {"token": doc.get("token") or settings.github_token}


async def create_github_pr(domain: str, changes: list[dict], token: str | None = None) -> dict | None:
    """Open a PR on a repo named after the domain when a GitHub token is configured."""
    token = token or settings.github_token
    if not token:
        return None
    repo = domain.replace(".", "-").replace(":", "-")
    headers = {
        "Authorization": f"Bearer {token}",
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
