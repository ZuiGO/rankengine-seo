"""Deterministic corpus keyword extraction (weighted TF-IDF over crawled text).

Single source of truth for the keywords that feed SERP ranking checks,
geo-alignment centroids and keyword tracking. Pure functions on text; the
async entry point reads the crawl corpus with per-field weights
(title > meta > URL slug > body) and scores unigrams plus 2-3 gram phrases
(with a sum-of-token-IDF prior so sitewide generic phrases rank lower).
"""
import math
import re
import string
from urllib.parse import urlparse

from backend.logging_setup import get_logger

logger = get_logger("keyword_extractor")

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "as", "at", "be", "because", "been", "before",
    "being", "below", "between", "both", "but", "by", "can", "did", "do",
    "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers",
    "herself", "him", "himself", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "itself", "just", "me", "more", "most", "my",
    "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only",
    "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same",
    "she", "should", "so", "some", "such", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "we", "were", "what", "when", "where", "which", "while",
    "who", "whom", "why", "with", "you", "your", "yours", "yourself",
    "yourselves", "home", "page", "index", "html", "www", "http", "https",
    "com", "org", "net", "read", "more", "click", "menu", "cart", "browse",
    "back", "next", "previous", "top", "skip", "content", "book",
}

MIN_TERM_LEN = 3
MIN_DOC_FREQ = 2
WORD_RE = re.compile(r"[a-z][a-z0-9'_-]+")
SLUG_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|7z|mp4|mp3|mov|avi|web[mp]|jpe?g|png|gif|svg|ico|webp|txt|json|csv)$", re.I)
SINGLE_SPACE_RE = re.compile(r"\s+")

TITLE_WEIGHT = 3.0
META_WEIGHT = 2.0
SLUG_WEIGHT = 2.0
BODY_WEIGHT = 1.0


def tokenize(text: str) -> list[str]:
    return [t for t in WORD_RE.findall((text or "").lower()) if len(t) >= MIN_TERM_LEN and t not in STOPWORDS]


def _leaf_slug(url: str) -> str:
    try:
        path = urlparse(url or "").path.strip("/")
        if not path:
            return ""
        leaf = SLUG_EXT_RE.sub("", path.split("/")[-1].lower())
        return leaf
    except Exception:
        return ""


def extract_keywords_from_docs(docs: list, top_k: int = 20, weights: list[float] | None = None) -> list[str]:
    """Weighted TF-IDF over documents; unigrams + 2-3 gram phrases with a
    token-IDF prior. Each doc is a string or a (text, weight) tuple."""
    docs = [d for d in docs if d]
    n = len(docs)
    if not n:
        return []
    parsed: list[tuple[str, float]] = []
    for i, d in enumerate(docs):
        if isinstance(d, tuple):
            text, w = d
        else:
            text, w = d, 1.0
        if weights is not None and i < len(weights):
            w = float(weights[i])
        parsed.append((text, w))

    unigram_dfs: dict[str, int] = {}
    term_dfs: dict[str, int] = {}
    doc_tfs: list[tuple[dict[str, int], float]] = []
    for text, w in parsed:
        tokens = tokenize(text)
        if not tokens:
            continue
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        phrases: set[str] = set()
        for gram_n in (2, 3):
            for i in range(len(tokens) - gram_n + 1):
                gram = " ".join(tokens[i:i + gram_n])
                if len(gram) >= 8:
                    tf[gram] = tf.get(gram, 0) + 1
                    phrases.add(gram)
        doc_tfs.append((tf, w))
        for t in set(tokens):
            unigram_dfs[t] = unigram_dfs.get(t, 0) + 1
        for g in phrases:
            term_dfs[g] = term_dfs.get(g, 0) + 1

    if not unigram_dfs and not term_dfs:
        return []

    def idf(term: str, df: int) -> float:
        return math.log(n / (1 + df))

    scores: dict[str, float] = {}
    for tf, w in doc_tfs:
        total = sum(tf.values())
        if not total:
            continue
        for term, count in tf.items():
            is_phrase = " " in term
            df = term_dfs.get(term, 0) if is_phrase else unigram_dfs.get(term, 0)
            if df < MIN_DOC_FREQ:
                continue
            prior = 1.0
            if is_phrase:
                prior = sum(idf(t, unigram_dfs.get(t, 0)) for t in term.split()) / len(term.split())
            scores[term] = scores.get(term, 0) + (count / total) * idf(term, df) * prior * w

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [term for term, _ in ranked[:top_k]]


async def extract_keywords_from_content(job_id: str, top_k: int = 20) -> list[str]:
    """Pull titles/meta/URL slugs/body from the crawl corpus and run weighted TF-IDF."""
    from backend.db.mongo import get_db

    db = get_db()
    docs: list[tuple[str, float]] = []

    cursor = db.pages.find(
        {"job_id": job_id},
        {"url": 1, "title": 1, "meta_description": 1},
    ).limit(200)
    pages = await cursor.to_list(length=200)
    for p in pages:
        title = (p.get("title") or "").strip()
        md = (p.get("meta_description") or "").strip()
        if title:
            docs.append((title, TITLE_WEIGHT))
        if md:
            docs.append((md, META_WEIGHT))
        slug = _leaf_slug(p.get("url") or "")
        if slug and len(slug) >= 4:
            docs.append((SINGLE_SPACE_RE.sub(" ", slug.replace("-", " ").replace("_", " ")), SLUG_WEIGHT))

    extras = await db.content_extractions.find(
        {"job_id": job_id, "text": {"$ne": None}},
        {"text": 1},
    ).limit(100).to_list(length=100)
    for e in extras:
        text = (e.get("text") or "").strip()
        if len(text) >= 200:
            docs.append((text[:3000], BODY_WEIGHT))

    keywords = extract_keywords_from_docs(docs, top_k=top_k)
    logger.info("Keyword extraction job=%s docs=%s keywords=%s", job_id, len(docs), len(keywords))
    return keywords