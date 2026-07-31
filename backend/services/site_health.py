"""Site-level health score computed from crawl + link-check data."""

from datetime import datetime

from backend.db.mongo import get_db


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


async def compute_site_health(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 0}).to_list(length=None)
    lh = await db.link_health_summaries.find_one({"job_id": job_id})
    issues: list[dict] = []
    metrics: dict = {}

    n = len(pages)
    metrics["pages_analyzed"] = n

    # Link health
    lh_counts = (lh or {}).get("counts") or (lh or {})
    links_checked = lh_counts.get("checked", 0) if lh_counts else 0
    broken = (
        lh_counts.get("broken", 0)
        + lh_counts.get("timeout", 0)
        + lh_counts.get("error", 0)
        + lh_counts.get("blocked", 0)
    )
    metrics["links_checked"] = links_checked
    metrics["broken_links"] = broken
    metrics["broken_link_rate"] = round(100 * broken / links_checked, 1) if links_checked else None
    if metrics["broken_link_rate"] is not None:
        if metrics["broken_link_rate"] > 10:
            issues.append({"severity": "high", "message": f"{broken} of {links_checked} links are broken or unreachable ({metrics['broken_link_rate']}%)."})
        elif metrics["broken_link_rate"] > 2:
            issues.append({"severity": "medium", "message": f"{broken} broken links found ({metrics['broken_link_rate']}%)."})

    if not n:
        score = 0
    else:
        with_meta = sum(1 for p in pages if p.get("meta_description"))
        with_h1 = sum(1 for p in pages if (p.get("h1_count") or 0) > 0)
        indexable = sum(1 for p in pages if p.get("is_indexable", True))
        thin = sum(1 for p in pages if (p.get("word_count") or 0) < 200)
        images_total = sum(p.get("image_count") or 0 for p in pages)
        images_missing_alt = sum(p.get("images_missing_alt") or 0 for p in pages)

        metrics["pages_with_meta_description"] = with_meta
        metrics["meta_description_coverage"] = round(100 * with_meta / n)
        metrics["pages_with_h1"] = with_h1
        metrics["h1_coverage"] = round(100 * with_h1 / n)
        metrics["indexable_pages"] = indexable
        metrics["indexable_rate"] = round(100 * indexable / n)
        metrics["thin_pages"] = thin
        metrics["images_total"] = images_total
        metrics["images_missing_alt"] = images_missing_alt
        metrics["alt_text_coverage"] = round(100 * (images_total - images_missing_alt) / images_total) if images_total else None

        if metrics["alt_text_coverage"] is not None and metrics["alt_text_coverage"] < 60:
            issues.append({"severity": "high", "message": f"{images_missing_alt} of {images_total} images are missing alt text ({metrics['alt_text_coverage']}% coverage)."})
        elif metrics["alt_text_coverage"] is not None and metrics["alt_text_coverage"] < 90:
            issues.append({"severity": "medium", "message": f"{images_missing_alt} images are missing alt text."})
        if metrics["meta_description_coverage"] < 70:
            issues.append({"severity": "medium", "message": f"Only {metrics['meta_description_coverage']}% of pages have a meta description."})
        if metrics["h1_coverage"] < 80:
            issues.append({"severity": "medium", "message": f"Only {metrics['h1_coverage']}% of pages have an H1 heading."})
        if metrics["thin_pages"] > 0:
            issues.append({"severity": "medium", "message": f"{metrics['thin_pages']} page(s) have fewer than 200 words (thin content)."})
        if metrics["indexable_rate"] < 100:
            issues.append({"severity": "low", "message": f"{n - indexable} page(s) are blocked from indexing (noindex)."})

        score = 100
        if metrics["broken_link_rate"] is not None:
            score -= min(30, round(3 * metrics["broken_link_rate"]))
        score -= round(15 * (100 - metrics["alt_text_coverage"] if metrics["alt_text_coverage"] is not None else 100) / 100)
        score -= round(10 * (100 - metrics["meta_description_coverage"]) / 100)
        score -= round(5 * (100 - metrics["h1_coverage"]) / 100)
        score -= min(10, round(2 * metrics["thin_pages"]))
        score = max(0, min(100, score))

    pending = await db.action_items.count_documents({"job_id": job_id, "status": "pending"})
    metrics["pending_action_items"] = pending
    if pending > 0:
        issues.append({"severity": "medium", "message": f"{pending} unresolved SEO action item(s). Approve or reject them to apply improvements."})

    health = {
        "job_id": job_id,
        "grade": _grade(score),
        "score": score,
        "metrics": metrics,
        "issues": issues,
        "generated_at": datetime.utcnow(),
    }
    await db.site_health.update_one(
        {"job_id": job_id},
        {"$set": health},
        upsert=True,
    )
    return health


async def get_site_health(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.site_health.find_one({"job_id": job_id})
    if not doc:
        return await compute_site_health(job_id)
    doc["id"] = str(doc.pop("_id"))
    return doc
