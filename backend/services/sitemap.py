"""XML sitemap audit: fetch robots-declared sitemaps, validate them, and check
which sitemap URLs were actually crawled.
"""

from datetime import datetime
from xml.etree import ElementTree

import httpx

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.url_normalizer import normalize_url

logger = get_logger("sitemap")

TIMEOUT = 15
MAX_SITEMAP_BYTES = 2_000_000
USER_AGENT = "ZuiGO-Engine/1.0 sitemap-audit (+https://zuigo.ai)"

SITEMAP_LOCATIONS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml")


async def _fetch(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        if len(resp.content) > MAX_SITEMAP_BYTES:
            return None
        return resp.text
    except Exception:
        return None


async def _parse_sitemap_urls(xml_text: str) -> list[str] | None:
    """Return URL list, or None if the body is not valid XML; [] if valid but empty."""
    entries = await _fetch_sitemap_entries(xml_text)
    if entries is None:
        return None
    return [e["loc"] for e in entries]


async def _fetch_sitemap_entries(xml_text: str, _nested: set[str] | None = None) -> list[dict] | None:
    """Parse sitemap XML into [{loc, lastmod}]. Returns None if not valid XML.

    Nested sitemap indexes are expanded recursively (each child fetched once).
    """
    if _nested is None:
        _nested = set()
    try:
        root = ElementTree.fromstring(xml_text)
    except Exception:
        return None
    tag = root.tag.split("}")[-1].lower()
    entries: list[dict] = []
    if tag == "urlset":
        for child in root:
            name = child.tag.split("}")[-1].lower()
            if name == "url":
                loc = child.findtext("{*}loc")
                if loc:
                    alternates: dict[str, str] = {}
                    for sub in child:
                        sub_name = sub.tag.split("}")[-1].lower()
                        if sub_name == "link" and "alternate" in (sub.get("rel") or ""):
                            code = (sub.get("hreflang") or "").strip().lower()
                            href = (sub.get("href") or "").strip()
                            if code and href:
                                alternates[code] = href
                    entries.append({
                        "loc": loc.strip(),
                        "lastmod": (child.findtext("{*}lastmod") or "").strip(),
                        "alternates": alternates,
                    })
    elif tag in ("sitemapindex", "sitemap"):
        for child in root:
            if child.tag.split("}")[-1].lower() == "sitemap":
                loc = child.findtext("{*}loc")
                if not loc:
                    continue
                loc = loc.strip()
                if loc in _nested:
                    continue
                _nested.add(loc)
                nested = await _fetch(loc)
                if nested:
                    entries.extend(await _fetch_sitemap_entries(nested, _nested) or [])
    else:
        return None
    return entries


async def _robots_sitemap_urls(origin: str) -> list[str]:
    text = await _fetch(origin + "/robots.txt")
    if not text:
        return []
    out = []
    for line in text.splitlines():
        low = line.lower()
        if low.startswith("sitemap:"):
            loc = line.split(":", 1)[1].strip()
            if loc:
                out.append(loc)
    return out


async def audit_sitemap(job_id: str, target_url: str) -> dict:
    db = get_db()
    parsed = target_url.split("//")[-1].split("/")[0]
    origin = "https://" + parsed

    candidates = await _robots_sitemap_urls(origin)
    for loc in SITEMAP_LOCATIONS:
        candidates.append(origin + loc)

    results = []
    seen = set()
    all_urls: set[str] = set()
    lastmod_missing = 0
    http_plain = 0
    sitemap_alt_entries = 0
    sitemap_alt_codes: set[str] = set()
    sitemap_missing_self_ref = 0
    sitemap_invalid_alt_codes = 0
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        text = await _fetch(cand)
        if text is None:
            results.append({"url": cand, "found": False})
            continue
        entries = await _fetch_sitemap_entries(text)
        if entries is None:
            results.append({"url": cand, "found": True, "valid": False})
            continue
        locs = {normalize_url(e["loc"]) for e in entries if normalize_url(e["loc"])}
        missing = sum(1 for e in entries if not e.get("lastmod"))
        results.append({
            "url": cand,
            "found": True,
            "valid": True,
            "url_count": len(locs),
            "lastmod_missing": missing,
        })
        for e in entries:
            nu = normalize_url(e["loc"])
            if nu:
                all_urls.add(nu)
            if e["loc"].lower().startswith("http://"):
                http_plain += 1
            alts = e.get("alternates") or {}
            if alts:
                sitemap_alt_entries += 1
                sitemap_alt_codes.update(alts)
                from backend.services.international_seo import is_valid_hreflang_code
                if any(not is_valid_hreflang_code(c) for c in alts):
                    sitemap_invalid_alt_codes += 1
                if nu and nu not in {normalize_url(a) for a in alts.values()}:
                    sitemap_missing_self_ref += 1
        if missing:
            lastmod_missing += missing

    pages = await db.pages.find({"job_id": job_id}, {"url": 1}).to_list(length=None)
    crawled = {normalize_url(p.get("url", "")) for p in pages if normalize_url(p.get("url", ""))}

    crawled_in_sitemap = len(all_urls & crawled)
    uncrawled = []
    for u in all_urls:
        if u not in crawled and u not in uncrawled:
            uncrawled.append(u)
            if len(uncrawled) >= 200:
                break

    pages_in_sitemap = len(all_urls)
    summary = {
        "job_id": job_id,
        "sitemap_found": any(r.get("found") for r in results),
        "sitemap_valid": any(r.get("valid") for r in results),
        "sitemap_count": len(results),
        "url_count": pages_in_sitemap,
        "pages_in_sitemap": pages_in_sitemap,
        "crawled_in_sitemap": crawled_in_sitemap,
        "crawled_coverage": round(100 * crawled_in_sitemap / pages_in_sitemap, 1) if pages_in_sitemap else 0,
        "missing_lastmod": lastmod_missing,
        "http_plain_urls": http_plain,
        "pages_crawled": len(pages),
        "uncrawled_urls_count": len(uncrawled),
        "uncrawled_urls": uncrawled[:20],
        "sitemap_alt_entries": sitemap_alt_entries,
        "sitemap_alt_codes": sorted(sitemap_alt_codes),
        "sitemap_missing_self_ref": sitemap_missing_self_ref,
        "sitemap_invalid_alt_codes": sitemap_invalid_alt_codes,
        "results": results,
        "generated_at": datetime.utcnow(),
    }
    await db.sitemap_audits.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("Sitemap audit job=%s found=%s valid=%s urls=%s coverage=%s", job_id, summary["sitemap_found"], summary["sitemap_valid"], summary["pages_in_sitemap"], summary["crawled_coverage"])
    return summary