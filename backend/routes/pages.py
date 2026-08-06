from fastapi import APIRouter, Query

from backend.db.mongo import get_db

router = APIRouter(prefix="/api/pages", tags=["pages"])

_SORTABLE = {
    "url": "url",
    "word_count": "word_count",
    "status_code": "status_code",
    "click_depth": "click_depth",
    "page_type": "page_type",
}


@router.get("/{job_id}/all")
async def list_pages_all(
    job_id: str,
    search: str = Query(""),
    page_type: str = Query(""),
    sort: str = Query("url"),
    order: str = Query("asc"),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
):
    db = get_db()
    filt: dict = {"job_id": job_id}
    if page_type:
        filt["page_type"] = page_type
    q = search.strip()
    if q:
        filt["$or"] = [
            {"url": {"$regex": q, "$options": "i"}},
            {"title": {"$regex": q, "$options": "i"}},
            {"meta_description": {"$regex": q, "$options": "i"}},
        ]
    sort_key = _SORTABLE.get(sort, "word_count")
    order_val = -1 if str(order).lower() == "desc" else 1
    cursor = db.pages.find(filt, {"html": 0}).sort(sort_key, order_val).skip(offset).limit(limit)
    pages = await cursor.to_list(length=limit)
    for p in pages:
        p["id"] = str(p.pop("_id"))
    total = await db.pages.count_documents(filt)
    types = {}
    async for t in db.pages.aggregate([
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$page_type", "n": {"$sum": 1}}},
    ]):
        types[t["_id"] or "other"] = t["n"]
    return {
        "pages": pages,
        "total": total,
        "types": types,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "order": order,
    }


@router.get("/{job_id}")
async def list_pages(job_id: str, limit: int = Query(100, le=500), offset: int = Query(0)):
    db = get_db()
    cursor = db.pages.find(
        {"job_id": job_id},
        {"html": 0},
    ).skip(offset).limit(limit).sort("url", 1)
    pages = await cursor.to_list(length=limit)
    for p in pages:
        p["id"] = str(p.pop("_id"))
    total = await db.pages.count_documents({"job_id": job_id})
    return {"pages": pages, "total": total, "limit": limit, "offset": offset}
