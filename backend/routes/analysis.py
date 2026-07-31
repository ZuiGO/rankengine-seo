import asyncio
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.crawler import crawl_site
from backend.services.graph_service import populate_graph
from backend.services.content_extractor import extract_all_content
from backend.services.vector_service import index_job_content
from backend.services.audit_service import log_audit

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

    asyncio.create_task(run_analysis_pipeline(job_id, url, req.max_pages))
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
            {"$set": {"progress_message": "Building graph database..."}}
        )

        try:
            await populate_graph(job_id)
        except Exception as graph_err:
            logger.error("Graph population warning job=%s: %s", job_id, graph_err)

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Extracting content data..."}}
        )

        try:
            extraction_summary = await extract_all_content(job_id)
        except Exception as ext_err:
            logger.error("Content extraction warning job=%s: %s", job_id, ext_err)
            extraction_summary = {}

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Indexing content vectors..."}}
        )

        try:
            vector_count = await index_job_content(job_id)
        except Exception as vec_err:
            logger.error("Vector indexing warning job=%s: %s", job_id, vec_err)
            vector_count = 0

        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"progress_message": "Fetching external SEO insights..."}}
        )

        try:
            from backend.services.dataforseo import fetch_all_insights
            domain = url.split("//")[-1].split("/")[0]
            insights = await fetch_all_insights(domain)
            await db.seo_insights_cache.update_one(
                {"job_id": job_id},
                {"$set": {"job_id": job_id, "data": insights, "fetched_at": datetime.utcnow()}},
                upsert=True,
            )
        except Exception as insight_err:
            logger.error("SEO insights warning job=%s: %s", job_id, insight_err)

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
                },
            }}
        )
        await log_audit("analysis_completed", job_id, {"pages": summary["total_pages"], "content_items": content_count})
        logger.info("Analysis completed job=%s pages=%s", job_id, summary["total_pages"])

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
        "summary": job.get("summary"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
    }
