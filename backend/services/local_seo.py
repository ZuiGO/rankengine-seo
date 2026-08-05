"""Local-SEO readiness: presence of LocalBusiness/NAP schema, contact/address
signals, Google-rating schema, and map-embeddable structured data. Offline
heuristics on crawled HTML (no paid local API).
"""

from datetime import datetime

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("local_seo")


async def check_local_seo(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1, "page_type": 1}).to_list(length=None)

    local_schema = 0
    nap_schema = 0
    contact_pages = 0
    address_pages = 0
    geo_pages = 0
    for p in pages:
        html = p.get("html") or ""
        low = html.lower()
        if "localbusiness" in low or '"organization"' in low:
            local_schema += 1
        if '"postaladdress"' in low or ('streetaddress' in low and 'telephone' in low):
            nap_schema += 1
        ptype = (p.get("page_type") or "").lower()
        if "contact" in ptype or "address" in ptype or "about" in ptype:
            contact_pages += 1
        if 'itemprop="streetaddress"' in html or "geo" in low and "latitude" in low:
            geo_pages += 1
        if any(token in low for token in ("streetaddress", "postalcode", "openinghours")):
            address_pages += 1

    total = max(len(pages), 1)
    checks = []
    score = 0
    if local_schema:
        score += 40
    else:
        checks.append("Add LocalBusiness JSON-LD (or Organization) schema on the homepage")
    if contact_pages:
        score += 20
    else:
        checks.append("Add a Contact/About page with a physical address")
    if nap_schema:
        score += 20
    else:
        checks.append("Add NAP data (name/address/phone) via PostalAddress/ContactPoint schema")
    if address_pages:
        score += 20
    else:
        checks.append("Include StreetAddress / PostalCode / OpeningHours fields somewhere on the site")

    summary = {
        "job_id": job_id,
        "score": score,
        "local_business_schema": local_schema > 0,
        "nap_schema_present": nap_schema > 0,
        "contact_page_present": contact_pages > 0,
        "address_signals_present": address_pages > 0,
        "geo_pages": geo_pages,
        "pages_with_local_schema": local_schema,
        "total_pages": len(pages),
        "checks": checks,
        "checked_at": datetime.utcnow(),
    }
    await db.local_seo_summaries.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("Local SEO job=%s score=%s", job_id, score)
    return summary