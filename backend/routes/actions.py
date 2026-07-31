from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db.mongo import get_db
from backend.services.audit_service import log_audit
from backend.services.change_applier import create_version_for_action, get_content_versions
from bson.objectid import ObjectId

router = APIRouter(prefix="/api/actions", tags=["actions"])


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
