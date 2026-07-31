from bson.objectid import ObjectId
from fastapi import APIRouter, Query

from backend.db.mongo import get_db

router = APIRouter(prefix="/api/content", tags=["content"])


@router.get("/{job_id}")
async def list_content(
    job_id: str,
    content_type: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    db = get_db()
    query = {"job_id": job_id}
    if content_type:
        query["content_type"] = content_type

    cursor = db.content_items.find(query).skip(offset).limit(limit).sort("page_url", 1)
    items = await cursor.to_list(length=limit)
    for item in items:
        item["id"] = str(item.pop("_id"))
    total = await db.content_items.count_documents(query)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{job_id}/detail/{content_id}")
async def get_content_detail(job_id: str, content_id: str):
    db = get_db()
    item = await db.content_items.find_one({"_id": ObjectId(content_id), "job_id": job_id})
    if not item:
        return {"error": "Content not found"}
    item["id"] = str(item.pop("_id"))

    # Find extraction data
    extraction = await db.content_extractions.find_one({
        "content_item_id": content_id,
        "job_id": job_id,
    })

    # Count action items for this content
    action_count = await db.action_items.count_documents({
        "job_id": job_id,
        "content_item_id": content_id,
    })

    return {
        "content": item,
        "extraction": extraction,
        "action_count": action_count,
    }


@router.get("/{job_id}/extraction-stats")
async def extraction_stats(job_id: str):
    db = get_db()
    cursor = db.content_extractions.find({"job_id": job_id})
    extractions = await cursor.to_list(length=None)

    types = {}
    for ext in extractions:
        ct = ext.get("content_type", "unknown")
        types.setdefault(ct, {"count": 0, "tables": 0, "images": 0})
        types[ct]["count"] += 1
        if "tables" in ext:
            types[ct]["tables"] += len(ext.get("tables", []))
        if "images" in ext:
            types[ct]["images"] += len(ext.get("images", []))

    return {
        "total_extractions": len(extractions),
        "by_type": types,
    }
