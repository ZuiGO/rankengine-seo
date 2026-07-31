from datetime import datetime
from urllib.parse import urlparse

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("backlinks")


def _domain_of(url: str) -> str:
    if "//" in url:
        return url.split("//")[-1].split("/")[0].split(":")[0]
    return url.split("/")[0]


async def fetch_backlinks(job_id: str, domain: str) -> dict:
    """List backlink source pages. DataForSEO first, SERP `link:` fallback."""
    db = get_db()
    sources = []
    source_api = None

    try:
        from backend.services.dataforseo import backlink_referring_pages
        items = await backlink_referring_pages(domain, limit=100)
        if items:
            source_api = "dataforseo"
            for item in items:
                url = item.get("url") or item.get("page_from")
                if not url:
                    continue
                sources.append({
                    "source_url": url,
                    "source_domain": item.get("source") or item.get("domain_from") or _domain_of(url),
                    "anchor": item.get("anchor", ""),
                    "backlinks_count": item.get("backlinks"),
                    "page_from_rank": item.get("page_from_rank"),
                    "first_seen": item.get("first_seen"),
                })
            logger.info("Backlinks via DataForSEO job=%s sources=%s", job_id, len(sources))
    except Exception as e:
        logger.warning("DataForSEO backlink list unavailable job=%s: %s", job_id, e)

    if not sources:
        try:
            from backend.services.serp_api import serp_link_search
            sources = await serp_link_search(domain)
            source_api = "serp"
            logger.info("Backlinks via SERP fallback job=%s sources=%s", job_id, len(sources))
        except Exception as e:
            logger.warning("SERP backlink fallback unavailable job=%s: %s", job_id, e)

    now = datetime.utcnow()
    docs = []
    seen = set()
    for s in sources:
        url = s["source_url"]
        src_domain = s.get("source_domain") or _domain_of(url)
        if url in seen or src_domain == domain:
            continue
        seen.add(url)
        docs.append({
            "job_id": job_id,
            "target_domain": domain,
            "source_url": url,
            "source_domain": src_domain,
            "anchor": s.get("anchor", ""),
            "backlinks_count": s.get("backlinks_count"),
            "page_from_rank": s.get("page_from_rank"),
            "first_seen": s.get("first_seen"),
            "source_api": source_api,
            "created_at": now,
        })

    if docs:
        await db.backlinks.delete_many({"job_id": job_id})
        await db.backlinks.insert_many(docs)

    preview = []
    for d in docs[:5]:
        preview.append({k: v for k, v in d.items() if k != "_id"})

    return {
        "total": len(docs),
        "referring_domains": len({d["source_domain"] for d in docs}),
        "source_api": source_api,
        "sources": preview,
    }


async def get_backlinks(job_id: str, limit: int = 100, offset: int = 0) -> dict:
    db = get_db()
    cursor = (
        db.backlinks.find({"job_id": job_id})
        .skip(offset)
        .limit(limit)
        .sort("page_from_rank", 1)
    )
    items = await cursor.to_list(length=limit)
    for b in items:
        b["id"] = str(b.pop("_id"))
    total = await db.backlinks.count_documents({"job_id": job_id})
    domains = await db.backlinks.distinct("source_domain", {"job_id": job_id})
    return {
        "backlinks": items,
        "total": total,
        "referring_domains": len(domains),
        "limit": limit,
        "offset": offset,
    }
