"""One-time migration: remove duplicate `content_items` rows so counts are exact
and globally unique per (job, content type, source URL).

After running, restart the server so `ensure_indexes` creates the unique index.

Usage:
    .venv/bin/python scripts/dedupe_content_items.py
"""

import asyncio
import sys

from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings


async def main() -> int:
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client.rankengine
    coll = db.content_items

    groups = await coll.aggregate([
        {"$group": {
            "_id": {"job_id": "$job_id", "content_type": "$content_type", "source_url": "$source_url"},
            "ids": {"$push": "$_id"},
            "n": {"$sum": 1},
        }},
        {"$match": {"n": {"$gt": 1}}},
    ]).to_list(length=None)

    if not groups:
        print("No duplicate content items found — nothing to do.")
        await client.close()
        return 0

    removed = 0
    removed_extractions = 0
    for g in groups:
        ids = g["ids"]
        keep = ids[0]
        drop = ids[1:]
        res = await coll.delete_many({"_id": {"$in": drop}})
        removed += res.deleted_count
        ex = await db.content_extractions.delete_many({"content_item_id": {"$in": [str(x) for x in drop]}})
        removed_extractions += ex.deleted_count

    print(f"Deduplicated {len(groups)} key(s) across jobs; removed {removed} content item(s) "
          f"and {removed_extractions} orphan extraction(s).")
    await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))