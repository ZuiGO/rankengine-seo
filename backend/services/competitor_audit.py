"""Free-tools competitor gap analysis.

Crawls every page of each competitor (queue + sitemap seed, safety ceiling),
runs the same local analyzers used for target audits (on-page, link health,
site health, PSI Core Web Vitals, structured data, corpus keywords), and diffs
them against the target job's stored crawl across 8 gap dimensions:

keyword, content, backlink, technical, schema, on-page, UX, SERP features.

All sources are free in this stack: Playwright crawl, PSI/Lighthouse,
local validators, and the SERP API as the Google Search proxy. Everything
degrades gracefully when the SERP key is unconfigured.
"""

import asyncio
import uuid
from datetime import datetime
from urllib.parse import urlparse

from backend.config import settings
from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("competitor_audit")

MAX_KEYWORDS = 10


def _domain(url: str) -> str:
    if "//" in url:
        return url.split("//")[-1].split("/")[0]
    return url


def _normalize(kw: str) -> str:
    return " ".join((kw or "").strip().lower().split())


async def _create_competitor_job(target_job_id: str, url: str) -> str:
    db = get_db()
    comp_job = str(uuid.uuid4())
    await db.analysis_jobs.insert_one({
        "_id": comp_job,
        "url": url,
        "status": "queued",
        "progress": 0,
        "progress_message": "Queued (competitor crawl)...",
        "created_at": datetime.utcnow(),
        "completed_at": None,
        "error_message": None,
        "summary": None,
        "competitor_job": True,
        "target_job_id": target_job_id,
    })
    return comp_job


async def _delete_competitor_job(comp_job: str):
    db = get_db()
    collections = [
        "pages", "page_links", "content_items", "content_extractions",
        "action_items", "content_versions", "link_health", "link_health_summaries",
        "site_health", "duplicate_content", "structured_data", "geo_alignment",
        "orphan_pages", "page_performance", "page_performance_summaries",
        "user_flows", "keyword_tracking", "keyword_tracking_summaries",
        "embeddings", "seo_insights_cache",
    ]
    for coll in collections:
        try:
            await db[coll].delete_many({"job_id": comp_job})
        except Exception:
            pass
    await db.analysis_jobs.delete_one({"_id": comp_job})


async def _crawl_competitor(comp_job: str, url: str) -> dict:
    from backend.services.crawler import crawl_site
    return await crawl_site(
        comp_job, url,
        max_pages=None,
        concurrency=settings.crawl_concurrency,
        seed_sitemap=True,
        unlimited=True,
        mobile=False,
    )


async def _target_baseline(target_job_id: str) -> dict:
    db = get_db()
    health = await db.site_health.find_one({"job_id": target_job_id})
    sd = await db.structured_data.find_one({"job_id": target_job_id})
    perf = await db.page_performance_summaries.find_one({"job_id": target_job_id})
    lh = await db.link_health_summaries.find_one({"job_id": target_job_id})

    pages = await db.pages.find({"job_id": target_job_id}, {"html": 0, "html_mobile": 0}).to_list(length=None)

    sd_types = set()
    for t, _count in (sd or {}).get("type_counts", {}).items():
        sd_types.add(t.split(" ")[0])

    return {
        "url": None,
        "health": health,
        "sd": sd,
        "sd_types": sd_types,
        "perf": perf,
        "lh": lh,
        "pages": pages,
        "titles": {p.get("url", ""): p.get("title", "") for p in pages},
        "word_counts": [p.get("word_count") or 0 for p in pages],
        "mobile_friendly": sum(1 for p in pages if p.get("mobile_friendly", True)),
    }


def _rate(numerator: int | None, denominator: int | None) -> float | None:
    if denominator is None or not denominator:
        return None
    return round(100 * (numerator or 0) / denominator, 1)


def _token_set(text: str) -> set[str]:
    import re
    return set(re.findall(r"[a-z0-9'_-]+", (text or "").lower()))


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


async def _serp_keyword_gaps(target_domain: str, comp_domain: str, keywords: list[str]) -> dict:
    from backend.services.serp_api import search_keyword
    target_ranks: dict[str, int] = {}
    comp_ranks: dict[str, int] = {}
    errors = []
    for kw in keywords:
        try:
            tr = await search_keyword(kw, target_domain)
            cr = await search_keyword(kw, comp_domain)
            target_ranks[kw] = tr.get("rank")
            comp_ranks[kw] = cr.get("rank")
        except Exception as e:
            errors.append(f"{kw}: {e}")
    gaps = []
    for kw in keywords:
        tr = target_ranks.get(kw)
        cr = comp_ranks.get(kw)
        if cr is not None and tr is None:
            gaps.append(kw)
    return {
        "gaps": gaps,
        "target_ranks": target_ranks,
        "comp_ranks": comp_ranks,
        "errors": errors,
    }


async def _serp_features_gap(target_domain: str, comp_domain: str, keywords: list[str]) -> dict:
    from backend.services.serp_api import search_keyword_full
    per_keyword = []
    errors = []
    for kw in keywords:
        try:
            data = await search_keyword_full(kw)
        except Exception as e:
            errors.append(f"{kw}: {e}")
            continue
        organic_domains = set(data.get("organic_domains", []))
        features = data.get("features", {})
        comp_owns = any(d == comp_domain for d in organic_domains)
        target_owns = any(d == target_domain for d in organic_domains)
        entry = {
            "keyword": kw,
            "features_present": sorted(features.keys()),
            "target_in_organic": target_owns,
            "comp_in_organic": comp_owns,
            "comp_only_features": [],
        }
        for name, feat in features.items():
            feat_domains = set(feat.get("domains") or [])
            if comp_owns and not target_owns:
                entry["comp_only_features"].append(name)
            elif not comp_owns and not target_owns:
                if feat_domains and comp_domain in feat_domains:
                    entry["comp_only_features"].append(name)
        if entry["comp_only_features"] and not target_owns:
            entry["gap"] = True
        per_keyword.append(entry)

    comp_only = {}
    for e in per_keyword:
        if e.get("gap") and e["comp_only_features"]:
            comp_only[e["keyword"]] = e["comp_only_features"]
    return {
        "per_keyword": per_keyword,
        "comp_only": comp_only,
        "errors": errors,
    }


async def _backlink_gap(target_domain: str, comp_domain: str) -> dict:
    from backend.services.serp_api import serp_link_search
    errors = []
    target_sources = set()
    comp_sources = set()
    try:
        for row in await serp_link_search(target_domain):
            target_sources.add(row.get("source_domain", ""))
    except Exception as e:
        errors.append(f"target: {e}")
    try:
        for row in await serp_link_search(comp_domain):
            comp_sources.add(row.get("source_domain", ""))
    except Exception as e:
        errors.append(f"competitor: {e}")
    gaps = sorted(s for s in comp_sources - target_sources if s)[:20]
    return {
        "gaps": gaps,
        "target_sources": sorted(s for s in target_sources if s)[:20],
        "comp_sources": sorted(s for s in comp_sources if s)[:20],
        "errors": errors,
    }


async def _se_rich_gap(target_domain: str, comp_domain: str, target_job_id: str) -> dict:
    """SE Ranking powered sections for the gap report (best-effort, per-key errors).

    Target metrics reuse the cached seo_insights_cache; competitor metrics are
    fetched live so the report shows organic traffic, backlinks, authority and
    keyword volume/CPC/KD for both sides.
    """
    from backend.services import se_ranking
    db = get_db()
    errors = []
    out: dict = {}

    # Target cached data (no extra spend)
    cached = await db.seo_insights_cache.find_one({"job_id": target_job_id})
    cached_data = (cached or {}).get("data") or {}
    t_overview = cached_data.get("overview") or {}
    t_keywords = cached_data.get("keywords") or []
    t_backlinks = cached_data.get("backlinks") or {}
    t_history = cached_data.get("overview_history") or []
    out["target"] = {
        "overview": t_overview,
        "keywords": t_keywords[:50],
        "backlinks": t_backlinks,
        "history": t_history,
        "source": cached_data.get("overview_source") or "none",
    }

    # Competitor live data
    comp_block = {}
    try:
        comp_block["overview"] = await se_ranking.domain_overview(comp_domain)
    except Exception as e:
        errors.append(f"overview: {e}")
    try:
        comp_block["keywords"] = await se_ranking.domain_keywords(comp_domain, limit=50)
    except Exception as e:
        errors.append(f"keywords: {e}")
    try:
        comp_block["ranked"] = await se_ranking.ranked_keywords(comp_domain, limit=50)
    except Exception as e:
        errors.append(f"ranked: {e}")
    try:
        comp_block["backlinks"] = await se_ranking.backlink_summary(comp_domain)
    except Exception as e:
        errors.append(f"backlinks: {e}")
    try:
        comp_block["history"] = await se_ranking.domain_overview_history(comp_domain)
    except Exception as e:
        errors.append(f"history: {e}")
    try:
        comp_block["backlink_sources"] = await se_ranking.backlink_list(comp_domain, limit=50)
    except Exception as e:
        errors.append(f"backlink_sources: {e}")
    try:
        comp_block["keyword_gap"] = await se_ranking.keyword_gap(comp_domain, target_domain, limit=50)
    except Exception as e:
        errors.append(f"keyword_gap: {e}")
    out["competitor"] = comp_block

    # Analysis helpers (rules over whichever data actually landed)
    c_names = {_normalize(k.get("keyword", "")) for k in comp_block.get("keywords") or []}
    t_names = {_normalize(k.get("keyword", "")) for k in t_keywords or []}
    shared = sorted(n for n in (c_names & t_names) if n)
    missing = sorted(n for n in (c_names - t_names) if n)
    unique_t = sorted(n for n in (t_names - c_names) if n)

    def _kw_meta(kws, ranked, name):
        info = None
        for k in kws:
            if _normalize(k.get("keyword", "")) == name:
                kd = k.get("keyword_data") or {}
                ki = kd.get("keyword_info") or {}
                kp = kd.get("keyword_properties") or {}
                info = {
                    "volume": ki.get("search_volume"),
                    "cpc": ki.get("cpc"),
                    "difficulty": kp.get("keyword_difficulty"),
                    "rank": None,
                }
                break
        rank = None
        for r in ranked or []:
            if _normalize(r.get("keyword", "")) == name:
                pos = r.get("rank")
                rank = pos if pos and pos > 0 else None
                break
        if info is None:
            return {"volume": None, "cpc": None, "difficulty": None, "rank": rank}
        info["rank"] = rank
        return info

    missing_detail = []
    for name in missing:
        meta = _kw_meta(comp_block.get("keywords") or [], comp_block.get("ranked") or [], name)
        if meta.get("volume"):
            missing_detail.append({"keyword": name, **meta})
    missing_detail.sort(key=lambda x: (x.get("volume") or 0), reverse=True)

    shared_detail = []
    for name in shared:
        cm = _kw_meta(comp_block.get("keywords") or [], comp_block.get("ranked") or [], name)
        kw_obj = next((k for k in t_keywords if _normalize(k.get("keyword", "")) == name), None)
        tm = {"volume": None, "cpc": None, "difficulty": None, "rank": None}
        if kw_obj:
            kd = kw_obj.get("keyword_data") or {}
            ki = kd.get("keyword_info") or {}
            kp = kd.get("keyword_properties") or {}
            tm = {
                "volume": ki.get("search_volume"),
                "cpc": ki.get("cpc"),
                "difficulty": kp.get("keyword_difficulty"),
                "rank": None,
            }
        shared_detail.append({
            "keyword": name,
            "comp": cm, "target": tm,
        })

    out["keyword_analysis"] = {
        "shared": shared[:50],
        "missing_from_target": missing[:50],
        "unique_target": unique_t[:50],
        "missing_detail": missing_detail[:30],
        "shared_detail": shared_detail[:30],
        "top_opportunities": missing_detail[:20],
    }

    # ---- Traffic
    c_ov = comp_block.get("overview") or {}
    t_ov = t_overview or {}
    out["traffic_analysis"] = {
        "target_traffic": t_ov.get("estimated_organic_traffic"),
        "competitor_traffic": c_ov.get("estimated_organic_traffic"),
        "target_keywords": t_ov.get("organic_keywords_count"),
        "competitor_keywords": c_ov.get("organic_keywords_count"),
        "target_history": t_history,
        "competitor_history": comp_block.get("history") or [],
        "traffic_value_estimate": _estimate_traffic_value(c_ov, comp_block.get("keywords") or []),
    }

    # ---- Backlinks / authority
    c_bl = comp_block.get("backlinks") or {}
    t_bl = t_backlinks or {}
    out["backlink_analysis"] = {
        "target": t_bl,
        "competitor": c_bl,
        "referring_domains_delta": _delta(t_bl.get("referring_domains"), c_bl.get("referring_domains")),
        "backlinks_delta": _delta(t_bl.get("backlinks"), c_bl.get("backlinks")),
        "high_authority_sources": [s for s in comp_block.get("backlink_sources") or []
                                  if (s.get("domain_inlink_rank") or 100) < 20][:15],
        "comp_sources": comp_block.get("backlink_sources") or [],
    }
    out["authority_analysis"] = {
        "target_domain_rank": t_bl.get("domain_rank"),
        "comp_domain_rank": c_bl.get("domain_rank"),
        "target_page_rank": t_bl.get("page_rank"),
        "comp_page_rank": c_bl.get("page_rank"),
        "delta": _delta(t_bl.get("domain_rank"), c_bl.get("domain_rank")),
    }
    out["errors"] = errors
    return out


def _delta(a, b):
    if a is None or b is None:
        return None
    return round(b - a, 1)


def _estimate_traffic_value(overview: dict, ranked_keywords: list[dict]) -> float | None:
    """Estimated monthly traffic value = sum(keyword traffic * CPC) proxy over ranked keywords.

    Clearly an estimate, not a paid-api revenue figure.
    """
    total = 0.0
    had = False
    for kw in ranked_keywords:
        info = (kw.get("keyword_data") or {}).get("keyword_info") or {}
        vol = info.get("search_volume") or 0
        cpc = info.get("cpc") or 0
        if vol and cpc:
            total += vol * cpc
            had = True
    if not had:
        return None
    return round(total, 2)


def _opportunity_score(se_rich: dict) -> int | None:
    """0-100 upside estimate of closing the gap on this competitor.

    Weights: keyword opportunity 0.4, traffic delta 0.3, backlink delta 0.3.
    Returns None when no comparable metrics landed (best-effort data missing).
    """
    ka = se_rich.get("keyword_analysis") or {}
    ta = se_rich.get("traffic_analysis") or {}
    ba = se_rich.get("backlink_analysis") or {}
    score = 0.0
    weight = 0.0

    missing = len(ka.get("missing_detail") or [])
    shared = len(ka.get("shared_detail") or [])
    if missing or shared:
        opp = min(missing, 20) / 20.0
        score += 0.4 * opp
        weight += 0.4

    c_t = ta.get("competitor_traffic")
    t_t = ta.get("target_traffic")
    if isinstance(c_t, (int, float)) and isinstance(t_t, (int, float)) and t_t > 0:
        growth = (c_t - t_t) / t_t
        if growth > 0:
            score += 0.3 * min(growth, 4.0)
            weight += 0.3

    c_rd = ba.get("referring_domains_delta")
    if isinstance(c_rd, (int, float)):
        score += 0.3 * (min(c_rd / 200.0, 1.0) if c_rd > 0 else 0.0)
        weight += 0.3

    if weight <= 0:
        return None
    return round(min(score / weight, 1.0) * 100)


def _build_recommendations(se_rich: dict) -> list[dict]:
    """Rule-based, data-grounded recommendations for the gap report."""
    ka = se_rich.get("keyword_analysis") or {}
    ta = se_rich.get("traffic_analysis") or {}
    ba = se_rich.get("backlink_analysis") or {}
    aa = se_rich.get("authority_analysis") or {}
    recs: list[dict] = []

    missing_detail = ka.get("missing_detail") or []
    if missing_detail:
        top3 = ", ".join(m.get("keyword", "") for m in missing_detail[:3])
        recs.append({
            "priority": "high",
            "title": "Target high-opportunity keywords you don't rank for",
            "detail": (
                f"Competitor ranks for keywords your site is missing. Top volume "
                f"opportunities: {top3}. Create or strengthen pages addressed "
                f"exactly to these intents."
            ),
            "count": len(missing_detail),
        })

    c_t = ta.get("competitor_traffic")
    t_t = ta.get("target_traffic")
    if isinstance(c_t, (int, float)) and isinstance(t_t, (int, float)) and c_t > t_t:
        recs.append({
            "priority": "medium",
            "title": "Close the organic traffic gap",
            "detail": (
                f"Competitor drives {c_t:,} estimated monthly organic visits vs "
                f"your {t_t:,}. Prioritize the missing keywords above plus "
                f"content depth where they outrank you."
            ),
            "count": None,
        })

    c_bl = ba.get("backlinks_delta")
    if isinstance(c_bl, (int, float)) and c_bl > 0:
        recs.append({
            "priority": "high" if c_bl > 100 else "medium",
            "title": "Grow the backlink profile",
            "detail": (
                f"Competitor leads by {c_bl:,} backlinks. Audit their highest "
                f"authority referring domains and pursue comparable placements "
                f"(digital PR, data-led content, directory/list inclusion)."
            ),
            "count": int(c_bl),
        })

    c_rd = ba.get("referring_domains_delta")
    if isinstance(c_rd, (int, float)) and c_rd > 0:
        recs.append({
            "priority": "medium",
            "title": "Diversify referring domains",
            "detail": (
                f"Competitor links from {int(c_rd):,} more referring domains. "
                f"Focus on breadth, not just volume — new domains signal "
                f"editorial trust."
            ),
            "count": int(c_rd),
        })

    c_dr = aa.get("comp_domain_rank")
    t_dr = aa.get("target_domain_rank")
    if isinstance(c_dr, (int, float)) and isinstance(t_dr, (int, float)) and c_dr > t_dr:
        recs.append({
            "priority": "medium",
            "title": "Raise domain authority",
            "detail": (
                f"Competitor domain authority is {c_dr:.0f} vs your {t_dr:.0f}. "
                f"Authority grows with quality backlinks and consistent "
                f"referring-domain diversity; see backlink recommendations."
            ),
            "count": int(int(c_dr) - int(t_dr)),
        })

    recs.sort(key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r["priority"], 3))
    return recs


def build_competitor_report(row: dict) -> dict:
    """Assemble the full sectioned gap report from a stored analysis row.

    Sources: local crawl diffs (content/technical/schema/on-page/UX/SERP) plus
    the SE Ranking `se_rich` block (keyword, traffic, backlink, authority).
    Returns a dict of named sections; individual sections stay empty when their
    data is missing so the frontend can render "not measured" honestly.
    """
    se_rich = row.get("se_rich") or {}
    ka = se_rich.get("keyword_analysis") or {}
    ta = se_rich.get("traffic_analysis") or {}
    ba = se_rich.get("backlink_analysis") or {}
    aa = se_rich.get("authority_analysis") or {}

    technical_gap = row.get("technical_gap") or {}
    content_gap = row.get("content_gap") or {}
    schema_gap = row.get("schema_gap") or {}
    onpage_gap = row.get("onpage_gap") or {}
    ux_gap = row.get("ux_gap") or {}
    serp_feat = row.get("serp_features_gap") or {}
    keyword_gap = row.get("keyword_gap") or {}

    src_k = (se_rich.get("competitor") or {}).get("overview") or {}
    tgt_src = se_rich.get("target") or {}
    t_ov = tgt_src.get("overview") or {}
    t_kws = tgt_src.get("keywords") or []

    sections = {
        "executive_overview": {
            "competitor": row.get("competitor"),
            "url": row.get("url"),
            "pages_crawled": row.get("pages_crawled"),
            "opportunity_score": se_rich.get("opportunity_score"),
            "gap_count": row.get("gap_count"),
            "generated_at": row.get("generated_at"),
            "status": row.get("status"),
            "errors": se_rich.get("errors") or row.get("errors") or [],
        },
        "keyword": {
            "missing_from_target": (ka.get("missing_from_target") or [])[:50],
            "missing_detail": ka.get("missing_detail") or [],
            "shared_detail": ka.get("shared_detail") or [],
            "unique_target": ka.get("unique_target") or [],
            "top_opportunities": ka.get("top_opportunities") or [],
            "comp_keywords_count": src_k.get("organic_keywords_count"),
            "target_keywords_count": t_ov.get("organic_keywords_count") or len(t_kws),
            "serp_derived_words": keyword_gap.get("gaps") or [],
            "errors": keyword_gap.get("errors") or [],
        },
        "traffic": {
            "target_estimated": ta.get("target_traffic"),
            "competitor_estimated": ta.get("competitor_traffic"),
            "target_keywords": ta.get("target_keywords"),
            "competitor_keywords": ta.get("competitor_keywords"),
            "traffic_value_estimate": ta.get("traffic_value_estimate"),
            "competitor_history": ta.get("competitor_history") or [],
            "target_history": ta.get("target_history") or [],
        },
        "content": {
            "missing_pages": (content_gap.get("missing") or [])[:30],
            "missing_count": content_gap.get("missing_count"),
            "competitor_pages": content_gap.get("comp_pages"),
        },
        "backlink": {
            "target": ba.get("target"),
            "competitor": ba.get("competitor"),
            "referring_domains_delta": ba.get("referring_domains_delta"),
            "backlinks_delta": ba.get("backlinks_delta"),
            "high_authority_sources": ba.get("high_authority_sources") or [],
            "comp_sources": ba.get("comp_sources") or [],
            "serp_derived_sources": (row.get("backlink_gap") or {}).get("gaps") or [],
            "error": (row.get("backlink_gap") or {}).get("errors") or [],
        },
        "authority": {
            "target_domain_rank": aa.get("target_domain_rank"),
            "comp_domain_rank": aa.get("comp_domain_rank"),
            "target_page_rank": aa.get("target_page_rank"),
            "comp_page_rank": aa.get("comp_page_rank"),
            "delta": aa.get("delta"),
        },
        "technical": technical_gap,
        "serp": {
            "features": serp_feat.get("comp_only"),
            "errors": serp_feat.get("errors") or [],
        },
        "on_page": onpage_gap,
        "ux": ux_gap,
        "schema": schema_gap,
        "insights": {
            "recommendations": se_rich.get("recommendations") or [],
            "opportunity_score": se_rich.get("opportunity_score"),
        },
        "source_report": {
            "target": row.get("competitor"),
            "generated_at": row.get("generated_at"),
        },
    }
    return sections


async def _content_gap(comp_pages: list[dict], target: dict) -> dict:
    comp_headings = [{"url": p.get("url", ""), "title": p.get("title", ""), "h1": p.get("h1_count", 0)} for p in comp_pages]
    target_titles = [t for t in target["titles"].values() if t]
    missing = []
    for h in comp_headings:
        title = h.get("title") or ""
        if not title:
            continue
        if not target_titles:
            missing.append({"url": h["url"], "title": title, "reason": "target has no page titles to compare"})
            continue
        title_tokens = _token_set(title)
        if max(_jaccard(title_tokens, _token_set(tt)) for tt in target_titles) < 0.2:
            missing.append({"url": h["url"], "title": title, "reason": "no similar page on target"})
    return {
        "missing": missing[:30],
        "missing_count": len(missing),
        "comp_pages": len(comp_pages),
    }


async def _technical_gap(comp_health: dict, comp_pages: list[dict], target: dict) -> dict:
    t_health = target["health"] or {}
    t_metrics = t_health.get("metrics") or {}
    c_metrics = comp_health.get("metrics") or {}

    def delta(a, b):
        if a is None and b is None:
            return None
        if a is None:
            return "n/a"
        if b is None:
            return "n/a"
        return round(b - a, 1)

    t_broken = t_metrics.get("broken_link_rate")
    c_broken = c_metrics.get("broken_link_rate")
    t_redirects = sum(1 for p in target["pages"] if (p.get("redirect_count") or 0) >= 3)
    c_redirects = sum(1 for p in comp_pages if (p.get("redirect_count") or 0) >= 3)
    t_https = _rate(sum(1 for p in target["pages"] if p.get("https_entry")), len(target["pages"]))
    c_https = _rate(sum(1 for p in comp_pages if p.get("https_entry")), len(comp_pages))
    return {
        "broken_link_rate": {"target": t_broken, "competitor": c_broken, "delta": delta(t_broken, c_broken)},
        "redirected_pages": {"target": t_redirects, "competitor": c_redirects, "delta": c_redirects - t_redirects},
        "https_pages_pct": {"target": t_https, "competitor": c_https, "delta": delta(t_https, c_https)},
        "avg_click_depth": {"target": _avg([p.get("click_depth", 0) for p in target["pages"]]), "competitor": _avg([p.get("click_depth", 0) for p in comp_pages])},
    }


def _avg(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


async def _schema_gap(comp_sd: dict | None, target: dict) -> dict:
    comp_types = set()
    for t, _count in (comp_sd or {}).get("type_counts", {}).items():
        comp_types.add(t.split(" ")[0])
    missing = sorted(comp_types - target["sd_types"])[:20]
    return {
        "competitor_types": sorted(comp_types),
        "target_types": sorted(target["sd_types"]),
        "missing_from_target": missing,
    }


async def _onpage_gap(comp_health: dict, comp_pages: list[dict], target: dict) -> dict:
    t_metrics = (target["health"] or {}).get("metrics") or {}
    c_metrics = comp_health.get("metrics") or {}

    def delta(a, b):
        if a is None or b is None:
            return None
        return round(b - a, 1)

    keys = [
        ("meta_description_coverage", "meta_coverage_pct"),
        ("h1_coverage", "h1_coverage_pct"),
        ("alt_text_coverage", "alt_text_pct"),
    ]
    out = {}
    for src, name in keys:
        tv = t_metrics.get(src)
        cv = c_metrics.get(src)
        out[name] = {"target": tv, "competitor": cv, "delta": delta(tv, cv)}
    out["avg_word_count"] = {
        "target": _avg(target["word_counts"]),
        "competitor": _avg([p.get("word_count") or 0 for p in comp_pages]),
    }
    return out


async def _ux_gap(comp_health: dict, comp_pages: list[dict], target: dict) -> dict:
    t_metrics = (target["health"] or {}).get("metrics") or {}
    c_metrics = comp_health.get("metrics") or {}

    def delta(a, b):
        if a is None or b is None:
            return None
        return round(b - a, 1)

    t_cwv = t_metrics.get("avg_cwv_score")
    c_cwv = c_metrics.get("avg_cwv_score")
    t_mf = _rate(target["mobile_friendly"], len(target["pages"]))
    c_mf = _rate(sum(1 for p in comp_pages if p.get("mobile_friendly", True)), len(comp_pages))
    return {
        "avg_cwv_score": {"target": t_cwv, "competitor": c_cwv, "delta": delta(t_cwv, c_cwv)},
        "mobile_friendly_pct": {"target": t_mf, "competitor": c_mf, "delta": delta(t_mf, c_mf)},
    }


async def _analyze_one(target_job_id: str, target_url: str, competitor: str) -> dict:
    db = get_db()
    comp_url = competitor if "//" in competitor else "https://" + competitor
    comp_domain = _domain(comp_url)
    comp_job = await _create_competitor_job(target_job_id, comp_url)

    async def _mark_error(message: str):
        await db.competitor_gap_analyses.update_one(
            {"target_job_id": target_job_id, "competitor": comp_domain},
            {"$set": {"status": "error", "errors": [message], "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    async def run():
        try:
            await db.competitor_gap_analyses.update_one(
                {"target_job_id": target_job_id, "competitor": comp_domain},
                {"$set": {"status": "running", "updated_at": datetime.utcnow()}},
                upsert=True,
            )
            await db.analysis_jobs.update_one({"_id": comp_job}, {"$set": {"status": "running", "progress_message": "Crawling competitor..."}})
            crawl = await _crawl_competitor(comp_job, comp_url)
            pages = await db.pages.find({"job_id": comp_job}, {"html": 0, "html_mobile": 0}).to_list(length=None)
            if not pages:
                raise Exception("Competitor crawl returned no pages")

            await db.competitor_gap_analyses.update_one(
                {"target_job_id": target_job_id, "competitor": comp_domain},
                {"$set": {"status": "running", "pages_crawled": crawl.get("total_pages", len(pages)), "updated_at": datetime.utcnow()}},
            )
            await db.analysis_jobs.update_one({"_id": comp_job}, {"$set": {"progress_message": "Analyzing competitor pages..."}})
            from backend.services.seo_analyzer import analyze_pages
            await analyze_pages(comp_job)

            from backend.services.link_checker import check_links
            await check_links(comp_job)

            from backend.services.site_health import compute_site_health
            comp_health = await compute_site_health(comp_job)

            from backend.services.performance_service import fetch_performance
            psi_max = min(len(pages), settings.competitor_psi_sample)
            try:
                await fetch_performance(comp_job, max_pages=psi_max)
            except Exception as pe:
                logger.warning("Competitor PSI failed job=%s: %s", comp_job, pe)

            from backend.services.structured_data import audit_structured_data
            comp_sd = await audit_structured_data(comp_job)

            from backend.services.keyword_extractor import extract_keywords_from_content
            comp_kw = await extract_keywords_from_content(comp_job, top_k=MAX_KEYWORDS)

            target_baseline = await _target_baseline(target_job_id)
            target_domain = _domain(target_url)

            serp_enabled = True
            try:
                from backend.config import settings as _s
                serp_enabled = bool(_s.serp_api_key)
            except Exception:
                serp_enabled = False

            keyword_gap = {"gaps": [], "errors": ["SERP key not configured"]}
            feature_gap = {"comp_only": {}, "errors": ["SERP key not configured"]}
            backlink_gap = {"gaps": [], "errors": ["SERP key not configured"]}
            if serp_enabled:
                try:
                    t_kw = await extract_keywords_from_content(target_job_id, top_k=MAX_KEYWORDS)
                    keyword_gap = await _serp_keyword_gaps(target_domain, comp_domain, t_kw or comp_kw)
                except Exception as e:
                    keyword_gap = {"gaps": [], "errors": [str(e)]}
                try:
                    t_kw2 = await extract_keywords_from_content(target_job_id, top_k=MAX_KEYWORDS)
                    feature_gap = await _serp_features_gap(target_domain, comp_domain, t_kw2 or comp_kw)
                except Exception as e:
                    feature_gap = {"comp_only": {}, "errors": [str(e)]}
                try:
                    backlink_gap = await _backlink_gap(target_domain, comp_domain)
                except Exception as e:
                    backlink_gap = {"gaps": [], "errors": [str(e)]}

            content_gap = await _content_gap(pages, target_baseline)
            technical_gap = await _technical_gap(comp_health, pages, target_baseline)
            schema_gap = await _schema_gap(comp_sd, target_baseline)
            onpage_gap = await _onpage_gap(comp_health, pages, target_baseline)
            ux_gap = await _ux_gap(comp_health, pages, target_baseline)

            se_rich = {}
            try:
                se_rich = await _se_rich_gap(target_domain, comp_domain, target_job_id)
                se_rich["recommendations"] = _build_recommendations(se_rich)
                se_rich["opportunity_score"] = _opportunity_score(se_rich)
            except Exception as e:
                logger.warning("SE Ranking gap failed target=%s comp=%s: %s", target_job_id, comp_domain, e)
                se_rich = {"errors": [f"se_ranking: {e}"]}

            gap_count = (
                len(keyword_gap.get("gaps", []))
                + content_gap.get("missing_count", 0)
                + len(backlink_gap.get("gaps", []))
                + len(schema_gap.get("missing_from_target", []))
                + len(feature_gap.get("comp_only", {}))
            )

            result = {
                "competitor": comp_domain,
                "url": comp_url,
                "target_job_id": target_job_id,
                "status": "completed",
                "pages_crawled": crawl.get("total_pages", len(pages)),
                "gap_count": gap_count,
                "keyword_gap": keyword_gap,
                "content_gap": content_gap,
                "backlink_gap": backlink_gap,
                "technical_gap": technical_gap,
                "schema_gap": schema_gap,
                "onpage_gap": onpage_gap,
                "ux_gap": ux_gap,
                "serp_features_gap": feature_gap,
                "se_rich": se_rich,
                "errors": [],
                "generated_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
            await db.competitor_gap_analyses.update_one(
                {"target_job_id": target_job_id, "competitor": comp_domain},
                {"$set": result},
                upsert=True,
            )
            return result
        except asyncio.TimeoutError as e:
            logger.error("Competitor audit timed out target=%s comp=%s", target_job_id, competitor)
            result = {
                "competitor": comp_domain,
                "url": comp_url,
                "target_job_id": target_job_id,
                "status": "error",
                "pages_crawled": 0,
                "gap_count": 0,
                "errors": [f"Timed out (overall job limit): {e}"],
                "generated_at": datetime.utcnow(),
            }
            await _mark_error(result["errors"][0])
            return result
        except asyncio.CancelledError:
            logger.warning("Competitor audit cancelled target=%s comp=%s", target_job_id, competitor)
            await _mark_error("Audit cancelled (worker restart or timeout)")
            raise
        except Exception as e:
            logger.error("Competitor audit failed target=%s comp=%s: %s", target_job_id, competitor, e)
            await _mark_error(str(e))
            result = {
                "competitor": comp_domain,
                "url": comp_url,
                "target_job_id": target_job_id,
                "status": "error",
                "pages_crawled": 0,
                "gap_count": 0,
                "errors": [str(e)],
                "generated_at": datetime.utcnow(),
            }
            return result
        finally:
            await _delete_competitor_job(comp_job)

    return await run()


async def audit_competitors(target_job_id: str, competitors: list[str]) -> dict:
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": target_job_id})
    if not job:
        raise ValueError("Target job not found")
    target_url = job.get("url", "")

    results = []
    parallel = min(2, len(competitors))
    sema = asyncio.Semaphore(parallel)

    async def run_one(comp):
        async with sema:
            try:
                return await asyncio.wait_for(
                    _analyze_one(target_job_id, target_url, comp),
                    timeout=900,
                )
            except asyncio.TimeoutError:
                comp_domain = _domain(comp)
                err_msg = "Competitor audit timed out (15-minute limit)"
                logger.error("Competitor audit timed out target=%s comp=%s", target_job_id, comp)
                await db.competitor_gap_analyses.update_one(
                    {"target_job_id": target_job_id, "competitor": comp_domain},
                    {"$set": {"status": "error", "errors": [err_msg], "updated_at": datetime.utcnow()}},
                    upsert=True,
                )
                return {
                    "competitor": comp_domain,
                    "url": comp if "//" in comp else "https://" + comp,
                    "target_job_id": target_job_id,
                    "status": "error",
                    "pages_crawled": 0,
                    "gap_count": 0,
                    "errors": [err_msg],
                    "generated_at": datetime.utcnow(),
                }

    raw_results = await asyncio.gather(*(run_one(c) for c in competitors), return_exceptions=True)
    for entry in raw_results:
        if isinstance(entry, dict) and "competitor" in entry:
            results.append(entry)

    return {"target": target_url, "results": results, "source": "free-tools"}