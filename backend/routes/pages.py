from fastapi import APIRouter, Query

from backend.db.mongo import get_db

router = APIRouter(prefix="/api/pages", tags=["pages"])


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
