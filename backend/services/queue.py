"""Redis-backed job queue (Arq). Enqueues degrade to in-process tasks if Redis is down."""

import asyncio

from arq.connections import RedisSettings, create_pool

from backend.config import settings
from backend.logging_setup import get_logger

logger = get_logger("queue")

_pool = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue(job_name: str, *args, **kwargs) -> bool:
    """Queue a job. Returns False when the queue is unavailable (caller may fall back)."""
    try:
        pool = await get_pool()
        await pool.enqueue_job(job_name, *args, **kwargs)
        return True
    except Exception as e:
        logger.warning("Queue enqueue %s failed: %s", job_name, e)
        return False


async def run_or_fallback(job_name: str, fn, *args, **kwargs) -> bool:
    """Queue `job_name`; if the queue is unavailable, run `fn(*args)` in-process."""
    if await enqueue(job_name, *args, **kwargs):
        return True
    logger.warning("Running %s in-process (queue unavailable)", job_name)
    asyncio.create_task(fn(*args, **kwargs))
    return True
