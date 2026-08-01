"""Real embeddings via Gemini gemini-embedding-2, with hash-vector fallback when no key is configured.

Python 3.14 has no wheels for onnxruntime/torch/mlx, so a local model is not installable on this
machine; Gemini's free tier (batch embed, 1500 req/day) is the primary embedder. When no key is
present the legacy hash embedder is used so the system keeps working (degraded semantic quality).
"""

import asyncio
import hashlib

import httpx
import numpy as np

from backend.config import settings

VECTOR_DIM = 256
NGRAM_RANGE = (2, 4)

GEMINI_MODEL = "gemini-embedding-2"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:batchEmbedContents"
GEMINI_DIM = 768


def _gemini_request_items(texts: list[str]) -> list[dict]:
    return [
        {"model": f"models/{GEMINI_MODEL}", "content": {"parts": [{"text": t}]}, "outputDimensionality": GEMINI_DIM}
        for t in texts
    ]


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
    body = {"requests": _gemini_request_items(texts)}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(GEMINI_URL, params={"key": settings.gemini_api_key}, json=body)
        if resp.status_code == 429 and "quota" in resp.text:
            raise QuotaExceeded(resp.text[:200])
        if resp.status_code >= 400:
            raise RuntimeError(f"Gemini embed failed (HTTP {resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    out = []
    for emb in data.get("embeddings", []):
        out.append([float(x) for x in emb.get("values", [])])
    return out


class QuotaExceeded(RuntimeError):
    """Gemini free-tier daily quota exhausted; embeddings unavailable for the rest of the day."""


async def embed_texts(texts: list[str], job_id: str | None = None) -> list[list[float]]:
    """Embed a batch of texts. Gemini when a key exists, otherwise hash vectors."""
    cleaned = [t if t else "" for t in texts]
    if settings.gemini_api_key:
        for attempt in range(2):
            try:
                vectors = await _gemini_embed(cleaned)
                from backend.services.spend_tracker import record_usage
                tokens = sum(max(1, len(t.split())) for t in cleaned)
                await record_usage("gemini", job_id or "", "embed_texts", tokens=tokens)
                return vectors
            except QuotaExceeded as e:
                from backend.logging_setup import get_logger
                get_logger("embeddings").warning(
                    "Gemini quota exhausted for the day (%s); using hash fallback", str(e)[:120],
                )
                break
            except Exception as e:
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                from backend.logging_setup import get_logger
                get_logger("embeddings").warning("Gemini embed failed (%s), using hash fallback", e)
    return [embed_text_hash(t) for t in cleaned]
