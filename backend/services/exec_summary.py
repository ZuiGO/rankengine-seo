"""Executive summary: an impact-ranked view of the audit.

Collates site-health issues + pending action items, annotates each with an
effort estimate and a concrete next step, splits quick wins from long-term
structural work, and compares the current health score against the previous
audit so the summary shows improvement over time.
"""

from datetime import datetime

from backend.db.mongo import get_db

IMPACT_WEIGHT = {"high": 3, "medium": 2, "low": 1}
SEVERITY_IMPACT = {"high": "high", "medium": "medium", "low": "low"}

EFFORT = {
    "thin_content": ("low", "Expand thin pages to 200+ words"),
    "meta_description_missing": ("low", "Write a meta description per page"),
    "meta_description_short": ("low", "Extend short meta descriptions to 50+ chars"),
    "meta_description_duplicate": ("low", "Rewrite duplicate meta descriptions"),
    "title_length": ("low", "Keep titles 30-60 characters"),
    "title_duplicate": ("low", "Make every page title unique"),
    "h1_missing": ("low", "Add a single H1 to each page"),
    "h1_multiple": ("low", "Consolidate multiple H1s into one"),
    "h2_missing": ("low", "Structure content with H2 headings"),
    "image_alt_missing": ("low", "Add descriptive alt text to images"),
    "image_alt_generic": ("low", "Rewrite generic alt text"),
    "image_alt_filename": ("low", "Use descriptive alt text, not filenames"),
    "image_too_large": ("low", "Compress oversized images"),
    "no_structured_data": ("medium", "Add JSON-LD structured data"),
    "invalid_structured_data": ("low", "Fix invalid structured-data markup"),
    "entity_coverage_low": ("medium", "Align titles/meta with target keywords"),
    "pdf_no_text_layer": ("medium", "Add a text layer to scanned PDFs"),
    "document_no_text": ("medium", "Make document content searchable"),
    "duplicate_content": ("medium", "Differentiate near-duplicate pages"),
    "canonical_conflicts": ("low", "Fix conflicting canonical tags"),
    "orphan_pages": ("low", "Add internal links to orphan pages"),
    "off_topic_pages": ("high", "Refocus pages that diverge from the core topic"),
    "broken_links": ("medium", "Fix or remove broken links"),
    "noindex_accidents": ("low", "Remove accidental noindex"),
    "poor_core_web_vitals": ("high", "Improve LCP/INP/CLS on slow pages"),
    "eaat_signals_missing": ("medium", "Add author/About/trust signals"),
    "no_extractable_format": ("low", "Add FAQ/list answer formatting"),
    "cannibalization": ("high", "Merge or differentiate competing pages"),
    "anchor_overoptimized": ("medium", "Diversify anchor text"),
    "https_redirect_entries": ("low", "Canonicalize to https / single host"),
    "redirect_chains": ("medium", "Flatten 3+ hop redirect chains"),
    "mobile_not_friendly": ("low", "Fix mobile viewport/zoom issues"),
    "sitemap_issues": ("medium", "Fix XML sitemap errors"),
    "click_depth": ("low", "Reduce pages beyond 3 clicks from home"),
    "local_signals_missing": ("medium", "Add LocalBusiness + NAP schema"),
    "toxic_links": ("high", "Disavow toxic backlinks"),
    "ai_visibility_low": ("medium", "Improve AI-search mention readiness"),
    "pending_actions": ("low", "Review and act on open action items"),
    "site_issue": ("medium", "Investigate the flagged site issue"),
}

TITLES = {
    "thin_content": "Thin content",
    "meta_description_missing": "Missing meta descriptions",
    "meta_description_short": "Short meta descriptions",
    "meta_description_duplicate": "Duplicate meta descriptions",
    "title_length": "Poor title lengths",
    "title_duplicate": "Duplicate titles",
    "h1_missing": "Missing H1 headings",
    "h1_multiple": "Multiple H1 headings",
    "h2_missing": "Missing H2 structure",
    "image_alt_missing": "Images missing alt text",
    "image_alt_generic": "Generic alt text",
    "image_alt_filename": "Alt text repeats filenames",
    "image_too_large": "Oversized images",
    "no_structured_data": "No structured data",
    "invalid_structured_data": "Invalid structured data",
    "entity_coverage_low": "Weak keyword/entity coverage",
    "pdf_no_text_layer": "PDFs without text layer",
    "document_no_text": "Unsearchable documents",
    "duplicate_content": "Duplicate content",
    "canonical_conflicts": "Conflicting canonicals",
    "orphan_pages": "Orphan pages",
    "off_topic_pages": "Off-topic pages",
    "broken_links": "Broken links",
    "noindex_accidents": "Accidental noindex",
    "poor_core_web_vitals": "Core Web Vitals",
    "eaat_signals_missing": "Missing E-E-A-T signals",
    "no_extractable_format": "No answer-formatting content",
    "cannibalization": "Keyword cannibalization",
    "anchor_overoptimized": "Over-optimized anchors",
    "https_redirect_entries": "HTTPS/host redirect entries",
    "redirect_chains": "Redirect chains",
    "mobile_not_friendly": "Mobile-friendliness issues",
    "sitemap_issues": "Sitemap errors",
    "click_depth": "Deep click depth",
    "local_signals_missing": "Missing local signals",
    "toxic_links": "Toxic backlinks",
    "ai_visibility_low": "Low AI-search visibility",
    "pending_actions": "Unresolved actions",
    "site_issue": "Site issue",
}

ISSUE_KEY_FROM_MESSAGE = [
    ("broken", "broken_links"),
    ("redirect chain", "redirect_chains"),
    ("https", "https_redirect_entries"),
    ("cannibal", "cannibalization"),
    ("anchor", "anchor_overoptimized"),
    ("sitemap", "sitemap_issues"),
    ("click depth", "click_depth"),
    ("mobile", "mobile_not_friendly"),
    ("local", "local_signals_missing"),
    ("ai", "ai_visibility_low"),
    ("e-e-a-t", "eaat_signals_missing"),
    ("extractable", "no_extractable_format"),
    ("alt text", "image_alt_missing"),
    ("meta description", "meta_description_missing"),
    ("h1 heading", "h1_missing"),
    ("h2", "h2_missing"),
    ("thin content", "thin_content"),
    ("noindex", "noindex_accidents"),
    ("core web vitals", "poor_core_web_vitals"),
    ("duplicate", "duplicate_content"),
    ("canonical", "canonical_conflicts"),
    ("structured data", "no_structured_data"),
    ("orphan", "orphan_pages"),
    ("industry", "off_topic_pages"),
    ("action item", "pending_actions"),
]


def issue_key_from_message(message: str) -> str:
    m = (message or "").lower()
    for kw, key in ISSUE_KEY_FROM_MESSAGE:
        if kw in m:
            return key
    return "site_issue"


def annotate(issue_key: str) -> tuple[str, str]:
    effort, step = EFFORT.get(issue_key, ("medium", "Review the flagged issue"))
    return effort, step


async def compute_exec_summary(job_id: str) -> dict | None:
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id}, {"url": 1})
    if not job:
        return None

    health = await db.site_health.find_one({"job_id": job_id})
    if not health:
        health = {"score": None, "grade": None, "issues": [], "metrics": {}}

    issues: list[dict] = []

    cursor = db.action_items.aggregate([
        {"$match": {"job_id": job_id, "status": "pending"}},
        {"$group": {
            "_id": "$issue_key",
            "n": {"$sum": 1},
            "impacts": {"$addToSet": "$impact_on_ranking"},
        }},
    ])
    health_message_keys = {issue_key_from_message(i.get("message", "")) for i in health.get("issues", [])}
    async for row in cursor:
        key = row["_id"] or "site_issue"
        n = row.get("n", 0)
        impacts = row.get("impacts") or []
        impact = "high" if "high" in impacts else "medium" if "medium" in impacts else "low"
        effort, step = annotate(key)
        issues.append({
            "type": "actions",
            "issue_key": key,
            "title": TITLES.get(key, key),
            "impact": impact,
            "effort": effort,
            "drive": f"{n} action{'s' if n != 1 else ''}",
            "next_step": step,
            "weight": IMPACT_WEIGHT[impact] * (1 + min(n / 3.0, 2.0)),
        })
        health_message_keys.discard(key)

    if health_message_keys or not health.get("issues"):
        for issue in health.get("issues", []):
            key = issue_key_from_message(issue.get("message", ""))
            impact = SEVERITY_IMPACT.get(issue.get("severity", "medium"), "medium")
            effort, step = annotate(key)
            issues.append({
                "type": "health",
                "issue_key": key,
                "title": TITLES.get(key, issue.get("message", "Site issue")),
                "impact": impact,
                "effort": effort,
                "drive": issue.get("message", ""),
                "next_step": step,
                "weight": IMPACT_WEIGHT[impact] * 1.1,
            })

    issues.sort(key=lambda i: (-i["weight"], -IMPACT_WEIGHT[i["impact"]]))
    top_issues = issues[:5]

    quick_wins = [i for i in issues if i["effort"] == "low" and IMPACT_WEIGHT[i["impact"]] >= 2][:5]
    long_term = [i for i in issues if i["effort"] == "high"][:5]

    cursor2 = db.site_health.find({"job_id": job_id}).sort("generated_at", -1).limit(2)
    history = await cursor2.to_list(length=2)
    previous_score = history[1].get("score") if len(history) > 1 else None
    score = health.get("score")
    direction = "stable"
    if score is not None and previous_score is not None:
        if score > previous_score:
            direction = "improved"
        elif score < previous_score:
            direction = "declined"

    summary = {
        "job_id": job_id,
        "url": job.get("url"),
        "score": score,
        "grade": health.get("grade"),
        "previous_score": previous_score,
        "direction": direction,
        "top_issues": top_issues,
        "quick_wins": quick_wins,
        "long_term": long_term,
        "generated_at": datetime.utcnow(),
    }
    await db.exec_summaries.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    return summary


async def get_exec_summary(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.exec_summaries.find_one({"job_id": job_id})
    if not doc:
        return await compute_exec_summary(job_id)
    doc["id"] = str(doc.pop("_id"))
    return doc