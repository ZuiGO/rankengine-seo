import asyncio
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.crawler import crawl_site
from backend.services.content_extractor import extract_all_content
from backend.services.vector_service import index_job_vectors
from backend.services.user_flow import detect_user_flows
from backend.services.audit_service import log_audit
from backend.services.queue import run_or_fallback

logger = get_logger("analysis")

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class AnalyzeRequest(BaseModel):
    url: str
    max_pages: int = 50


class AnalyzeResponse(BaseModel):
    job_id: str
    status: str
    url: str


@router.post("")
async def start_analysis(req: AnalyzeRequest):
    url = req.url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url

    job_id = str(uuid.uuid4())
    db = get_db()

    await db.analysis_jobs.insert_one({
        "_id": job_id,
        "url": url,
        "status": "queued",
        "progress": 0,
        "progress_message": "Queued...",
        "created_at": datetime.utcnow(),
        "completed_at": None,
        "error_message": None,
        "summary": None,
    })

    await run_or_fallback("analyze_job", run_analysis_pipeline, job_id, url, req.max_pages)
    await log_audit("analysis_started", job_id, {"url": url, "max_pages": req.max_pages})

    return {"job_id": job_id, "status": "queued", "url": url, "max_pages": req.max_pages}


async def run_analysis_pipeline(job_id: str, url: str, max_pages: int = 50):
    db = get_db()
    logger.info("Analysis started job=%s url=%s max_pages=%s", job_id, url, max_pages)

    try:
        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"status": "running", "progress_message": "Starting crawl..."}}
        )

        summary = await crawl_site(job_id, url, max_pages)
        if not summary:
            raise Exception("Crawl returned no results")

        content_count = await db.content_items.count_documents({"job_id": job_id})

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Identifying user flows..."}}
        )

        try:
            flow_count = await detect_user_flows(job_id)
        except Exception as flow_err:
            logger.error("User flow detection warning job=%s: %s", job_id, flow_err)
            flow_count = 0

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Extracting content data..."}}
        )

        try:
            extraction_summary = await extract_all_content(job_id)
        except Exception as ext_err:
            logger.error("Content extraction warning job=%s: %s", job_id, ext_err)
            extraction_summary = {}

        try:
            from backend.services.seo_analyzer import analyze_pages
            await analyze_pages(job_id)
        except Exception as act_err:
            logger.error("Action analysis warning job=%s: %s", job_id, act_err)

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Fetching external SEO insights..."}}
        )

        try:
            from backend.services.dataforseo import fetch_all_insights
            from backend.routes.seo_insights import CACHE_VERSION
            domain = url.split("//")[-1].split("/")[0]
            insights = await fetch_all_insights(domain, job_id)
            await db.seo_insights_cache.update_one(
                {"job_id": job_id},
                {"$set": {"job_id": job_id, "data": insights, "v": CACHE_VERSION, "fetched_at": datetime.utcnow()}},
                upsert=True,
            )
        except Exception as insight_err:
            logger.error("SEO insights warning job=%s: %s", job_id, insight_err)

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Listing backlink sources..."}}
        )

        try:
            from backend.services.backlinks import fetch_backlinks
            backlink_result = await fetch_backlinks(job_id, domain)
            backlink_count = backlink_result["total"]
        except Exception as bl_err:
            logger.error("Backlink listing warning job=%s: %s", job_id, bl_err)
            backlink_count = 0

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Indexing content vectors..."}}
        )

        try:
            vector_count = await index_job_vectors(job_id)
        except Exception as vec_err:
            logger.error("Vector indexing warning job=%s: %s", job_id, vec_err)
            vector_count = 0

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Checking link health..."}}
        )

        try:
            from backend.services.link_checker import check_links
            link_health = await check_links(job_id)
        except Exception as lh_err:
            logger.error("Link health check warning job=%s: %s", job_id, lh_err)
            link_health = {}

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Measuring Core Web Vitals..."}}
        )

        try:
            from backend.services.performance_service import fetch_performance
            perf = await fetch_performance(job_id)
            cwv_pages = perf.get("pages_checked", perf.get("checked", 0))
        except Exception as p_err:
            logger.error("PageSpeed warning job=%s: %s", job_id, p_err)
            cwv_pages = 0

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Detecting duplicate content and validating structured data..."}}
        )

        try:
            from backend.services.duplicate_content import detect_duplicate_content
            dup = await detect_duplicate_content(job_id)
            duplicate_pages = dup.get("duplicate_pages", 0)
            canonical_issues = dup.get("canonical_conflicting", 0) + dup.get("canonical_cross_domain", 0)
        except Exception as dup_err:
            logger.error("Duplicate detection warning job=%s: %s", job_id, dup_err)
            duplicate_pages = 0
            canonical_issues = 0

        try:
            from backend.services.structured_data import audit_structured_data
            sd = await audit_structured_data(job_id)
            structured_valid = sd.get("valid", 0)
        except Exception as sd_err:
            logger.error("Structured data audit warning job=%s: %s", job_id, sd_err)
            structured_valid = 0

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Checking industry alignment and orphan pages..."}}
        )

        try:
            from backend.services.geo_alignment import audit_geo_alignment
            geo = await audit_geo_alignment(job_id)
            geo_off_topic = geo.get("off_topic_pages", 0)
        except Exception as geo_err:
            logger.error("GEO alignment warning job=%s: %s", job_id, geo_err)
            geo_off_topic = 0

        try:
            from backend.services.orphan_detection import detect_orphan_pages
            orphans = await detect_orphan_pages(job_id)
            orphan_count = orphans.get("orphan_pages", 0)
        except Exception as o_err:
            logger.error("Orphan detection warning job=%s: %s", job_id, o_err)
            orphan_count = 0

        try:
            from backend.services.site_health import compute_site_health
            health = await compute_site_health(job_id)
            health_grade = health.get("grade")
        except Exception as h_err:
            logger.error("Site health warning job=%s: %s", job_id, h_err)
            health_grade = None

        try:
            from backend.services.geo_readiness import check_geo_readiness
            geo_readiness = await check_geo_readiness(url)
        except Exception as geo_err:
            logger.error("GEO readiness warning job=%s: %s", job_id, geo_err)
            geo_readiness = {"status": "unknown", "score": None, "robots_txt_found": False, "error": str(geo_err)[:200]}

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {
                "status": "completed",
                "progress": 100,
                "progress_message": "Analysis complete",
                "completed_at": datetime.utcnow(),
                "summary": {
                    "total_pages": summary["total_pages"],
                    "total_links": summary["total_links"],
                    "total_internal_links": summary["total_internal_links"],
                    "total_external_links": summary["total_external_links"],
                    "total_content_items": content_count,
                    "total_vectors": vector_count,
                    "total_user_flows": flow_count,
                    "total_backlinks": backlink_count,
                    "links_checked": link_health.get("checked", 0),
                    "broken_links": link_health.get("broken_link_count", link_health.get("broken", 0)),
                    "broken_link_count": link_health.get("broken_link_count", link_health.get("broken", 0)),
                    "total_links_scanned": link_health.get("total_links_scanned", link_health.get("checked", 0)),
                    "health_grade": health_grade,
                    "cwv_pages": cwv_pages,
                    "duplicate_pages": duplicate_pages,
                    "canonical_issues": canonical_issues,
                    "structured_data_valid": structured_valid,
                    "geo_off_topic_pages": geo_off_topic,
                    "orphan_pages": orphan_count,
                    "geo_readiness": {
                        "status": geo_readiness.get("status"),
                        "score": geo_readiness.get("score"),
                        "robots_txt_found": geo_readiness.get("robots_txt_found", False),
                        "blocked_ai_crawlers": geo_readiness.get("blocked_ai_crawlers", []),
                        "allowed_ai_crawlers": geo_readiness.get("allowed_ai_crawlers", []),
                        "ai_agents_scanned": geo_readiness.get("ai_agents_scanned", []),
                    },
                },
            }}
        )
        await log_audit("analysis_completed", job_id, {"pages": summary["total_pages"], "content_items": content_count})
        logger.info("Analysis completed job=%s pages=%s", job_id, summary["total_pages"])

        try:
            from backend.services.notifications import send_slack
            domain = url.split("//")[-1].split("/")[0]
            prev = await db.analysis_jobs.find_one(
                {"url": {"$regex": domain, "$options": "i"}, "status": "completed", "_id": {"$ne": job_id}},
                {"summary": 1},
                sort=[("completed_at", -1)],
            )
            prev_grade = ((prev or {}).get("summary") or {}).get("health_grade")
            drop = None
            grade_rank = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
            if prev_grade and health_grade and grade_rank.get(health_grade, 0) < grade_rank.get(prev_grade, 0):
                drop = f"{prev_grade} → {health_grade}"
            prev_summary = (prev or {}).get("summary") or {}
            prev_broken = prev_summary.get("broken_link_count")
            if prev_broken is None:
                prev_broken = prev_summary.get("broken_links")
            new_broken = summary.get("broken_link_count")
            if new_broken is None:
                new_broken = summary.get("broken_links")
            try:
                from backend.config import settings
                broken_threshold = settings.broken_link_alert_threshold
            except Exception:
                broken_threshold = 5
            broken_surge = None
            if (new_broken is not None and prev_broken is not None
                    and new_broken > prev_broken and new_broken >= broken_threshold):
                broken_surge = f"{prev_broken} → {new_broken}"
            fields = {
                "Site": url,
                "Pages": summary["total_pages"],
                "Content items": content_count,
                "Health grade": health_grade,
                "Broken links": link_health.get("broken", 0),
                "Action items": summary.get("total_action_items", 0),
            }
            if drop:
                fields["Health drop"] = drop
                await send_slack("Health grade dropped", fields, color="danger")
            elif broken_surge:
                fields["Broken links increase"] = broken_surge
                await send_slack("Broken links increased", fields, color="danger")
            else:
                await send_slack("Analysis complete", fields, color="good")
        except Exception as n_err:
            logger.warning("Slack notification failed job=%s: %s", job_id, n_err)

    except Exception as e:
        logger.error("Analysis failed job=%s: %s", job_id, e)
        await log_audit("analysis_failed", job_id, {"error": str(e)})
        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {
                "status": "failed",
                "error_message": str(e),
                "progress_message": f"Failed: {str(e)}",
                "completed_at": datetime.utcnow(),
            }}
        )
        try:
            from backend.services.notifications import send_slack
            await send_slack("Analysis failed", {"Site": url, "Error": str(e)[:300]}, color="danger")
        except Exception as n_err:
            logger.warning("Slack failure notification failed job=%s: %s", job_id, n_err)


@router.get("/{job_id}")
async def get_job_status(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["id"] = job.pop("_id")
    return job


@router.get("/{job_id}/summary")
async def get_job_summary(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    page_count = await db.pages.count_documents({"job_id": job_id})
    content_count = await db.content_items.count_documents({"job_id": job_id})
    action_count = await db.action_items.count_documents({"job_id": job_id})

    content_breakdown_pipeline = [
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$content_type", "count": {"$sum": 1}}}
    ]
    content_breakdown_cursor = db.content_items.aggregate(content_breakdown_pipeline)
    content_breakdown = {}
    async for row in content_breakdown_cursor:
        content_breakdown[row["_id"]] = row["count"]

    page_type_pipeline = [
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$page_type", "count": {"$sum": 1}}}
    ]
    page_type_cursor = db.pages.aggregate(page_type_pipeline)
    page_type_breakdown = {}
    async for row in page_type_cursor:
        page_type_breakdown[row["_id"]] = row["count"]

    user_flow_count = await db.user_flows.count_documents({"job_id": job_id})

    return {
        "job_id": job_id,
        "url": job.get("url", ""),
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "progress_message": job.get("progress_message", ""),
        "total_pages": page_count,
        "total_content_items": content_count,
        "total_action_items": action_count,
        "content_breakdown": content_breakdown,
        "page_type_breakdown": page_type_breakdown,
        "total_user_flows": user_flow_count,
        "summary": job.get("summary"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
    }
