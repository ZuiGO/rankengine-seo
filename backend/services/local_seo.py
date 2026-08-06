"""Local-SEO readiness: presence of LocalBusiness/Organization JSON-LD with
NAP (name/address/phone), contact and address signals, geo metadata, reviews
and opening-hours schema. Offline heuristics on crawled HTML — schema signals
are parsed from real <script type="application/ld+json"> blocks only.
"""

import json
import re
from datetime import datetime

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("local_seo")

LDJSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)

LOCAL_TYPES = {
    "localbusiness",
    "store",
    "restaurant",
    "cafe",
    "food establishment",
    "healthandbeautybusiness",
    "homeandconstructionbusiness",
    "automotivebusiness",
    "professional service",
    "dentist",
    "physician",
    "veterinarycare",
    "hair salon",
    "moving company",
    "travelagency",
    "insuranceagency",
    "realestateagent",
    "bedandbreakfast",
    "lodgingbusiness",
    "hotel",
}

PHONE_RE = re.compile(r"(\+?[\d][\d\s().\-]{6,}\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
STREET_RE = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9\.\- ]{1,40}\b(?:street|st|road|rd|avenue|ave|"
    r"drive|dr|lane|ln|boulevard|blvd|crescent|cres|court|ct|place|pl|"
    r"parkway|park|highway|hwy|suite|ste)\b",
    re.I,
)
POSTAL_RE = re.compile(r"\b\d{4,5}(-\d{4})?\b")


def _iter_schema_objects(blocks: list[str]):
    for text in blocks:
        try:
            data = json.loads(text)
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                if isinstance(node.get("@graph"), list):
                    stack.extend(node["@graph"])
                stack.extend(v for v in node.values() if isinstance(v, dict))


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _types_of(obj: dict) -> list[str]:
    return [str(t).lower() for t in _as_list(obj.get("@type"))]


def _find_key(objs: list[dict], key: str):
    """Return the first value for `key` anywhere in the parsed schema objects."""
    k = key.lower()
    found = []

    def walk(n):
        if isinstance(n, dict):
            for kk, vv in n.items():
                if str(kk).lower() == k:
                    found.append(vv)
                else:
                    walk(vv)
        elif isinstance(n, list):
            for it in n:
                walk(it)

    for o in objs:
        walk(o)
    return found[0] if found else None


def _extract_nap(objs: list[dict]) -> dict | None:
    """NAP (name, street address, telephone) from the first qualifying object."""
    for o in objs:
        types = set(_types_of(o))
        is_local = bool(types & LOCAL_TYPES) or "organization" in types
        if not is_local:
            continue
        name = o.get("name")
        tel = o.get("telephone")
        addr = o.get("address")
        street = None
        if isinstance(addr, dict):
            street = addr.get("streetAddress")
        if name and (tel or street):
            return {
                "name": str(name),
                "street_address": str(street) if street else None,
                "phone": str(tel) if tel else None,
            }
    return None


def _is_homepage(url: str) -> bool:
    if not url:
        return False
    u = url.rstrip("/")
    from urllib.parse import urlparse
    path = urlparse(u).path
    return path in ("", "/")


async def check_local_seo(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1, "page_type": 1}).to_list(length=None)

    local_schema = 0
    local_homepage = False
    nap_schema_pages = 0
    contact_pages = 0
    address_pages = 0
    phone_pages = 0
    email_pages = 0
    geo_pages = 0
    reviews_pages = 0
    opening_hours_pages = 0
    pages_with_local_schema = 0
    naps_found: list[dict] = []
    nap_keys: set[str] = set()

    for p in pages:
        html = p.get("html") or ""
        url = p.get("url") or ""
        ptype = (p.get("page_type") or "").lower()
        low = html.lower()
        is_home = _is_homepage(url)

        ld_blocks = [m.group(1) for m in LDJSON_RE.finditer(html)]
        objs = list(_iter_schema_objects(ld_blocks))
        page_types: set[str] = set()
        for o in objs:
            page_types.update(_types_of(o))

        page_has_local = any(t in LOCAL_TYPES for t in page_types)
        page_has_org_addr = any(
            "organization" in _types_of(o) and _find_key([o], "address") is not None for o in objs
        )
        if page_has_local or page_has_org_addr:
            local_schema += 1
            pages_with_local_schema += 1
            if is_home:
                local_homepage = True

        nap = _extract_nap(objs)
        if nap:
            nap_schema_pages += 1
            nap_keys.add((nap.get("name") or "").strip().lower() + "|" + (nap.get("phone") or "").strip())
            if len(naps_found) < 3:
                naps_found.append(nap)

        is_contact = ("contact" in ptype or "address" in ptype or "about" in ptype) or re.search(
            r"/contact|/about|/find-us|/locations", url, re.I
        )
        if is_contact:
            contact_pages += 1

        page_addr = _find_key(objs, "streetaddress") is not None or bool(STREET_RE.search(low)) or bool(POSTAL_RE.search(low))
        if _find_key(objs, "openinghours") is not None or "openinghours" in low:
            opening_hours_pages += 1
        if _find_key(objs, "aggregaterating") is not None:
            reviews_pages += 1

        if page_addr:
            address_pages += 1
        if _find_key(objs, "telephone") is not None or (PHONE_RE.search(html) and (is_contact or page_addr)):
            phone_pages += 1
        if EMAIL_RE.search(low):
            email_pages += 1

        if any(k in low for k in ("geo.region", "geo.position", "icbm", 'name="geo"')) or \
           _find_key(objs, "geocoordinates") is not None or _find_key(objs, "latitude") is not None:
            geo_pages += 1

    total = max(len(pages), 1)
    local_business_schema = local_schema > 0
    nap_schema_present = nap_schema_pages > 0
    contact_page_present = contact_pages > 0
    address_signals_present = address_pages > 0
    nap_inconsistent = len(nap_keys) > 1

    subscores = {
        "local_business_schema": 40 if local_homepage else (25 if local_business_schema else 0),
        "nap": 20 if nap_schema_present else 0,
        "contact_page": 15 if contact_page_present else 0,
        "address_signals": 10 if address_signals_present else 0,
        "geo_signals": 10 if geo_pages else 0,
        "reviews": 5 if reviews_pages else 0,
    }
    score = sum(subscores.values())

    checks = [
        {
            "passed": local_business_schema,
            "label": "LocalBusiness / Organization JSON-LD with contact info",
            "detail": (f"LocalBusiness/Organization schema is on the homepage ({pages_with_local_schema} page(s) total)."
                       if local_homepage else
                       (f"Local schema found on {pages_with_local_schema} page(s), but not the homepage."
                        if local_business_schema else
                        "Add LocalBusiness JSON-LD (or Organization with an address) on the homepage.")),
        },
        {
            "passed": nap_schema_present,
            "label": "NAP (name / address / phone) present",
            "detail": f"{nap_schema_pages} page(s) expose NAP via schema." if nap_schema_present
                      else "Add PostalAddress + ContactPoint (name/address/phone) via JSON-LD.",
        },
        {
            "passed": contact_page_present,
            "label": "Dedicated Contact / About page",
            "detail": f"{contact_pages} page(s) are contact-typed or match /contact|/about.",
        },
        {
            "passed": address_signals_present,
            "label": "Street address / postal code / opening hours on the site",
            "detail": f"{address_pages} page(s) carry address-style signals.",
        },
        {
            "passed": bool(geo_pages),
            "label": "Geo coordinates (meta geo.* or GeoCoordinates schema)",
            "detail": f"Found on {geo_pages} page(s).",
        },
        {
            "passed": bool(reviews_pages),
            "label": "Reviews / aggregateRating schema",
            "detail": f"Found on {reviews_pages} page(s).",
        },
    ]
    if nap_inconsistent:
        checks.insert(1, {
            "passed": False,
            "label": "NAP is consistent across the site",
            "detail": f"{len(nap_keys)} distinct NAP values detected — use one canonical name/address/phone everywhere.",
        })

    summary = {
        "job_id": job_id,
        "score": score,
        "subscores": subscores,
        "checks": checks,
        "local_business_schema": local_business_schema,
        "local_business_on_homepage": local_homepage,
        "nap_schema_present": nap_schema_present,
        "contact_page_present": contact_page_present,
        "address_signals_present": address_signals_present,
        "geo_pages": geo_pages,
        "reviews_pages": reviews_pages,
        "opening_hours_pages": opening_hours_pages,
        "phone_pages": phone_pages,
        "email_pages": email_pages,
        "nap_inconsistent": nap_inconsistent,
        "naps_found": naps_found[:3],
        "pages_with_local_schema": pages_with_local_schema,
        "total_pages": len(pages),
        "checked_at": datetime.utcnow(),
    }
    await db.local_seo_summaries.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("Local SEO job=%s score=%s", job_id, score)
    return summary