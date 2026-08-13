"""Staging page capture, storage, and replica rendering."""

import asyncio
import os
from datetime import datetime
from typing import Any

from playwright.async_api import async_playwright

from backend.config import settings
from backend.db.mongo import get_db
from backend.services.staging_extractor import extract_content_model

CAPTURE_CONCURRENCY = 2
MAX_HTML_STORED = 300_000


async def capture_page(url: str, job_id: str | None = None) -> dict[str, Any]:
    """Fetch a page via Playwright, extract model, store in staging_pages."""
    html, status_code = await _fetch_html_playwright(url)
    if not html:
        return {"status": "error", "message": f"Failed to fetch {url}, status {status_code}"}

    model = extract_content_model(html, url)

    db = get_db()
    doc = {
        "url": url,
        "html": html[:MAX_HTML_STORED],
        "status_code": status_code,
        "model": model,
        "job_id": job_id,
        "captured_at": datetime.utcnow(),
    }
    result = await db.staging_pages.insert_one(doc)
    doc["_id"] = result.inserted_id

    return {
        "status": "ok",
        "staging_page_id": str(result.inserted_id),
        "url": url,
        "model": model,
    }


async def _fetch_html_playwright(url: str) -> tuple[str | None, int | None]:
    """Fetch page HTML via Playwright (shared with crawler path)."""
    from backend.services.crawler import _chromium_slots
    async with _chromium_slots:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (compatible; ZuiGO-Engine/1.0; +https://zuigo.ai/bot)",
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                status = response.status if response else None
                html = await page.content()
                return html, status
            except Exception as e:
                return None, None
            finally:
                await browser.close()


async def get_staging_page(staging_page_id: str) -> dict[str, Any] | None:
    from bson import ObjectId
    db = get_db()
    doc = await db.staging_pages.find_one({"_id": ObjectId(staging_page_id)})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


async def list_staging_pages(job_id: str | None = None, limit: int = 50) -> list[dict]:
    db = get_db()
    query = {}
    if job_id:
        query["job_id"] = job_id
    cursor = db.staging_pages.find(query).sort("captured_at", -1).limit(limit)
    pages = await cursor.to_list(length=limit)
    for p in pages:
        p["id"] = str(p.pop("_id"))
    return pages


async def delete_staging_page(staging_page_id: str) -> bool:
    from bson import ObjectId
    db = get_db()
    result = await db.staging_pages.delete_one({"_id": ObjectId(staging_page_id)})
    return result.deleted_count > 0


async def render_staging_page(
    staging_page_id: str,
    applied_overrides: dict[str, str] | None = None,
) -> str:
    """Render the stored HTML with applied suggestion overrides."""
    doc = await get_staging_page(staging_page_id)
    if not doc:
        return "<html><body>Staging page not found</body></html>"

    html = doc.get("html", "")
    if not html:
        return "<html><body>No HTML stored</body></html>"

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")

    if applied_overrides:
        _apply_overrides(soup, applied_overrides)

    _inject_noindex(soup)
    return str(soup)


def _apply_overrides(soup: BeautifulSoup, overrides: dict[str, str]) -> None:
    """Apply suggestion overrides to the HTML soup."""
    for field_type, value in overrides.items():
        if field_type == "title_tag":
            title_tag = soup.find("title")
            if title_tag:
                title_tag.string = value
        elif field_type == "meta_description":
            meta = soup.find("meta", attrs={"name": "description"})
            if meta:
                meta["content"] = value
            else:
                head = soup.find("head")
                if head:
                    new_meta = soup.new_tag("meta", attrs={"name": "description", "content": value})
                    head.append(new_meta)
        elif field_type == "h1":
            h1 = soup.find("h1")
            if h1:
                h1.string = value
        elif field_type == "h2":
            h2 = soup.find("h2")
            if h2:
                h2.string = value
        elif field_type == "meta_robots":
            pass
        elif field_type == "schema_jsonld":
            pass


def _inject_noindex(soup: BeautifulSoup) -> None:
    """Inject noindex, nofollow meta tag into head."""
    head = soup.find("head")
    if not head:
        return
    existing = soup.find("meta", attrs={"name": "robots"})
    if existing:
        existing["content"] = "noindex, nofollow"
    else:
        meta = soup.new_tag("meta", attrs={"name": "robots", "content": "noindex, nofollow"})
        head.append(meta)


async def get_overrides_for_page(staging_page_id: str) -> dict[str, str]:
    """Get all applied overrides for a staging page."""
    db = get_db()
    cursor = db.staging_overrides.find({"staging_page_id": staging_page_id})
    overrides = {}
    async for doc in cursor:
        overrides[doc["field_type"]] = doc["value"]
    return overrides


async def apply_override(
    staging_page_id: str,
    field_type: str,
    value: str,
    suggestion_id: str,
) -> None:
    """Store an applied override for a staging page."""
    db = get_db()
    await db.staging_overrides.update_one(
        {"staging_page_id": staging_page_id, "field_type": field_type},
        {
            "$set": {
                "value": value,
                "suggestion_id": suggestion_id,
                "applied_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )


async def remove_override(staging_page_id: str, field_type: str) -> None:
    db = get_db()
    await db.staging_overrides.delete_one(
        {"staging_page_id": staging_page_id, "field_type": field_type}
    )