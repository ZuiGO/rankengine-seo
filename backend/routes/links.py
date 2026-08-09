from fastapi import APIRouter, Query

from backend.db.mongo import get_db
from backend.services.backlinks import get_backlinks
from backend.services.link_checker import check_links, get_link_health
from backend.services.url_normalizer import normalize_url

router = APIRouter(prefix="/api/links", tags=["links"])


@router.get("/{job_id}")
async def get_link_summary(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}

    summary = job.get("summary") or {}
    occurrences = summary.get("total_link_occurrences") or summary.get("total_links", 0)
    return {
        "total_links": summary.get("total_links", 0),
        "total_internal": summary.get("total_internal_links", 0),
        "total_external": summary.get("total_external_links", 0),
        "total_link_occurrences": occurrences,
    }


@router.get("/{job_id}/all")
async def all_links(job_id: str, status: str | None = None, external: bool | None = None, limit: int = Query(200, le=1000), offset: int = Query(0)):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id}, {"_id": 1})
    if not job:
        return {"error": "Job not found"}
    q: dict = {"job_id": job_id}
    if status:
        q["status"] = status
    if external is not None:
        q["external"] = external
    flagged = await db.link_health.count_documents({"job_id": job_id, "external": {"$exists": True}})
    fallback = flagged == 0
    if fallback and external is not None:
        q.pop("external", None)
    total = await db.link_health.count_documents(q)
    unchecked_count = await db.link_health.count_documents({"job_id": job_id, "status": "unchecked"})
    cursor = db.link_health.find(q).sort("url", 1).skip(offset).limit(limit)
    rows = []
    async for r in cursor:
        r["id"] = str(r.pop("_id"))
        rows.append(r)

    if fallback:
        external_urls = set()
        page_cursor = db.page_links.find({"job_id": job_id}, {"external_link_urls": 1})
        async for doc in page_cursor:
            for target in doc.get("external_link_urls", []) or []:
                norm = normalize_url(target)
                if norm:
                    external_urls.add(norm)
        for r in rows:
            r["external"] = r.get("url") in external_urls
        if external is not None:
            rows = [r for r in rows if r["external"] is external]
            total = len(rows)
    return {"total": total, "links": rows, "offset": offset, "limit": limit, "unchecked_count": unchecked_count}


@router.get("/{job_id}/backlinks")
async def list_backlinks(job_id: str):
    return await get_backlinks(job_id, limit=1000)


@router.get("/{job_id}/health")
async def link_health(job_id: str, limit: int = Query(100, le=500), offset: int = Query(0)):
    return await get_link_health(job_id, limit, offset)


@router.post("/{job_id}/check")
async def run_link_check(job_id: str):
    summary = await check_links(job_id)
    return summary
