"""Real embeddings via Gemini text-embedding-004, with hash-vector fallback when no key is configured.

Python 3.14 has no wheels for onnxruntime/torch/mlx, so a local model is not installable on this
machine; Gemini's free tier (batch embed, 1500 req/day) is the primary embedder. When no key is
present the legacy hash embedder is used so the system keeps working (degraded semantic quality).
"""

import hashlib

import httpx
import numpy as np

from backend.config import settings

VECTOR_DIM = 256
NGRAM_RANGE = (2, 4)

GEMINI_MODEL = "text-embedding-004"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:batchEmbedContents"
GEMINI_DIM = 768


def _hash_feature(text: str, index: int) -> int:
    h = hashlib.md5(f"{text}:{index}".encode()).hexdigest()
    return int(h, 16)


def embed_text_hash(text: str) -> list[float]:
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


def embedding_source() -> str:
    return "gemini" if settings.gemini_api_key else "hash"


async def _gemini_embed(texts: list[str]) -> list[list[float]]:
    body = {
        "requests": [
            {"model": f"models/{GEMINI_MODEL}", "content": {"parts": [{"text": t}]}}
            for t in texts
        ]
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(GEMINI_URL, params={"key": settings.gemini_api_key}, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"Gemini embed failed (HTTP {resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    out = []
    for emb in data.get("embeddings", []):
        out.append([float(x) for x in emb.get("values", [])])
    return out


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Gemini when a key exists, otherwise hash vectors."""
    cleaned = [t if t else "" for t in texts]
    if settings.gemini_api_key:
        try:
            return await _gemini_embed(cleaned)
        except Exception:
            from backend.logging_setup import get_logger
            get_logger("embeddings").warning("Gemini embed failed, using hash fallback")
    return [embed_text_hash(t) for t in cleaned]
