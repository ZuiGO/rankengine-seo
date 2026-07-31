from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.services.dataforseo import fetch_all_insights
from backend.services.serp_api import search_keyword, bulk_keyword_search, extract_keywords_from_content
from backend.services.backlinks import get_backlinks, fetch_backlinks
from backend.db.mongo import get_db

router = APIRouter(prefix="/api/seo-insights", tags=["seo-insights"])

CACHE_TTL_MINUTES = 60


class KeywordSearchRequest(BaseModel):
    job_id: str
    keyword: str


class BulkKeywordRequest(BaseModel):
    job_id: str
    keywords: list[str]


def _domain_from_url(url: str) -> str:
    if "//" in url:
        return url.split("//")[-1].split("/")[0]
    return url


@router.get("/{job_id}")
async def get_insights(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    domain = _domain_from_url(job.get("url", ""))

    cached = await db.seo_insights_cache.find_one({"job_id": job_id})
    if cached and cached.get("fetched_at", datetime.min) > datetime.utcnow() - timedelta(minutes=CACHE_TTL_MINUTES):
        return {"job_id": job_id, "domain": domain, "cached": True, **cached["data"]}

    insights = await fetch_all_insights(domain)
    await db.seo_insights_cache.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, "data": insights, "fetched_at": datetime.utcnow()}},
        upsert=True,
    )
    return {"job_id": job_id, "domain": domain, "cached": False, **insights}


@router.post("/refresh/{job_id}")
async def refresh_insights(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    domain = _domain_from_url(job.get("url", ""))
    insights = await fetch_all_insights(domain)
    await db.seo_insights_cache.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, "data": insights, "fetched_at": datetime.utcnow()}},
        upsert=True,
    )
    return {"job_id": job_id, "domain": domain, "cached": False, **insights}


@router.post("/keyword-search")
async def keyword_search(req: KeywordSearchRequest):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": req.job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    domain = _domain_from_url(job.get("url", ""))
    result = await search_keyword(req.keyword, domain)
    return result


@router.post("/bulk-keyword-search")
async def bulk_search(req: BulkKeywordRequest):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": req.job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    domain = _domain_from_url(job.get("url", ""))
    results = await bulk_keyword_search(req.keywords, domain)
    return {"results": results}


@router.get("/{job_id}/suggested-keywords")
async def suggested_keywords(job_id: str):
    keywords = await extract_keywords_from_content(job_id)
    return {"keywords": keywords}


@router.get("/{job_id}/backlinks")
async def list_backlinks(job_id: str, limit: int = Query(100, le=500), offset: int = Query(0)):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return await get_backlinks(job_id, limit, offset)


@router.post("/{job_id}/backlinks/refresh")
async def refresh_backlinks(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    domain = _domain_from_url(job.get("url", ""))
    result = await fetch_backlinks(job_id, domain)
    return {"job_id": job_id, "domain": domain, **result}
