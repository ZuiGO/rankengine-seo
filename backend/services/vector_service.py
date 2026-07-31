import hashlib
from typing import List, Optional
import numpy as np

from backend.db.mongo import get_db

VECTOR_DIM = 256
NGRAM_RANGE = (2, 4)

def _hash_feature(text: str, index: int) -> int:
    h = hashlib.md5(f"{text}:{index}".encode()).hexdigest()
    return int(h, 16)

def embed_text(text: str) -> List[float]:
    vec = np.zeros(VECTOR_DIM, dtype=np.float64)
    text_lower = text.lower()
    for n in range(NGRAM_RANGE[0], NGRAM_RANGE[1] + 1):
        for i in range(len(text_lower) - n + 1):
            ngram = text_lower[i:i + n]
            idx = _hash_feature(ngram, 0) % VECTOR_DIM
            sign = 1 if _hash_feature(ngram, 1) % 2 == 0 else -1
            vec[idx] += sign
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()

def cosine_similarity(a: List[float], b: List[float]) -> float:
    aa = np.array(a, dtype=np.float64)
    bb = np.array(b, dtype=np.float64)
    dot = float(np.dot(aa, bb))
    na = float(np.linalg.norm(aa))
    nb = float(np.linalg.norm(bb))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def _index_doc(db, job_id: str, doc_type: str, doc_id: str, text: str, fields: dict):
    if not text.strip():
        return 0
    vector = embed_text(text)
    await db.embeddings.update_one(
        {"doc_type": doc_type, "doc_id": doc_id, "job_id": job_id},
        {"$set": {
            "doc_type": doc_type,
            "doc_id": doc_id,
            "job_id": job_id,
            "vector": vector,
            "text": text[:2000],
            **fields,
        }},
        upsert=True,
    )
    return 1


async def _index_content_items(db, job_id: str) -> int:
    count = 0
    cursor = db.content_items.find({"job_id": job_id})
    async for doc in cursor:
        extraction = await db.content_extractions.find_one(
            {"job_id": job_id, "content_item_id": str(doc["_id"])}
        )
        text_parts = []
        if doc.get("source_url"):
            text_parts.append(doc["source_url"])
        if doc.get("mime_type"):
            text_parts.append(doc["mime_type"])
        if doc.get("file_path"):
            text_parts.append(doc["file_path"])
        if extraction:
            if extraction.get("text"):
                text_parts.append(extraction["text"])
            for chunk in extraction.get("text_chunks", []):
                if chunk.get("text"):
                    text_parts.append(chunk["text"])
            for table in extraction.get("tables", []):
                if table.get("headers"):
                    text_parts.append(" ".join(str(h) for h in table["headers"]))
            meta = extraction.get("metadata") or {}
            if meta:
                text_parts.append(" ".join(f"{k}={v}" for k, v in meta.items()))
        count += await _index_doc(
            db, job_id, "content", str(doc["_id"]), " ".join(text_parts),
            {
                "source_url": doc.get("source_url", ""),
                "content_type": doc.get("content_type", ""),
                "page_url": doc.get("page_url", ""),
            },
        )
    return count


async def _index_pages(db, job_id: str) -> int:
    count = 0
    cursor = db.pages.find({"job_id": job_id})
    async for doc in cursor:
        text = " ".join([
            doc.get("url", ""),
            doc.get("title", ""),
            doc.get("meta_description", ""),
            f"page type: {doc.get('page_type', '')}",
            f"page role: {doc.get('page_role', '')}",
            f"word count: {doc.get('word_count', 0)}",
        ])
        count += await _index_doc(
            db, job_id, "page", str(doc["_id"]), text,
            {"url": doc.get("url", ""), "page_type": doc.get("page_type", "other")},
        )
    return count


async def _index_actions(db, job_id: str) -> int:
    count = 0
    cursor = db.action_items.find({"job_id": job_id})
    async for doc in cursor:
        text = " ".join([
            f"content type: {doc.get('content_type', '')}",
            doc.get("source_url", ""),
            "issues: " + "; ".join(doc.get("identified_issues", [])),
            "improvements: " + "; ".join(doc.get("improvement_suggestions", [])),
            f"status: {doc.get('status', '')}",
        ])
        count += await _index_doc(
            db, job_id, "action", str(doc["_id"]), text,
            {
                "content_type": doc.get("content_type", ""),
                "source_url": doc.get("source_url", ""),
                "page_url": doc.get("page_url", ""),
                "impact": doc.get("impact_on_ranking", ""),
            },
        )
    return count


async def _index_backlinks(db, job_id: str) -> int:
    count = 0
    cursor = db.backlinks.find({"job_id": job_id})
    async for doc in cursor:
        text = " ".join([
            f"backlink source domain: {doc.get('source_domain', '')}",
            doc.get("source_url", ""),
            f"anchor: {doc.get('anchor', '')}",
            f"target domain: {doc.get('target_domain', '')}",
        ])
        count += await _index_doc(
            db, job_id, "backlink", str(doc["_id"]), text,
            {
                "source_url": doc.get("source_url", ""),
                "source_domain": doc.get("source_domain", ""),
                "target_domain": doc.get("target_domain", ""),
            },
        )
    return count


async def index_job_vectors(job_id: str) -> int:
    """Index pages, content items (with extractions), action items, and backlinks."""
    db = get_db()
    await db.embeddings.delete_many({"job_id": job_id})
    counts = await _index_content_items(db, job_id)
    counts += await _index_pages(db, job_id)
    counts += await _index_actions(db, job_id)
    counts += await _index_backlinks(db, job_id)
    return counts


async def index_job_content(job_id: str) -> int:
    return await index_job_vectors(job_id)


async def search_similar(
    job_id: str,
    query: str,
    limit: int = 5,
    doc_types: Optional[list[str]] = None,
    content_type: Optional[str] = None,
) -> List[dict]:
    db = get_db()
    query_vec = embed_text(query)
    cursor = db.embeddings.find({"job_id": job_id})
    scored = []
    async for doc in cursor:
        if doc_types and doc.get("doc_type") not in doc_types:
            continue
        if content_type and doc.get("content_type") != content_type:
            continue
        vec = doc.get("vector", [])
        if not vec:
            continue
        score = cosine_similarity(query_vec, vec)
        scored.append({
            "doc_type": doc.get("doc_type", "content"),
            "doc_id": doc.get("doc_id", ""),
            "score": score,
            "source_url": doc.get("source_url", ""),
            "content_type": doc.get("content_type", ""),
            "page_url": doc.get("page_url", ""),
            "url": doc.get("url", ""),
            "impact": doc.get("impact", ""),
            "text": doc.get("text", ""),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]
