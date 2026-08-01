"""JSON-LD structured-data validation for rich-result types (FAQ schema intentionally excluded -
Google deprecated FAQ rich results in May 2026)."""

import json
from datetime import datetime

from bs4 import BeautifulSoup

from backend.db.mongo import get_db

SUPPORTED_TYPES = {
    "Product": ["name", "offers"],
    "Article": ["headline", "author"],
    "Organization": ["name"],
    "BreadcrumbList": ["itemListElement"],
}


def _json_ld_objects(html: str) -> list[dict]:
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out.extend(data)
        else:
            out.append(data)
    return out


def _type_names(node: dict) -> list[str]:
    t = node.get("@type")
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return [t] if isinstance(t, str) else []


def _has_required(obj: dict, type_name: str) -> list[str]:
    required = SUPPORTED_TYPES.get(type_name, [])
    missing = []
    for field in required:
        if field not in obj:
            missing.append(field)
    return missing


def validate_structured_data(page_url: str, html: str) -> dict:
    report = {
        "page_url": page_url,
        "types_present": [],
        "invalid_types": [],
        "missing_required": {},
        "has_structured_data": False,
        "valid": False,
    }
    objects = _json_ld_objects(html)
    if not objects:
        return report
    report["has_structured_data"] = True
    seen = set()
    valid_types = set()
    for obj in objects:
        for t in _type_names(obj):
            if t in seen:
                continue
            seen.add(t)
            report["types_present"].append(t)
            if t in SUPPORTED_TYPES:
                missing = _has_required(obj, t)
                if missing:
                    report["invalid_types"].append(t)
                    report["missing_required"][t] = missing
                else:
                    valid_types.add(t)
            elif t in ("FAQPage", "FAQPageQuestion"):
                report["types_present"].append(f"{t} (deprecated - ignored)")
    report["valid"] = bool(valid_types) and not report["invalid_types"]
    return report


async def audit_structured_data(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1}).to_list(length=None)
    if not pages:
        return {"status": "error", "message": "No pages for this job"}

    per_page = []
    valid_count = 0
    missing_count = 0
    invalid_count = 0
    type_counts = {}
    for p in pages:
        report = validate_structured_data(p["url"], p.get("html") or "")
        per_page.append(report)
        if report["has_structured_data"]:
            if report["valid"]:
                valid_count += 1
            elif report["invalid_types"]:
                invalid_count += 1
            else:
                missing_count += 1
        for t in report["types_present"]:
            type_counts[t] = type_counts.get(t, 0) + 1

    summary = {
        "job_id": job_id,
        "pages": len(pages),
        "with_structured_data": valid_count + invalid_count + missing_count,
        "valid": valid_count,
        "invalid_types": invalid_count,
        "no_structured_data": len(pages) - valid_count - invalid_count - missing_count,
        "type_counts": type_counts,
        "per_page": per_page,
        "generated_at": datetime.utcnow(),
    }
    await db.structured_data.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    return summary


async def get_structured_data(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.structured_data.find_one({"job_id": job_id})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
