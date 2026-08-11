"""Smart site-specific keyword generation.

Combines multiple signal sources into exact-match product keywords:
  1. URL slug phrases (e.g. /double-ferrule-fittings/ -> "double ferrule fittings")
  2. Title/meta ngrams from the crawl corpus, ranked by count x IDF prior
  3. Purchase-modifier suffixes (manufacturer, supplier, price, India, ...)
  4. Optional LLM polish (Groq) that dedupes and picks expert variations.
Terms are canonicalized via snowball stems so "Double Ferrule Fittings" /
"double-ferrule-fittings" / "double ferrule fitting" merge into one keyword.
Results are cached in the `job_keywords` collection once per analysis; every
consumer slices the same ranked list (no repeated SE Ranking spend).
Falls back gracefully when any source fails; never raises into callers.
"""
import json
import math
import re
from urllib.parse import urlparse

from snowballstemmer import EnglishStemmer

from backend.logging_setup import get_logger
from backend.services.keyword_extractor import STOPWORDS

logger = get_logger("keyword_engine")

MODIFIERS = [
    "manufacturer", "supplier", "manufacturer india", "supplier india", "india",
]
MODIFIER_WORDS = {w for m in MODIFIERS for w in m.split()}
MAX_MODIFIERS_PER_PHRASE = 3

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
    "overview", "services", "service", "values", "vision", "mission",
    "history", "leadership", "management", "investors", "press", "media",
    "events", "testimonials", "support",
}
TITLE_STOP = {
    "the", "and", "for", "of", "to", "in", "on", "with", "at", "a", "an",
    "or", "home", "page", "welcome", "product", "products", "buy", "shop",
    "overview", "zui", "engine",
}
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'\-]+")
CANON_WORD_RE = re.compile(r"[a-z0-9]+")
UNIT_RE = re.compile(r"\d+[a-z]{2,4}\b")
BOUNDARY_STOP = TITLE_STOP | STOPWORDS | GREEDY_SLUGS | MODIFIER_WORDS
KEYWORD_CACHE_VERSION = 4

_STEMMER = EnglishStemmer()


def canonicalize(phrase: str) -> str:
    """Stem-key for near-duplicate merging (internal identity, not display form)."""
    words = CANON_WORD_RE.findall((phrase or "").lower())
    if not words:
        return ""
    return " ".join(_STEMMER.stemWords(words))


def _core_score(weight: float, surface: str) -> float:
    """Multi-word product phrases outrank single-word cores."""
    words = CANON_WORD_RE.findall(surface or "")
    return weight * (1.8 if len(words) >= 2 else 1.0)


def _passes_intent(phrase: str) -> bool:
    """Search-intent gate: no stopword/modifier/nav boundaries, no unit tokens."""
    words = [w.lower() for w in CANON_WORD_RE.findall(phrase or "")]
    if not words or len(words) > 7:
        return False
    if words[0] in BOUNDARY_STOP or words[-1] in BOUNDARY_STOP:
        return False
    if any(UNIT_RE.fullmatch(w) for w in words):
        return False
    if all(w in GREEDY_SLUGS for w in words):
        return False
    return True


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
        canon = canonicalize(phrase)
        if not canon or canon in seen:
            continue
        seen.add(canon)
        out.append(phrase)
    out.sort(key=lambda p: (len(p), p))
    return out[:max_total]


def corpus_ngrams(extracts: list[str], min_freq: int = 2, max_total: int = 80) -> list[str]:
    """2-4 gram phrases recurring across page titles/meta/text.

    Ranked by count x sum-of-term-IDF so sitewide nav phrases ("industrial
    fittings") lose to product-specific phrases; grams with stopword/modifier
    boundaries are rejected.
    """
    counts: dict[str, int] = {}
    token_dfs: dict[str, int] = {}
    n_docs = 0
    for text in extracts:
        if not text:
            continue
        n_docs += 1
        words = [w.lower() for w in WORD_RE.findall(text) if w.lower() not in TITLE_STOP]
        for t in set(words):
            token_dfs[t] = token_dfs.get(t, 0) + 1
        for n in (2, 3, 4):
            for i in range(len(words) - n + 1):
                gram = " ".join(words[i:i + n])
                if gram and len(gram) >= 8:
                    counts[gram] = counts.get(gram, 0) + 1

    if not counts:
        return []

    def idf_prior(gram: str) -> float:
        return sum(math.log(n_docs / (1 + token_dfs.get(t, 0))) for t in gram.split())

    ranked = sorted(
        ((g, c) for g, c in counts.items() if c >= min_freq and _passes_intent(g)),
        key=lambda kv: (-(kv[1] * idf_prior(kv[0])), kv[0]),
    )
    return [g for g, _ in ranked[:max_total]]


def apply_modifiers(phrases: list[str], modifiers: list[str] | None = None, max_total: int = 40) -> list[str]:
    """Append purchase modifiers to the strongest phrases (originals kept).

    Modifier variants are only generated for product-like cores (no modifier
    words inside the core), so a bare "india" never begets "india india".
    """
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
        core_words = {w for w in WORD_RE.findall(low)}
        if core_words & MODIFIER_WORDS:
            continue
        for i, m in enumerate(mods):
            if i >= MAX_MODIFIERS_PER_PHRASE or len(out) >= max_total:
                break
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


async def llm_polish(keywords: list[str], site_name: str, max_total: int = 40, corpus_texts: list[str] | None = None, _attempt: int = 0) -> list[str]:
    """Optional Groq polish: dedupe + produce exact-match variations.

    Fact-anchored: candidates must share >=2 tokens with a seed keyword or
    appear verbatim in the crawl corpus, so hallucinated terms are rejected.
    One retry on unparseable responses. Returns [] on failure.
    """
    from backend.config import settings

    if not settings.groq_api_key or not keywords:
        return []
    anchor_tokens: set[str] = set()
    for k in keywords:
        anchor_tokens.update(CANON_WORD_RE.findall(k.lower()))
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
            + "\n".join(sorted(set(k.lower() for k in keywords))[:40])
        )
        completion = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": "You return only a JSON array of keyword strings."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=2048,
        )
        text = (completion.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n|\n```$", "", text)
        try:
            arr = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            if _attempt == 0:
                logger.warning("LLM keyword polish returned unparseable content; retrying once")
                return await llm_polish(keywords, site_name, max_total=max_total, corpus_texts=corpus_texts, _attempt=1)
            raise
        raw = [str(k).strip().lower() for k in arr if isinstance(k, str) and k.strip()]
        known = {k.lower() for k in keywords}
        corpus_low = [(t or "").lower() for t in (corpus_texts or [])]
        out = []
        for k in raw:
            if k in known or len(k) > 70:
                continue
            toks = CANON_WORD_RE.findall(k)
            if not toks:
                continue
            overlap = sum(1 for t in toks if t in anchor_tokens)
            if overlap >= 2:
                out.append(k)
                continue
            if any(k in t for t in corpus_low):
                out.append(k)
        return out[:max_total]
    except Exception as e:
        logger.warning("LLM keyword polish failed: %s", e)
        return []


async def _read_corpus(job_id: str) -> tuple[list[str], list[str]]:
    """URLs + titles/meta/body texts for a job (weighted sampling)."""
    from backend.db.mongo import get_db

    db = get_db()
    urls: list[str] = []
    texts: list[str] = []
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
    return urls, texts


async def get_smart_keywords(
    job_id: str,
    max_total: int = 40,
    use_llm: bool = True,
    force_llm: bool = False,
    rebuild: bool = False,
) -> list[str]:
    """Main entry: ranked keyword list for a job (slug + ngram + SE Ranking + modifiers [+ LLM]).

    Cache-first: reads the `job_keywords` collection (versioned); the pipeline
    rebuilds once per analysis via `rebuild=True` so every consumer slices the
    same ranked list without re-running extraction or re-spending SE Ranking.
    """
    from backend.db.mongo import get_db

    db = get_db()
    if not rebuild:
        try:
            cached = await db.job_keywords.find_one(
                {"job_id": job_id, "version": KEYWORD_CACHE_VERSION},
                {"keywords": 1},
            )
            if cached and cached.get("keywords"):
                return cached["keywords"][:max_total]
        except Exception as ex:
            logger.warning("smart keyword cache read failed: %s", ex)

    urls, texts = await _read_corpus(job_id)

    # SE Ranking organic keywords (best-effort, may be empty)
    se_kws: list[str] = []
    if urls:
        try:
            from backend.services import se_ranking
            raw = await se_ranking.domain_keywords(domain_from_urls(urls), limit=30)
            se_kws = [str(k.get("keyword") or "").strip() for k in raw if k.get("keyword")]
        except Exception as ex:
            logger.warning("smart keywords se_ranking pull failed: %s", ex)

    entries: list[tuple[str, str, float]] = []
    for p in slug_phrases(urls):
        entries.append((p, canonicalize(p), 2.0))
    for g in corpus_ngrams(texts):
        entries.append((g, canonicalize(g), 1.0))
    for k in se_kws:
        entries.append((k, canonicalize(k), 1.5))

    merged: dict[str, tuple[str, float]] = {}
    for surface, canon, w in entries:
        if not canon:
            continue
        cur = merged.get(canon)
        if cur is None or w > cur[1] or (w == cur[1] and len(surface) < len(cur[0])):
            merged[canon] = (surface, w)

    ranked = sorted(merged.items(), key=lambda kv: (-_core_score(kv[1][1], kv[1][0]), len(kv[1][0]), kv[1][0]))
    cores = [surface for _, (surface, _) in ranked]
    gated = [p for p in cores if _passes_intent(p)]
    if gated:
        cores = gated

    base = apply_modifiers(cores[:60], max_total=max_total)
    if use_llm or force_llm:
        extra = await llm_polish(cores[:60], domain_from_urls(urls), corpus_texts=texts)
        if extra:
            base = apply_modifiers(cores[:60], max_total=max(1, max_total - len(extra)))
            base = (base + extra)[:max_total]

    try:
        import time
        await db.job_keywords.update_one(
            {"job_id": job_id},
            {"$set": {
                "version": KEYWORD_CACHE_VERSION,
                "keywords": base,
                "built_at": time.time(),
            }},
            upsert=True,
        )
    except Exception as ex:
        logger.warning("smart keyword cache write failed: %s", ex)

    return base or ["industrial fittings"]