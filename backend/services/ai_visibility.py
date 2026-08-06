"""AI-search visibility readiness: checks whether the site is citable by
generative engines — robots rules for AI crawlers (section-aware parsing),
structured data counted from real JSON-LD scripts, plain extractable text,
sitemap + llms.txt presence. Offline heuristics only (no paid AI-overview
monitoring API).
"""

import re
from collections import Counter
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

LDJSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)
ATYPE_RE = re.compile(r'["\']@type["\']\s*:\s*(\[[^\]]*\]|"[^"]*"|\'[^\']*\')')


def _extract_types(block: str) -> set[str]:
    """Pull @type values out of one JSON-LD block (handles plain + arrays)."""
    out: set[str] = set()
    for m in ATYPE_RE.finditer(block):
        val = m.group(1).strip()
        if val.startswith("["):
            for part in val.strip("[]").split(","):
                t = part.strip().strip("'\"").strip()
                if t:
                    out.add(t.lower())
        elif val[:1] in ("'", '"') and len(val) > 1:
            out.add(val.strip("'\"").strip().lower())
    return out


def _ld_types(html: str) -> set[str]:
    types: set[str] = set()
    for m in LDJSON_RE.finditer(html or ""):
        types.update(_extract_types(m.group(1)))
    return types


def _parse_robots(text: str) -> dict[str, dict]:
    """Section-aware robots.txt parse -> {agent(lower): {disallow, allow, delay}}."""
    rules: dict[str, dict] = {}
    current: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        low = line.lower()
        if not low or low.startswith("#"):
            continue
        if low.startswith("user-agent:"):
            current = [a.strip().lower() for a in low[len("user-agent:"):].split(",") if a.strip()]
            for a in current:
                rules.setdefault(a, {"disallow": [], "allow": [], "delay": None})
        elif current:
            if low.startswith("disallow:"):
                val = low[len("disallow:"):].strip()
                if val:
                    for a in current:
                        rules[a]["disallow"].append(val)
            elif low.startswith("allow:"):
                val = line[len("allow:"):].strip()
                if val:
                    for a in current:
                        rules[a]["allow"].append(val)
            elif low.startswith("crawl-delay:"):
                try:
                    dv = float(low[len("crawl-delay:"):].strip())
                except ValueError:
                    dv = None
                if dv:
                    for a in current:
                        rules[a]["delay"] = dv
    return rules


def _agent_status(disallow: list[str]) -> str:
    if any(r in ("/", "/*", "/?") for r in disallow):
        return "blocked"
    if disallow:
        return "partial"
    return "allowed"


async def _fetch_plain(url: str, user_agent: str) -> tuple[str | None, int | None]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": user_agent})
        if resp.status_code == 200:
            return resp.text, resp.status_code
        return None, resp.status_code
    except Exception:
        return None, None


async def check_ai_visibility(job_id: str, target_url: str) -> dict:
    db = get_db()
    domain = target_url.split("//")[-1].split("/")[0]
    robots_txt, robots_status = await _fetch_plain("https://" + domain + "/robots.txt", "ZuiGO-Engine/1.0 ai-visibility")

    robots_rules = _parse_robots(robots_txt)
    agent_rows = []
    for agent in AI_AGENTS:
        rules = robots_rules.get(agent) or robots_rules.get("*") or {"disallow": [], "allow": [], "delay": None}
        agent_rows.append({
            "agent": agent,
            "status": _agent_status(rules["disallow"]),
            "disallow_rules": len(rules["disallow"]),
            "allow_rules": len(rules["allow"]),
            "crawl_delay": rules["delay"],
            "sample_rules": rules["disallow"][:4],
        })
    blocked_agents = [r["agent"] for r in agent_rows if r["status"] == "blocked"]
    allowed_agents = [r["agent"] for r in agent_rows if r["status"] != "blocked"]

    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1}).to_list(length=None)
    with_structured = 0
    extractable_plain = 0
    schema_counter: Counter[str] = Counter()
    for p in pages:
        html = p.get("html") or ""
        if not html:
            continue
        types = _ld_types(html)
        if types:
            with_structured += 1
            schema_counter.update(types)
        signals = compute_page_signals(html)
        if signals.get("extractable_format"):
            extractable_plain += 1

    llms_txt, llms_status = await _fetch_plain("https://" + domain + "/llms.txt", "ZuiGO-Engine/1.0 ai-visibility")

    total = max(len(pages), 1)
    sitemap_doc = await db.sitemap_audits.find_one({"job_id": job_id})
    sitemap_ok = False
    if sitemap_doc and sitemap_doc.get("sitemap_valid"):
        sitemap_ok = True
    else:
        from backend.services.sitemap import _robots_sitemap_urls, _fetch, _parse_sitemap_urls
        candidates = await _robots_sitemap_urls("https://" + domain)
        candidates.append("https://" + domain + "/sitemap.xml")
        for cand in candidates:
            text = await _fetch(cand)
            if text:
                urls = await _parse_sitemap_urls(text)
                if urls:
                    sitemap_ok = True
                    break

    struct_ratio = with_structured / total
    extract_ratio = extractable_plain / total
    subscores = {
        "sitemap": 25 if sitemap_ok else 0,
        "llms_txt": 25 if llms_txt else 0,
        "structured_data": 25 if struct_ratio >= 0.5 else 0,
        "extractable_content": 25 if extract_ratio >= 0.5 else 0,
    }
    score = sum(subscores.values())

    checks = [
        {
            "passed": sitemap_ok,
            "label": "The site exposes a valid XML sitemap",
            "detail": (
                f"Sitemap lists {(sitemap_doc or {}).get('pages_in_sitemap', 0)} URLs for AI crawlers."
                if sitemap_ok
                else "Add or repair an XML sitemap (and reference it in robots.txt) so AI crawlers index every page."
            ),
        },
        {
            "passed": llms_txt is not None,
            "label": "The site publishes an llms.txt file",
            "detail": "llms.txt lists pages for LLM consumers."
                      if llms_txt else "Add an llms.txt file at /llms.txt so LLM products can cite the pages.",
        },
        {
            "passed": struct_ratio >= 0.5,
            "label": "Structured data on at least half of crawled pages",
            "detail": f"JSON-LD containing @type found on {with_structured} of {total} crawled pages.",
        },
        {
            "passed": extract_ratio >= 0.5,
            "label": "Verbatim-extractable content (FAQ / tables / lists)",
            "detail": f"{extractable_plain} of {total} pages contain extractable structure (FAQ, tables, lists).",
        },
    ]
    if blocked_agents:
        checks.append({
            "passed": False,
            "label": "robots.txt does not block AI agents",
            "detail": f"robots.txt fully blocks: {', '.join(blocked_agents[:5])}.",
        })

    summary = {
        "job_id": job_id,
        "url": target_url,
        "score": score,
        "subscores": subscores,
        "checks": checks,
        "robots_txt_found": robots_txt is not None,
        "robots_status": robots_status,
        "ai_agents": agent_rows,
        "blocked_ai_agents": blocked_agents,
        "allowed_ai_agents": allowed_agents,
        "ai_agents_scanned": AI_AGENTS,
        "llms_txt_present": llms_txt is not None,
        "llms_txt_status": llms_status,
        "structured_data_pages": with_structured,
        "extractable_pages": extractable_plain,
        "schema_types": dict(schema_counter.most_common(10)),
        "total_pages": len(pages),
        "sitemap_valid": sitemap_ok,
        "checked_at": datetime.utcnow(),
    }
    await db.ai_visibility_summaries.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("AI visibility job=%s score=%s blocked=%s", job_id, score, blocked_agents)
    return summary