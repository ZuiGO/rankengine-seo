import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from backend.db.mongo import get_db
from backend.services.audit_service import log_audit
from backend.services.change_applier import create_version_for_action, get_content_versions
from bson.objectid import ObjectId

router = APIRouter(prefix="/api/actions", tags=["actions"])

_active_batches: set[str] = set()


async def _notify_external(job_id: str, item: dict, status: str, version: dict | None = None) -> None:
    """Push approved/rejected actions to the configured webhook (+ GitHub PR hook)."""
    try:
        from backend.services.notifications import send_webhook, create_github_pr
        payload = {
            "event": f"action_{status}",
            "job_id": job_id,
            "action_id": str(item.get("_id")),
            "issue_key": item.get("issue_key", ""),
            "content_type": item.get("content_type", ""),
            "page_url": item.get("page_url", ""),
            "impact_on_ranking": item.get("impact_on_ranking", ""),
            "status": status,
            "identified_issues": item.get("identified_issues") or [],
            "improvement_suggestions": item.get("improvement_suggestions") or [],
        }
        if version:
            payload["version"] = {
                "field": version.get("field"),
                "before": version.get("before"),
                "after": version.get("after"),
                "diff": version.get("diff") or [],
                "generated_by": version.get("generated_by"),
                "qa": version.get("qa"),
            }
        await send_webhook(payload)
    except Exception as e:
        from backend.logging_setup import get_logger
        get_logger("actions").warning("External webhook notification failed job=%s: %s", job_id, e)


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


async def _approve_items(db, items: list[dict], job_id: str) -> list[str]:
    sem = asyncio.Semaphore(6)
    errors = []

    async def process(item):
        async with sem:
            try:
                version = await asyncio.wait_for(create_version_for_action(item, "approved"), timeout=20)
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
                await _notify_external(job_id, item, "approved", version)
            except Exception as e:
                errors.append(f"{item.get('content_type', '')} {item.get('page_url', '')}: {e}")

    await asyncio.gather(*[process(i) for i in items])
    if errors:
        from backend.logging_setup import get_logger
        get_logger("actions").warning("Approve processed with %s error(s) for job=%s: %s", len(errors), job_id, errors[:5])
    return errors


async def _reject_items(db, items: list[dict], job_id: str) -> None:
    await db.action_items.update_many(
        {"_id": {"$in": [i["_id"] for i in items]}},
        {"$set": {"status": "rejected"}},
    )
    for item in items:
        await _record_feedback(db, item, "rejected")
        await log_audit(
            "action_rejected",
            job_id,
            {"action_id": str(item["_id"]), "content_type": item.get("content_type"), "impact": item.get("impact_on_ranking")},
        )
        await _notify_external(job_id, item, "rejected")


async def _approve_all_batch(job_id: str) -> None:
    db = get_db()
    try:
        cursor = db.action_items.find({"job_id": job_id, "status": "pending"}).sort("content_type", 1)
        items = await cursor.to_list(length=1000)
        if items:
            await _approve_items(db, items, job_id)
            try:
                from backend.services.dummy_site import regenerate_after_change
                asyncio.create_task(regenerate_after_change(job_id))
            except Exception as e:
                from backend.logging_setup import get_logger
                get_logger("actions").warning("Dummy site auto-regeneration hook failed: %s", e)
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
async def list_actions(job_id: str, status_filter: str | None = None, severity: str | None = None):
    db = get_db()
    query = {"job_id": job_id}
    if status_filter:
        query["status"] = status_filter
    if severity:
        query["impact_on_ranking"] = severity

    cursor = db.action_items.find(query).sort("content_type", 1)
    items = await cursor.to_list(length=1000)
    for item in items:
        item["id"] = str(item.pop("_id"))
    return {"actions": items, "total": len(items)}


class BatchRequest(BaseModel):
    status: str  # approved, rejected
    ids: list[str] | None = None
    severity: str | None = None
    status_filter: str | None = None


@router.post("/{job_id}/batch")
async def batch_update_actions(job_id: str, req: BatchRequest):
    if req.status not in ("approved", "rejected"):
        raise HTTPException(400, "status must be 'approved' or 'rejected'")
    db = get_db()
    query: dict = {"job_id": job_id}
    if req.status_filter:
        query["status"] = req.status_filter
    else:
        query["status"] = "pending"
    if req.ids:
        try:
            query["_id"] = {"$in": [ObjectId(i) for i in req.ids]}
        except Exception:
            raise HTTPException(400, "Invalid action id in ids")
    if req.severity:
        query["impact_on_ranking"] = req.severity

    items = await db.action_items.find(query).to_list(length=1000)
    if not items:
        return {"status": "ok", "job_id": job_id, "updated": 0, "errors": []}

    if req.status == "rejected":
        await _reject_items(db, items, job_id)
        return {"status": "ok", "job_id": job_id, "updated": len(items), "errors": []}

    errors = await _approve_items(db, items, job_id)
    try:
        from backend.services.dummy_site import regenerate_after_change
        asyncio.create_task(regenerate_after_change(job_id))
    except Exception as e:
        from backend.logging_setup import get_logger
        get_logger("actions").warning("Dummy site auto-regeneration hook failed: %s", e)
    return {"status": "ok", "job_id": job_id, "updated": len(items), "errors": errors}


@router.get("/{job_id}/patch")
async def export_patch(job_id: str, format: str = "json"):
    """Export all reviewed actions as a machine-applicable JSON patch or Markdown."""
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id}, {"url": 1})
    cursor = db.action_items.find({"job_id": job_id}).sort("content_type", 1)
    items = await cursor.to_list(length=1000)
    versions_data = await get_content_versions(job_id, limit=1000)
    by_action = {v.get("action_id"): v for v in versions_data.get("versions", [])}

    changes = []
    for item in items:
        v = by_action.get(str(item.get("_id")))
        changes.append({
            "action_id": str(item.get("_id")),
            "issue_key": item.get("issue_key", ""),
            "content_type": item.get("content_type", ""),
            "page_url": item.get("page_url", ""),
            "impact_on_ranking": item.get("impact_on_ranking", ""),
            "status": item.get("status", "pending"),
            "identified_issues": item.get("identified_issues") or [],
            "improvement_suggestions": item.get("improvement_suggestions") or [],
            "evidence": item.get("evidence") or {},
            "version": {
                "field": v.get("field"),
                "before": v.get("before"),
                "after": v.get("after"),
                "diff": v.get("diff") or [],
                "generated_by": v.get("generated_by"),
                "qa": v.get("qa"),
            } if v else None,
        })

    counts = {"approved": 0, "rejected": 0, "pending": 0}
    for c in changes:
        counts[c["status"]] = counts.get(c["status"], 0) + 1

    if format == "md":
        lines = [
            f"# SEO Patch - {(job or {}).get('url', '')}",
            "",
            f"Generated: {datetime.utcnow().isoformat()}",
            f"Summary: {counts['approved']} approved, {counts['rejected']} rejected, {counts['pending']} pending",
            "",
        ]
        for c in changes:
            lines.append(f"## [{c['status']}] {c['content_type']} - {c['page_url'] or '(page-level)'}")
            if c["issue_key"]:
                lines.append(f"- Issue key: `{c['issue_key']}` ({c['impact_on_ranking']} impact)")
            if c["identified_issues"]:
                lines.append(f"- Problems: {'; '.join(c['identified_issues'])}")
            if c["improvement_suggestions"]:
                lines.append(f"- Suggested fixes: {'; '.join(c['improvement_suggestions'])}")
            v = c["version"]
            if v and v.get("after"):
                lines.append(f"- Applied change ({v.get('field')}): {v.get('after')[:300]}")
            lines.append("")
        return Response(content="\n".join(lines), media_type="text/markdown; charset=utf-8")

    return {
        "patch_version": 1,
        "job_id": job_id,
        "site": (job or {}).get("url", ""),
        "generated_at": datetime.utcnow().isoformat(),
        "summary": counts,
        "changes": changes,
    }


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
        await _notify_external(item.get("job_id"), item, req.status, version)
    except Exception as e:
        from backend.logging_setup import get_logger
        get_logger("actions").warning("External notification failed action=%s: %s", action_id, e)

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
