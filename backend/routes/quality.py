from fastapi import APIRouter, HTTPException

from backend.db.mongo import get_db
from backend.services.duplicate_content import get_duplicate_content
from backend.services.geo_alignment import get_geo_alignment
from backend.services.orphan_detection import get_orphan_pages
from backend.services.performance_service import get_performance_summary
from backend.services.structured_data import get_structured_data
from backend.services.vector_service import get_embedding_report

router = APIRouter(prefix="/api/quality", tags=["quality"])


async def _ensure_job(job_id: str):
    db = get_db()
    if not await db.analysis_jobs.find_one({"_id": job_id}):
        raise HTTPException(404, "Job not found")


@router.get("/{job_id}/duplicates")
async def duplicates(job_id: str):
    await _ensure_job(job_id)
    doc = await get_duplicate_content(job_id)
    if not doc:
        raise HTTPException(404, "Duplicate analysis not run for this job")
    return doc


@router.get("/{job_id}/structured-data")
async def structured_data(job_id: str):
    await _ensure_job(job_id)
    doc = await get_structured_data(job_id)
    if not doc:
        raise HTTPException(404, "Structured data audit not run for this job")
    return doc


@router.get("/{job_id}/performance")
async def performance(job_id: str):
    await _ensure_job(job_id)
    doc = await get_performance_summary(job_id)
    if not doc:
        raise HTTPException(404, "Performance audit not run for this job")
    return doc


@router.get("/{job_id}/embeddings")
async def embeddings(job_id: str):
    await _ensure_job(job_id)
    return await get_embedding_report(job_id)


@router.get("/{job_id}/geo-alignment")
async def geo_alignment(job_id: str):
    await _ensure_job(job_id)
    doc = await get_geo_alignment(job_id)
    if not doc:
        raise HTTPException(404, "GEO alignment check not run for this job")
    return doc


@router.get("/{job_id}/orphans")
async def orphans(job_id: str):
    await _ensure_job(job_id)
    doc = await get_orphan_pages(job_id)
    if not doc:
        raise HTTPException(404, "Orphan detection not run for this job")
    return doc


@router.get("/{job_id}/sitemap")
async def sitemap(job_id: str):
    await _ensure_job(job_id)
    db = get_db()
    doc = await db.sitemap_audits.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(404, "Sitemap audit not run for this job")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/{job_id}/ai-visibility")
async def ai_visibility(job_id: str):
    await _ensure_job(job_id)
    db = get_db()
    doc = await db.ai_visibility_summaries.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(404, "AI visibility check not run for this job")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/{job_id}/local-seo")
async def local_seo(job_id: str):
    await _ensure_job(job_id)
    db = get_db()
    doc = await db.local_seo_summaries.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(404, "Local SEO check not run for this job")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/{job_id}/hreflang")
async def hreflang(job_id: str):
    await _ensure_job(job_id)
    db = get_db()
    doc = await db.hreflang_audits.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(404, "International-SEO check not run for this job")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/{job_id}/url-hygiene")
async def url_hygiene(job_id: str):
    await _ensure_job(job_id)
    db = get_db()
    doc = await db.url_hygiene_audits.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(404, "URL-hygiene check not run for this job")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/{job_id}/indexation")
async def indexation(job_id: str):
    await _ensure_job(job_id)
    db = get_db()
    doc = await db.indexation_audits.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(404, "Indexation check not run for this job")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/{job_id}/image-optimization")
async def image_optimization(job_id: str):
    await _ensure_job(job_id)
    db = get_db()
    doc = await db.image_optimization_audits.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(404, "Image-optimization check not run for this job")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/{job_id}/programmatic-seo")
async def programmatic_seo(job_id: str):
    await _ensure_job(job_id)
    db = get_db()
    doc = await db.programmatic_seo_audits.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(404, "Programmatic-SEO check not run for this job")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/{job_id}/decay")
async def content_decay(job_id: str, months: int = 6):
    await _ensure_job(job_id)
    from datetime import datetime, timedelta

    db = get_db()
    cutoff = datetime.utcnow() - timedelta(days=30 * max(1, min(months, 24)))
    pages = await db.pages.find(
        {"job_id": job_id, "last_modified": {"$ne": None}},
        {"url": 1, "title": 1, "last_modified": 1},
    ).to_list(length=None)
    stale = []
    for p in pages:
        lm = p.get("last_modified")
        if lm and lm < cutoff:
            stale.append({
                "page_url": p["url"],
                "title": p.get("title", ""),
                "last_modified": lm.isoformat(),
                "stale_days": (datetime.utcnow() - lm).days,
            })
    stale.sort(key=lambda s: s["stale_days"], reverse=True)
    return {
        "job_id": job_id,
        "pages_with_last_modified": len(pages),
        "stale_pages": len(stale),
        "stale_after_days": 30 * max(1, min(months, 24)),
        "pages": stale,
    }
