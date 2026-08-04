import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db.mongo import get_db
from backend.services.audit_service import log_audit
from backend.services.change_applier import create_version_for_action, get_content_versions
from bson.objectid import ObjectId

router = APIRouter(prefix="/api/actions", tags=["actions"])

_active_batches: set[str] = set()


async def _record_feedback(db, item: dict, status: str) -> None:
    """One row per review so generation can learn issue_key approval rates."""
    issue_key = item.get("issue_key")
    if not issue_key:
        return
    from datetime import datetime
    await db.action_feedback.insert_one({
        "job_id": item.get("job_id"),
        "action_id": str(item.get("_id")),
        "issue_key": issue_key,
        "content_type": item.get("content_type", ""),
        "page_url": item.get("page_url", ""),
        "status": status,
        "reviewed_at": datetime.utcnow(),
    })


async def _approve_all_batch(job_id: str) -> None:
    db = get_db()
    sem = asyncio.Semaphore(6)
    errors = []

    async def process(item):
        async with sem:
            try:
                await asyncio.wait_for(create_version_for_action(item, "approved"), timeout=20)
                await db.action_items.update_one(
                    {"_id": item["_id"]},
                    {"$set": {"status": "approved"}},
                )
                await _record_feedback(db, item, "approved")
                await log_audit(
                    "action_approved",
                    job_id,
                    {"action_id": str(item["_id"]), "content_type": item.get("content_type"), "impact": item.get("impact_on_ranking")},
                )
            except Exception as e:
                errors.append(f"{item.get('content_type', '')} {item.get('page_url', '')}: {e}")

    try:
        cursor = db.action_items.find({"job_id": job_id, "status": "pending"}).sort("content_type", 1)
        items = await cursor.to_list(length=1000)
        await asyncio.gather(*[process(i) for i in items])
        try:
            from backend.services.dummy_site import regenerate_after_change
            asyncio.create_task(regenerate_after_change(job_id))
        except Exception as e:
            from backend.logging_setup import get_logger
            get_logger("actions").warning("Dummy site auto-regeneration hook failed: %s", e)
        if errors:
            from backend.logging_setup import get_logger
            get_logger("actions").warning("Approve-all completed with %s error(s) for job=%s: %s", len(errors), job_id, errors[:5])
    finally:
        _active_batches.discard(job_id)


@router.post("/{job_id}/approve-all")
async def approve_all_actions(job_id: str):
    if job_id in _active_batches:
        return {"status": "running", "job_id": job_id}

    db = get_db()
    pending = await db.action_items.count_documents({"job_id": job_id, "status": "pending"})
    if not pending:
        return {"status": "ok", "job_id": job_id, "approved": 0, "failed": 0, "errors": []}

    _active_batches.add(job_id)
    from backend.services.queue import run_or_fallback
    await run_or_fallback("approve_all_batch", _approve_all_batch, job_id)
    return {"status": "started", "job_id": job_id, "pending": pending}


class ApproveRequest(BaseModel):
    status: str  # approved, rejected


@router.get("/{job_id}")
async def list_actions(job_id: str, status_filter: str | None = None):
    db = get_db()
    query = {"job_id": job_id}
    if status_filter:
        query["status"] = status_filter

    cursor = db.action_items.find(query).sort("content_type", 1)
    items = await cursor.to_list(length=1000)
    for item in items:
        item["id"] = str(item.pop("_id"))
    return {"actions": items, "total": len(items)}


@router.post("/{action_id}/approve")
async def approve_action(action_id: str, req: ApproveRequest):
    db = get_db()
    item = await db.action_items.find_one({"_id": ObjectId(action_id)})
    if not item:
        raise HTTPException(404, "Action item not found")
    await db.action_items.update_one(
        {"_id": ObjectId(action_id)},
        {"$set": {"status": req.status}}
    )
    await _record_feedback(db, item, req.status)
    await log_audit(
        "action_" + req.status,
        item.get("job_id"),
        {"action_id": action_id, "content_type": item.get("content_type"), "impact": item.get("impact_on_ranking")},
    )

    version = None
    try:
        version = await create_version_for_action(item, req.status)
    except Exception as e:
        from backend.logging_setup import get_logger
        get_logger("actions").warning("Change application failed action=%s: %s", action_id, e)

    try:
        import asyncio
        from backend.services.dummy_site import regenerate_after_change
        job_id = item.get("job_id")
        if job_id:
            asyncio.create_task(regenerate_after_change(job_id))
    except Exception as e:
        from backend.logging_setup import get_logger
        get_logger("actions").warning("Dummy site auto-regeneration hook failed: %s", e)

    return {
        "status": "ok",
        "action_id": action_id,
        "new_status": req.status,
        "version": version,
    }


@router.get("/{job_id}/versions")
async def list_content_versions(job_id: str):
    return await get_content_versions(job_id)


@router.get("/{job_id}/report")
async def get_action_report(job_id: str):
    db = get_db()
    cursor = db.action_items.find({"job_id": job_id})
    items = await cursor.to_list(length=1000)
    report_rows = []
    for item in items:
        report_rows.append({
            "content_id": str(item.get("_id", "")),
            "content_type": item.get("content_type", ""),
            "impact_on_ranking": item.get("impact_on_ranking", ""),
            "identified_issues": item.get("identified_issues", []),
            "how_to_improve": item.get("improvement_suggestions", []),
            "status": item.get("status", "pending"),
        })
    return {"job_id": job_id, "action_items": report_rows}
