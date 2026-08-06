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
    "hreflang_errors": ("medium", "Fix hreflang self-reference / reciprocity / codes"),
    "url_param_issues": ("low", "Clean faceted and pagination URL parameters"),
    "image_optimization": ("low", "Use WebP/AVIF and explicit image dimensions"),
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
    "hreflang_errors": "Hreflang / international errors",
    "url_param_issues": "Faceted URL parameters",
    "image_optimization": "Image optimization gaps",
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
    ("hreflang", "hreflang_errors"),
    ("faceted", "url_param_issues"),
    ("pagination url", "url_param_issues"),
    ("image optimization", "image_optimization"),
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


EXPLANATIONS = {
    "thin_content": "Pages with very little text give search engines few signals to match queries, so they rarely rank and bounce users who expect substance.",
    "meta_description_missing": "Without a meta description, search engines draw a random snippet from the page, and CTR from the SERP suffers.",
    "meta_description_short": "Descriptions under ~50 characters truncate awkwardly and fail to sell the click.",
    "meta_description_duplicate": "Duplicated descriptions waste the SERP real estate of multiple pages and confuse which result to click.",
    "title_length": "Titles shorter than 30 or longer than 60 characters get truncated or look incomplete in the SERP.",
    "title_duplicate": "Duplicate titles make pages compete against each other and leave Google guessing which one is canonical.",
    "h1_missing": "An H1 is the primary heading signal for the topic; without it, the page's main intent is less clear to crawlers.",
    "h1_multiple": "Multiple H1s dilute the single top-level topic signal and confuse the page hierarchy.",
    "h2_missing": "H2s break content into readable sections and surface in SERP rich results and AI answers.",
    "image_alt_missing": "Alt text is what search engines (and screen readers) use to understand images; missing alt = invisible images.",
    "image_alt_generic": "Generic alt text like 'image1' adds no descriptive value for ranking or accessibility.",
    "image_alt_filename": "Alt text that repeats the filename reads like noise and misses the chance to describe the image.",
    "image_too_large": "Oversized images inflate LCP, the biggest page-speed ranking factor, and slow every visit.",
    "no_structured_data": "Structured data is what unlocks rich results (stars, FAQs, product info); its absence caps CTR and visibility.",
    "invalid_structured_data": "Malformed structured data is ignored by Google and can generate warnings in Search Console.",
    "entity_coverage_low": "Titles and meta that miss the target keywords leave ranking-relevant entities unaddressed.",
    "pdf_no_text_layer": "Scanned PDFs without a text layer cannot be indexed or searched at all.",
    "document_no_text": "Documents with no extractable text are invisible to search engines and users searching for their content.",
    "duplicate_content": "Near-duplicate pages split link equity and rank signals across pages that should be one.",
    "canonical_conflicts": "Conflicting or missing canonicals let Google pick the wrong URL as the canonical version.",
    "orphan_pages": "Pages no other page links to are nearly impossible for crawlers to find and rank.",
    "off_topic_pages": "Pages off the core topic dilute topical authority and drag down relevance for everything else.",
    "broken_links": "Broken links waste crawl budget, leak link equity, and signal a poorly maintained site to Google and users.",
    "noindex_accidents": "An accidental noindex removes the page from the index entirely - a silent traffic loss.",
    "poor_core_web_vitals": "Core Web Vitals are a ranking factor; slow LCP/INP/CLS also measurably reduce engagement and conversions.",
    "eaat_signals_missing": "Missing author, About, and trust signals hurt E-E-A-T, which is decisive in YMYL and competitive niches.",
    "no_extractable_format": "FAQ/list/table formatting is what feeds featured snippets, AI answers, and People Also Ask boxes.",
    "cannibalization": "Multiple pages targeting the same keyword split rankings so none of them wins.",
    "anchor_overoptimized": "Uniform keyword anchors look like link schemes and reduce the diversity of ranking signals.",
    "https_redirect_entries": "HTTP or non-canonical host entries that don't redirect waste crawl budget and split signals.",
    "redirect_chains": "3+ hop redirect chains add latency, waste crawl budget, and lose a little link equity per hop.",
    "mobile_not_friendly": "A broken mobile viewport pushes mobile users out and fails Google's mobile-first evaluation.",
    "sitemap_issues": "A broken or missing sitemap means pages get discovered slower and can be excluded from the index.",
    "click_depth": "Pages 4+ clicks from home are crawled and crawled less often and rank worse for deep queries.",
    "local_signals_missing": "Without LocalBusiness/NAP signals, local packs and map results are out of reach.",
    "toxic_links": "Toxic backlinks can trigger manual penalties; disavowing them protects the profile.",
    "ai_visibility_low": "AI search and LLM answers cite pages they can read and find; blocked or unformatted pages get no mentions.",
    "hreflang_errors": "Broken hreflang clusters make Google ignore your language annotations or index the wrong locale variant.",
    "url_param_issues": "Faceted and pagination parameters create near-duplicate URLs that split signals and burn crawl budget.",
    "image_optimization": "Legacy image formats and missing dimensions inflate page weight and LCP, hurting Core Web Vitals.",
    "pending_actions": "Open action items represent confirmed fixes that are not yet applied - each one is captured traffic risk.",
    "site_issue": "A flagged site-level issue may affect many pages at once and should be investigated first.",
}

HOW_TO_FIX = {
    "thin_content": ["Identify pages under 200 words", "Expand each to 300+ words of useful, unique content", "Add a keyword-relevant H2 structure and internal links"],
    "meta_description_missing": ["List pages without descriptions", "Write a unique 50-160 char description per page with the target keyword", "Verify the snippet in the SERP"],
    "meta_description_short": ["Find descriptions under 50 chars", "Extend them to 120-160 chars with a call to action"],
    "meta_description_duplicate": ["Group pages sharing descriptions", "Rewrite each description to be unique", "Re-crawl to confirm"],
    "title_length": ["Flag titles outside 30-60 chars", "Rewrite to 50-60 chars with the primary keyword first"],
    "title_duplicate": ["Find duplicate titles", "Rewrite each to be unique and descriptive"],
    "h1_missing": ["List pages without H1", "Add exactly one descriptive H1 with the primary keyword"],
    "h1_multiple": ["List pages with 2+ H1s", "Keep one H1 and demote the rest to H2"],
    "h2_missing": ["List long pages without H2s", "Split content into keyword-relevant H2 sections"],
    "image_alt_missing": ["Find images without alt", "Add descriptive alt text including the image subject and relevant keywords"],
    "image_alt_generic": ["Find generic alt text", "Replace with a specific description of the image"],
    "image_alt_filename": ["Find filename alt text", "Rewrite as descriptive, human-readable alt"],
    "image_too_large": ["Find images over ~200KB", "Compress or convert to modern formats (WebP/AVIF)", "Add width/height attributes to prevent CLS"],
    "no_structured_data": ["Pick a schema type per page (Product, Article, FAQ, Breadcrumb...)", "Add JSON-LD markup", "Validate with the Rich Results Test"],
    "invalid_structured_data": ["Validate each schema block", "Fix errors flagged by the validator"],
    "entity_coverage_low": ["Compare titles/meta against the target keywords", "Rewrite to include primary entities near the start"],
    "pdf_no_text_layer": ["Find scanned PDFs", "Run OCR to add a text layer", "Re-upload and confirm the text is extractable"],
    "document_no_text": ["Find documents with no extractable text", "Re-save with text (not images) or provide an HTML version"],
    "duplicate_content": ["Group near-duplicate pages", "Merge them or differentiate each with unique content", "301 redirect duplicates to the winner"],
    "canonical_conflicts": ["List conflicting canonicals", "Point every variant to one canonical URL", "Keep the canonical self-referencing"],
    "orphan_pages": ["List pages with no internal links", "Add contextual internal links from related pages (home links are weakest)"],
    "off_topic_pages": ["Identify pages diverging from the core topic", "Refocus them on the site's main themes or remove/redirect them"],
    "broken_links": ["List confirmed 404/5xx links", "Restore, redirect, or remove each target", "Re-run the link check to confirm 0 broken"],
    "noindex_accidents": ["List pages marked noindex", "Remove the noindex directive where indexing is intended", "Confirm in Search Console"],
    "poor_core_web_vitals": ["Measure LCP/INP/CLS per page", "Compress images, preload LCP, lazy-load below-fold, remove layout shifts", "Re-test after each change"],
    "eaat_signals_missing": ["Add author bios, About page, and contact info", "Add publisher/author structured data", "Publish dates and update dates on content"],
    "no_extractable_format": ["Convert key answers to FAQ/list/table format", "Keep the direct answer in a standalone paragraph"],
    "cannibalization": ["Cluster pages by keyword", "Merge or differentiate each group with unique intents", "301 redirect extras"],
    "anchor_overoptimized": ["List pages with repetitive anchors", "Vary anchors with brand, URL, and natural phrases"],
    "https_redirect_entries": ["Find http/host variants", "301 them to the https canonical host"],
    "redirect_chains": ["Find 3+ hop chains", "Point the first link directly at the final URL"],
    "mobile_not_friendly": ["Check the viewport meta tag", "Add the viewport meta and disable zoom blocking", "Test in Chrome DevTools mobile mode"],
    "sitemap_issues": ["Validate the XML sitemap", "Fix broken URLs and malformed entries", "Resubmit in Search Console"],
    "click_depth": ["Find pages 4+ clicks deep", "Add contextual links from top-level pages to bring them within 3 clicks"],
    "local_signals_missing": ["Add LocalBusiness JSON-LD with NAP", "Keep name/address/phone consistent across the web"],
    "toxic_links": ["Export the backlink profile", "Identify spam/low-quality domains", "Disavow the toxic links and re-fetch"],
    "ai_visibility_low": ["Unblock AI crawlers in robots.txt", "Add llms.txt and extractable formats", "Keep content open and structured"],
    "pending_actions": ["Review open action items", "Approve the high-impact ones and apply the changes"],
    "hreflang_errors": ["Add a self-referencing hreflang entry to every localized page", "Mirror every alternate link back (reciprocity)", "Declare x-default and validate language-region codes", "Keep canonicals inside the hreflang set"],
    "url_param_issues": ["Canonicalize faceted URLs to their clean variant", "Noindex or remove unbounded filter combinations", "Keep pagination crawlable with self-referencing canonicals"],
    "image_optimization": ["Convert images to WebP/AVIF", "Add explicit width/height attributes", "Lazy-load below-the-fold images"],
    "site_issue": ["Investigate the flagged issue", "Fix the root cause", "Re-run the audit to confirm"],
}


def issue_key_from_message(message: str) -> str:
    m = (message or "").lower()
    for kw, key in ISSUE_KEY_FROM_MESSAGE:
        if kw in m:
            return key
    return "site_issue"


def annotate(issue_key: str) -> tuple[str, str]:
    effort, step = EFFORT.get(issue_key, ("medium", "Review the flagged issue"))
    return effort, step


async def _evidence_for(db, job_id: str, key: str) -> list[str]:
    """Top-5 concrete examples per issue type, pulled from the collected audit data."""
    out: list[str] = []
    try:
        if key == "broken_links":
            cursor = db.link_health.find({"job_id": job_id, "status": "broken"}).sort("length_chars", -1).limit(5)
            for r in await cursor.to_list(length=5):
                srcs = ", ".join(r.get("pages", [])[:2])
                out.append(f"{r.get('status_code') or '?'} · {r['url']}" + (f"  (linked from {srcs})" if srcs else ""))
        elif key == "redirect_chains":
            cursor = db.link_health.find({"job_id": job_id, "redirect_count": {"$gte": 3}}).sort("redirect_count", -1).limit(5)
            for r in await cursor.to_list(length=5):
                out.append(f"{r.get('redirect_count')} hops · {r['url']}")
        elif key == "poor_core_web_vitals":
            cursor = db.page_performance.find({"job_id": job_id, "strategy": "mobile", "cwv_score": {"$ne": None}}).sort("cwv_score", 1).limit(5)
            for r in await cursor.to_list(length=5):
                f, l = r.get("field") or {}, r.get("lab") or {}
                lcp = f.get("lcp") or l.get("lcp")
                inp = f.get("inp") or l.get("inp")
                bits = [f"score {r.get('cwv_score')}", r["url"]]
                if isinstance(lcp, (int, float)):
                    bits.append(f"LCP {lcp / 1000:.1f}s" if lcp > 1000 else f"LCP {lcp:.1f}s")
                if isinstance(inp, (int, float)):
                    bits.append(f"INP {inp:.0f}ms")
                out.append(" · ".join(bits))
        elif key == "thin_content":
            cursor = db.pages.find({"job_id": job_id, "word_count": {"$lt": 200}}).sort("word_count", 1).limit(5)
            for r in await cursor.to_list(length=5):
                out.append(f"{r.get('word_count') or 0} words · {r['url']}")
        elif key == "orphan_pages":
            doc = await db.orphan_pages.find_one({"job_id": job_id})
            for p in (doc or {}).get("pages", [])[:5]:
                out.append(p.get("page_url", ""))
        elif key == "image_alt_missing":
            cursor = db.pages.find({"job_id": job_id, "images_missing_alt": {"$gt": 0}}).sort("images_missing_alt", -1).limit(5)
            for r in await cursor.to_list(length=5):
                out.append(f"{r.get('images_missing_alt')} images · {r['url']}")
        elif key == "image_too_large":
            cursor = db.pages.find({"job_id": job_id, "image_count": {"$gt": 0}}).sort("image_count", -1).limit(5)
            for r in await cursor.to_list(length=5):
                out.append(f"{r.get('image_count')} images · {r['url']}")
        elif key == "meta_description_missing":
            cursor = db.pages.find({"job_id": job_id, "$or": [{"meta_description": ""}, {"meta_description": None}]}).limit(5)
            for r in await cursor.to_list(length=5):
                out.append(r["url"])
        elif key == "meta_description_duplicate":
            pipeline = [
                {"$match": {"job_id": job_id, "meta_description": {"$nin": ["", None]}}},
                {"$group": {"_id": "$meta_description", "n": {"$sum": 1}, "urls": {"$first": "$url"}}},
                {"$match": {"n": {"$gt": 1}}}, {"$sort": {"n": -1}}, {"$limit": 5},
            ]
            async for g in db.pages.aggregate(pipeline):
                out.append(f"{g['n']}× · {g['urls']}")
        elif key == "title_duplicate":
            pipeline = [
                {"$match": {"job_id": job_id, "title": {"$nin": ["", None]}}},
                {"$group": {"_id": "$title", "n": {"$sum": 1}, "urls": {"$first": "$url"}}},
                {"$match": {"n": {"$gt": 1}}}, {"$sort": {"n": -1}}, {"$limit": 5},
            ]
            async for g in db.pages.aggregate(pipeline):
                out.append(f"{g['n']}× · {g['urls']}")
        elif key == "h1_missing":
            cursor = db.pages.find({"job_id": job_id, "h1_count": 0}).limit(5)
            for r in await cursor.to_list(length=5):
                out.append(r["url"])
        elif key == "h1_multiple":
            cursor = db.pages.find({"job_id": job_id, "h1_count": {"$gt": 1}}).sort("h1_count", -1).limit(5)
            for r in await cursor.to_list(length=5):
                out.append(f"{r.get('h1_count')} H1s · {r['url']}")
        elif key == "noindex_accidents":
            cursor = db.pages.find({"job_id": job_id, "is_indexable": False}).limit(5)
            for r in await cursor.to_list(length=5):
                out.append(r["url"])
        elif key == "sitemap_issues":
            doc = await db.sitemap_audits.find_one({"job_id": job_id})
            if doc:
                out.append(f"found: {doc.get('sitemap_found')} · sitemaps: {doc.get('sitemap_count')} · uncrawled URLs: {doc.get('uncrawled_urls_count')}")
        elif key == "click_depth":
            cursor = db.pages.find({"job_id": job_id, "click_depth": {"$gte": 4}}).sort("click_depth", -1).limit(5)
            for r in await cursor.to_list(length=5):
                out.append(f"depth {r.get('click_depth')} · {r['url']}")
        elif key == "duplicate_content":
            doc = await db.duplicate_content.find_one({"job_id": job_id})
            for g in (doc or {}).get("duplicate_groups", [])[:5]:
                out.append(" ≈ ".join((g.get("urls") or [])[:3]))
    except Exception as e:
        logger.warning("Evidence resolution failed job=%s key=%s: %s", job_id, key, e)
    return out or ["No specific examples recorded yet"]


def _narrative(score, grade, direction, previous_score, top_issues: list[dict]) -> str:
    parts = []
    if score is not None:
        arrow = {"improved": "up", "declined": "down"}.get(direction)
        if previous_score is not None:
            parts.append(f"Site health is {score}/100 ({grade or 'n/a'}), {arrow or 'unchanged'} from {previous_score}.")
        else:
            parts.append(f"Site health is {score}/100 ({grade or 'n/a'}).")
    if top_issues:
        parts.append("Priorities: " + "; ".join(f"{it['title']} ({it['drive']})" for it in top_issues[:3]) + ".")
    if direction == "improved" and score is not None:
        parts.append("Keep the momentum - apply the remaining quick wins next.")
    elif direction == "declined" and score is not None:
        parts.append("The score dropped since the last audit; prioritize the top issue this week.")
    return " ".join(parts)


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

    evidence_cache: dict[str, list[str]] = {}
    for it in issues:
        key = it["issue_key"]
        if key not in evidence_cache:
            evidence_cache[key] = await _evidence_for(db, job_id, key)
        it["explanation"] = EXPLANATIONS.get(key, "This issue can drag down visibility or user experience.")
        it["how_to_fix"] = HOW_TO_FIX.get(key, ["Investigate the flagged issue", "Apply a fix", "Re-run the audit"])
        it["evidence"] = evidence_cache[key]

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
        "overview": _narrative(score, health.get("grade"), direction, previous_score, top_issues),
        "top_issues": top_issues,
        "quick_wins": quick_wins,
        "long_term": long_term,
        "all_issues": issues,
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