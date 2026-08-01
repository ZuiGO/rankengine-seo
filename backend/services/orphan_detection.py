"""Orphan page detection: pages with no internal links pointing at them.

Uses per-page `internal_link_urls` gathered during the crawl (all pages were crawled,
so the target set is complete). Home pages are exempt, and URLs are normalized so
trailing-slash variants do not count as separate targets.
"""

from datetime import datetime

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("orphans")


def _norm(url: str) -> str:
    return (url or "").rstrip("/").lower()


async def detect_orphan_pages(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 0, "html_mobile": 0}).to_list(length=None)
    if not pages:
        return {"status": "error", "message": "No pages for this job"}

    targets = set()
    async for pl in db.page_links.find({"job_id": job_id}, {"internal_link_urls": 1}):
        for target in pl.get("internal_link_urls", []):
            targets.add(_norm(target))

    orphans = []
    for p in pages:
        if p.get("page_type") == "home":
            continue
        if _norm(p["url"]) not in targets:
            orphans.append({"page_url": p["url"], "title": p.get("title", "")})

    doc = {
        "job_id": job_id,
        "pages": orphans,
        "pages_analyzed": len(pages),
        "orphan_pages": len(orphans),
        "generated_at": datetime.utcnow(),
    }
    await db.orphan_pages.update_one({"job_id": job_id}, {"$set": doc}, upsert=True)
    logger.info("Orphan detection job=%s pages=%s orphans=%s", job_id, len(pages), len(orphans))
    return doc


async def get_orphan_pages(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.orphan_pages.find_one({"job_id": job_id})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
