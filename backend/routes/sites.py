from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db.mongo import get_db

router = APIRouter(prefix="/api/sites", tags=["sites"])


def _domain(url: str) -> str:
    if "//" in url:
        return url.split("//")[-1].split("/")[0]
    return url


async def _site_metrics(job: dict) -> dict:
    db = get_db()
    job_id = job["_id"]
    pages = await db.pages.count_documents({"job_id": job_id})
    content = await db.content_items.count_documents({"job_id": job_id})
    vectors = await db.embeddings.count_documents({"job_id": job_id})
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
    }


@router.get("")
async def list_sites():
    db = get_db()
    cursor = db.analysis_jobs.find({}).sort("created_at", -1)
    jobs = await cursor.to_list(length=200)
    sites = []
    for job in jobs:
        sites.append(await _site_metrics(job))
    return {"sites": sites, "total": len(sites)}


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
