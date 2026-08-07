"""Fact-anchored SEO action generation.

Actions are created only when a measured fact from the crawl/extraction
indicates a real problem. Every action carries:
  - issue_key  : stable identifier for dedup + feedback learning
  - confidence : how decisive the measured fact is
  - evidence   : the fact that triggered the suggestion
  - facts      : snapshot of the relevant item/page fields
  - impact_on_ranking : computed per check (plus approval-rate learning)
"""
from datetime import datetime
from urllib.parse import urlparse

from bson.objectid import ObjectId

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("seo_analyzer")

THIN_WORDS = 200
META_MIN_CHARS = 50
ALT_MIN_CHARS = 8
IMAGE_OVERSIZED_BYTES = 200_000
DOC_OVERSIZED_BYTES = 5_000_000
PAGE_ACTION_CAP = 5
ITEM_ACTION_CAP = 10
LEARN_MIN_SAMPLES = 5
LEARN_PROMOTE_RATE = 0.7
LEARN_DEMOTE_RATE = 0.2

IMPACT_RANK = {"low": 0, "medium": 1, "high": 2}


def _filename(url: str) -> str:
    return (url or "").split("/")[-1].split("?")[0]


def _filename_stem(url: str) -> str:
    f = _filename(url)
    return f.rsplit(".", 1)[0].lower() if "." in f else f.lower()


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


_DOC_OVERSIZED = {
    "issue_key": "document_oversized",
    "impact": "medium",
    "confidence": 1.0,
    "condition": lambda d: (d.get("file_size") or 0) > DOC_OVERSIZED_BYTES,
    "issues": lambda d: [f"Document is {round((d.get('file_size') or 0) / 1048576, 1)} MB - slow downloads hurt engagement"],
    "improvements": lambda d: [
        "Split into smaller files or move to a fast CDN",
        "Add descriptive link text pointing to the document",
    ],
    "evidence": lambda d: {"file_size_bytes": d.get("file_size"), "file_size_mb": round((d.get("file_size") or 0) / 1048576, 1)},
}

_DOC_EXTRACTION_FAILED = {
    "issue_key": "document_extraction_failed",
    "impact": "medium",
    "confidence": 0.9,
    "condition": lambda e: bool(e.get("error")),
    "issues": lambda e: ["Document could not be parsed for text - content is invisible to search engines"],
    "improvements": lambda e: [
        "Re-export the document to a standard format and provide an HTML summary page"
    ],
    "evidence": lambda e: {"error": (e.get("error") or "")[:200]},
}


ITEM_CHECKS = {
    "image": [
        {
            "issue_key": "image_alt_missing",
            "impact": "high",
            "confidence": 1.0,
            "condition": lambda d: not (d.get("alt") or "").strip(),
            "issues": lambda d: ["Image has no alt text"],
            "improvements": lambda d: [
                f"Add descriptive alt text for '{_filename(d.get('source_url', ''))}' (max 125 chars, include the page's target keyword)"
            ],
            "evidence": lambda d: {"alt": d.get("alt", ""), "source_url": d.get("source_url", "")},
        },
        {
            "issue_key": "image_alt_generic",
            "impact": "medium",
            "confidence": 0.7,
            "condition": lambda d: 0 < len((d.get("alt") or "").strip()) < ALT_MIN_CHARS,
            "issues": lambda d: [f"Alt text is only {len((d.get('alt') or '').strip())} chars - too generic for image SEO"],
            "improvements": lambda d: [
                "Replace generic alt text with a specific, descriptive description of the image content"
            ],
            "evidence": lambda d: {"alt": d.get("alt", ""), "alt_chars": len((d.get("alt") or "").strip())},
        },
        {
            "issue_key": "image_alt_is_filename",
            "impact": "medium",
            "confidence": 0.85,
            "condition": lambda d: (d.get("alt") or "").strip().lower() in (
                _filename_stem(d.get("source_url", "")),
                _filename(d.get("source_url", "")).lower(),
            ),
            "issues": lambda d: ["Alt text repeats the filename instead of describing the image"],
            "improvements": lambda d: [
                "Rewrite alt text to describe what the image actually shows, not its filename"
            ],
            "evidence": lambda d: {"alt": d.get("alt", ""), "filename": _filename(d.get("source_url", ""))},
        },
        {
            "issue_key": "image_oversized",
            "impact": "medium",
            "confidence": 1.0,
            "condition": lambda d: (d.get("file_size") or 0) > IMAGE_OVERSIZED_BYTES,
            "issues": lambda d: [
                f"Image is {round((d.get('file_size') or 0) / 1024)} KB, above the ~200 KB guidance - slows LCP"
            ],
            "improvements": lambda d: [
                "Compress to WebP/AVIF and serve responsive srcset sizes",
                "Add explicit width/height attributes to prevent layout shift (CLS)",
            ],
            "evidence": lambda d: {"file_size_bytes": d.get("file_size"), "file_size_kb": round((d.get("file_size") or 0) / 1024)},
        },
    ],
    "video": [
        {
            "issue_key": "video_self_hosted",
            "impact": "high",
            "confidence": 0.9,
            "condition": lambda d: _host(d.get("source_url")) == _host(d.get("page_url")),
            "issues": lambda d: ["Video is self-hosted on the same domain, slowing page load"],
            "improvements": lambda d: [
                "Embed from YouTube/Vimeo (CDN-hosted) instead of self-hosting",
                "Add a transcript to make video content indexable",
            ],
            "evidence": lambda d: {"source_url": d.get("source_url")},
        },
    ],
    "pdf": [_DOC_OVERSIZED],
    "doc": [_DOC_OVERSIZED],
    "xlsx": [_DOC_OVERSIZED],
    "presentation": [_DOC_OVERSIZED],
}

EXTRACTION_CHECKS = {
    "pdf": [
        {
            "issue_key": "pdf_no_text_layer",
            "impact": "high",
            "confidence": 1.0,
            "condition": lambda e: not e.get("error") and not (e.get("word_count") or 0),
            "issues": lambda e: ["PDF has no selectable text - search engines cannot index it"],
            "improvements": lambda e: ["OCR the PDF to add a text layer, or convert the content to an HTML page"],
            "evidence": lambda e: {"word_count": e.get("word_count", 0), "error": e.get("error")},
        },
    ],
    "doc": [_DOC_EXTRACTION_FAILED],
    "xlsx": [_DOC_EXTRACTION_FAILED],
    "presentation": [_DOC_EXTRACTION_FAILED],
}


def run_item_checks(doc: dict) -> list[dict]:
    """Return the list of failing item checks with filled evidence/issues/improvements."""
    ctype = doc.get("content_type", "")
    out = []
    for check in ITEM_CHECKS.get(ctype, []):
        try:
            if check["condition"](doc):
                out.append(_materialize(check, doc))
        except Exception as e:
            logger.warning("Item check %s failed: %s", check["issue_key"], e)
    return out


def run_extraction_checks(extra: dict) -> list[dict]:
    ctype = extra.get("content_type", "")
    out = []
    for check in EXTRACTION_CHECKS.get(ctype, []):
        try:
            if check["condition"](extra):
                out.append(_materialize(check, extra))
        except Exception as e:
            logger.warning("Extraction check %s failed: %s", check["issue_key"], e)
    return out


def run_page_checks(page: dict, ctx: dict | None = None) -> list[dict]:
    """Page-level checks. ctx carries {meta_counts} for duplicate detection."""
    ctx = ctx or {}
    meta_counts = ctx.get("meta_counts") or {}
    checks = []
    p = page
    word_count = p.get("word_count") or 0
    meta = (p.get("meta_description") or "").strip()
    indexable = p.get("is_indexable", True)

    if indexable and word_count < THIN_WORDS:
        checks.append({
            "issue_key": "thin_content",
            "impact": "medium",
            "confidence": 0.9,
            "identified_issues": [f"Thin content: {word_count} words is below the {THIN_WORDS}-word minimum"],
            "improvement_suggestions": [
                "Expand the page to 600+ words of unique value",
                "Add supporting H2/H3 sections covering related subtopics",
            ],
            "evidence": {"word_count": word_count},
        })
    if not meta:
        checks.append({
            "issue_key": "meta_description_missing",
            "impact": "high",
            "confidence": 1.0,
            "identified_issues": ["Page has no meta description"],
            "improvement_suggestions": [
                "Write a 140-160 char meta description summarizing the page value with a call to action"
            ],
            "evidence": {"meta_description": ""},
        })
    elif len(meta) < META_MIN_CHARS:
        checks.append({
            "issue_key": "meta_description_short",
            "impact": "medium",
            "confidence": 0.9,
            "identified_issues": [f"Meta description is only {len(meta)} chars (min {META_MIN_CHARS})"],
            "improvement_suggestions": ["Expand the meta description to 140-160 characters"],
            "evidence": {"meta_description": meta, "meta_chars": len(meta)},
        })
    if meta and meta_counts.get(meta, 0) > 1:
        checks.append({
            "issue_key": "meta_description_duplicate",
            "impact": "medium",
            "confidence": 1.0,
            "identified_issues": [f"Meta description is used on {meta_counts.get(meta)} pages"],
            "improvement_suggestions": ["Write a unique meta description per page"],
            "evidence": {"meta_description": meta, "pages_using_it": meta_counts.get(meta)},
        })
    h1 = p.get("h1_count") or 0
    if h1 == 0:
        checks.append({
            "issue_key": "h1_missing",
            "impact": "high",
            "confidence": 1.0,
            "identified_issues": ["Page has no H1 heading"],
            "improvement_suggestions": ["Add a single H1 containing the page's primary keyword"],
            "evidence": {"h1_count": 0},
        })
    elif h1 > 1:
        checks.append({
            "issue_key": "h1_multiple",
            "impact": "low",
            "confidence": 1.0,
            "identified_issues": [f"Page has {h1} H1 headings - dilutes topic focus"],
            "improvement_suggestions": ["Keep exactly one H1 and demote the rest to H2"],
            "evidence": {"h1_count": h1},
        })
    if not indexable:
        checks.append({
            "issue_key": "noindex_page",
            "impact": "low",
            "confidence": 1.0,
            "identified_issues": ["Page is marked noindex"],
            "improvement_suggestions": ["Confirm this page is intentionally excluded from indexing"],
            "evidence": {"is_indexable": False},
        })
    sd = ctx.get("sd") or {}
    if indexable and sd.get(p.get("url", "")) is False:
        checks.append({
            "issue_key": "no_structured_data",
            "impact": "low",
            "confidence": 0.8,
            "identified_issues": ["Page has no structured data (schema.org) - invisible to rich results and AI answers"],
            "improvement_suggestions": [
                "Add JSON-LD structured data matching the page type (Product, Article, FAQ, etc.)",
                "Keep entity names consistent across the site so generative engines can cite them",
            ],
            "evidence": {"has_structured_data": False, "page_type": p.get("page_type", "")},
        })
    corpus = ctx.get("corpus_keywords") or []
    if corpus:
        surface = f"{p.get('title') or ''} {p.get('meta_description') or ''}".lower()
        matched = [kw for kw in corpus if kw.lower() in surface]
        if not matched:
            checks.append({
                "issue_key": "entity_coverage_low",
                "impact": "low",
                "confidence": 0.6,
                "identified_issues": ["Page title and meta description mention none of the site's core topics - hard for AI engines to cite"],
                "improvement_suggestions": [
                    "Align the title/meta with at least one of the site's core topics",
                    "Add entity-linked phrases that generative engines can quote",
                ],
                "evidence": {"corpus_keywords": corpus[:10], "matched": 0},
            })
    total_imgs = p.get("image_count") or 0
    missing = p.get("images_missing_alt") or 0
    if total_imgs > 0 and missing / total_imgs > 0.3:
        checks.append({
            "issue_key": "page_images_missing_alt",
            "impact": "medium",
            "confidence": 1.0,
            "identified_issues": [f"{missing} of {total_imgs} images on the page are missing alt text"],
            "improvement_suggestions": ["Add descriptive alt text to every image (see image-level actions)"],
            "evidence": {"images_missing_alt": missing, "image_count": total_imgs},
        })
    eaat_map = ctx.get("eaat") or {}
    eaat_sigs = eaat_map.get(p.get("url", "")) or {}
    if indexable and "eaat" in ctx and eaat_sigs.get("missing_signals") and word_count >= THIN_WORDS:
        checks.append({
            "issue_key": "eaat_signals_missing",
            "impact": "medium",
            "confidence": 0.7,
            "identified_issues": [
                f"No E-E-A-T signals detected: {', '.join(eaat_sigs.get('missing_signals')[:4])}"
            ],
            "improvement_suggestions": [
                "Add author bylines with credentials and links to author pages",
                "Add About/Contact pages and citations or sources",
                "Include a last-updated date to signal freshness",
            ],
            "evidence": {"present": eaat_sigs.get("present") or [], "missing": eaat_sigs.get("missing_signals") or []},
        })
    if indexable and "extractable" in ctx and not (ctx.get("extractable") or {}).get(p.get("url", "")) and word_count >= THIN_WORDS:
        checks.append({
            "issue_key": "no_extractable_format",
            "impact": "low",
            "confidence": 0.6,
            "identified_issues": ["No FAQ/list/table/definition formatting - hard for AI engines to quote in answers"],
            "improvement_suggestions": [
                "Add an FAQ section or bulleted lists answering direct queries",
                "Use tables and definition lists so answers can be extracted verbatim",
            ],
            "evidence": {"extractable_format": False},
        })
    return checks


def _materialize(check: dict, doc: dict) -> dict:
    out = dict(check)
    out["identified_issues"] = check["issues"](doc)
    out["improvement_suggestions"] = check["improvements"](doc)
    out["evidence"] = check["evidence"](doc)
    return out


def _weighted_impact(impact: str, learning: dict | None) -> tuple[str, bool]:
    """Apply approval-rate learning. Returns (impact, demoted)."""
    if not learning:
        return impact, False
    n = learning.get("n", 0)
    rate = learning.get("rate", 0.5)
    if n < LEARN_MIN_SAMPLES:
        return impact, False
    if rate >= LEARN_PROMOTE_RATE and IMPACT_RANK[impact] < IMPACT_RANK["high"]:
        return "high" if IMPACT_RANK[impact] == IMPACT_RANK["medium"] else "medium", False
    if rate <= LEARN_DEMOTE_RATE:
        return impact, True
    return impact, False


def _make_action(job_id: str, content_type: str, content_item_id: str, page_url: str,
                 source_url: str, check: dict, impact: str, demoted: bool,
                 rank_corr: float | None = None, already_applied: bool = False) -> dict | None:
    evidence = check.get("evidence") or {}
    if not evidence:
        logger.warning("Skipping action without evidence: job=%s issue=%s", job_id, check.get("issue_key"))
        return None
    action = {
        "job_id": job_id,
        "page_url": page_url,
        "content_item_id": content_item_id,
        "content_type": content_type,
        "source_url": source_url,
        "issue_key": check["issue_key"],
        "impact_on_ranking": impact,
        "confidence": check.get("confidence", 0.5),
        "evidence": evidence,
        "identified_issues": check.get("identified_issues") or [],
        "improvement_suggestions": check.get("improvement_suggestions") or [],
        "status": "pending",
        "created_at": datetime.utcnow(),
    }
    if demoted:
        action["learned_demoted"] = True
    if rank_corr is not None:
        action["rank_correlation"] = round(rank_corr, 1)
    if already_applied:
        action["already_applied"] = True
    return action


async def _approval_weights(db) -> dict[str, dict]:
    """issue_key -> {"n": samples, "rate": approval_rate} from the feedback collection."""
    cursor = db.action_feedback.aggregate([
        {"$group": {
            "_id": "$issue_key",
            "approved": {"$sum": {"$cond": [{"$eq": ["$status", "approved"]}, 1, 0]}},
            "n": {"$sum": 1},
        }},
    ])
    out = {}
    async for row in cursor:
        n = row.get("n", 0)
        out[row["_id"]] = {"n": n, "rate": round((row.get("approved") or 0) / n, 3) if n else 0.5}
    return out


async def _rank_correlation(db, domain: str) -> dict[str, float]:
    """content_type -> mean rank delta for pages where that type was approved."""
    acc: dict[str, list[int]] = {}
    cursor = db.keyword_tracking.find({"domain": domain, "results": {"$ne": []}})
    async for doc in cursor:
        for r in doc.get("results", []):
            delta = r.get("delta")
            if delta is None or abs(delta) < 1:
                continue
            for ctype in r.get("approved_action_types") or []:
                acc.setdefault(ctype, []).append(delta)
    return {k: sum(v) / len(v) for k, v in acc.items() if len(v) >= 2}


async def _applied_keys(db, domain: str) -> set[tuple]:
    """(page_url|source_url, issue_key) pairs already fixed in prior jobs of this domain."""
    keys = set()
    cursor = db.content_versions.find(
        {"status": "approved"},
        {"page_url": 1, "source_url": 1, "issue_key": 1, "content_type": 1, "action_id": 1},
    )
    async for v in cursor:
        page = v.get("page_url") or v.get("source_url") or ""
        if not page or domain not in page:
            continue
        if v.get("issue_key"):
            keys.add((page, v["issue_key"]))
    return keys


async def analyze_content_item(item: dict, page_url: str, job_id: str) -> list[dict]:
    """Crawl-time generation from item facts. Only failing checks become actions."""
    checks = run_item_checks(item)
    if not checks:
        return []
    db = get_db()
    actions = []
    for check in checks:
        action = _make_action(
            job_id, item.get("content_type", ""), item.get("_id", ""),
            page_url, item.get("source_url", ""), check, check["impact"], False,
        )
        if action is None:
            continue
        await db.action_items.insert_one(action)
        actions.append(action)
    return actions


async def analyze_pages(job_id: str) -> dict:
    """Post-crawl enrichment: page-level actions + extraction facts + learning + caps."""
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    domain = (job or {}).get("url", "").split("//")[-1].split("/")[0]

    pages = await db.pages.find({"job_id": job_id}, {"html_mobile": 0}).to_list(length=None)
    if not pages:
        return {"status": "error", "message": "No pages for this job"}

    meta_counts = {}
    sd_map = {}
    for p in pages:
        m = (p.get("meta_description") or "").strip()
        if m:
            meta_counts[m] = meta_counts.get(m, 0) + 1
        if p.get("html"):
            try:
                from backend.services.structured_data import validate_structured_data
                sd_map[p.get("url", "")] = validate_structured_data(
                    p.get("url", ""), p.get("html")
                ).get("has_structured_data", False)
            except Exception as sd_err:
                logger.warning("Structured data check failed page=%s: %s", p.get("url"), sd_err)
    corpus_keywords = []
    try:
        from backend.services.keyword_extractor import extract_keywords_from_content
        corpus_keywords = await extract_keywords_from_content(job_id, top_k=20)
    except Exception as k_err:
        logger.warning("Corpus keywords unavailable job=%s: %s", job_id, k_err)

    eaat_map = {}
    extractable_map = {}
    try:
        from backend.services.content_signals import compute_page_signals
        for p in pages:
            signals = compute_page_signals(p.get("html") or "")
            eaat_map[p.get("url", "")] = signals
            extractable_map[p.get("url", "")] = signals.get("extractable_format", False)
    except Exception as sig_err:
        logger.warning("Page signals unavailable job=%s: %s", job_id, sig_err)
    ctx = {
        "meta_counts": meta_counts,
        "sd": sd_map,
        "corpus_keywords": corpus_keywords,
        "eaat": eaat_map,
        "extractable": extractable_map,
    }

    weights = await _approval_weights(db)
    rank_corr = await _rank_correlation(db, domain) if domain else {}
    applied = await _applied_keys(db, domain) if domain else set()

    await db.action_items.delete_many({"job_id": job_id, "content_type": "page"})

    created = 0
    skipped_learned = 0
    page_actions: dict[str, int] = {}
    for p in pages:
        for check in run_page_checks(p, ctx):
            issue_key = check["issue_key"]
            impact, demoted = _weighted_impact(check["impact"], weights.get(issue_key))
            if demoted:
                skipped_learned += 1
                continue
            source_url = ""
            if issue_key == "noindex_page":
                source_url = p.get("url", "")
            page_action = _make_action(
                job_id, "page", "", p.get("url", ""), source_url, check, impact, demoted,
                rank_corr=rank_corr.get("page"),
                already_applied=(p.get("url", ""), issue_key) in applied,
            )
            if page_action is None:
                continue
            await db.action_items.insert_one(page_action)
            created += 1
            page_actions[p.get("url", "")] = page_actions.get(p.get("url", ""), 0) + 1

    capped_pages = 0
    for url, count in page_actions.items():
        if count > PAGE_ACTION_CAP:
            over = count - PAGE_ACTION_CAP
            cursor = db.action_items.find(
                {"job_id": job_id, "content_type": "page", "page_url": url}
            ).sort("impact_on_ranking", 1)
            victims = await cursor.to_list(length=over)
            ids = [ObjectId(v["_id"]) for v in victims if "_id" in v]
            if ids:
                await db.action_items.delete_many({"_id": {"$in": ids}})
                created -= len(ids)
                capped_pages += 1

    item_map = {}
    cursor = db.content_items.find({"job_id": job_id}, {"_id": 1, "page_url": 1, "source_url": 1, "content_type": 1})
    async for doc in cursor:
        item_map[str(doc["_id"])] = doc

    extras = await db.content_extractions.find({"job_id": job_id}).to_list(length=None)
    item_action_counts: dict[str, int] = {}
    for extra in extras:
        item = item_map.get(extra.get("content_item_id"))
        if not item:
            continue
        for check in run_extraction_checks(extra):
            issue_key = check["issue_key"]
            impact, demoted = _weighted_impact(check["impact"], weights.get(issue_key))
            if demoted:
                skipped_learned += 1
                continue
            page_url = item.get("page_url", "")
            existing = await db.action_items.find_one({
                "job_id": job_id, "content_item_id": item.get("_id"), "issue_key": issue_key,
            })
            action = _make_action(
                job_id, item.get("content_type", ""), str(item.get("_id")), page_url,
                item.get("source_url", ""), check, impact, demoted,
                rank_corr=rank_corr.get(item.get("content_type", "")),
                already_applied=(item.get("source_url", "") or page_url, issue_key) in applied,
            )
            if action is None:
                continue
            if existing:
                await db.action_items.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {k: v for k, v in action.items() if k != "_id" and k != "content_item_id"}},
                )
            else:
                await db.action_items.insert_one(action)
            created += 1
            item_action_counts[page_url] = item_action_counts.get(page_url, 0) + 1

    for url, count in item_action_counts.items():
        if count > ITEM_ACTION_CAP:
            over = count - ITEM_ACTION_CAP
            cursor = db.action_items.find(
                {"job_id": job_id, "page_url": url, "content_type": {"$ne": "page"}},
                {"_id": 1, "impact_on_ranking": 1},
            ).sort("impact_on_ranking", 1)
            victims = await cursor.to_list(length=over)
            ids = [v["_id"] for v in victims if "_id" in v]
            if ids:
                await db.action_items.delete_many({"_id": {"$in": ids}})

    result = {
        "status": "ok",
        "page_actions": created,
        "extraction_actions": len(extras),
        "skipped_learned": skipped_learned,
        "capped_pages": capped_pages,
    }
    logger.info("Action analysis job=%s %s", job_id, result)
    return result