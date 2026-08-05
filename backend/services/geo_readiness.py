"""GEO (Generative Engine Optimization) readiness check.

Fetches robots.txt and checks which AI crawlers can access the site:
GPTBot, PerplexityBot, ClaudeBot, anthropic-ai, Google-Extended, CCBot, Bytespider.

Framed as "improves visibility in ChatGPT/Perplexity and other AI search",
NOT as a requirement for Google AI Overviews.
"""

import httpx

from backend.logging_setup import get_logger

logger = get_logger("geo")

AI_AGENTS = [
    ("GPTBot", "OpenAI / ChatGPT"),
    ("PerplexityBot", "Perplexity"),
    ("ClaudeBot", "Anthropic / Claude"),
    ("anthropic-ai", "Anthropic / Claude"),
    ("Google-Extended", "Google (AI features)"),
    ("CCBot", "Common Crawl / AI training"),
    ("Bytespider", "ByteDance"),
]

USER_AGENT = "ZuiGO-EngineBot/1.0 (+https://zuigo.ai)"


def _parse_robots(text: str) -> dict:
    """Parse robots.txt and return which AI agents are allowed or blocked."""
    blocked_agents = []
    allowed_agents = []
    no_rules = True
    current_agent = None
    for raw in text.splitlines():
        line = raw.strip().lower()
        if not line or line.startswith("#"):
            continue
        if line.startswith("user-agent"):
            current_agent = line.split(":", 1)[1].strip().split()[0] if ":" in line else ""
            continue
        if line.startswith("allow") or line.startswith("disallow"):
            if not current_agent:
                continue
            no_rules = False
            if line.startswith("disallow") and line.split(":", 1)[1].strip():
                blocked_agents.append(current_agent)
            else:
                allowed_agents.append(current_agent)
    blocked = [name for name, _ in AI_AGENTS if name.lower() in blocked_agents]
    allowed = [name for name, _ in AI_AGENTS if name.lower() in allowed_agents and name not in blocked]
    return {"blocked": blocked, "allowed": allowed, "no_rules": no_rules}


def check_robots_text(text: str) -> dict:
    parsed = _parse_robots(text)
    known = [name for name, _ in AI_AGENTS]
    scanned = [name for name in known if name.lower() in text.lower()]
    if parsed["blocked"]:
        score = 0
        status = "blocked"
    elif parsed["no_rules"]:
        score = 80
        status = "allowed-by-default"
    else:
        score = 100
        status = "allowed"
    return {
        "status": status,
        "score": score,
        "robots_txt_found": True,
        "blocked_ai_crawlers": parsed["blocked"],
        "allowed_ai_crawlers": parsed["allowed"],
        "ai_agents_scanned": scanned,
        "note": (
            "Improves visibility in AI search (ChatGPT, Perplexity, etc.). "
            "Not required for Google AI Overviews or AI Mode."
        ),
    }


async def check_geo_readiness(url: str, timeout: float = 15.0) -> dict:
    """Fetch robots.txt for the site and run the AI-crawler readiness check."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(origin + "/robots.txt", headers={"User-Agent": USER_AGENT})
    except Exception as e:
        logger.warning("GEO robots.txt fetch failed for %s: %s", origin, e)
        return {"status": "unknown", "score": None, "robots_txt_found": False, "error": str(e)[:200]}
    if resp.status_code >= 400:
        return {"status": "unknown", "score": None, "robots_txt_found": False, "http_status": resp.status_code}
    result = check_robots_text(resp.text)
    result["robots_txt_url"] = origin + "/robots.txt"
    return result
