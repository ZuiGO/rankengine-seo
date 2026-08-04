from groq import AsyncGroq

from backend.config import settings
from backend.services.vector_service import search_similar
from backend.db.mongo import get_db

SYSTEM_PROMPT = """You are an SEO analysis assistant. Answer questions about the crawled website based on the provided context.

Rules:
- Only answer based on the context provided.
- If the context doesn't contain the answer, say you don't have that information.
- Be concise and specific.
- Reference specific URLs and content types when relevant.
- When answering questions about backlinks, keyword rankings, or domain metrics, use the "External SEO Insights" section of the context."""

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
    "flows, external SEO insights, and site health. The user does not need to pick a section - "
    "answer their question using whichever parts of the context are relevant. If the answer is "
    "not in the context, say so plainly."
)

GROQ_MODEL = "llama-3.1-8b-instant"


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
    "You are the RankEngine SEO assistant. Answer general questions about SEO, website "
    "analysis, Core Web Vitals, page speed, backlinks, keyword research, content strategy, "
    "and how to use the RankEngine app. Be concise, practical, and accurate. If the question "
    "is about a specific analyzed website, ask the user to open that site in RankEngine first."
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
