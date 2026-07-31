from datetime import datetime

from backend.db.mongo import get_db


async def log_audit(event: str, job_id: str | None = None, details: dict | None = None):
    db = get_db()
    try:
        await db.audit_logs.insert_one({
            "event": event,
            "job_id": job_id,
            "details": details or {},
            "timestamp": datetime.utcnow(),
        })
    except Exception as e:
        print(f"Audit log write failed: {e}")
