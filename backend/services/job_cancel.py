"""Cooperative job cancellation: a `cancelled: true` flag on the analysis_jobs doc.

Checkpoints call `check_cancelled(job_id)` and it raises JobCancelled; the pipeline's
JobCancelled handler marks the job cancelled and cleans up its data.
"""


class JobCancelled(Exception):
    def __init__(self, job_id: str):
        super().__init__(f"Job {job_id} cancelled by user")
        self.job_id = job_id


async def check_cancelled(job_id: str) -> None:
    """Raise JobCancelled if the analysis_jobs doc carries the cancelled flag.

    Never raises networking/DB errors: cancellation is best-effort, so a
    missing DB (tests, degraded mode) just skips the check.
    """
    try:
        from backend.db.mongo import get_db

        db = get_db()
    except Exception:
        return
    if db is None:
        return
    try:
        doc = await db.analysis_jobs.find_one({"_id": job_id}, {"cancelled": 1, "status": 1})
    except Exception:
        return
    if doc and (doc.get("cancelled") or doc.get("status") == "cancelled"):
        raise JobCancelled(job_id)