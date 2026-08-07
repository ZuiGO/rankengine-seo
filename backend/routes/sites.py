from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.db.mongo import get_db

router = APIRouter(prefix="/api/sites", tags=["sites"])


async def log_audit(event: str, job_id: str, details: dict | None = None):
    try:
        from backend.services.audit_service import log_audit as _log
        await _log(event, job_id=job_id, details=details)
    except Exception:
        pass


def _domain(url: str) -> str:
    if "//" in url:
        return url.split("//")[-1].split("/")[0]
    return url


async def _site_metrics(job: dict) -> dict:
    db = get_db()
    job_id = job["_id"]
    pages = await db.pages.count_documents({"job_id": job_id})
    content = await db.content_items.count_documents({"job_id": job_id})
    vectors = (job.get("summary") or {}).get("total_vectors", 0)
    actions = await db.action_items.count_documents({"job_id": job_id})

    breakdown = {}
    cursor = db.content_items.aggregate([
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$content_type", "count": {"$sum": 1}}},
    ])
    async for row in cursor:
        breakdown[row["_id"]] = row["count"]

    insights = {}
    cached = await db.seo_insights_cache.find_one({"job_id": job_id})
    if cached:
        bl = cached.get("data", {}).get("backlinks") or {}
        ov = cached.get("data", {}).get("overview") or {}
        insights = {
            "backlinks": bl.get("backlinks"),
            "referring_domains": bl.get("referring_domains"),
            "domain_rank": bl.get("rank"),
            "organic_traffic": ov.get("estimated_organic_traffic"),
        }

    health_doc = await db.site_health.find_one({"job_id": job_id})
    health = {}
    if health_doc:
        health = {
            "health_grade": health_doc.get("grade"),
            "health_score": health_doc.get("score"),
        }

    return {
        "job_id": job_id,
        "url": job.get("url", ""),
        "domain": _domain(job.get("url", "")),
        "status": job.get("status"),
        "completed_at": job.get("completed_at"),
        "total_pages": pages,
        "total_content_items": content,
        "total_vectors": vectors,
        "total_action_items": actions,
        "content_breakdown": breakdown,
        **insights,
        **health,
    }


@router.get("/{job_id}/health")
async def site_health(job_id: str):
    from backend.services.site_health import get_site_health

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")
    health = await get_site_health(job_id)
    health.pop("_id", None)
    return health


@router.post("/{job_id}/compare-changes")
async def compare_changes(job_id: str):
    from backend.services.compare_service import compare_site_with_changes

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")
    return await compare_site_with_changes(job_id)


@router.get("")
async def list_sites(include_archived: bool = Query(False)):
    db = get_db()
    query = {} if include_archived else {"deleted": {"$ne": True}}
    query["competitor_job"] = {"$ne": True}
    cursor = db.analysis_jobs.find(query).sort("created_at", -1)
    jobs = await cursor.to_list(length=200)
    sites = []
    for job in jobs:
        site = await _site_metrics(job)
        site["archived"] = bool(job.get("deleted"))
        site["deleted_at"] = job.get("deleted_at")
        sites.append(site)
    return {"sites": sites, "total": len(sites)}


@router.delete("/{job_id}")
async def delete_site(job_id: str):
    """Soft-delete (archive) a site: it disappears from the default list but data is kept."""
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")
    await db.analysis_jobs.update_one(
        {"_id": job_id},
        {"$set": {"deleted": True, "deleted_at": datetime.utcnow()}},
    )
    return {"status": "ok", "job_id": job_id, "archived": True}


@router.post("/{job_id}/restore")
async def restore_site(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")
    await db.analysis_jobs.update_one(
        {"_id": job_id},
        {"$unset": {"deleted": "", "deleted_at": ""}},
    )
    return {"status": "ok", "job_id": job_id, "archived": False}


@router.delete("/{job_id}/hard")
async def hard_delete_site(job_id: str):
    """Permanently delete a site and every trace of it (DB rows, vectors, files)."""
    import os
    import shutil

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")

    collections = [
        "pages", "page_links", "content_items", "content_extractions",
        "action_items", "content_versions", "link_health", "link_health_summaries",
        "backlinks", "backlink_meta", "seo_insights_cache", "site_health",
        "duplicate_content", "structured_data", "geo_alignment", "orphan_pages",
        "page_performance", "page_performance_summaries", "user_flows",
        "dummy_sites", "site_comparisons", "keyword_tracking",
        "keyword_tracking_summaries", "audit_logs", "api_usage", "embeddings",
        "competitor_gap_analyses", "sitemap_audits", "ai_visibility_summaries",
        "local_seo_summaries", "hreflang_audits",
        "url_hygiene_audits", "indexation_audits", "image_optimization_audits",
        "programmatic_seo_audits", "exec_summaries", "serp_cache",
    ]
    deleted = {}
    for coll in collections:
        deleted[coll] = (await db[coll].delete_many({"job_id": job_id})).deleted_count
    for coll in collections:
        deleted[f"{coll}(target)"] = (await db[coll].delete_many({"target_job_id": job_id})).deleted_count
    comp_jobs = await db.analysis_jobs.find({"target_job_id": job_id}).to_list(length=1000)
    for cj in comp_jobs:
        for coll in collections:
            try:
                await db[coll].delete_many({"job_id": cj["_id"]})
            except Exception:
                pass
    deleted["competitor_jobs"] = len(comp_jobs)
    deleted["analysis_jobs"] = (await db.analysis_jobs.delete_one({"_id": job_id})).deleted_count
    await db.crawl_schedules.update_many(
        {}, {"$pull": {"history": {"job_id": job_id}}},
    )

    try:
        from backend.db.chroma import delete_collection
        delete_collection(f"job_{job_id}")
    except Exception:
        pass

    for path in (os.path.join("dummy_site", job_id), os.path.join("downloads", job_id)):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    await log_audit("site_deleted", job_id, {"url": job.get("url"), "purged": sum(deleted.values())})
    return {"status": "ok", "job_id": job_id, "deleted": deleted}


class CompareRequest(BaseModel):
    job_ids: list[str]


@router.post("/compare")
async def compare_sites(req: CompareRequest):
    if not req.job_ids:
        raise HTTPException(400, "job_ids required")
    if len(req.job_ids) > 10:
        raise HTTPException(400, "Maximum 10 sites to compare")

    db = get_db()
    sites = []
    for job_id in req.job_ids:
        job = await db.analysis_jobs.find_one({"_id": job_id})
        if job:
            sites.append(await _site_metrics(job))
    if not sites:
        raise HTTPException(404, "No sites found")

    domains = [s["domain"] for s in sites]
    page_counts = [s["total_pages"] for s in sites]
    content_counts = [s["total_content_items"] for s in sites]
    backlinks = [s.get("backlinks") for s in sites]

    best_content = {}
    for s in sites:
        for ctype, count in s["content_breakdown"].items():
            best_content.setdefault(ctype, {"count": 0, "domain": ""})
            if count > best_content[ctype]["count"]:
                best_content[ctype] = {"count": count, "domain": s["domain"]}

    return {
        "sites": sites,
        "comparison": {
            "domains": domains,
            "page_counts": page_counts,
            "content_counts": content_counts,
            "backlinks": backlinks,
            "most_content_by_type": best_content,
            "largest_site": max(sites, key=lambda s: s["total_pages"])["domain"] if sites else None,
            "most_backlinks": max(sites, key=lambda s: s.get("backlinks") or 0)["domain"] if sites else None,
        },
    }
