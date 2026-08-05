"""AI-search visibility readiness: checks whether the site is citable by
generative engines — robots rules for AI crawlers, structured data, plain
extractable text, sitemap + llms.txt presence. Offline heuristics only
(no paid AI-overview monitoring API).
"""

from datetime import datetime

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.content_signals import compute_page_signals

logger = get_logger("ai_visibility")

AI_AGENTS = [
    "gptbot",
    "claudebot",
    "anthropic-ai",
    "perplexitybot",
    "google-extended",
    "chatgpt-user",
    "ccbot",
    "bingbot",
]


async def check_ai_visibility(job_id: str, target_url: str) -> dict:
    db = get_db()
    robots_txt = None
    try:
        import httpx
        parsed = target_url.split("//")[-1].split("/")[0]
        origin = "https://" + parsed
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(origin + "/robots.txt", headers={"User-Agent": "ZuiGO.ai/1.0 ai-visibility"})
        if resp.status_code == 200:
            robots_txt = resp.text
    except Exception as e:
        logger.warning("AI visibility robots fetch failed job=%s: %s", job_id, e)

    blocked_agents = []
    allowed_agents = []
    scanned = AI_AGENTS
    if robots_txt:
        for agent in AI_AGENTS:
            pat = f"user-agent: {agent}"
            if pat in robots_txt.lower():
                section = robots_txt.lower().split(pat)
                if len(section) > 1:
                    rest = section[1].split("user-agent:")[0]
                    if "disallow: /" in rest or "disallow:/" in rest:
                        blocked_agents.append(agent)
                    else:
                        allowed_agents.append(agent)

    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1}).to_list(length=None)
    with_structured = 0
    extractable_plain = 0
    for p in pages:
        html = p.get("html") or ""
        if not html:
            continue
        if '"@type"' in html or "@type" in html:
            with_structured += 1
        signals = compute_page_signals(html)
        if signals.get("extractable_format"):
            extractable_plain += 1

    llms_txt = None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get("https://" + target_url.split("//")[-1].split("/")[0] + "/llms.txt")
        if resp.status_code == 200:
            llms_txt = resp.text[:2000]
    except Exception:
        llms_txt = None

    total = max(len(pages), 1)
    sitemap_doc = await db.sitemap_audits.find_one({"job_id": job_id})
    sitemap_ok = bool(sitemap_doc and sitemap_doc.get("sitemap_valid"))

    score = 0
    checks = []
    if sitemap_ok:
        score += 25
    else:
        checks.append("Add a valid XML sitemap so AI crawlers discover all pages")
    if llms_txt:
        score += 25
    else:
        checks.append("Add an llms.txt file listing pages for LLM consumers")
    if with_structured / total >= 0.5:
        score += 25
    else:
        checks.append("Add structured data on most pages so AI engines can cite entities")
    if extractable_plain / total >= 0.5:
        score += 25
    else:
        checks.append("Add FAQ/table/list content so answers are extractable verbatim")
    if blocked_agents:
        checks.append(f"robots.txt blocks AI crawlers: {', '.join(blocked_agents[:4])}")

    summary = {
        "job_id": job_id,
        "url": target_url,
        "score": score,
        "robots_txt_found": robots_txt is not None,
        "blocked_ai_agents": blocked_agents,
        "allowed_ai_agents": allowed_agents,
        "ai_agents_scanned": scanned,
        "llms_txt_present": llms_txt is not None,
        "structured_data_pages": with_structured,
        "extractable_pages": extractable_plain,
        "total_pages": len(pages),
        "sitemap_valid": sitemap_ok,
        "checks": checks,
        "checked_at": datetime.utcnow(),
    }
    await db.ai_visibility_summaries.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("AI visibility job=%s score=%s blocked=%s", job_id, score, blocked_agents)
    return summary