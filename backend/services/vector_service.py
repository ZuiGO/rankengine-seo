"""Semantic indexing and search backed by Chroma with real embeddings (Gemini) or hash fallback."""

import asyncio
from typing import Optional

from backend.db.chroma import get_or_create_collection, delete_collection
from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.embeddings import embed_texts, embed_text_hash, embedding_source

logger = get_logger("vector")

BATCH_SIZE = 100
MAX_INDEX_DOCS = 500
VECTOR_DIM = 256
GEMINI_DIM = 768


def _collection_name(job_id: str) -> str:
    return f"job_{job_id}"


async def _collect_docs(db, job_id: str) -> list[tuple[str, str, dict]]:
    docs: list[tuple[str, str, dict]] = []

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
        docs.append((
            str(doc["_id"]),
            " ".join(text_parts),
            {
                "doc_type": "content",
                "source_url": doc.get("source_url", ""),
                "content_type": doc.get("content_type", ""),
                "page_url": doc.get("page_url", ""),
            },
        ))

    cursor = db.pages.find({"job_id": job_id}, {"html": 0, "html_mobile": 0})
    async for doc in cursor:
        text = " ".join([
            doc.get("url", ""),
            doc.get("title", ""),
            doc.get("meta_description", ""),
            f"page type: {doc.get('page_type', '')}",
            f"page role: {doc.get('page_role', '')}",
            f"word count: {doc.get('word_count', 0)}",
        ])
        docs.append((
            str(doc["_id"]),
            text,
            {
                "doc_type": "page",
                "url": doc.get("url", ""),
                "page_type": doc.get("page_type", "other"),
            },
        ))

    cursor = db.action_items.find({"job_id": job_id})
    async for doc in cursor:
        text = " ".join([
            f"content type: {doc.get('content_type', '')}",
            doc.get("source_url", ""),
            "issues: " + "; ".join(doc.get("identified_issues", [])),
            "improvements: " + "; ".join(doc.get("improvement_suggestions", [])),
            f"status: {doc.get('status', '')}",
        ])
        docs.append((
            str(doc["_id"]),
            text,
            {
                "doc_type": "action",
                "content_type": doc.get("content_type", ""),
                "source_url": doc.get("source_url", ""),
                "page_url": doc.get("page_url", ""),
                "impact": doc.get("impact_on_ranking", ""),
            },
        ))

    cursor = db.backlinks.find({"job_id": job_id})
    async for doc in cursor:
        text = " ".join([
            f"backlink source domain: {doc.get('source_domain', '')}",
            doc.get("source_url", ""),
            f"anchor: {doc.get('anchor', '')}",
            f"target domain: {doc.get('target_domain', '')}",
        ])
        docs.append((
            str(doc["_id"]),
            text,
            {
                "doc_type": "backlink",
                "source_url": doc.get("source_url", ""),
                "source_domain": doc.get("source_domain", ""),
                "target_domain": doc.get("target_domain", ""),
            },
        ))

    return docs


async def index_job_vectors(job_id: str) -> int:
    """Rebuild the semantic index for a job (Chroma collection, wiped first).

    Embeds everything up front so a mid-run quota hit cannot mix embedding dimensions;
    if dimensions are mixed, the job falls back to hash vectors for consistency.
    """
    db = get_db()
    docs = (await _collect_docs(db, job_id))[:MAX_INDEX_DOCS]
    name = _collection_name(job_id)
    delete_collection(name)
    collection = get_or_create_collection(name)

    all_vectors = []
    for start in range(0, len(docs), BATCH_SIZE):
        chunk = docs[start:start + BATCH_SIZE]
        all_vectors.extend(await embed_texts([t for _, t, _ in chunk], job_id))

    if not all_vectors:
        return 0

    dims = {len(v) for v in all_vectors}
    if len(dims) != 1 or dims not in ({VECTOR_DIM}, {GEMINI_DIM}):
        logger.warning(
            "Vector dimensions mixed (%s) for job=%s; re-embedding with hash fallback",
            sorted(dims), job_id,
        )
        all_vectors = [embed_text_hash(t) for _, t, _ in docs]

    indexed = 0
    for start in range(0, len(docs), BATCH_SIZE):
        chunk = docs[start:start + BATCH_SIZE]
        collection.add(
            ids=[doc_id for doc_id, _, _ in chunk],
            embeddings=all_vectors[start:start + BATCH_SIZE],
            documents=[t for _, t, _ in chunk],
            metadatas=[m for _, _, m in chunk],
        )
        indexed += len(chunk)
    return indexed


async def index_job_content(job_id: str) -> int:
    return await index_job_vectors(job_id)


async def search_similar(
    job_id: str,
    query: str,
    limit: int = 5,
    doc_types: Optional[list[str]] = None,
    content_type: Optional[str] = None,
) -> list[dict]:
    if not query.strip():
        return []
    try:
        collection = get_or_create_collection(_collection_name(job_id))
        if collection.count() == 0:
            return []
    except Exception:
        return []

    query_vec = (await embed_texts([query], job_id))[0]

    try:
        sample = collection.get(include=["embeddings"], limit=1)["embeddings"][0]
        if len(query_vec) != len(sample):
            query_vec = embed_text_hash(query)
    except Exception:
        pass

    where = {}
    if doc_types:
        where["doc_type"] = {"$in": doc_types}
    if content_type:
        where["content_type"] = content_type

    try:
        result = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_vec],
            n_results=min(max(limit, 1), 50),
            where=where or None,
        )
    except Exception:
        return []

    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    texts = (result.get("documents") or [[]])[0]

    out = []
    for i, doc_id in enumerate(ids):
        m = metas[i] if i < len(metas) else {}
        distance = distances[i] if i < len(distances) else 1.0
        out.append({
            "doc_type": m.get("doc_type", "content"),
            "doc_id": doc_id,
            "score": round(max(0.0, min(1.0, 1.0 - distance)), 4),
            "source_url": m.get("source_url", ""),
            "content_type": m.get("content_type", ""),
            "page_url": m.get("page_url", ""),
            "url": m.get("url", ""),
            "impact": m.get("impact", ""),
            "text": texts[i] if i < len(texts) else "",
        })
    return out[:limit]


async def get_embedding_report(job_id: str) -> dict:
    try:
        collection = get_or_create_collection(_collection_name(job_id))
        return {"indexed": collection.count(), "source": embedding_source()}
    except Exception:
        return {"indexed": 0, "source": embedding_source()}
