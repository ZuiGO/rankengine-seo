"""AI-search visibility readiness: checks whether the site is citable by
generative engines — robots rules for AI crawlers (section-aware parsing),
structured data counted from real JSON-LD scripts, plain extractable text,
sitemap + llms.txt presence. Offline heuristics only (no paid AI-overview
monitoring API).
"""

import re
from collections import Counter
from datetime import datetime

from bs4 import BeautifulSoup

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

TRAINING_ONLY_AGENTS = {"ccbot"}
ANSWER_BLOCK_WORDS = (40, 60)
DEFINITION_BLOCK_WORDS = (30, 80)
FRESHNESS_DAYS = 183
MAX_SCAN_PAGES = 50

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


def _word_count(text: str) -> int:
    return len((text or "").split())


def _parse_date(value: str) -> datetime | None:
    v = (value or "").strip()
    if not v:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return parsed
    except ValueError:
        return None


def _uttcnow_naive() -> datetime:
    return datetime.utcnow()


def _is_fresh(value: str, now: datetime | None = None) -> bool:
    parsed = _parse_date(value)
    if parsed is None:
        return False
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    now = now or _uttcnow_naive()
    return (now - parsed).days <= FRESHNESS_DAYS


def _ai_extractability(html: str) -> dict:
    """ai-seo skill Pillar 1/2 signals from one page — extractable structure,
    authority (author + freshness), and agent-friendly semantics."""
    soup = BeautifulSoup(html or "", "lxml")
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    paragraphs = [p for p in paragraphs if p]

    answer_blocks = sum(1 for t in paragraphs if ANSWER_BLOCK_WORDS[0] <= _word_count(t) <= ANSWER_BLOCK_WORDS[1])
    first = paragraphs[0] if paragraphs else ""
    definition_first = (
        DEFINITION_BLOCK_WORDS[0] <= _word_count(first) <= DEFINITION_BLOCK_WORDS[1]
        if first
        else False
    )
    faq_headings = sum(
        1 for h in soup.find_all(["h2", "h3"]) if (h.get_text(" ", strip=True).strip().endswith("?"))
    )
    comparison_tables = len(soup.select("table"))
    stat_cited = 0
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if re.search(r"\d", text) and text.find(" ") > 0 and p.find("a"):
            stat_cited += 1
    author = bool(soup.select_one('meta[name="author"], meta[property="article:author"]'))
    fresh = False
    for sel in (
        'meta[property="article:modified_time"]',
        'meta[name="last-modified"]',
        'meta[property="article:published_time"]',
    ):
        node = soup.select_one(sel)
        if node and _is_fresh(node.attrs.get("content") or ""):
            fresh = True
            break
    if not fresh:
        for t in soup.select("time[datetime]"):
            if _is_fresh(t.attrs.get("datetime") or ""):
                fresh = True
                break
    landmarks = bool(soup.select("main, article, nav"))
    return {
        "answer_block": answer_blocks,
        "definition_first": definition_first,
        "faq_heading": faq_headings,
        "comparison_table": comparison_tables,
        "stat_cited": stat_cited,
        "author": author,
        "fresh": fresh,
        "semantic_landmark": landmarks,
    }


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
    blocked_training_agents = [
        r["agent"] for r in agent_rows if r["agent"] in TRAINING_ONLY_AGENTS and r["status"] == "blocked"
    ]

    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1}).to_list(length=None)
    with_structured = 0
    extractable_plain = 0
    schema_counter: Counter[str] = Counter()
    ai_ext = Counter()
    scanned = 0
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
        if scanned < MAX_SCAN_PAGES:
            ex = _ai_extractability(html)
            for key, val in ex.items():
                if val is True:
                    ai_ext[key + "_pages"] += 1
                elif isinstance(val, int) and val > 0:
                    ai_ext[key + "_pages"] += 1
            scanned += 1

    llms_txt, llms_status = await _fetch_plain("https://" + domain + "/llms.txt", "ZuiGO-Engine/1.0 ai-visibility")
    pricing_md, pricing_md_status = await _fetch_plain("https://" + domain + "/pricing.md", "ZuiGO-Engine/1.0 ai-visibility")
    pricing_txt, pricing_txt_status = await _fetch_plain("https://" + domain + "/pricing.txt", "ZuiGO-Engine/1.0 ai-visibility")
    okf_html, okf_status = await _fetch_plain("https://" + domain + "/okf/", "ZuiGO-Engine/1.0 ai-visibility")
    okf_present = okf_html is not None and len(okf_html.strip()) > 0

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

    scanned_ratio = scanned / total if scanned else 0
    pricing_ratio = (ai_ext["author_pages"] / scanned) if scanned else 0
    fresh_ratio = (ai_ext["fresh_pages"] / scanned) if scanned else 0
    answer_ratio = (ai_ext["answer_blocks_pages"] / scanned) if scanned else 0

    checks.extend([
        {
            "passed": pricing_md is not None or pricing_txt is not None,
            "label": "Machine-readable pricing for AI agents",
            "detail": (
                "pricing.md is published for AI agents to parse."
                if pricing_md is not None
                else ("pricing.txt is published for AI agents to parse."
                      if pricing_txt is not None
                      else "Add a /pricing.md (or /pricing.txt) file so buying agents can compare your plans.")
            ),
        },
        {
            "passed": answer_ratio >= 0.3,
            "label": "Answer blocks (40-60 word passages) on content pages",
            "detail": (
                f"{ai_ext['answer_blocks_pages']} of {scanned} scanned pages contain self-contained answer blocks."
                if scanned
                else "No content pages scanned."
            ),
        },
        {
            "passed": pricing_ratio >= 0.3,
            "label": "Author attribution on content pages",
            "detail": (
                f"{ai_ext['author_pages']} of {scanned} scanned pages name an author."
                if scanned
                else "No content pages scanned."
            ),
        },
        {
            "passed": fresh_ratio >= 0.3,
            "label": "Freshness signals (last-updated within 6 months)",
            "detail": (
                f"{ai_ext['fresh_pages']} of {scanned} scanned pages show a recent update date."
                if scanned
                else "No content pages scanned."
            ),
        },
    ])
    if blocked_training_agents:
        checks.append({
            "passed": False,
            "label": "robots.txt blocks training-only crawlers",
            "detail": (
                f"robots.txt blocks training-only crawler(s): {', '.join(blocked_training_agents)}. "
                "This is a defensible business choice (blocks training, allows citation) — "
                "verify search-and-cite bots (GPTBot, PerplexityBot, ClaudeBot) stay allowed."
            ),
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
        "blocked_training_agents": blocked_training_agents,
        "ai_agents_scanned": AI_AGENTS,
        "llms_txt_present": llms_txt is not None,
        "llms_txt_status": llms_status,
        "pricing_md_present": pricing_md is not None,
        "pricing_md_status": pricing_md_status,
        "pricing_txt_present": pricing_txt is not None,
        "pricing_txt_status": pricing_txt_status,
        "okf_present": okf_present,
        "okf_status": okf_status,
        "structured_data_pages": with_structured,
        "extractable_pages": extractable_plain,
        "scanned_pages": scanned,
        "answer_block_pages": ai_ext["answer_block_pages"],
        "definition_first_pages": ai_ext["definition_first_pages"],
        "faq_heading_pages": ai_ext["faq_headings_pages"],
        "comparison_table_pages": ai_ext["comparison_tables_pages"],
        "stat_cited_pages": ai_ext["stat_cited_pages"],
        "author_pages": ai_ext["author_pages"],
        "fresh_pages": ai_ext["fresh_pages"],
        "semantic_landmark_pages": ai_ext["landmarks_pages"],
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