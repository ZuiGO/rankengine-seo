"""One-shot demo seed: rebuild the Chroma semantic index for seeded jobs.

Idempotent — index_job_vectors wipes and rebuilds each job collection.
Run inside the app container after mongo-seed restores the dump:
    docker compose run --rm seed-vectors
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings
from backend.db.mongo import connect_db, get_db
from backend.logging_setup import get_logger
from backend.services.vector_service import index_job_vectors

logger = get_logger("seed")


async def main() -> int:
    await connect_db(settings.mongodb_uri)
    db = get_db()
    cursor = db.analysis_jobs.find({"status": "completed"}).sort("created_at", -1)
    jobs = await cursor.to_list(length=None)
    if not jobs:
        logger.warning("No completed jobs found to index")
        return 1
    total = 0
    for job in jobs:
        job_id = str(job["_id"])
        domain = job.get("url") or job.get("domain") or job_id
        try:
            indexed = await index_job_vectors(job_id)
            total += indexed
            logger.info("Indexed job=%s domain=%s docs=%s", job_id, domain, indexed)
        except Exception as exc:  # noqa: BLE001
            logger.error("Index failed for job=%s: %s", job_id, exc)
    logger.info("Seed complete: %s docs indexed across %s jobs", total, len(jobs))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
