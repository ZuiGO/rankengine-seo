import asyncio
from datetime import datetime

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("comparison_view")

async def get_comparison_data() -> dict:
    db = get_db()
    
    # 1. Fetch snapshots
    snapshots_cursor = db.sandbox_snapshots.find().sort("created_at", 1)
    snapshots = await snapshots_cursor.to_list(length=None)
    
    if not snapshots:
        return {"error": "No snapshots found"}
        
    baseline = snapshots[0]
    current = snapshots[-1]
    
    # Extract images
    baseline_img = baseline.get("screenshot_b64", "")
    current_img = current.get("screenshot_b64", "")
    
    # 2. Fetch suggestions to build the field comparison table
    suggestions_cursor = db.sandbox_suggestions.find()
    suggestions = await suggestions_cursor.to_list(length=None)
    
    field_comparison = []
    
    for sug in suggestions:
        field_type = sug.get("field_type")
        current_val = sug.get("current_value")
        suggested_val = sug.get("suggested_value")
        status = sug.get("status")
        
        # Calculate what the "new" value is based on status
        new_val = current_val
        is_changed = False
        
        if status == "applied":
            new_val = suggested_val
            is_changed = (new_val != current_val)
        else:
            new_val = current_val
            is_changed = False
            
        field_comparison.append({
            "field": field_type,
            "old_value": current_val,
            "new_value": new_val,
            "is_changed": is_changed,
            "status": status
        })
        
    # 3. Calculate SEO Score Delta
    # For a simple demo:
    # Title (15pts), Meta (15pts), Alt Text (15pts), Schema (20pts)
    
    def calculate_score(fields: list[dict], use_old: bool) -> int:
        score = 100
        for f in fields:
            val = f["old_value"] if use_old else f["new_value"]
            if f["field"] == "title" and not val:
                score -= 15
            elif f["field"] == "meta_description" and not val:
                score -= 15
            elif f["field"] == "alt_text" and not val:
                score -= 15
            elif f["field"] == "schema_markup" and not val:
                score -= 20
        return max(0, min(100, score))
        
    old_score = calculate_score(field_comparison, use_old=True)
    new_score = calculate_score(field_comparison, use_old=False)
    score_delta = new_score - old_score
    
    # 4. Fetch raw history trail from audit logs
    audit_logs_cursor = db.sandbox_audit_logs.find().sort("timestamp", -1)
    audit_logs = await audit_logs_cursor.to_list(length=None)
    
    raw_history = []
    for log in audit_logs:
        # Filter for relevant state changes
        if log.get("new_status") in ["applied", "rolled_back"]:
            raw_history.append({
                "suggestion_id": str(log.get("suggestion_id")),
                "action": log.get("new_status"),
                "timestamp": log.get("timestamp").isoformat() if log.get("timestamp") else None,
                "commit_hash": log.get("commit_hash"),
                "preview_url": log.get("preview_url")
            })
            
    # Enrich raw history with field names
    sug_map = {str(s.get("id", s.get("_id"))): s.get("field_type") for s in suggestions}
    for item in raw_history:
        item["field"] = sug_map.get(item["suggestion_id"], "Unknown")
        
    return {
        "baseline_screenshot": baseline_img,
        "current_screenshot": current_img,
        "field_comparison": field_comparison,
        "seo_score": {
            "old": old_score,
            "new": new_score,
            "delta": score_delta
        },
        "raw_history": raw_history
    }
