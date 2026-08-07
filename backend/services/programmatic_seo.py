"""Programmatic-SEO audit: detects template-driven page clusters (locations,
integrations, templates, personas...) and grades them against the
programmatic-seo skill's quality bar — unique value per page, thin-content
risk, competing-page duplication, hub-and-spoke internal linking, and
indexation. Fully crawl-driven; no external API calls.
"""

import re
from collections import Counter, defaultdict
from datetime import datetime
from urllib.parse import urlparse

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("programmatic_seo")

MIN_CLUSTER_PAGES = 3
THIN_WORDS = 150
MAX_REPORTED_CLUSTERS = 12
MAX_CLUSTER_SAMPLES = 6
UNIQUE_SHARE_TARGET = 0.15


def url_pattern(url: str) -> str | None:
    """Collapse a page URL into a template pattern such as '/locations/{slug}/'.

    The final path segment is treated as the per-page variable (locations,
    integrations, templates, blog leafs...), and numeric/hex segments anywhere
    are variables too. Returns None for home/root URLs and pages with fewer
    than two path segments, which cannot evidence a template cluster.
    """
    parsed = urlparse(url or "")
    path = parsed.path.strip("/")
    if not path:
        return None
    segs = [s for s in path.split("/") if s]
    if len(segs) < 2:
        return None
    norm = []
    for s in segs:
        low = re.sub(r"\.(html?|php)$", "", s.lower())
        if low.isdigit() or re.fullmatch(r"[0-9a-f]{8,}", low) or len(low) > 60:
            norm.append("{slug}")
        else:
            norm.append(low)
    parent = norm[:-1]
    if not parent:
        return None
    return "/" + "/".join(parent) + "/{slug}/"


def detect_clusters(pages: list[dict]) -> list[dict]:
    """Group pages into template clusters by shared URL pattern (>=3 pages)."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for p in pages:
        pattern = url_pattern(p.get("url", ""))
        if pattern:
            buckets[pattern].append(p)
    clusters = []
    for pattern, members in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        if len(members) < MIN_CLUSTER_PAGES:
            continue
        clusters.append({"pattern": pattern, "pages": members})
    return clusters


async def audit_programmatic_seo(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find(
        {"job_id": job_id},
        {"url": 1, "title": 1, "word_count": 1, "is_indexable": 1, "internal_links": 1},
    ).to_list(length=None)
    if not pages:
        return {"status": "error", "message": "No pages for this job"}

    dup_doc = await db.duplicate_content.find_one({"job_id": job_id})
    dup_groups = (dup_doc or {}).get("duplicate_groups") or []
    dup_urls = {u for g in dup_groups for u in (g.get("urls") or [])}
    canon_flags = (dup_doc or {}).get("canonical_flags") or []
    conflict_urls = {
        f.get("page_url")
        for f in canon_flags
        if f.get("canonical_conflicting") or f.get("canonical_cross_domain")
    }

    orphan_doc = await db.orphan_pages.find_one({"job_id": job_id})
    orphan_urls = {p.get("page_url") for p in (orphan_doc or {}).get("pages") or []}

    sitemap_doc = await db.sitemap_audits.find_one({"job_id": job_id})
    sitemap_coverage = sitemap_doc.get("crawled_coverage") if sitemap_doc else None
    if sitemap_coverage is None:
        sitemap_coverage = 100.0

    clusters = detect_clusters(pages)
    page_by_url = {p.get("url"): p for p in pages}

    cluster_rows = []
    total_pages = len(pages)
    template_pages = 0
    thin_total = 0
    dup_total = 0
    unlinked_total = 0
    title_dup_total = 0
    not_indexable = 0
    for c in clusters:
        members = c["pages"]
        n = len(members)
        template_pages += n
        thin_n = sum(1 for p in members if (p.get("word_count") or 0) < THIN_WORDS)
        dup_n = sum(1 for p in members if p["url"] in dup_urls)
        unlinked_n = sum(1 for p in members if p["url"] in orphan_urls)
        canon_n = sum(1 for p in members if p["url"] in conflict_urls)
        title_counts = Counter((p.get("title") or "").strip().lower() for p in members)
        dup_title_n = sum(1 for t, count in title_counts.items() if t and count > 1)
        not_indexable_n = sum(1 for p in members if p.get("is_indexable") is False)
        thin_total += thin_n
        dup_total += dup_n
        unlinked_total += unlinked_n
        title_dup_total += dup_title_n
        not_indexable += not_indexable_n
        cluster_rows.append({
            "pattern": c["pattern"],
            "page_count": n,
            "thin_pages": thin_n,
            "duplicate_pages": dup_n,
            "unlinked_pages": unlinked_n,
            "canonical_conflicts": canon_n,
            "duplicate_titles": dup_title_n,
            "not_indexable": not_indexable_n,
            "sample_urls": [p["url"] for p in members[:MAX_CLUSTER_SAMPLES]],
        })
    cluster_rows.sort(key=lambda r: -r["page_count"])
    cluster_rows = cluster_rows[:MAX_REPORTED_CLUSTERS]

    template_share = template_pages / total_pages if total_pages else 0
    indexable_ratio = (template_pages - not_indexable) / template_pages if template_pages else 0

    structure = round(25 * min(1.0, template_share / UNIQUE_SHARE_TARGET))
    uniqueness_ratios = []
    for c in clusters:
        n = max(len(c["pages"]), 1)
        title_counts = Counter((p.get("title") or "").strip().lower() for p in c["pages"])
        dup_titles = sum(1 for t, count in title_counts.items() if t and count > 1)
        weakness = (
            (sum(1 for p in c["pages"] if (p.get("word_count") or 0) < THIN_WORDS) / n)
            + (sum(1 for p in c["pages"] if p["url"] in dup_urls) / n)
            + (dup_titles / n)
        ) / 3
        uniqueness_ratios.append(1.0 - weakness)
    content_uniqueness = round(25 * (sum(uniqueness_ratios) / len(uniqueness_ratios))) if uniqueness_ratios else 0
    unlinked_ratio = unlinked_total / template_pages if template_pages else 0
    internal_linking = round(25 * (1.0 - unlinked_ratio))
    indexation = round(25 * min(1.0, sitemap_coverage / 100.0) * indexable_ratio)

    subscores = {
        "structure": structure,
        "content_uniqueness": content_uniqueness,
        "internal_linking": internal_linking,
        "indexation": indexation,
    }
    score = sum(subscores.values())

    checks = [
        {
            "passed": template_pages > 0,
            "label": "Template page clusters detected",
            "detail": (
                f"{len(clusters)} template pattern(s) cover {template_pages} of {total_pages} pages."
                if template_pages
                else "No URL pattern with 3+ pages found — the site is not using programmatic templates."
            ),
        },
        {
            "passed": thin_total == 0,
            "label": "No thin template pages",
            "detail": (
                f"{thin_total} template page(s) have under {THIN_WORDS} words — swapped-variable thin content risk."
                if thin_total
                else f"Every template page carries at least {THIN_WORDS} words of unique content."
            ),
        },
        {
            "passed": dup_total == 0,
            "label": "Template pages are not near-duplicates",
            "detail": (
                f"{dup_total} template page(s) are near-duplicates of other pages (unique value needed)."
                if dup_total
                else "No template page is a near-duplicate of another page."
            ),
        },
        {
            "passed": unlinked_total == 0,
            "label": "Template pages are linked (hub-and-spoke)",
            "detail": (
                f"{unlinked_total} template page(s) have no internal links pointing to them."
                if unlinked_total
                else "Every template page is reachable from other pages."
            ),
        },
        {
            "passed": sitemap_coverage >= 60,
            "label": "Template pages covered by the sitemap",
            "detail": (
                f"Sitemap covers {sitemap_coverage}% of crawled URLs."
                if sitemap_coverage is not None
                else "No sitemap data to compare against."
            ),
        },
    ]

    summary = {
        "job_id": job_id,
        "score": score,
        "subscores": subscores,
        "checks": checks,
        "clusters": cluster_rows,
        "clusters_count": len(clusters),
        "template_pages": template_pages,
        "total_pages": total_pages,
        "template_page_share": round(template_share * 100, 1),
        "thin_template_pages": thin_total,
        "duplicate_template_pages": dup_total,
        "unlinked_template_pages": unlinked_total,
        "duplicate_title_template_pages": title_dup_total,
        "not_indexable_template_pages": not_indexable,
        "sitemap_coverage": sitemap_coverage,
        "generated_at": datetime.utcnow(),
    }
    await db.programmatic_seo_audits.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info(
        "Programmatic SEO job=%s clusters=%s template_pages=%s score=%s",
        job_id, len(clusters), template_pages, score,
    )
    return summary
