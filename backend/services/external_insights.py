"""External SEO insights orchestrator.

Primary provider is SE Ranking (api.seranking.com/v1); every paid section
degrades to a local crawl-data fallback with the source labeled accordingly.
"""

from datetime import datetime

from backend.services.service_errors import ServiceError


async def fetch_all_insights(domain: str, job_id: str | None = None) -> dict:
    """Fetch external SEO insights with per-section errors and local fallbacks."""
    from backend.services.local_insights import local_keywords, local_onpage, local_backlinks, local_overview
    from backend.services import se_ranking
    from backend.services import gsc as gsc_mod

    insights = {"domain": domain}

    try:
        kws = await se_ranking.domain_keywords(domain)
        if not kws:
            raise ServiceError("se_ranking", "no keyword data returned for this domain")
        insights["keywords"] = kws
        insights["keywords_source"] = "se-ranking"
        insights["keywords_error"] = None
    except Exception as e:
        insights["keywords_error"] = str(e)
        insights["keywords"] = await local_keywords(job_id) if job_id else []
        insights["keywords_source"] = "local" if insights["keywords"] else "none"

    try:
        insights["backlinks"] = await se_ranking.backlink_summary(domain)
        if not insights["backlinks"]:
            raise ServiceError("se_ranking", "no backlink data returned")
        insights["backlinks_source"] = "se-ranking"
        insights["backlinks_error"] = None
    except Exception as e:
        insights["backlinks_error"] = str(e)
        insights["backlinks"] = await local_backlinks(job_id) if job_id else None
        insights["backlinks_source"] = "local" if insights["backlinks"] else "none"

    try:
        insights["overview"] = await se_ranking.domain_overview(domain)
        if not insights["overview"]:
            raise ServiceError("se_ranking", "no overview data returned")
        insights["overview_source"] = "se-ranking"
        insights["overview_error"] = None
    except Exception as e:
        insights["overview_error"] = str(e)
        insights["overview"] = await local_overview(job_id) if job_id else None
        insights["overview_source"] = "local" if insights["overview"] else "none"

    # On-page audit uses crawl data only (no SE Ranking equivalent).
    try:
        insights["onpage"] = await local_onpage(job_id) if job_id else None
        insights["onpage_source"] = "local" if insights["onpage"] else "none"
        insights["onpage_error"] = None
    except Exception as e:
        insights["onpage"] = None
        insights["onpage_source"] = "none"
        insights["onpage_error"] = str(e)

    try:
        dis_trend = await se_ranking.domain_overview_history(domain)
        insights["overview_history"] = dis_trend
        insights["overview_history_error"] = None
    except Exception as e:
        insights["overview_history"] = []
        insights["overview_history_error"] = str(e)

    try:
        comps = await se_ranking.domain_competitors(domain)
        insights["competitors"] = comps
        insights["competitors_error"] = None
    except Exception as e:
        insights["competitors"] = []
        insights["competitors_error"] = str(e)

    try:
        insights["backlink_anchors"] = await se_ranking.backlink_anchors(domain)
        insights["backlink_anchors_error"] = None
    except Exception as e:
        insights["backlink_anchors"] = []
        insights["backlink_anchors_error"] = str(e)

    try:
        insights["backlink_refdomains"] = await se_ranking.backlink_refdomains(domain)
        insights["backlink_refdomains_error"] = None
    except Exception as e:
        insights["backlink_refdomains"] = []
        insights["backlink_refdomains_error"] = str(e)

    try:
        insights["backlink_top_pages"] = await se_ranking.backlink_top_pages(domain)
        insights["backlink_top_pages_error"] = None
    except Exception as e:
        insights["backlink_top_pages"] = []
        insights["backlink_top_pages_error"] = str(e)

    try:
        insights["backlink_authority"] = await se_ranking.backlink_authority(domain)
        insights["backlink_authority_error"] = None
    except Exception as e:
        insights["backlink_authority"] = None
        insights["backlink_authority_error"] = str(e)

    try:
        insights["authority_history"] = await se_ranking.authority_history(domain)
        insights["authority_history_error"] = None
    except Exception as e:
        insights["authority_history"] = []
        insights["authority_history_error"] = str(e)

    try:
        insights["backlink_new_lost"] = await se_ranking.backlink_new_lost(domain)
        insights["backlink_new_lost_error"] = None
    except Exception as e:
        insights["backlink_new_lost"] = []
        insights["backlink_new_lost_error"] = str(e)

    try:
        insights["backlink_new_lost_counts"] = await se_ranking.backlink_new_lost_counts(domain)
        insights["backlink_new_lost_counts_error"] = None
    except Exception as e:
        insights["backlink_new_lost_counts"] = []
        insights["backlink_new_lost_counts_error"] = str(e)

    try:
        gsc_data = await gsc_mod.fetch_gsc(domain)
        if gsc_data:
            insights["gsc"] = gsc_data
            insights["gsc_error"] = None
            ov = dict(insights.get("overview") or {})
            ov.update({
                "estimated_organic_traffic": gsc_data.get("clicks"),
                "organic_keywords_count": len(gsc_data.get("queries") or []),
                "source": "gsc",
            })
            insights["overview"] = ov
            insights["overview_source"] = "gsc"
            insights["overview_error"] = None
        else:
            insights["gsc"] = None
            insights["gsc_error"] = None
    except Exception as e:
        insights["gsc"] = None
        insights["gsc_error"] = str(e)

    try:
        from backend.services.serp_api import run_serp_rankings
        insights["serp_rankings"], failed = await run_serp_rankings(domain, job_id)
        insights["serp_source"] = "serp"
        insights["serp_error"] = None
        if failed:
            insights["serp_error"] = f"{len(failed)} keyword check(s) failed: " + "; ".join(failed[:2])
    except Exception as e:
        insights["serp_rankings"] = []
        insights["serp_source"] = "none"
        insights["serp_error"] = str(e)
    if not insights["serp_rankings"]:
        try:
            rankings = await se_ranking.ranked_keywords(domain)
            if rankings:
                insights["serp_rankings"] = rankings
                insights["serp_source"] = "se-ranking"
                insights["serp_error"] = None
        except Exception:
            pass

    return insights


async def merge_gsc_into_insights(db, job_id: str, domain: str, gsc_data: dict, cache_version: int) -> bool:
    """Merge a fresh GSC snapshot into the stored insights cache without refetching other sections."""
    cached = await db.seo_insights_cache.find_one({"job_id": job_id})
    if not cached:
        return False
    data = dict(cached.get("data") or {})
    data["gsc"] = gsc_data
    data["gsc_error"] = None
    ov = dict(data.get("overview") or {})
    ov.update({
        "estimated_organic_traffic": gsc_data.get("clicks"),
        "organic_keywords_count": len(gsc_data.get("queries") or []),
        "source": "gsc",
    })
    data["overview"] = ov
    data["overview_source"] = "gsc"
    data["overview_error"] = None
    await db.seo_insights_cache.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, "data": data, "fetched_at": datetime.utcnow(), "v": cache_version}},
        upsert=True,
    )
    return True