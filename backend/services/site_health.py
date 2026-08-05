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
    links_checked = lh_counts.get("checked", 0)
    broken = lh_counts.get("broken_link_count")
    legacy = False
    if broken is None:
        legacy = True
        broken = (
            lh_counts.get("broken", 0)
            + lh_counts.get("timeout", 0)
            + lh_counts.get("error", 0)
            + lh_counts.get("blocked", 0)
        )
    metrics["links_checked"] = links_checked
    metrics["broken_links"] = broken
    if legacy:
        metrics["broken_links_legacy_bucket"] = True
    metrics["broken_link_rate"] = round(100 * broken / links_checked, 1) if links_checked else None
    if metrics["broken_link_rate"] is not None:
        label = "broken or unreachable" if legacy else "broken"
        if metrics["broken_link_rate"] > 10:
            issues.append({"severity": "high", "message": f"{broken} of {links_checked} links are {label} ({metrics['broken_link_rate']}%)."})
        elif metrics["broken_link_rate"] > 2:
            issues.append({"severity": "medium", "message": f"{broken} {label} links found ({metrics['broken_link_rate']}%)."})

    if not n:
        score = 0
    else:
        evaluated = lambda key: [p for p in pages if p.get(key) is not None]
        with_meta = sum(1 for p in pages if p.get("meta_description"))
        meta_evaluated = len(evaluated("meta_description"))
        with_h1 = sum(1 for p in pages if (p.get("h1_count") or 0) > 0)
        h1_evaluated = len(evaluated("h1_count"))
        indexable = sum(1 for p in pages if p.get("is_indexable", True))
        thin = sum(1 for p in pages if p.get("word_count") is not None and p["word_count"] < 200)
        thin_evaluated = len(evaluated("word_count"))
        images_total = sum(p.get("image_count") or 0 for p in pages)
        images_missing_alt = sum(p.get("images_missing_alt") or 0 for p in pages)

        metrics["pages_with_meta_description"] = with_meta
        metrics["pages_evaluated_meta"] = meta_evaluated
        metrics["meta_description_coverage"] = round(100 * with_meta / meta_evaluated) if meta_evaluated else None
        metrics["pages_with_h1"] = with_h1
        metrics["pages_evaluated_h1"] = h1_evaluated
        metrics["h1_coverage"] = round(100 * with_h1 / h1_evaluated) if h1_evaluated else None
        metrics["indexable_pages"] = indexable
        metrics["indexable_rate"] = round(100 * indexable / n)
        metrics["thin_pages"] = thin
        metrics["pages_evaluated_word_count"] = thin_evaluated
        metrics["images_total"] = images_total
        metrics["images_missing_alt"] = images_missing_alt
        metrics["alt_text_coverage"] = round(100 * (images_total - images_missing_alt) / images_total) if images_total else None

        if metrics["alt_text_coverage"] is not None and metrics["alt_text_coverage"] < 60:
            issues.append({"severity": "high", "message": f"{images_missing_alt} of {images_total} images are missing alt text ({metrics['alt_text_coverage']}% coverage)."})
        elif metrics["alt_text_coverage"] is not None and metrics["alt_text_coverage"] < 90:
            issues.append({"severity": "medium", "message": f"{images_missing_alt} images are missing alt text."})
        if metrics["meta_description_coverage"] is not None and metrics["meta_description_coverage"] < 70:
            issues.append({"severity": "medium", "message": f"Only {metrics['meta_description_coverage']}% of pages have a meta description."})
        if metrics["h1_coverage"] is not None and metrics["h1_coverage"] < 80:
            issues.append({"severity": "medium", "message": f"Only {metrics['h1_coverage']}% of pages have an H1 heading."})
        if metrics["thin_pages"] > 0:
            issues.append({"severity": "medium", "message": f"{metrics['thin_pages']} page(s) have fewer than 200 words (thin content)."})
        if metrics["indexable_rate"] < 100:
            issues.append({"severity": "low", "message": f"{n - indexable} page(s) are blocked from indexing (noindex)."})

        perfs = await db.page_performance.find({"job_id": job_id}).to_list(length=None)
        seen_pages = {}
        for p in perfs:
            seen_pages.setdefault(p.get("url"), p)
        cwv_scores = [p.get("cwv_score") for p in seen_pages.values() if p.get("cwv_score") is not None]
        avg_cwv = None
        if cwv_scores:
            avg_cwv = round(sum(cwv_scores) / len(cwv_scores))
            metrics["cwv_pages_checked"] = len(seen_pages)
            metrics["avg_cwv_score"] = avg_cwv
            metrics["poor_lcp_pages"] = sum(1 for p in seen_pages.values() if (p.get("cwv") or {}).get("lcp", 0) > 2500)
            metrics["poor_inp_pages"] = sum(1 for p in seen_pages.values() if (p.get("cwv") or {}).get("inp", 0) > 200)
            metrics["poor_cls_pages"] = sum(1 for p in seen_pages.values() if (p.get("cwv") or {}).get("cls", 0) > 0.1)
            if avg_cwv < 60:
                issues.append({"severity": "high", "message": f"Poor Core Web Vitals (avg score {avg_cwv}/100) - slow LCP/INP/CLS on {metrics['poor_lcp_pages'] + metrics['poor_inp_pages'] + metrics['poor_cls_pages']} page(s)."})
            elif avg_cwv < 80:
                issues.append({"severity": "medium", "message": f"Core Web Vitals need work (avg score {avg_cwv}/100)."})

        score = 100
        if metrics["broken_link_rate"] is not None:
            score -= min(30, round(3 * metrics["broken_link_rate"]))
        if metrics["alt_text_coverage"] is not None:
            score -= round(15 * (100 - metrics["alt_text_coverage"]) / 100)
        if metrics["meta_description_coverage"] is not None:
            score -= round(10 * (100 - metrics["meta_description_coverage"]) / 100)
        if metrics["h1_coverage"] is not None:
            score -= round(5 * (100 - metrics["h1_coverage"]) / 100)
        score -= min(10, round(2 * metrics["thin_pages"]))
        if cwv_scores:
            score -= round(15 * (100 - avg_cwv) / 100)
        https_pages = sum(1 for p in pages if p.get("https_entry"))
        metrics["https_entry_pages"] = https_pages
        score -= n - https_pages
        deep_count = sum(1 for p in pages if (p.get("click_depth") or 0) > 3)
        metrics["deep_click_depth_pages"] = deep_count
        mobile_friendly = sum(1 for p in pages if p.get("mobile_friendly") is True)
        mobile_evaluated = sum(1 for p in pages if p.get("mobile_friendly") is not None)
        metrics["mobile_friendly_pages"] = mobile_friendly
        metrics["mobile_friendly_evaluated"] = mobile_evaluated
        score -= round(2 * (mobile_evaluated - mobile_friendly))
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

    sitemap_audit = await db.sitemap_audits.find_one({"job_id": job_id})
    if sitemap_audit:
        metrics["sitemap_found"] = sitemap_audit.get("sitemap_found", False)
        metrics["sitemap_valid"] = sitemap_audit.get("sitemap_valid", False)
        metrics["sitemap_uncrawled"] = sitemap_audit.get("uncrawled_urls_count", 0)
        if not sitemap_audit.get("sitemap_found", False):
            issues.append({"severity": "low", "message": "No XML sitemap found."})
        elif not sitemap_audit.get("sitemap_valid", False):
            issues.append({"severity": "medium", "message": "Sitemap found but could not be parsed."})
        if sitemap_audit.get("uncrawled_urls_count", 0) > 0:
            issues.append({"severity": "low", "message": f"{sitemap_audit.get('uncrawled_urls_count')} sitemap URL(s) were never crawled."})

    if n:
        deep = sum(1 for p in pages if (p.get("click_depth") or 0) > 3)
        metrics["deep_click_depth_pages"] = deep
        if deep > 0:
            issues.append({"severity": "low", "message": f"{deep} page(s) are more than 3 clicks from the homepage (deep click depth)."})
        redirected = sum(1 for p in pages if (p.get("redirect_count") or 0) >= 3)
        metrics["long_redirect_chain_pages"] = redirected
        if redirected > 0:
            issues.append({"severity": "medium", "message": f"{redirected} page(s) are reached through 3+ hop redirect chains."})
        if https_pages != n:
            issues.append({"severity": "medium", "message": f"{n - https_pages} page(s) are linked over non-HTTPS entries (mixed content / host drift)."})
        if mobile_evaluated > 0 and mobile_friendly < mobile_evaluated:
            issues.append({"severity": "low", "message": f"{mobile_evaluated - mobile_friendly} of {mobile_evaluated} evaluated page(s) are missing a mobile viewport / zoom fix."})
        lh_redirected = (lh or {}).get("redirected_links")
        if lh_redirected:
            metrics["redirected_links"] = lh_redirected
            metrics["max_redirect_chain"] = (lh or {}).get("max_redirect_chain", 0)
            if (lh or {}).get("max_redirect_chain", 0) >= 3:
                issues.append({"severity": "low", "message": f"{lh_redirected} links redirect; longest chain is {lh.get('max_redirect_chain')} hops."})

    ai = await db.ai_visibility_summaries.find_one({"job_id": job_id})
    if ai:
        metrics["ai_visibility_score"] = ai.get("score")
        metrics["ai_blocked_agents"] = ai.get("blocked_ai_agents", [])
        if ai.get("blocked_ai_agents"):
            issues.append({"severity": "high", "message": f"robots.txt blocks AI crawlers: {', '.join(ai['blocked_ai_agents'][:4])} — the site is invisible to AI search."})
        if not ai.get("llms_txt_present"):
            issues.append({"severity": "low", "message": "No llms.txt present for LLM consumers."})

    local = await db.local_seo_summaries.find_one({"job_id": job_id})
    if local:
        metrics["local_seo_score"] = local.get("score")
        if local.get("score", 0) < 60:
            missing = ", ".join(local.get("checks", [])[:3])
            issues.append({"severity": "low", "message": f"Local-SEO signals weak ({local.get('score')}/100): {missing}"})

    can = await db.cannibalization_summaries.find_one({"job_id": job_id})
    if can:
        metrics["cannibalization_groups"] = can.get("groups", 0)
        if can.get("groups", 0) > 0:
            issues.append({"severity": "high", "message": f"{can.get('groups')} keyword(s) are targeted by {can.get('affected_pages')} competing page(s) (cannibalization)."})

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
