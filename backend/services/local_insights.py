"""Local crawl-data fallbacks for external SEO insights that are unavailable."""

from backend.db.mongo import get_db


async def local_keywords(job_id: str) -> list[dict]:
    from backend.services.serp_api import extract_keywords_from_content

    keywords = await extract_keywords_from_content(job_id)
    return [{"keyword": kw} for kw in keywords]


async def local_onpage(job_id: str) -> dict | None:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}).to_list(length=None)
    if not pages:
        return None

    n = len(pages)
    indexable = sum(1 for p in pages if p.get("is_indexable", True))
    with_title = sum(1 for p in pages if p.get("title"))
    with_meta = sum(1 for p in pages if p.get("meta_description"))
    with_h1 = sum(1 for p in pages if (p.get("h1_count") or 0) > 0)
    images_total = sum(p.get("image_count") or 0 for p in pages)
    images_missing_alt = sum(p.get("images_missing_alt") or 0 for p in pages)
    avg_words = round(sum(p.get("word_count") or 0 for p in pages) / n)
    avg_title = round(sum(len(p.get("title") or "") for p in pages) / n)

    score = 100
    if images_total:
        score -= round(60 * images_missing_alt / images_total)
    score -= round(15 * (n - with_meta) / n)
    score -= round(10 * (n - with_h1) / n)
    score -= round(5 * (n - indexable) / n)
    score = max(0, min(100, score))

    return {
        "score": score,
        "pages_analyzed": n,
        "indexable_pages": indexable,
        "pages_with_title": with_title,
        "pages_with_meta_description": with_meta,
        "pages_with_h1": with_h1,
        "images_total": images_total,
        "images_missing_alt": images_missing_alt,
        "avg_word_count": avg_words,
        "avg_title_length": avg_title,
        "source": "local-crawl",
    }


async def local_backlinks(job_id: str) -> dict | None:
    db = get_db()
    total = await db.backlinks.count_documents({"job_id": job_id})
    domains = await db.backlinks.distinct("source_domain", {"job_id": job_id})
    if not total:
        return None
    return {
        "backlinks": total,
        "referring_domains": len(domains),
        "rank": None,
        "source": "serp-discovery",
    }
