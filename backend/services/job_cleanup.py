"""Permanent job data removal: every DB row, Chroma vectors and files for a job_id."""

JOB_COLLECTIONS = [
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
    "programmatic_seo_audits", "exec_summaries", "serp_cache", "job_keywords",
]


async def hard_delete_job(job_id: str) -> dict:
    """Permanently delete a job and every trace of it (DB rows, vectors, files)."""
    import os
    import shutil

    from backend.db.mongo import get_db

    db = get_db()
    deleted = {}
    for coll in JOB_COLLECTIONS:
        deleted[coll] = (await db[coll].delete_many({"job_id": job_id})).deleted_count
    for coll in JOB_COLLECTIONS:
        deleted[f"{coll}(target)"] = (await db[coll].delete_many({"target_job_id": job_id})).deleted_count
    comp_jobs = await db.analysis_jobs.find({"target_job_id": job_id}).to_list(length=1000)
    comp_ids = [cj["_id"] for cj in comp_jobs]
    for cj in comp_jobs:
        for coll in JOB_COLLECTIONS:
            try:
                await db[coll].delete_many({"job_id": cj["_id"]})
            except Exception:
                pass
    if comp_ids:
        await db.analysis_jobs.delete_many({"_id": {"$in": comp_ids}})
    deleted["competitor_jobs"] = len(comp_ids)
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

    return deleted