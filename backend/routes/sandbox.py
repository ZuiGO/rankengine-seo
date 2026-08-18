import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.snapshots.comparison_view import get_comparison_data
from backend.services.snapshot_service import capture_snapshot
from backend.services.notifications import create_github_pr

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])

LOW_RISK_FIELDS = {"alt_text", "canonical", "footer_copyright"}

class EditRequest(BaseModel):
    suggested_value: str

class BatchApproveRequest(BaseModel):
    field_type: str

async def _log_audit(suggestion_id: str, field_type: str, old_status: str, new_status: str, edited_value: Optional[str] = None, commit_hash: Optional[str] = None, diff: Optional[str] = None, preview_url: Optional[str] = None):
    db = get_db()
    log = {
        "id": str(uuid.uuid4()),
        "suggestion_id": suggestion_id,
        "field_type": field_type,
        "old_status": old_status,
        "new_status": new_status,
        "edited_value": edited_value,
        "commit_hash": commit_hash,
        "diff": diff,
        "preview_url": preview_url,
        "timestamp": datetime.utcnow()
    }
    await db.sandbox_audit_logs.insert_one(log)

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
        
    page_url = doc.get("page_url", "https://example.com")
    
    # Take visual snapshot with injected changes
    try:
        await capture_snapshot(page_url, job_id=doc.get("job_id"), tag=f"apply_{id}", changes=[doc])
    except Exception as e:
        pass  # Snapshot failing shouldn't block PR
        
    from urllib.parse import urlparse
    domain = urlparse(page_url).netloc
    
    # Create PR directly
    pr_result = await create_github_pr(domain, [doc])
    
    if pr_result and pr_result.get("ok"):
        success = True
        preview_url = pr_result.get("html_url")
        msg = "Successfully applied via GitHub PR"
    else:
        success = False
        msg = pr_result.get("error") if pr_result else "No GitHub token configured"
        preview_url = ""
        
    new_status = "applied" if success else "failed"
    
    update_data = {"status": new_status}
    if success:
        update_data["last_commit_hash"] = "github_pr" # Placeholder
        
    await db.sandbox_suggestions.update_one({"id": id}, {"$set": update_data})
    await _log_audit(id, doc.get("field_type", ""), old_status, new_status, commit_hash="github_pr" if success else None, diff="", preview_url=preview_url)
    
    if not success:
        raise HTTPException(status_code=500, detail=f"Apply failed: {msg}")
        
    return {"status": "success", "preview_url": preview_url, "commit_hash": "github_pr"}

@router.post("/suggestions/{id}/rollback")
async def rollback_suggestion(id: str):
    db = get_db()
    doc = await db.sandbox_suggestions.find_one({"id": id})
    if not doc:
        raise HTTPException(status_code=404, detail="Suggestion not found")
        
    old_status = doc.get("status", "")
    if old_status != "applied":
        raise HTTPException(status_code=400, detail="Suggestion is not applied")
        
    # Since we are using GitHub PRs, we can't easily auto-rollback. We just revert state to pending.
    new_status = "approved, pending apply"
    await db.sandbox_suggestions.update_one(
        {"id": id}, 
        {"$set": {"status": new_status, "last_commit_hash": ""}}
    )
    await _log_audit(id, doc.get("field_type", ""), old_status, new_status, commit_hash="", preview_url="")
    
    return {"status": "success", "preview_url": "", "commit_hash": ""}

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
