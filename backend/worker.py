"""Arq worker process. Run with: .venv/bin/python -m arq backend.worker.WorkerSettings"""

from backend.config import settings
from backend.services.queue import redis_settings

async def startup(ctx):
    from backend.logging_setup import setup_logging
    setup_logging()
    from backend.db.mongo import connect_db
    await connect_db(settings.mongodb_uri)
    from backend.logging_setup import get_logger
    get_logger("worker").info("Worker connected to MongoDB")


async def shutdown(ctx):
    from backend.db.mongo import close_db
    await close_db()


async def analyze_job(ctx, job_id: str, url: str, max_pages: int = 50):
    from backend.routes.analysis import run_analysis_pipeline
    await run_analysis_pipeline(job_id, url, max_pages)


async def approve_all_batch(ctx, job_id: str):
    from backend.routes.actions import _approve_all_batch
    await _approve_all_batch(job_id)


async def keyword_check(ctx, job_id: str):
    from backend.services.keyword_tracking import check_keywords
    await check_keywords(job_id)


async def competitor_audit(ctx, target_job_id: str, competitors: list[str]):
    from backend.routes.analysis import run_competitor_pipeline
    await run_competitor_pipeline(target_job_id, competitors)


class WorkerSettings:
    functions = [analyze_job, approve_all_batch, keyword_check, competitor_audit]
    redis_settings = redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 3
    job_timeout = 14400
    keep_result = 60
    keep_result_failed = 3600
