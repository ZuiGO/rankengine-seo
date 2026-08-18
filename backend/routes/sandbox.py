import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional

from backend.db.mongo import get_db
from backend.models.schemas import SandboxAuditLog
from backend.services.connectors.git_static_connector import GitStaticConnector
from backend.services.snapshots.comparison_view import get_comparison_data

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])

LOW_RISK_FIELDS = {"alt_text", "canonical", "footer_copyright"}

class EditRequest(BaseModel):
    suggested_value: str

class BatchApproveRequest(BaseModel):
    field_type: str

async def _log_audit(suggestion_id: str, field_type: str, old_status: str, new_status: str, edited_value: Optional[str] = None, commit_hash: Optional[str] = None, diff: Optional[str] = None, preview_url: Optional[str] = None):
    db = get_db()
    log = SandboxAuditLog(
        id=str(uuid.uuid4()),
        suggestion_id=suggestion_id,
        field_type=field_type,
        old_status=old_status,
        new_status=new_status,
        edited_value=edited_value,
        commit_hash=commit_hash,
        diff=diff,
        preview_url=preview_url,
        timestamp=datetime.utcnow()
    )
    await db.sandbox_audit_logs.insert_one(log.model_dump())

@router.get("/suggestions")
async def get_suggestions():
    db = get_db()
    cursor = db.sandbox_suggestions.find({"status": {"$in": ["pending", "approved, pending apply", "applied", "failed"]}})
    suggestions = await cursor.to_list(length=100)
    
    # Exclude _id object
    for s in suggestions:
        if "_id" in s:
            del s["_id"]
    return {"suggestions": suggestions}

@router.post("/suggestions/{id}/approve")
async def approve_suggestion(id: str):
    db = get_db()
    doc = await db.sandbox_suggestions.find_one({"id": id})
    if not doc:
        raise HTTPException(status_code=404, detail="Suggestion not found")
        
    old_status = doc.get("status", "pending")
    new_status = "approved, pending apply"
    
    await db.sandbox_suggestions.update_one(
        {"id": id}, 
        {"$set": {"status": new_status}}
    )
    await _log_audit(id, doc.get("field_type", ""), old_status, new_status)
    return {"status": "success"}

@router.post("/suggestions/{id}/reject")
async def reject_suggestion(id: str):
    db = get_db()
    doc = await db.sandbox_suggestions.find_one({"id": id})
    if not doc:
        raise HTTPException(status_code=404, detail="Suggestion not found")
        
    old_status = doc.get("status", "pending")
    new_status = "rejected"
    
    await db.sandbox_suggestions.update_one(
        {"id": id}, 
        {"$set": {"status": new_status}}
    )
    await _log_audit(id, doc.get("field_type", ""), old_status, new_status)
    return {"status": "success"}

@router.post("/suggestions/{id}/edit")
async def edit_suggestion(id: str, payload: EditRequest):
    db = get_db()
    doc = await db.sandbox_suggestions.find_one({"id": id})
    if not doc:
        raise HTTPException(status_code=404, detail="Suggestion not found")
        
    old_status = doc.get("status", "pending")
    new_status = "approved, pending apply"
    edited_value = payload.suggested_value
    
    await db.sandbox_suggestions.update_one(
        {"id": id}, 
        {"$set": {"status": new_status, "suggested_value": edited_value}}
    )
    await _log_audit(id, doc.get("field_type", ""), old_status, new_status, edited_value=edited_value)
    return {"status": "success"}

@router.post("/suggestions/batch_approve")
async def batch_approve(payload: BatchApproveRequest):
    db = get_db()
    if payload.field_type not in LOW_RISK_FIELDS:
        raise HTTPException(status_code=400, detail=f"Cannot batch approve high-risk field: {payload.field_type}")
        
    cursor = db.sandbox_suggestions.find({"field_type": payload.field_type, "status": "pending"})
    suggestions = await cursor.to_list(length=100)
    
    count = 0
    for doc in suggestions:
        old_status = doc.get("status", "pending")
        new_status = "approved, pending apply"
        await db.sandbox_suggestions.update_one(
            {"id": doc["id"]},
            {"$set": {"status": new_status}}
        )
        await _log_audit(doc["id"], doc.get("field_type", ""), old_status, new_status)
        count += 1
        
    return {"status": "success", "count": count}

@router.post("/suggestions/{id}/apply")
async def apply_suggestion(id: str):
    db = get_db()
    doc = await db.sandbox_suggestions.find_one({"id": id})
    if not doc:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    
    old_status = doc.get("status", "")
    if old_status not in ["approved, pending apply", "failed"]:
        raise HTTPException(status_code=400, detail="Suggestion is not approved")
        
    connector = GitStaticConnector()
    success, msg, commit_hash, diff, preview_url = await connector.apply_field(doc)
    
    new_status = "applied" if success else "failed"
    
    update_data = {"status": new_status}
    if commit_hash:
        update_data["last_commit_hash"] = commit_hash
        
    await db.sandbox_suggestions.update_one({"id": id}, {"$set": update_data})
    await _log_audit(id, doc.get("field_type", ""), old_status, new_status, commit_hash=commit_hash, diff=diff, preview_url=preview_url)
    
    if not success:
        raise HTTPException(status_code=500, detail=f"Apply failed: {msg}")
        
    return {"status": "success", "preview_url": preview_url, "commit_hash": commit_hash}

@router.post("/suggestions/{id}/rollback")
async def rollback_suggestion(id: str):
    db = get_db()
    doc = await db.sandbox_suggestions.find_one({"id": id})
    if not doc:
        raise HTTPException(status_code=404, detail="Suggestion not found")
        
    old_status = doc.get("status", "")
    if old_status != "applied":
        raise HTTPException(status_code=400, detail="Suggestion is not applied")
        
    commit_hash = doc.get("last_commit_hash")
    if not commit_hash:
        raise HTTPException(status_code=400, detail="No commit hash found to rollback")
        
    connector = GitStaticConnector()
    success, msg, new_commit, preview_url = await connector.rollback_field(doc, commit_hash)
    
    if not success:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {msg}")
        
    new_status = "approved, pending apply"
    await db.sandbox_suggestions.update_one(
        {"id": id}, 
        {"$set": {"status": new_status, "last_commit_hash": new_commit}}
    )
    await _log_audit(id, doc.get("field_type", ""), old_status, new_status, commit_hash=new_commit, preview_url=preview_url)
    
    return {"status": "success", "preview_url": preview_url, "commit_hash": new_commit}

@router.get("/audit")
async def get_audit_logs():
    db = get_db()
    cursor = db.sandbox_audit_logs.find().sort("timestamp", -1)
    logs = await cursor.to_list(length=100)
    for l in logs:
        if "_id" in l:
            del l["_id"]
    return {"logs": logs}

@router.get("/comparison")
async def get_sandbox_comparison():
    """
    Returns the page-level comparison view data:
    - baseline and current screenshots
    - field-by-field Old vs New table
    - composite SEO score delta
    - raw history panel data
    """
    try:
        data = await get_comparison_data()
        if "error" in data:
            raise HTTPException(status_code=404, detail=data["error"])
        return data
    except Exception as e:
        logger.error(f"Failed to fetch comparison data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class SinglePageRequest(BaseModel):
    url: str

@router.post("/single-page")
async def start_single_page(payload: SinglePageRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    from backend.services.single_page_service import run_single_page_analysis
    background_tasks.add_task(run_single_page_analysis, payload.url, job_id)
    return {"status": "accepted", "job_id": job_id}

@router.get("/single-page/{job_id}")
async def get_single_page_status(job_id: str):
    db = get_db()
    doc = await db.single_page_analyses.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")

    if "_id" in doc:
        del doc["_id"]

    return doc
