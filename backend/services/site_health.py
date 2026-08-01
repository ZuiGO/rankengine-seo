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

        perfs = await db.page_performance.find({"job_id": job_id}).to_list(length=None)
        cwv_scores = [p.get("cwv_score") for p in perfs if p.get("cwv_score") is not None]
        avg_cwv = None
        if cwv_scores:
            avg_cwv = round(sum(cwv_scores) / len(cwv_scores))
            metrics["cwv_pages_checked"] = len(perfs)
            metrics["avg_cwv_score"] = avg_cwv
            metrics["poor_lcp_pages"] = sum(1 for p in perfs if (p.get("cwv") or {}).get("lcp", 0) > 2500)
            metrics["poor_inp_pages"] = sum(1 for p in perfs if (p.get("cwv") or {}).get("inp", 0) > 200)
            metrics["poor_cls_pages"] = sum(1 for p in perfs if (p.get("cwv") or {}).get("cls", 0) > 0.1)
            if avg_cwv < 60:
                issues.append({"severity": "high", "message": f"Poor Core Web Vitals (avg score {avg_cwv}/100) - slow LCP/INP/CLS on {metrics['poor_lcp_pages'] + metrics['poor_inp_pages'] + metrics['poor_cls_pages']} page(s)."})
            elif avg_cwv < 80:
                issues.append({"severity": "medium", "message": f"Core Web Vitals need work (avg score {avg_cwv}/100)."})

        score = 100
        if metrics["broken_link_rate"] is not None:
            score -= min(30, round(3 * metrics["broken_link_rate"]))
        score -= round(15 * (100 - metrics["alt_text_coverage"] if metrics["alt_text_coverage"] is not None else 100) / 100)
        score -= round(10 * (100 - metrics["meta_description_coverage"]) / 100)
        score -= round(5 * (100 - metrics["h1_coverage"]) / 100)
        score -= min(10, round(2 * metrics["thin_pages"]))
        if cwv_scores:
            score -= round(15 * (100 - avg_cwv) / 100)
        score = max(0, min(100, score))

    pending = await db.action_items.count_documents({"job_id": job_id, "status": "pending"})
    metrics["pending_action_items"] = pending
    if pending > 0:
        issues.append({"severity": "medium", "message": f"{pending} unresolved SEO action item(s). Approve or reject them to apply improvements."})

    dup = await db.duplicate_content.find_one({"job_id": job_id})
    if dup:
        metrics["duplicate_pages"] = dup.get("duplicate_pages", 0)
        metrics["canonical_missing"] = dup.get("canonical_missing", 0)
        metrics["canonical_conflicts"] = dup.get("canonical_conflicting", 0) + dup.get("canonical_cross_domain", 0)
        if dup.get("duplicate_pages", 0) > 0:
            issues.append({"severity": "medium", "message": f"{dup.get('duplicate_pages')} page(s) are near-duplicates of other pages."})
        if dup.get("canonical_conflicting", 0) > 0:
            issues.append({"severity": "medium", "message": f"{dup.get('canonical_conflicting')} page(s) have conflicting canonical tags."})

    sd = await db.structured_data.find_one({"job_id": job_id})
    if sd:
        metrics["structured_data_valid"] = sd.get("valid", 0)
        metrics["structured_data_missing"] = sd.get("no_structured_data", 0)
        if sd.get("no_structured_data", 0) > 0:
            issues.append({"severity": "low", "message": f"{sd.get('no_structured_data')} page(s) have no structured data (Product/Article/Organization/Breadcrumb)."})
        if sd.get("invalid_types", 0) > 0:
            issues.append({"severity": "low", "message": f"{sd.get('invalid_types')} page(s) have invalid structured data markup."})

    geo = await db.geo_alignment.find_one({"job_id": job_id})
    if geo:
        metrics["geo_off_topic_pages"] = geo.get("off_topic_pages", 0)
        if geo.get("off_topic_pages", 0) > 0:
            issues.append({"severity": "low", "message": f"{geo.get('off_topic_pages')} page(s) diverge from the site's core industry — a risk for generative-search visibility."})

    orphans = await db.orphan_pages.find_one({"job_id": job_id})
    if orphans:
        metrics["orphan_pages"] = orphans.get("orphan_pages", 0)
        if orphans.get("orphan_pages", 0) > 0:
            issues.append({"severity": "medium", "message": f"{orphans.get('orphan_pages')} page(s) have no internal links pointing to them (orphans)."})

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
