from backend.db.mongo import get_db


IMPACT_BY_TYPE = {
    "image": {
        "impact": "medium",
        "factors": [
            "Missing alt text reduces accessibility and image search ranking",
            "Large file sizes slow page load, hurting Core Web Vitals",
            "Lack of descriptive filenames misses keyword relevance signals",
        ],
        "improvements": [
            "Add descriptive alt text with target keywords",
            "Compress images to WebP/AVIF format",
            "Use descriptive, keyword-rich filenames",
            "Add structured data (ImageObject) for rich snippets",
        ],
    },
    "pdf": {
        "impact": "low",
        "factors": [
            "PDF content is not indexed as effectively as HTML",
            "Slow-loading PDFs increase bounce rate",
            "Missing text layer prevents indexing entirely",
        ],
        "improvements": [
            "Convert key PDF content to HTML pages",
            "Ensure PDFs have selectable text (OCR if scanned)",
            "Add descriptive link text pointing to PDFs",
            "Host PDFs with fast CDN delivery",
        ],
    },
    "video": {
        "impact": "high",
        "factors": [
            "Video content increases dwell time significantly",
            "Video rich snippets appear prominently in SERPs",
            "Self-hosted videos slow page load dramatically",
        ],
        "improvements": [
            "Embed videos from YouTube/Vimeo (CDN-hosted)",
            "Add video structured data (VideoObject)",
            "Provide transcripts for accessibility and indexing",
            "Use engaging thumbnail images with alt text",
        ],
    },
    "doc": {
        "impact": "low",
        "factors": [
            "DOCX files are not indexed well by search engines",
            "Users must download to view, reducing engagement",
        ],
        "improvements": [
            "Convert documents to HTML or Google Docs embed",
            "Provide summary HTML page with download link",
        ],
    },
    "xlsx": {
        "impact": "low",
        "factors": [
            "Spreadsheets are poorly indexed by search engines",
            "Data in cells lacks semantic HTML context",
        ],
        "improvements": [
            "Present key data as HTML tables on the page",
            "Provide CSV/JSON downloads with schema markup",
        ],
    },
    "presentation": {
        "impact": "medium",
        "factors": [
            "Embedded slideshows can increase engagement",
            "Slide content is not indexed directly",
        ],
        "improvements": [
            "Embed slides with descriptive titles",
            "Provide a text summary of key slides",
        ],
    },
    "text": {
        "impact": "high",
        "factors": [
            "Thin content (<300 words) ranks poorly",
            "Duplicate content causes ranking penalties",
            "Poor readability reduces engagement",
        ],
        "improvements": [
            "Expand content to 600+ words with unique value",
            "Improve readability score (Flesch 60+)",
            "Use proper heading hierarchy (H1→H2→H3)",
        ],
    },
}


async def analyze_content_item(item: dict, page_url: str, job_id: str):
    ctype = item["content_type"]
    info = IMPACT_BY_TYPE.get(ctype, IMPACT_BY_TYPE["text"])

    action = {
        "job_id": job_id,
        "page_url": page_url,
        "content_item_id": item.get("_id", ""),
        "content_type": ctype,
        "source_url": item.get("source_url", ""),
        "impact_on_ranking": info["impact"],
        "identified_issues": info["factors"],
        "improvement_suggestions": info["improvements"],
        "status": "pending",
    }

    db = get_db()
    await db.action_items.insert_one(action)
    return action
