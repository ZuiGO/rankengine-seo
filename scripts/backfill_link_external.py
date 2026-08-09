"""One-time backfill: stamp the `external` flag on link_health rows for jobs
whose rows were written before the flag existed (pre-UI-overhaul crawls).

Pure DB update — derives external targets from page_links.external_link_urls
(no network, idempotent). Run from repo root:
    .venv/bin/python scripts/backfill_link_external.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import settings
from backend.db.mongo import connect_db, get_db
from backend.services.url_normalizer import normalize_url


async def backfill_one(db, job_id: str) -> int:
    ext_urls = set()
    ext_pages = {}
    cursor = db.page_links.find({"job_id": job_id}, {"url": 1, "external_link_urls": 1})
    async for doc in cursor:
        page_url = doc.get("url", "")
        for target in doc.get("external_link_urls", []) or []:
            norm = normalize_url(target)
            if not norm:
                continue
            ext_urls.add(norm)
            ext_pages.setdefault(norm, set()).add(page_url)
    if not ext_urls:
        return 0
    norms = list(ext_urls)
    await db.link_health.update_many(
        {"job_id": job_id, "url": {"$in": norms}},
        {"$set": {"external": True}},
    )
    await db.link_health.update_many(
        {"job_id": job_id, "url": {"$nin": norms}},
        {"$set": {"external": False}},
    )
    from datetime import datetime
    for norm in norms:
        existing_row = await db.link_health.find_one({"job_id": job_id, "url": norm})
        if existing_row:
            continue
        await db.link_health.insert_one({
            "job_id": job_id,
            "url": norm,
            "status": "unchecked",
            "status_code": None,
            "external": True,
            "pages": sorted(ext_pages.get(norm, [])),
            "checked_at": datetime.utcnow(),
        })
    return len(norms)


async def main() -> None:
    await connect_db(settings.mongodb_uri)
    db = get_db()
    job_ids = await db.link_health.distinct("job_id")
    affected = []
    for job_id in job_ids:
        flagged_true = await db.link_health.count_documents(
            {"job_id": job_id, "external": True}
        )
        if flagged_true:
            continue
        n = await backfill_one(db, job_id)
        if n:
            affected.append((job_id, n))
    print("backfilled:", affected)


if __name__ == "__main__":
    asyncio.run(main())
