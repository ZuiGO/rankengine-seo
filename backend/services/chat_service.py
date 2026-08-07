from groq import AsyncGroq

from backend.config import settings
from backend.services.vector_service import search_similar
from backend.db.mongo import get_db

# Guidance vendored from the seo-audit skill (marketing-skills, MIT licensed) and condensed
# into the assistant's standing instructions.
SEO_AUDIT_GUIDANCE = """SEO audit guidance (vendored from the seo-audit skill, marketing-skills, MIT licensed):
- Crawl checks: inspect page HTTP status, canonical tags, meta robots and X-Robots-Tag. Report
  only what the crawl observed; never invent counts.
- hreflang: every localized page needs a self-referencing hreflang entry; every alternate link
  must be mirrored back (reciprocity); declare x-default; language tags must be valid
  ISO 639-1 language codes (region part ISO 3166-1 alpha-2) — "en-uk" and "es-419" are invalid;
  canonicals must stay inside the hreflang set; a locale URL structure (/fr/, /de-de/ or gTLD
  subfolders) makes clusters crawlable. If a site has no localized URL structure, hreflang does
  not apply.
- URL parameters: faceted filters (sort, color, size) and pagination params create near-duplicate
  URLs; recommend canonicalization, noindex for unbounded combinations, and keeping canonical +
  hreflang tags crawlable. Clean paths (hyphens, no underscores or uppercase, consistent
  trailing slash, slugs under ~80 chars) help readability and indexing.
- Indexation: site: queries return an adwords-indexed estimate of how many pages Google has
  indexed; treat it as an estimate, not an exact count, and pair it with crawled totals.
- Images: WebP/AVIF over legacy formats, explicit width/height attributes prevent layout shift,
  lazy-load below-the-fold images.
- Language: be specific and honest. Cite URLs and observed values from the analysis context.
  If a metric was not measured, say so instead of guessing."""

PROGRAMMATIC_SEO_GUIDANCE = """Programmatic-SEO guidance (vendored from the programmatic-seo skill, marketing-skills, MIT licensed):
- Programmatic pages (locations, integrations, templates, personas, comparisons) rank only when each page
  provides unique value — never just swapped variables in identical content. Thin, templated duplicates
  risk scaled-content spam treatment.
- Hierarchy of defensible data: proprietary > product-derived > user-generated > licensed > public.
- Use subfolders, not subdomains, for template sections (subdomains split domain authority).
- Build hub-and-spoke internal linking: hub category pages linking to every spoke, plus cross-links
  between related spokes; every page reachable from the main site, covered by the XML sitemap.
- Watch for keyword cannibalization: multiple template pages targeting the same keyword split rankings.
- Indexation: prioritize high-volume patterns, noindex truly thin variations, separate sitemaps by page type."""

AI_SEO_GUIDANCE = """AI-search (AEO/GEO) guidance (vendored from the ai-seo skill, marketing-skills, MIT licensed):
- AI engines cite, not just rank: a well-structured page can be cited from position 2-3 of its category.
- Google's official line: no special markup or files needed for AI Overviews — optimize for people and
  core Search (E-E-A-T, original info, clean indexability) first.
- Non-Google engines (ChatGPT, Perplexity, Claude, Copilot) reward extractable structure: 40-60 word
  answer blocks, FAQ sections, comparison tables, numbered lists, statistics with sources.
- Authority signals for citation: named authors with credentials, expert quotes, recent update dates
  (within ~6 months), transparent sourcing. Never block GPTBot/PerplexityBot/ClaudeBot/Google-Extended
  if you want citation; blocking training-only CCBot is a defensible middle ground.
- Machine-readable files (/llms.txt, /pricing.md, /okf/) help AI agents and buying agents parse your
  site without rendering JavaScript; opaque pricing gets filtered out of AI-mediated purchases.
- Semantic HTML (main/article/nav, labelled controls) makes pages agent-accessible."""

SYSTEM_PROMPT = """You are an SEO analysis assistant. Answer questions about the crawled website based on the provided context.

Rules:
- Only answer based on the context provided.
- If the context doesn't contain the answer, say you don't have that information.
- Be concise and specific.
- Reference specific URLs and content types when relevant.
- When answering questions about backlinks, keyword rankings, or domain metrics, use the "External SEO Insights" section of the context.

""" + SEO_AUDIT_GUIDANCE + "\n" + PROGRAMMATIC_SEO_GUIDANCE + "\n" + AI_SEO_GUIDANCE

SECTION_PROMPTS = {
    "overview": (
        "You are discussing the site OVERVIEW: overall crawl stats, page counts, content breakdown, "
        "user flows, and external insights. Summarize numbers clearly and reference the sections."
    ),
    "pages": (
        "You are discussing the PAGES section: page inventory, page architecture/types "
        "(home, product, category, blog, etc.), titles, meta descriptions, word counts, indexability, "
        "and internal link counts per page."
    ),
    "content": (
        "You are discussing the CONTENT section: content items (images, PDFs, documents, spreadsheets, "
        "videos, audio), their types, extractions (text, tables), downloads, and where they live."
    ),
    "links": (
        "You are discussing the LINKS section: total/internal/external links, link health "
        "(broken links, redirects, timeouts), link lengths, backlink sources and referring domains."
    ),
    "actions": (
        "You are discussing the SEO ACTIONS section: action items per content type, their impact on "
        "ranking, identified issues, improvement suggestions, approval status, and before/after "
        "generated content changes."
    ),
    "insights": (
        "You are discussing the EXTERNAL SEO INSIGHTS: keyword rankings, backlink counts, domain "
        "overview metrics (organic traffic), on-page analysis, and SERP positions."
    ),
    "report": (
        "You are discussing the SEO REPORT: its structure, metrics, page type breakdown, user flows, "
        "backlink sources, content versions (before/after), and action items."
    ),
}

FULL_SITE_PROMPT = (
    "You are discussing the ENTIRE site analysis covering all sections at once: overview, pages, "
    "content items, links & backlinks, SEO actions (impact/issues/improvements/approvals), user "
    "flows, external SEO insights, site health, hreflang/international, URL hygiene, indexation, "
    "image optimization, programmatic-SEO template quality, and AI-search citation readiness. "
    "The user does not need to pick a section - answer their question "
    "using whichever parts of the context are relevant. If the answer is not in the context, "
"say so plainly."
)

GROQ_MODEL = settings.groq_model


async def _insights_context(job_id: str) -> str:
    db = get_db()
    cached = await db.seo_insights_cache.find_one({"job_id": job_id})
    if not cached:
        return ""
    data = cached.get("data", {})
    parts = []

    backlinks = data.get("backlinks") or {}
    if backlinks:
        parts.append(
            "External SEO Insights (Backlinks): "
            f"total_backlinks={backlinks.get('backlinks')}, "
            f"referring_domains={backlinks.get('referring_domains')}, "
            f"referring_ips={backlinks.get('referring_ips')}, "
            f"domain_rank={backlinks.get('rank')}, "
            f"broken_backlinks={backlinks.get('broken_backlinks')}, "
            f"broken_pages={backlinks.get('broken_pages')}"
        )

    overview = data.get("overview") or {}
    if overview:
        parts.append(
            "External SEO Insights (Domain Overview): "
            f"organic_traffic={overview.get('estimated_organic_traffic')}, "
            f"organic_keywords={overview.get('organic_keywords_count')}, "
            f"paid_keywords={overview.get('paid_keywords_count')}, "
            f"domain_rank={overview.get('domain_rank')}"
        )

    keywords = data.get("keywords") or []
    if keywords:
        top_kw = [
            f"{k.get('keyword')}(vol:{k.get('keyword_data', {}).get('keyword_info', {}).get('search_volume', 'N/A')})"
            for k in keywords[:5]
        ]
        parts.append("External SEO Insights (Top Keywords): " + ", ".join(top_kw))

    return "\n".join(parts)


async def _overview_context(job_id: str) -> str:
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return ""
    summary = job.get("summary") or {}
    page_types = {}
    cursor = db.pages.aggregate([
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$page_type", "count": {"$sum": 1}}},
    ])
    async for row in cursor:
        page_types[row["_id"]] = row["count"]

    flows = await db.user_flows.count_documents({"job_id": job_id})
    content_types = {}
    cursor = db.content_items.aggregate([
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$content_type", "count": {"$sum": 1}}},
    ])
    async for row in cursor:
        content_types[row["_id"]] = row["count"]

    parts = [
        f"URL: {job.get('url', '')}",
        f"Status: {job.get('status')}",
        f"Pages crawled: {summary.get('total_pages')}",
        f"Total links: {summary.get('total_links')} (internal: {summary.get('total_internal_links')}, external: {summary.get('total_external_links')})",
        f"Content items: {summary.get('total_content_items')}",
        f"User flows: {flows}",
        f"Backlink sources: {summary.get('total_backlinks')}",
        f"Links checked: {summary.get('links_checked')} (broken: {summary.get('broken_links')})",
        f"Page types: {page_types}",
        f"Content types: {content_types}",
    ]
    return "\n".join(parts)


async def _pages_context(job_id: str) -> str:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}).to_list(length=30)
    if not pages:
        return "No pages indexed."
    rows = [
        f"- {p.get('url', '')} | type={p.get('page_type', 'other')} | title={p.get('title', '')[:60]} | "
        f"words={p.get('word_count', 0)} | internal={p.get('internal_links', 0)} | "
        f"external={p.get('external_links', 0)} | indexable={p.get('is_indexable', True)}"
        for p in pages
    ]
    return "Pages:\n" + "\n".join(rows)


async def _links_context(job_id: str) -> str:
    db = get_db()
    parts = []
    summary = await db.link_health_summaries.find_one({"job_id": job_id})
    if summary:
        parts.append(
            "Link health: "
            f"checked={summary.get('checked')}, ok={summary.get('ok')}, broken={summary.get('broken')}, "
            f"redirects={summary.get('redirect')}, blocked={summary.get('blocked')}, "
            f"timeouts={summary.get('timeout')}, errors={summary.get('error')}"
        )
        issues = await db.link_health.find(
            {"job_id": job_id, "status": {"$in": ["broken", "timeout", "error", "blocked"]}}
        ).to_list(length=10)
        if issues:
            parts.append("Problematic links:\n" + "\n".join(
                f"- {i.get('url', '')} ({i.get('status', '')})"
                for i in issues
            ))

    backlinks = await db.backlinks.find({"job_id": job_id}).to_list(length=10)
    total_bl = await db.backlinks.count_documents({"job_id": job_id})
    domains = await db.backlinks.distinct("source_domain", {"job_id": job_id})
    if total_bl:
        parts.append(f"Backlink sources: {total_bl} from {len(domains)} referring domains")
        parts.append("Top sources:\n" + "\n".join(
            f"- {b.get('source_domain', '')} | {b.get('source_url', '')[:90]} | anchor: {b.get('anchor', '')[:50]}"
            for b in backlinks[:5]
        ))
    return "\n".join(parts) if parts else "No link data yet."


async def _actions_context(job_id: str) -> str:
    db = get_db()
    actions = await db.action_items.find({"job_id": job_id}).to_list(length=15)
    if not actions:
        return "No action items."
    rows = [
        f"- [{a.get('status', 'pending')}] {a.get('content_type', '')} "
        f"impact={a.get('impact_on_ranking', '')} | issues: {', '.join(a.get('identified_issues', [])[:2])} | "
        f"improve: {', '.join(a.get('improvement_suggestions', [])[:2])}"
        for a in actions[:10]
    ]
    versions = await db.content_versions.count_documents({"job_id": job_id, "status": "approved"})
    return f"Action items ({len(actions)} total, {versions} applied changes):\n" + "\n".join(rows)


async def _graph_context(job_id: str) -> str:
    db = get_db()
    flows = await db.user_flows.find({"job_id": job_id}).to_list(length=10)
    if not flows:
        return "No user flows recorded."
    parts = [f"User flows ({len(flows)} recorded):"]
    for f in flows[:8]:
        parts.append(
            f"- {f.get('start_type', '')} -> {f.get('intermediate_type') or '-'} -> "
            f"{f.get('target_type', '')} depth={f.get('depth', 0)} target={f.get('target_url', '')[:60]}"
        )
    return "\n".join(parts)


async def _report_context(job_id: str) -> str:
    db = get_db()
    parts = [await _overview_context(job_id)]
    parts.append(await _actions_context(job_id))
    parts.append(await _links_context(job_id))
    return "\n".join(parts)


async def _full_site_context(job_id: str) -> str:
    parts = ["=== OVERVIEW ===\n" + await _overview_context(job_id)]
    parts.append("=== PAGES ===\n" + await _pages_context(job_id))
    parts.append("=== LINKS & BACKLINKS ===\n" + await _links_context(job_id))
    parts.append("=== SEO ACTIONS ===\n" + await _actions_context(job_id))
    flows = await _graph_context(job_id)
    if flows and "No user flows" not in flows:
        parts.append("=== USER FLOWS ===\n" + flows)
    health = await _site_health_context(job_id)
    if health:
        parts.append("=== SITE HEALTH ===\n" + health)
    parts.append("=== HREFLANG / INTERNATIONAL ===\n" + await _hreflang_context(job_id))
    parts.append("=== URL HYGIENE ===\n" + await _url_hygiene_context(job_id))
    parts.append("=== INDEXATION ===\n" + await _indexation_context(job_id))
    parts.append("=== IMAGE OPTIMIZATION ===\n" + await _image_opt_context(job_id))
    parts.append("=== PROGRAMMATIC SEO ===\n" + await _programmatic_seo_context(job_id))
    parts.append("=== AI-SEARCH VISIBILITY ===\n" + await _ai_seo_context(job_id))
    return "\n".join(parts)


async def _site_health_context(job_id: str) -> str:
    db = get_db()
    doc = await db.site_health.find_one({"job_id": job_id})
    if not doc:
        return ""
    parts = [f"Grade: {doc.get('grade')} (score {doc.get('score')})"]
    checks = doc.get("checks") or {}
    for name, check in list(checks.items())[:10]:
        if isinstance(check, dict):
            parts.append(f"- {name}: {check.get('status', '')} ({check.get('score', '')})")
    return "\n".join(parts)


async def _hreflang_context(job_id):
    db = get_db()
    doc = await db.hreflang_audits.find_one({"job_id": job_id})
    if not doc:
        return "No hreflang/international audit yet."
    if doc.get("applicable") is False:
        return "International audit: not applicable — no localized URL structure detected."
    failed = [c.get("label", c) for c in (doc.get("checks") or []) if not c.get("passed")]
    parts = [
        "hreflang score: %s/100, locales: %s" % (doc.get("score"), ", ".join(doc.get("locales") or []) or "none"),
        "pages_with_hreflang=%s missing_self_ref=%s missing_xdefault=%s invalid_codes=%s "
        "one_way_pairs=%s canonical_conflicts=%s lang_param_pages=%s"
        % (doc.get("pages_with_hreflang", 0), doc.get("missing_self_ref", 0),
           doc.get("missing_xdefault", 0), doc.get("invalid_codes", 0),
           doc.get("one_way_pairs_count", 0), doc.get("canonical_conflicts_count", 0),
           doc.get("lang_param_pages", 0)),
    ]
    if doc.get("sitemap_alt_entries"):
        parts.append(
            "sitemap: %s alternate entries, codes %s, invalid_codes=%s missing_self_ref=%s"
            % (doc.get("sitemap_alt_entries"), ", ".join(doc.get("sitemap_alt_codes") or []) or "none",
               doc.get("sitemap_invalid_alt_codes", 0), doc.get("sitemap_missing_self_ref", 0)))
    if failed:
        parts.append("Failed checks: " + ", ".join(failed[:6]))
    return "hreflang/international:\n" + "\n".join(parts)


async def _url_hygiene_context(job_id: str) -> str:
    db = get_db()
    doc = await db.url_hygiene_audits.find_one({"job_id": job_id})
    if not doc:
        return "No URL hygiene audit yet."
    failed = [c.get("label", c) for c in (doc.get("checks") or []) if not c.get("passed")]
    tp_raw = doc.get("top_params") or {}
    if isinstance(tp_raw, dict):
        tp_items = list(tp_raw.items())
    elif isinstance(tp_raw, list):
        tp_items = [(p if isinstance(p, tuple) else (p, None)) for p in tp_raw]
    else:
        tp_items = []
    top = ", ".join("%s (%s)" % (k, v or "?") for k, v in tp_items[:6]) or "none"
    lines = [
        "URL hygiene score: %s/100" % (doc.get("score"),),
        "param_pages=%s facet_pages=%s lang_param_pages=%s uppercase_slugs=%s underscore_slugs=%s long_slugs=%s"
        % (doc.get("param_pages", 0), doc.get("facet_pages", 0), doc.get("lang_param_pages", 0),
           doc.get("uppercase_slugs", 0), doc.get("underscore_slugs", 0), doc.get("long_slugs", 0)),
        "top parameters: " + top,
    ]
    if failed:
        lines.append("Failed checks: " + ", ".join(failed[:6]))
    return "URL hygiene:\n" + "\n".join(lines)


async def _indexation_context(job_id: str) -> str:
    db = get_db()
    doc = await db.indexation_audits.find_one({"job_id": job_id})
    if not doc:
        return "No indexation audit yet."
    if doc.get("status") == "unmeasured":
        return "Indexation: not measured (SERP API key missing or spend exhausted)."
    sample = ", ".join(str((p.get("url") if isinstance(p, dict) else p)) for p in (doc.get("top_indexed_pages") or [])[:5]) or "empty"
    return "Indexation: approx %s of %s crawled pages indexed (site: sample)\nSample: %s" % (
        doc.get("indexed_estimate"), doc.get("crawled_pages", doc.get("crawled", "N/A")), sample)


async def _image_opt_context(job_id: str) -> str:
    db = get_db()
    doc = await db.image_optimization_audits.find_one({"job_id": job_id})
    if not doc:
        return "No image optimization audit yet."
    failed = [c.get("label", c) for c in (doc.get("checks") or []) if not c.get("passed")]
    lines = [
        "Image optimization score: %s/100" % (doc.get("score"),),
        "unique_images=%s occurrences=%s modern=%s lazy=%s dims_missing=%s" % (doc.get("total_images", doc.get("total_imgs", 0)),
                                                                               doc.get("image_occurrences", doc.get("total_images", 0)),
                                                                               doc.get("modern_images", doc.get("modern", 0)),
                                                                               doc.get("lazy_images", doc.get("lazy", 0)),
                                                                               doc.get("missing_dimensions", doc.get("dims_missing", 0))),
    ]
    if failed:
        lines.append("Failed checks: " + ", ".join(failed[:6]))
    return "Image optimization:\n" + "\n".join(lines)


async def _programmatic_seo_context(job_id: str) -> str:
    db = get_db()
    doc = await db.programmatic_seo_audits.find_one({"job_id": job_id})
    if not doc:
        return "No programmatic-SEO audit yet."
    failed = [c.get("label", c) for c in (doc.get("checks") or []) if not c.get("passed")]
    lines = [
        "Programmatic-SEO score: %s/100" % (doc.get("score"),),
        "clusters=%s template_pages=%s/%s (%s%%) thin=%s dup=%s unlinked=%s dup_titles=%s not_indexable=%s"
        % (doc.get("clusters_count", 0), doc.get("template_pages", 0), doc.get("total_pages", 0),
           doc.get("template_page_share", 0), doc.get("thin_template_pages", 0),
           doc.get("duplicate_template_pages", 0), doc.get("unlinked_template_pages", 0),
           doc.get("duplicate_title_template_pages", 0), doc.get("not_indexable_template_pages", 0)),
    ]
    for c in (doc.get("clusters") or [])[:6]:
        lines.append("  %s: %s pages (thin %s, dup %s, unlinked %s)"
                     % (c.get("pattern"), c.get("page_count"), c.get("thin_pages"),
                        c.get("duplicate_pages"), c.get("unlinked_pages")))
    if failed:
        lines.append("Failed checks: " + ", ".join(failed[:6]))
    return "Programmatic-SEO:\n" + "\n".join(lines)


async def _ai_seo_context(job_id: str) -> str:
    db = get_db()
    doc = await db.ai_visibility_summaries.find_one({"job_id": job_id})
    if not doc:
        return "No AI-search visibility audit yet."
    failed = [c.get("label", c) for c in (doc.get("checks") or []) if not c.get("passed")]
    lines = [
        "AI-search visibility score: %s/100" % (doc.get("score"),),
        "llms.txt=%s pricing.md=%s pricing.txt=%s okf=%s" % (doc.get("llms_txt_present", False),
                                                             doc.get("pricing_md_present", False),
                                                             doc.get("pricing_txt_present", False),
                                                             doc.get("okf_present", False)),
        "blocked AI agents=%s training-only blocked=%s" % (doc.get("blocked_ai_agents", []),
                                                           doc.get("blocked_training_agents", [])),
        "scanned %s pages: answer blocks on %s, author on %s, fresh on %s, FAQ headings on %s, comparison tables on %s"
        % (doc.get("scanned_pages", 0), doc.get("answer_block_pages", 0), doc.get("author_pages", 0),
           doc.get("fresh_pages", 0), doc.get("faq_heading_pages", 0), doc.get("comparison_table_pages", 0)),
    ]
    if failed:
        lines.append("Failed checks: " + ", ".join(failed[:6]))
    return "AI-search visibility:\n" + "\n".join(lines)


async def _context_for_section(job_id: str, section: str | None) -> str:
    if section is None or section == "all":
        return await _full_site_context(job_id)
    if section in ("pages",):
        return await _pages_context(job_id)
    if section in ("links",):
        return await _links_context(job_id)
    if section in ("actions",):
        return await _actions_context(job_id)
    if section in ("graph",):
        return await _graph_context(job_id)
    if section in ("report",):
        return await _report_context(job_id)
    if section in ("hreflang", "international"):
        return await _hreflang_context(job_id)
    if section in ("url-hygiene", "url_hygiene", "url"):
        return await _url_hygiene_context(job_id)
    if section in ("indexation", "indexing"):
        return await _indexation_context(job_id)
    if section in ("image-optimization", "images", "image"):
        return await _image_opt_context(job_id)
    if section in ("programmatic-seo", "programmatic", "templates", "template"):
        return await _programmatic_seo_context(job_id)
    if section in ("ai-seo", "ai-visibility", "ai_search", "ai"):
        return await _ai_seo_context(job_id)
    return await _overview_context(job_id)


async def chat_with_context(job_id: str, message: str, section: str | None = None) -> str:
    db = get_db()

    if section == "content":
        results = await search_similar(job_id, message, limit=5)
    elif section == "pages":
        results = await search_similar(job_id, message, limit=5, doc_types=["page"])
    elif section == "links":
        results = await search_similar(job_id, message, limit=5, doc_types=["backlink"])
    elif section == "actions":
        results = await search_similar(job_id, message, limit=5, doc_types=["action"])
    elif section == "graph":
        results = []
    else:
        results = await search_similar(job_id, message, limit=5)

    context_parts = []
    for r in results:
        ctx = (
            f"URL: {r.get('source_url') or r.get('url', '')}\n"
            f"Type: {r.get('doc_type')}/{r.get('content_type', '')}\n"
            f"Relevance: {r['score']:.2f}"
        )
        if r.get("impact"):
            ctx += f"\nImpact: {r['impact']}"
        if r.get("text"):
            ctx += f"\nIndexed text: {r['text'][:300]}"
        context_parts.append(ctx)

    section_context = await _context_for_section(job_id, section)
    if section_context:
        context_parts.append(f"=== {section.upper() if section else 'FULL SITE'} ===\n{section_context}")

    insights_ctx = await _insights_context(job_id)
    if insights_ctx:
        context_parts.append(f"=== External SEO Insights ===\n{insights_ctx}")

    context = "\n---\n".join(context_parts) if context_parts else "No relevant content found."
    system = SYSTEM_PROMPT + "\n\n" + (SECTION_PROMPTS.get(section, "") if section and section != "all" else FULL_SITE_PROMPT)

    if not settings.groq_api_key:
        return f"[Simulated] Found {len(results)} relevant items. Context:\n{context[:500]}..."

    from backend.services.groq_limiter import acquire_token_budget

    await acquire_token_budget(est_tokens=1024)
    client = AsyncGroq(api_key=settings.groq_api_key)
    try:
        completion = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {message}"},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
    except Exception as e:
        from backend.logging_setup import get_logger
        get_logger("chat").warning("Groq chat request failed: %s", e)
        return (
            "Error: The AI service (Groq) is currently unavailable. "
            f"Details: {e}. "
            f"\n\nMeanwhile, here is the raw analysis context that would have been used:\n{context[:1200]}"
        )
    try:
        from backend.services.spend_tracker import record_usage
        usage = getattr(completion, "usage", None)
        await record_usage("groq", job_id, "chat", tokens=(usage.total_tokens if usage else 0))
    except Exception:
        pass
    return completion.choices[0].message.content or "No reply generated."


GENERAL_SYSTEM_PROMPT = (
    "You are the ZuiGO Engine SEO assistant. Answer general questions about SEO, website "
    "analysis, Core Web Vitals, page speed, backlinks, keyword research, content strategy, "
    "programmatic-SEO at scale, AI-search (AEO/GEO) readiness, and how to use the ZuiGO Engine app. "
    "Be concise, practical, and accurate. If the question "
    "is about a specific analyzed website, ask the user to open that site in ZuiGO Engine first.\n\n"
    + SEO_AUDIT_GUIDANCE + "\n" + PROGRAMMATIC_SEO_GUIDANCE + "\n" + AI_SEO_GUIDANCE
)


async def general_chat(message: str) -> str:
    """General-purpose assistant mode used when no site/job is open."""
    if not settings.groq_api_key:
        return (
            "[Simulated] No Groq API key configured. I can still help with general SEO tips: "
            "keep titles under 60 chars, meta descriptions 140-160 chars, use descriptive alt "
            "text, and make sure every page has one H1."
        )

    from backend.services.groq_limiter import acquire_token_budget

    await acquire_token_budget(est_tokens=512)
    client = AsyncGroq(api_key=settings.groq_api_key)
    try:
        completion = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": GENERAL_SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            temperature=0.4,
            max_tokens=768,
        )
    except Exception as e:
        from backend.logging_setup import get_logger
        get_logger("chat").warning("Groq general chat request failed: %s", e)
        return f"Error: The AI service (Groq) is currently unavailable. Details: {e}"
    try:
        from backend.services.spend_tracker import record_usage
        usage = getattr(completion, "usage", None)
        await record_usage("groq", "", "chat", tokens=(usage.total_tokens if usage else 0))
    except Exception:
        pass
    return completion.choices[0].message.content or "No reply generated."
