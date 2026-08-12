import asyncio
import time
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
    email: str = ""


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
        "email": (req.email or "").strip(),
    })

    await run_or_fallback("analyze_job", run_analysis_pipeline, job_id, url, req.max_pages)
    await log_audit("analysis_started", job_id, {"url": url, "max_pages": req.max_pages})

    return {"job_id": job_id, "status": "queued", "url": url, "max_pages": req.max_pages}


@router.post("/{job_id}/cancel")
async def cancel_analysis(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"Analysis is not running (status: {job.get('status')})")
    await db.analysis_jobs.update_one(
        {"_id": job_id},
        {"$set": {"cancelled": True, "cancelled_at": datetime.utcnow(), "progress_message": "Cancelling..."}},
    )
    await log_audit("analysis_cancelled", job_id, {"url": job.get("url")})
    return {"status": "cancelled", "job_id": job_id}


async def run_competitor_pipeline(target_job_id: str, competitors: list[str]):
    from backend.services.competitor_audit import audit_competitors

    db = get_db()
    logger.info("Competitor audit started target=%s competitors=%s", target_job_id, competitors)

    async def _mark_errors(message: str):
        await db.competitor_gap_analyses.update_many(
            {"target_job_id": target_job_id, "status": {"$in": ["queued", "running"]}},
            {"$set": {"status": "error", "errors": [message], "updated_at": datetime.utcnow()}},
        )

    try:
        await audit_competitors(target_job_id, competitors)
    except asyncio.CancelledError:
        logger.warning("Competitor audit cancelled target=%s", target_job_id)
        await db.competitor_gap_analyses.update_many(
            {"target_job_id": target_job_id, "status": "running"},
            {"$set": {"status": "queued", "updated_at": datetime.utcnow()}},
        )
        raise
    except asyncio.TimeoutError:
        logger.error("Competitor audit timed out target=%s", target_job_id)
        await _mark_errors("Timed out (overall job limit)")
    except Exception as e:
        logger.error("Competitor audit failed target=%s: %s", target_job_id, e)
        await _mark_errors(str(e))


async def run_analysis_pipeline(job_id: str, url: str, max_pages: int = 50):
    db = get_db()
    logger.info("Analysis started job=%s url=%s max_pages=%s", job_id, url, max_pages)

    try:
        from backend.services.job_cancel import check_cancelled, JobCancelled
        await check_cancelled(job_id)
        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"status": "running", "progress_message": "Starting crawl..."}}
        )

        summary = await crawl_site(job_id, url, max_pages, seed_sitemap=True, unlimited=True)
        if not summary:
            raise Exception("Crawl returned no results")
        if summary.get("total_pages", 0) == 0:
            raise Exception(
                "Crawled 0 pages. The site did not respond to headless browser or HTTP requests; "
                "no URLs were seeded from its sitemap. Check that the site is reachable and "
                "does not block the ZuiGO Engine user-agent."
            )

        content_count = await db.content_items.count_documents({"job_id": job_id})
        domain = url.split("//")[-1].split("/")[0]

        async def _progress(message: str):
            from backend.services.job_cancel import check_cancelled
            await check_cancelled(job_id)
            await db.analysis_jobs.update_one(
                {"_id": job_id},
                {"$set": {"progress_message": message}}
            )

        async def _stage(name: str, stage, fallback=None):
            started = time.monotonic()
            try:
                value = await stage()
                logger.info("Stage %s ok job=%s t=%.1fs", name, job_id, time.monotonic() - started)
                return name, value
            except JobCancelled:
                raise
            except Exception as err:
                logger.error("Stage %s warning job=%s: %s", name, job_id, err)
                return name, fallback

        async def _user_flows():
            await _progress("Identifying user flows...")
            return await detect_user_flows(job_id)

        async def _extraction():
            await _progress("Extracting content data...")
            return await extract_all_content(job_id)

        async def _insights():
            await _progress("Fetching external SEO insights...")
            from backend.services.external_insights import fetch_all_insights
            from backend.routes.seo_insights import CACHE_VERSION
            insights = await fetch_all_insights(domain, job_id)
            await db.seo_insights_cache.update_one(
                {"job_id": job_id},
                {"$set": {"job_id": job_id, "data": insights, "v": CACHE_VERSION, "fetched_at": datetime.utcnow()}},
                upsert=True,
            )

        async def _backlinks():
            await _progress("Listing backlink sources...")
            from backend.services.backlinks import fetch_backlinks
            return await fetch_backlinks(job_id, domain)

        async def _vectors():
            await _progress("Indexing content vectors...")
            return await index_job_vectors(job_id)

        async def _link_health():
            await _progress("Checking link health...")
            from backend.services.link_checker import check_links
            return await check_links(job_id)

        async def _performance():
            await _progress("Measuring Core Web Vitals...")
            from backend.services.performance_service import fetch_performance
            return await fetch_performance(job_id)

        async def _duplicate():
            await _progress("Detecting duplicate content and validating structured data...")
            from backend.services.duplicate_content import detect_duplicate_content
            return await detect_duplicate_content(job_id)

        async def _structured():
            from backend.services.structured_data import audit_structured_data
            return await audit_structured_data(job_id)

        async def _geo_readiness():
            from backend.services.geo_readiness import check_geo_readiness
            return await check_geo_readiness(url)

        async def _sitemap():
            await _progress("Auditing sitemap...")
            from backend.services.sitemap import audit_sitemap
            return await audit_sitemap(job_id, url)

        async def _ai_visibility():
            await _progress("Checking AI-search visibility...")
            from backend.services.ai_visibility import check_ai_visibility
            return await check_ai_visibility(job_id, url)

        async def _local_seo():
            await _progress("Checking local-SEO readiness...")
            from backend.services.local_seo import check_local_seo
            return await check_local_seo(job_id)

        async def _orphans():
            await _progress("Checking industry alignment and orphan pages...")
            from backend.services.orphan_detection import detect_orphan_pages
            return await detect_orphan_pages(job_id)

        async def _hreflang():
            await _progress("Auditing international SEO / hreflang...")
            from backend.services.international_seo import check_international_seo
            return await check_international_seo(job_id, url)

        async def _url_hygiene():
            await _progress("Checking URL hygiene and crawl budget...")
            from backend.services.url_hygiene import audit_url_hygiene
            return await audit_url_hygiene(job_id)

        async def _indexation():
            await _progress("Checking indexation status...")
            from backend.services.indexation import check_indexation
            return await check_indexation(job_id, url)

        async def _image_opt():
            await _progress("Auditing image optimization...")
            from backend.services.image_optimization import audit_image_optimization
            return await audit_image_optimization(job_id)

        w1 = dict(await asyncio.gather(*[
            _stage("user_flows", _user_flows, fallback=0),
            _stage("extraction", _extraction, fallback={}),
            _stage("insights", _insights, fallback=None),
            _stage("backlinks", _backlinks, fallback={"total": 0}),
            _stage("link_health", _link_health, fallback={}),
            _stage("performance", _performance, fallback={}),
            _stage("duplicate", _duplicate, fallback={}),
            _stage("structured", _structured, fallback={}),
            _stage("geo_readiness", _geo_readiness, fallback={"status": "unknown", "score": None, "robots_txt_found": False, "error": "geo readiness stage failed"}),
            _stage("sitemap", _sitemap, fallback={}),
            _stage("ai_visibility", _ai_visibility, fallback={}),
            _stage("local_seo", _local_seo, fallback={}),
            _stage("orphans", _orphans, fallback={}),
            _stage("hreflang", _hreflang, fallback={}),
            _stage("url_hygiene", _url_hygiene, fallback={}),
            _stage("indexation", _indexation, fallback={}),
            _stage("image_opt", _image_opt, fallback={}),
        ]))

        flow_count = w1["user_flows"]
        extraction_summary = w1["extraction"]
        backlink_count = w1["backlinks"]["total"]
        link_health = w1["link_health"]
        perf = w1["performance"]
        cwv_pages = perf.get("pages_checked", perf.get("checked", 0))
        dup = w1["duplicate"]
        duplicate_pages = dup.get("duplicate_pages", 0)
        canonical_issues = dup.get("canonical_conflicting", 0) + dup.get("canonical_cross_domain", 0)
        sd = w1["structured"]
        structured_valid = sd.get("valid", 0)
        geo_readiness = w1["geo_readiness"]
        orphan_count = w1["orphans"].get("orphan_pages", 0)
        sitemap_audit = w1["sitemap"]
        ai_visibility = w1["ai_visibility"]
        local_seo = w1["local_seo"]

        async def _action_analysis():
            from backend.services.seo_analyzer import analyze_pages
            await analyze_pages(job_id)

        async def _geo_alignment():
            from backend.services.geo_alignment import audit_geo_alignment
            return await audit_geo_alignment(job_id)

        async def _programmatic_seo():
            await _progress("Detecting programmatic page templates...")
            from backend.services.programmatic_seo import audit_programmatic_seo
            return await audit_programmatic_seo(job_id)

        async def _smart_keywords():
            await _progress("Extracting smart keywords...")
            from backend.services.keyword_engine import get_smart_keywords
            kws = await get_smart_keywords(job_id, max_total=40, use_llm=True, rebuild=True)
            return {"count": len(kws)}

        w2 = dict(await asyncio.gather(*[
            _stage("action_analysis", _action_analysis, fallback=None),
            _stage("geo_alignment", _geo_alignment, fallback={}),
            _stage("programmatic_seo", _programmatic_seo, fallback={}),
            _stage("keywords", _smart_keywords, fallback={"count": 0}),
            _stage("vectors", _vectors, fallback=0),
        ]))
        vector_count = w2["vectors"]
        keyword_count = w2["keywords"].get("count", 0)
        geo_off_topic = w2["geo_alignment"].get("off_topic_pages", 0)
        programmatic = w2["programmatic_seo"]

        async def _health():
            await _progress("Computing site health...")
            from backend.services.site_health import compute_site_health
            return await compute_site_health(job_id)

        health = (await _stage("site_health", _health, fallback={}))[1]
        health_grade = health.get("grade")

        try:
            from backend.services.exec_summary import compute_exec_summary
            await compute_exec_summary(job_id)
        except Exception as exec_err:
            logger.warning("Exec summary failed job=%s: %s", job_id, exec_err)

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
                    "total_link_occurrences": summary.get("total_link_occurrences", summary.get("total_links", 0)),
                    "total_internal_occurrences": summary.get("total_internal_occurrences", summary.get("total_internal_links", 0)),
                    "total_external_occurrences": summary.get("total_external_occurrences", summary.get("total_external_links", 0)),
                    "total_content_items": content_count,
                    "total_vectors": vector_count,
                    "total_smart_keywords": keyword_count,
                    "total_user_flows": flow_count,
                    "total_backlinks": backlink_count,
                    "failed_urls_count": summary.get("failed_urls_count", 0),
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
                    "ai_visibility": {
                        "score": ai_visibility.get("score"),
                        "blocked_ai_agents": ai_visibility.get("blocked_ai_agents", []),
                        "llms_txt_present": ai_visibility.get("llms_txt_present", False),
                        "sitemap_valid": ai_visibility.get("sitemap_valid", False),
                    },
                    "local_seo": {
                        "score": local_seo.get("score"),
                        "local_business_schema": local_seo.get("local_business_schema", False),
                        "nap_schema_present": local_seo.get("nap_schema_present", False),
                        "contact_page_present": local_seo.get("contact_page_present", False),
                    },
                    "programmatic_seo": {
                        "score": programmatic.get("score"),
                        "template_pages": programmatic.get("template_pages", 0),
                        "clusters": programmatic.get("clusters_count", 0),
                        "thin_template_pages": programmatic.get("thin_template_pages", 0),
                    },
                    "sitemap": {
                        "found": sitemap_audit.get("sitemap_found", False),
                        "valid": sitemap_audit.get("sitemap_valid", False),
                        "count": sitemap_audit.get("sitemap_count", 0),
                        "url_count": sitemap_audit.get("url_count", 0),
                        "uncrawled_urls_count": sitemap_audit.get("uncrawled_urls_count", 0),
                    },
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

        try:
            from backend.services.notifications import email_report
            job_doc = await db.analysis_jobs.find_one({"_id": job_id}, {"email": 1})
            report_email = (job_doc or {}).get("email") or ""
            if report_email:
                await email_report(job_id, report_email)
        except Exception as m_err:
            logger.warning("Report email failed job=%s: %s", job_id, m_err)

    except JobCancelled:
        logger.info("Analysis cancelled job=%s", job_id)
        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {"status": "cancelled", "progress_message": "Cancelled by user", "completed_at": datetime.utcnow()}},
        )
        try:
            from backend.services.job_cleanup import hard_delete_job
            await hard_delete_job(job_id)
            logger.info("Cancelled job data purged job=%s", job_id)
        except Exception as c_err:
            logger.warning("Cancelled job cleanup failed job=%s: %s", job_id, c_err)
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
            from backend.services.notifications import send_slack, send_email
            await send_slack("Analysis failed", {"Site": url, "Error": str(e)[:300]}, color="danger")
            job_doc = await db.analysis_jobs.find_one({"_id": job_id}, {"email": 1})
            report_email = (job_doc or {}).get("email") or ""
            if report_email:
                await send_email(
                    report_email,
                    "[ZuiGO Engine] Analysis failed",
                    f"Your ZuiGO Engine analysis of {url} failed.\n\nError: {e}\n\nRetry from the app when ready.",
                )
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
