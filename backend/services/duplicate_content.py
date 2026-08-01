"""Duplicate-content detection and canonical-tag audit from stored crawl HTML."""

from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.embeddings import embed_texts
from backend.services.dummy_site import _normalize_page_url

logger = get_logger("duplicate_content")

SIMILARITY_THRESHOLD = 0.92


def _page_text(html: str, max_chars: int = 4000) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return text[:max_chars]


def canonical_audit(page_url: str, html: str) -> dict:
    """Return canonical flags for a page. Works even when html is missing/placeholder."""
    result = {
        "page_url": page_url,
        "canonical_present": False,
        "canonical_self": False,
        "canonical_conflicting": False,
        "canonical_cross_domain": False,
        "canonical_multiple": False,
        "canonical_target": None,
    }
    if not html:
        return result
    soup = BeautifulSoup(html, "lxml")
    canonicals = [t for t in soup.find_all("link", rel="canonical")]
    hrefs = []
    for c in canonicals:
        h = (c.get("href") or "").strip()
        if h:
            hrefs.append(h)
    if not hrefs:
        return result
    result["canonical_present"] = True
    if len(hrefs) > 1:
        result["canonical_multiple"] = True
    target = hrefs[0]
    result["canonical_target"] = target
    result["canonical_self"] = _normalize_page_url(target) == _normalize_page_url(page_url)
    target_host = urlparse(target).netloc
    page_host = urlparse(page_url).netloc
    result["canonical_cross_domain"] = bool(target_host) and target_host != page_host
    if len(hrefs) > 1 and len(set(_normalize_page_url(h) for h in hrefs)) > 1:
        result["canonical_conflicting"] = True
    elif not result["canonical_self"] and not result["canonical_cross_domain"]:
        result["canonical_conflicting"] = True
    return result


async def detect_duplicate_content(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1, "title": 1, "meta_description": 1}).to_list(length=None)
    if not pages:
        return {"status": "error", "message": "No pages for this job"}

    canonical_flags = []
    for p in pages:
        flag = canonical_audit(p["url"], p.get("html") or "")
        flag["title"] = p.get("title", "")
        canonical_flags.append(flag)

    groups = []
    texts = []
    targets = []
    for p in pages:
        text = " ".join([
            p.get("title", ""),
            p.get("meta_description", ""),
            _page_text(p.get("html") or ""),
        ]).strip()
        texts.append(text if text else p.get("url", ""))
        targets.append(p["url"])

    if len(texts) > 1:
        vectors = await embed_texts(texts, job_id)
        dim = len(vectors[0])
        matched = [False] * len(texts)
        for i in range(len(texts)):
            if matched[i]:
                continue
            group = [targets[i]]
            for j in range(i + 1, len(texts)):
                if matched[j]:
                    continue
                sim = _cosine(vectors[i], vectors[j], dim)
                if sim >= SIMILARITY_THRESHOLD:
                    group.append(targets[j])
                    matched[j] = True
            if len(group) > 1:
                groups.append({"urls": group, "similarity": "high"})
                for url in group:
                    matched[[k for k, t in enumerate(targets) if t == url][0]] = True

    duplicates = [u for g in groups for u in g["urls"]]
    flags_by_url = {f["page_url"]: f for f in canonical_flags}
    summary = {
        "job_id": job_id,
        "duplicate_groups": groups,
        "duplicate_pages": len(duplicates),
        "canonical_missing": sum(1 for f in canonical_flags if not f["canonical_present"]),
        "canonical_self": sum(1 for f in canonical_flags if f["canonical_self"]),
        "canonical_conflicting": sum(1 for f in canonical_flags if f["canonical_conflicting"]),
        "canonical_cross_domain": sum(1 for f in canonical_flags if f["canonical_cross_domain"]),
        "canonical_flags": canonical_flags,
        "generated_at": datetime.utcnow(),
    }
    await db.duplicate_content.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    return summary


def _cosine(a: list[float], b: list[float], dim: int) -> float:
    dot = sum(a[i] * b[i] for i in range(dim))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def get_duplicate_content(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.duplicate_content.find_one({"job_id": job_id})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
