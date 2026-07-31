import hashlib
import math
from typing import List, Tuple
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

async def index_job_content(job_id: str):
    db = get_db()
    cursor = db.content_items.find({"job_id": job_id})
    count = 0
    async for doc in cursor:
        text_parts = []
        if doc.get("source_url"):
            text_parts.append(doc["source_url"])
        if doc.get("mime_type"):
            text_parts.append(doc["mime_type"])
        if doc.get("file_path"):
            text_parts.append(doc["file_path"])
        text = " ".join(text_parts)
        if not text.strip():
            continue
        vector = embed_text(text)
        await db.embeddings.update_one(
            {"content_item_id": str(doc["_id"]), "job_id": job_id},
            {"$set": {
                "content_item_id": str(doc["_id"]),
                "job_id": job_id,
                "vector": vector,
                "source_url": doc.get("source_url", ""),
                "content_type": doc.get("content_type", ""),
                "page_url": doc.get("page_url", ""),
            }},
            upsert=True,
        )
        count += 1
    return count

async def search_similar(job_id: str, query: str, limit: int = 5) -> List[dict]:
    db = get_db()
    query_vec = embed_text(query)
    cursor = db.embeddings.find({"job_id": job_id})
    scored = []
    async for doc in cursor:
        vec = doc.get("vector", [])
        if not vec:
            continue
        score = cosine_similarity(query_vec, vec)
        scored.append({
            "content_item_id": doc["content_item_id"],
            "score": score,
            "source_url": doc.get("source_url", ""),
            "content_type": doc.get("content_type", ""),
            "page_url": doc.get("page_url", ""),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]
