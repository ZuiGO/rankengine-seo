"""Keyword cannibalization: flag groups of pages competing for the same core
keyword so teams can merge or differentiate them.
"""

from datetime import datetime

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("cannibalization")

MIN_KEYWORD_LEN = 5
MAX_KEYWORDS = 40
MAX_CLUSTER_PAGES = 8


async def detect_cannibalization(job_id: str) -> dict:
    db = get_db()
    try:
        from backend.services.keyword_extractor import extract_keywords_from_content
        corpus = await extract_keywords_from_content(job_id, top_k=MAX_KEYWORDS)
    except Exception as e:
        logger.warning("Cannibalization corpus unavailable job=%s: %s", job_id, e)
        corpus = []

    pages = await db.pages.find(
        {"job_id": job_id, "is_indexable": True},
        {"html": 0, "html_mobile": 0},
    ).to_list(length=None)

    keyword_pages: dict[str, list[dict]] = {}
    for kw in corpus:
        kw_low = kw.lower()
        if len(kw_low) < MIN_KEYWORD_LEN:
            continue
        for p in pages:
            surface = f"{p.get('title') or ''} {p.get('meta_description') or ''}".lower()
            if kw_low in surface:
                keyword_pages.setdefault(kw_low, []).append(p)

    groups = []
    for kw, pages in keyword_pages.items():
        if len(pages) < 2:
            continue
        ranked = sorted(pages, key=lambda p: (p.get("click_depth") or 0, p.get("url", "")))
        group = {
            "keyword": kw,
            "page_count": len(ranked),
            "pages": [
                {
                    "url": p.get("url", ""),
                    "title": p.get("title", ""),
                    "click_depth": p.get("click_depth") or 0,
                }
                for p in ranked[:MAX_CLUSTER_PAGES]
            ],
        }
        groups.append(group)

    await db.action_items.delete_many({"job_id": job_id, "content_type": "cannibalization"})

    created = 0
    for group in groups:
        for p in group["pages"]:
            action = {
                "job_id": job_id,
                "page_url": p["url"],
                "content_item_id": "",
                "content_type": "cannibalization",
                "source_url": "",
                "issue_key": "cannibalization",
                "impact_on_ranking": "high",
                "confidence": 0.8,
                "evidence": {"keyword": group["keyword"], "page_count": group["page_count"], "competing_urls": [x["url"] for x in group["pages"]]},
                "identified_issues": [f"Page competes for '{group['keyword']}' with {group['page_count'] - 1} other page(s)"],
                "improvement_suggestions": [
                    "Differentiate the pages by distinct intent/audience or merge them",
                    "Point internal links at the strongest single page for the keyword",
                ],
                "status": "pending",
                "created_at": datetime.utcnow(),
            }
            await db.action_items.insert_one(action)
            created += 1

    summary = {
        "job_id": job_id,
        "groups": len(groups),
        "affected_pages": created,
        "cannibalized_keywords": [g["keyword"] for g in groups[:10]],
        "checked_at": datetime.utcnow(),
    }
    await db.cannibalization_summaries.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("Cannibalization job=%s groups=%s actions=%s", job_id, len(groups), created)
    return summary