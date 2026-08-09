"""Smart site-specific keyword generation.

Combines multiple signal sources into exact-match product keywords:
  1. URL slug phrases (e.g. /double-ferrule-fittings/ -> "double ferrule fittings")
  2. Title/meta bigrams from the crawl corpus
  3. Purchase-modifier suffixes (manufacturer, supplier, price, India, ...)
  4. Optional LLM polish (Groq) that dedupes and picks expert variations.
Falls back gracefully when any source fails; never raises into callers.
"""
import json
import re
from urllib.parse import urlparse

from backend.logging_setup import get_logger

logger = get_logger("keyword_engine")

MODIFIERS = [
    "manufacturer", "supplier", "manufacturer india", "supplier india",
    "india", "price", "oem", "for sale", "wholesale", "exporter",
]

SLUG_SEP_RE = re.compile(r"[-_/]+")
FILE_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|7z|mp4|mp3|mov|avi|web[mp]|jpe?g|png|gif|svg|ico|webp|txt|json|csv)$", re.I)
GREEDY_SLUGS = {
    "products", "product", "category", "categories", "shop", "store",
    "catalog", "catalogue", "index", "page", "content", "search", "404",
    "contact", "about", "blog", "news", "privacy", "terms", "cart",
    "checkout", "faq", "help", "home", "sitemap", "randd", "rnd", "uk", "usa",
    "awards", "certifications", "certificate", "certificates", "quality",
    "team", "careers", "career", "jobs", "clients", "partners", "partner",
    "distributors", "gallery", "downloads", "download", "videos", "video",
    "manual", "manuals", "tenders", "insurance", "csr", "sustainability", "china",
}
TITLE_STOP = {
    "the", "and", "for", "of", "to", "in", "on", "with", "at", "a", "an",
    "or", "home", "page", "welcome", "product", "products", "buy", "shop",
    "zui", "engine",
}
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'\-]+")


def slug_phrases(urls: list[str], max_total: int = 60) -> list[str]:
    """Humanized product phrases from URL leaf segments (max 7 words)."""
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if not u:
            continue
        try:
            path = urlparse(u).path.strip("/")
        except Exception:
            continue
        parts = [p for p in path.split("/") if p]
        if not parts:
            continue
        leaf = FILE_EXT_RE.sub("", parts[-1].lower())
        if leaf in GREEDY_SLUGS or len(leaf) < 4:
            continue
        words = [w for w in leaf.split("-") if w]
        if len(words) == 1 and "_" in leaf:
            words = [w for w in leaf.split("_") if w]
        words = [w for w in words if not re.fullmatch(r"[0-9]+", w)]
        if not words:
            continue
        if words[-1] in GREEDY_SLUGS:
            continue
        phrase = " ".join(words)
        if len(words) > 7:
            phrase = " ".join(words[-7:])
        if len(phrase.strip()) < 3:
            continue
        if len(words) == 1 and phrase in MODIFIERS:
            continue
        norm = phrase.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(phrase)
    out.sort(key=lambda p: (len(p), p))
    return out[:max_total]


def corpus_ngrams(extracts: list[str], min_freq: int = 2, max_total: int = 80) -> list[str]:
    """2-4 gram phrases recurring across page titles/meta/text."""
    counts: dict[str, int] = {}
    for text in extracts:
        if not text:
            continue
        words = [w.lower() for w in WORD_RE.findall(text) if w.lower() not in TITLE_STOP]
        for n in (2, 3, 4):
            for i in range(len(words) - n + 1):
                gram = " ".join(words[i:i + n])
                if gram and len(gram) >= 8:
                    counts[gram] = counts.get(gram, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [g for g, c in ranked if c >= min_freq][:max_total]


def apply_modifiers(phrases: list[str], modifiers: list[str] | None = None, max_total: int = 40) -> list[str]:
    """Append purchase modifiers to the strongest phrases (originals kept)."""
    mods = modifiers or MODIFIERS
    out: list[str] = []
    seen: set[str] = set()
    for p in phrases:
        p = p.strip()
        if not p:
            continue
        low = p.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(p)
        for m in mods:
            if len(out) >= max_total:
                return out
            cand = f"{p} {m}".strip()
            if cand.lower() in seen or len(cand) > 70:
                continue
            seen.add(cand.lower())
            out.append(cand)
    return out[:max_total]


def domain_from_urls(urls: list[str]) -> str:
    for u in urls:
        try:
            host = urlparse(u).netloc
            if host:
                return host
        except Exception:
            continue
    return ""


async def llm_polish(keywords: list[str], site_name: str, max_total: int = 40) -> list[str]:
    """Optional Groq polish: dedupe + produce exact-match variations. Returns [] on failure."""
    from backend.config import settings

    if not settings.groq_api_key or not keywords:
        return []
    try:
        from backend.services.groq_limiter import acquire_token_budget
        from groq import AsyncGroq

        await acquire_token_budget(est_tokens=400)
        client = AsyncGroq(api_key=settings.groq_api_key)
        prompt = (
            "You are an SEO keyword expert for the industrial fittings website. "
            "Return a JSON array of 25 exact-match SEO keywords. Base them on the given seed phrases "
            "and site name; prefere long-tail purchase phrases like "
            '"<product> manufacturer india", "<product> supplier india", "<product> price", '
            '"<product> for sale". Dedupe, lowercase, max 8 words each, only the JSON array, no other text.\n'
            f"Site: {site_name}\nSeeds:\n"
            + "\n".join(sorted(set(k.lower() for k in keywords))[:80])
        )
        completion = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": "You return only a JSON array of keyword strings."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=512,
        )
        text = (completion.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n|\n```$", "", text)
        arr = json.loads(text)
        out = [str(k).strip().lower() for k in arr if isinstance(k, str) and k.strip()]
        known = {k.lower() for k in keywords}
        out = [k for k in out if k not in known and len(k) <= 70]
        return out[:max_total]
    except Exception as e:
        logger.warning("LLM keyword polish failed: %s", e)
        return []


async def get_smart_keywords(
    job_id: str,
    max_total: int = 40,
    use_llm: bool = True,
    force_llm: bool = False,
) -> list[str]:
    """Main entry: ranked keyword list for a job (slug + ngram + SE Ranking + modifiers [+ LLM])."""
    from backend.db.mongo import get_db

    db = get_db()
    urls: list[str] = []
    texts: list[str] = []
    se_kws: list[str] = []
    try:
        pages = await db.pages.find(
            {"job_id": job_id},
            {"url": 1, "title": 1, "meta_description": 1},
        ).limit(300).to_list(length=300)
        for p in pages:
            if p.get("url"):
                urls.append(p["url"])
            t = p.get("title") or ""
            md = p.get("meta_description") or ""
            joined = f"{t} {md}".strip()
            if joined:
                texts.append(joined)
        extras = await db.content_extractions.find(
            {"job_id": job_id, "text": {"$ne": None}}, {"text": 1}
        ).limit(100).to_list(length=100)
        for e in extras:
            text = (e.get("text") or "").strip()
            if len(text) >= 200:
                texts.append(text[:2500])
    except Exception as ex:
        logger.warning("smart keyword corpus read failed: %s", ex)

    # SE Ranking organic keywords (best-effort, may be empty)
    if urls:
        try:
            from backend.services import se_ranking
            raw = await se_ranking.domain_keywords(domain_from_urls(urls), limit=30)
            se_kws = [str(k.get("keyword") or "").strip() for k in raw if k.get("keyword")]
        except Exception as ex:
            logger.warning("smart keywords se_ranking pull failed: %s", ex)

    core = slug_phrases(urls) + corpus_ngrams(texts) + se_kws
    seen: set[str] = set()
    dedup: list[str] = []
    for c in core:
        c = c.strip()
        if not c or c.lower() in seen:
            continue
        seen.add(c.lower())
        dedup.append(c)

    base = apply_modifiers(dedup[:60], max_total=max_total)
    if use_llm or force_llm:
        extra = await llm_polish(dedup[:60], domain_from_urls(urls))
        if extra:
            base = (base + extra)[:max_total]

    return base or ["industrial fittings"]