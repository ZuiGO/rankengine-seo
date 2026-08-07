"""GEO/industry alignment: flags pages whose topics deviate from the site's core industry.

For each page we build a topic centroid from its top local keywords (embedded via the
active embedder) and compare it against the industry centroid derived from the homepage.
Low cosine alignment marks a page as off-topic — content a generative search engine
would not associate with the site's vertical.
"""

import asyncio
import math
import re
from collections import Counter
from datetime import datetime

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.embeddings import embed_texts

logger = get_logger("geo_alignment")

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "our", "your", "you", "are", "was", "were",
    "have", "has", "had", "from", "they", "their", "them", "its", "it", "is", "are", "not",
    "but", "can", "will", "all", "any", "one", "two", "new", "more", "most", "such", "about",
    "into", "over", "after", "before", "also", "only", "when", "where", "which", "what", "who",
    "page", "pages", "site", "website", "company", "contact", "home", "menu", "get", "see",
}

ALIGNMENT_THRESHOLD = 0.30
MAX_KEYWORDS = 12
INDUSTRY_KEYWORDS = 15


def _tokens(text: str) -> list[str]:
    if not text:
        return []
    words = re.findall(r"[a-z][a-z\-]{2,}", text.lower())
    return [w for w in words if w not in STOPWORDS]


def _top_keywords(tokens: list[str], n: int = MAX_KEYWORDS) -> list[str]:
    return [w for w, _ in Counter(tokens).most_common(n)]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _mean_vec(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    mean = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            mean[i] += v[i]
    return [x / len(vectors) for x in mean]


async def _page_text(db, job_id: str, page: dict) -> str:
    parts = [page.get("title", ""), page.get("meta_description", "")]
    items = await db.content_items.find(
        {"job_id": job_id, "page_url": page["url"]},
        {"text": 1},
    ).to_list(length=20)
    for item in items:
        if item.get("text"):
            parts.append(item["text"])
    return " ".join(p for p in parts if p)


async def _topic_vector(db, job_id: str, page: dict) -> tuple[list[str], list[float]]:
    tokens = _tokens(await _page_text(db, job_id, page))
    keywords = _top_keywords(tokens)
    if not keywords:
        return [], []
    vectors = await embed_texts(keywords, job_id)
    return keywords, _mean_vec(vectors)


async def audit_geo_alignment(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 0, "html_mobile": 0}).to_list(length=None)
    home = [p for p in pages if p.get("page_type") == "home"] or pages[:1]
    if not home:
        return {"status": "error", "message": "No pages for this job"}

    home_tokens = []
    for p in home:
        home_tokens += _tokens(await _page_text(db, job_id, p))
    industry_keywords = _top_keywords(home_tokens, INDUSTRY_KEYWORDS)
    try:
        from backend.services.keyword_extractor import extract_keywords_from_content as corpus_keywords
        corpus = await corpus_keywords(job_id, top_k=INDUSTRY_KEYWORDS)
        if corpus:
            industry_keywords = corpus
    except Exception as kw_err:
        logger.warning("Corpus keyword fallback for geo alignment job=%s: %s", job_id, kw_err)
    if not industry_keywords:
        return {"status": "error", "message": "No keywords extractable from homepage"}

    industry_vec = _mean_vec(await embed_texts(industry_keywords, job_id))

    report = []
    async def analyze_page(p):
        keywords, page_vec = await _topic_vector(db, job_id, p)
        if not keywords or not page_vec:
            return {"page_url": p["url"], "title": p.get("title", ""), "alignment": 0.0,
                    "top_keywords": keywords, "off_topic": True, "reason": "No extractable topic"}
        alignment = round(_cosine(page_vec, industry_vec), 3)
        return {"page_url": p["url"], "title": p.get("title", ""), "alignment": alignment,
                "top_keywords": keywords, "off_topic": alignment < ALIGNMENT_THRESHOLD}

    sem_page = asyncio.Semaphore(8)
    async def bounded(p):
        async with sem_page:
            return await analyze_page(p)

    pages_iter = [p for p in pages if p.get("page_type") != "home"]
    report = list(await asyncio.gather(*(bounded(p) for p in pages_iter)))
    off_topic_pages = sum(1 for r in report if r.get("off_topic"))

    doc = {
        "job_id": job_id,
        "industry_keywords": industry_keywords,
        "pages": report,
        "pages_analyzed": len(report),
        "off_topic_pages": off_topic_pages,
        "generated_at": datetime.utcnow(),
    }
    await db.geo_alignment.update_one({"job_id": job_id}, {"$set": doc}, upsert=True)
    logger.info("GEO alignment job=%s pages=%s off_topic=%s", job_id, len(report), off_topic_pages)
    return doc


async def get_geo_alignment(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.geo_alignment.find_one({"job_id": job_id})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
