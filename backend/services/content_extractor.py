import asyncio
import os
from datetime import datetime

from backend.config import settings
from backend.db.mongo import get_db
from backend.db.neo4j_db import get_driver
from backend.services.pdf_extractor import extract_pdf_data
from backend.services.docs_extractor import extract_doc_file
from backend.services.image_metadata import parse_image_metadata
from backend.services.content_classifier import classify_with_magic

BATCH_SIZE = 50


async def extract_all_content(job_id: str):
    db = get_db()
    driver = get_driver()

    cursor = db.content_items.find({
        "job_id": job_id,
        "file_path": {"$ne": None},
    })
    items = await cursor.to_list(length=None)

    extracted_texts = []
    extracted_tables = []
    extracted_images = []
    sem = asyncio.Semaphore(settings.extract_workers)

    async def process_item(item: dict):
        async with sem:
            file_path = item.get("file_path", "")
            content_type = item.get("content_type", "")
            source_url = item["source_url"]
            extracted_at = datetime.utcnow()

            if content_type == "pdf" and file_path:
                data = await asyncio.to_thread(extract_pdf_data, file_path)
                if "error" not in data:
                    await db.content_extractions.insert_one({
                        "job_id": job_id,
                        "content_item_id": str(item["_id"]),
                        "content_type": "pdf",
                        "source_url": source_url,
                        "extracted_at": extracted_at,
                        **data,
                    })

                    extracted_texts.extend(
                        {"source_url": source_url, "text": c["text"], "word_count": c["word_count"]}
                        for c in data.get("text_chunks", [])
                    )
                    extracted_tables.extend(
                        {**t, "source_url": source_url}
                        for t in data.get("tables", [])
                    )
                    extracted_images.extend(
                        {**img, "source_url": source_url}
                        for img in data.get("images", [])
                    )

            elif content_type in ("doc", "xlsx", "presentation") and file_path:
                data = await asyncio.to_thread(extract_doc_file, file_path, content_type)
                mime_type = await asyncio.to_thread(classify_with_magic, file_path) or item.get("mime_type")
                if "error" in data:
                    await db.content_extractions.insert_one({
                        "job_id": job_id,
                        "content_item_id": str(item["_id"]),
                        "content_type": content_type,
                        "source_url": source_url,
                        "file_path": file_path,
                        "file_size": item.get("file_size"),
                        "mime_type": mime_type,
                        "extracted_at": extracted_at,
                        "error": data["error"],
                    })
                else:
                    await db.content_extractions.insert_one({
                        "job_id": job_id,
                        "content_item_id": str(item["_id"]),
                        "content_type": content_type,
                        "source_url": source_url,
                        "file_path": file_path,
                        "file_size": item.get("file_size"),
                        "mime_type": mime_type,
                        "extracted_at": extracted_at,
                        "text": data.get("text", ""),
                        "word_count": data.get("word_count", 0),
                        "text_chunks": data.get("text_chunks", []),
                        "tables": data.get("tables", data.get("slides", [])),
                        "metadata": data.get("metadata", {}),
                    })

                    extracted_texts.extend(
                        {"source_url": source_url, "text": c["text"], "word_count": c["word_count"]}
                        for c in data.get("text_chunks", [])
                    )
                    extracted_tables.extend(
                        {**t, "source_url": source_url}
                        for t in data.get("tables", [])
                    )

            elif content_type == "image" and file_path:
                stats = None
                if await asyncio.to_thread(os.path.exists, file_path):
                    stats = await asyncio.to_thread(os.stat, file_path)
                meta = await asyncio.to_thread(parse_image_metadata, file_path)
                mime_type = item.get("mime_type") or await asyncio.to_thread(classify_with_magic, file_path)
                await db.content_extractions.insert_one({
                    "job_id": job_id,
                    "content_item_id": str(item["_id"]),
                    "content_type": "image",
                    "source_url": source_url,
                    "file_path": file_path,
                    "file_size": stats.st_size if stats else item.get("file_size"),
                    "mime_type": mime_type,
                    "extracted_at": extracted_at,
                    "metadata": {
                        "width": meta.get("width"),
                        "height": meta.get("height"),
                        "format": meta.get("format"),
                    },
                })

    await asyncio.gather(*[process_item(item) for item in items])

    # Store in Neo4j if available
    if driver:
        async with driver.session(database="neo4j") as session:
            # Table nodes
            for i in range(0, len(extracted_tables), BATCH_SIZE):
                batch = extracted_tables[i:i + BATCH_SIZE]
                await session.run(
                    """
                    UNWIND $tables AS t
                    MATCH (c:ContentItem {source_url: t.source_url, job_id: $job_id})
                    MERGE (tab:Table {id: t.source_url + '_table_' + toString(t.index), job_id: $job_id})
                    SET tab.page = t.page,
                        tab.rows = t.rows,
                        tab.cols = t.cols,
                        tab.headers = t.headers,
                        tab.page_number = t.page
                    MERGE (c)-[:HAS_TABLE]->(tab)
                    """,
                    tables=[{**t, "index": t.get("index", 0)} for t in batch],
                    job_id=job_id,
                )

            # Extracted image nodes (from PDFs)
            for i in range(0, len(extracted_images), BATCH_SIZE):
                batch = extracted_images[i:i + BATCH_SIZE]
                await session.run(
                    """
                    UNWIND $images AS img
                    MATCH (c:ContentItem {source_url: img.source_url, job_id: $job_id})
                    MERGE (ei:ExtractedImage {id: img.source_url + '_img_' + toString(img.index), job_id: $job_id})
                    SET ei.page = img.page,
                        ei.width = img.width,
                        ei.height = img.height,
                        ei.format = img.format,
                        ei.size_bytes = img.size_bytes
                    MERGE (c)-[:HAS_IMAGE]->(ei)
                    """,
                    images=[{**img, "index": img.get("index", 0)} for img in batch],
                    job_id=job_id,
                )

    return {
        "total_extracted": len(items),
        "pdfs_processed": len([i for i in items if i.get("content_type") == "pdf"]),
        "tables_found": len(extracted_tables),
        "images_extracted": len(extracted_images),
        "text_chunks": len(extracted_texts),
    }
