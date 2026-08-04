"""Deterministic corpus keyword extraction (TF-IDF over crawled text).

Single source of truth for the keywords that feed SERP ranking checks,
geo-alignment centroids and keyword tracking. Pure functions on text; the
async entry point reads the crawl corpus.
"""
import math
import re
import string

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


def tokenize(text: str) -> list[str]:
    return [t for t in WORD_RE.findall((text or "").lower()) if len(t) >= MIN_TERM_LEN and t not in STOPWORDS]


def extract_keywords_from_docs(docs: list[str], top_k: int = 20) -> list[str]:
    """TF-IDF over a list of documents; returns ranked keyword phrases (unigrams)."""
    docs = [d for d in docs if d]
    n = len(docs)
    if not n:
        return []
    dfs: dict[str, int] = {}
    tfs: list[dict[str, int]] = []
    for doc in docs:
        tokens = tokenize(doc)
        if not tokens:
            continue
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        tfs.append(tf)
        for t in set(tokens):
            dfs[t] = dfs.get(t, 0) + 1

    scores: dict[str, float] = {}
    for tf in tfs:
        total = sum(tf.values())
        if not total:
            continue
        for term, count in tf.items():
            df = dfs.get(term, 0)
            if df < MIN_DOC_FREQ:
                continue
            idf = math.log(n / (1 + df))
            scores[term] = scores.get(term, 0) + (count / total) * idf

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [term for term, _ in ranked[:top_k]]


async def extract_keywords_from_content(job_id: str, top_k: int = 20) -> list[str]:
    """Pull titles/meta/text from the crawl corpus and run TF-IDF."""
    from backend.db.mongo import get_db

    db = get_db()
    docs: list[str] = []

    cursor = db.pages.find({"job_id": job_id}, {"title": 1, "meta_description": 1}).limit(200)
    pages = await cursor.to_list(length=200)
    for p in pages:
        parts = [p.get("title") or "", p.get("meta_description") or ""]
        parts = [s for s in parts if s]
        if parts:
            docs.append(" ".join(parts))

    extras = await db.content_extractions.find(
        {"job_id": job_id, "text": {"$ne": None}},
        {"text": 1},
    ).limit(100).to_list(length=100)
    for e in extras:
        text = (e.get("text") or "").strip()
        if len(text) >= 200:
            docs.append(text[:3000])

    keywords = extract_keywords_from_docs(docs, top_k=top_k)
    logger.info("Keyword extraction job=%s docs=%s keywords=%s", job_id, len(docs), len(keywords))
    return keywords