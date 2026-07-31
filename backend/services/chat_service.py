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


async def chat_with_context(job_id: str, message: str) -> str:
    results = await search_similar(job_id, message, limit=5)

    context_parts = []
    for r in results:
        ctx = f"URL: {r['source_url']}\nType: {r['content_type']}\nPage: {r['page_url']}\nRelevance: {r['score']:.2f}"
        context_parts.append(ctx)

    context = "\n---\n".join(context_parts) if context_parts else "No relevant content found."

    insights_ctx = await _insights_context(job_id)
    if insights_ctx:
        context += f"\n\n=== External SEO Insights ===\n{insights_ctx}"

    if not settings.groq_api_key:
        return f"[Simulated] Found {len(results)} relevant items. Context:\n{context[:500]}..."

    client = AsyncGroq(api_key=settings.groq_api_key)
    completion = await client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {message}"},
        ],
        temperature=0.3,
        max_tokens=1024,
    )
    return completion.choices[0].message.content
