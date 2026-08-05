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
USER_AGENT = "ZuiGO.ai/1.0 sitemap-audit (+https://zuigo.ai)"

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
    try:
        root = ElementTree.fromstring(xml_text)
    except Exception:
        return None
    tag = root.tag.split("}")[-1].lower()
    urls: list[str] = []
    if tag == "urlset":
        for child in root:
            name = child.tag.split("}")[-1].lower()
            if name == "url":
                loc = child.findtext("{*}loc")
                if loc:
                    urls.append(loc.strip())
    elif tag in ("sitemapindex", "sitemap"):
        for child in root:
            if child.tag.split("}")[-1].lower() == "sitemap":
                loc = child.findtext("{*}loc")
                if loc:
                    nested = await _fetch(loc.strip())
                    if nested:
                        urls.extend(await _parse_sitemap_urls(nested) or [])
    return urls


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
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        text = await _fetch(cand)
        if text is None:
            results.append({"url": cand, "found": False})
            continue
        urls = await _parse_sitemap_urls(text)
        if urls is None:
            results.append({"url": cand, "found": True, "valid": False})
        else:
            results.append({"url": cand, "found": True, "valid": True, "url_count": len(urls)})

    pages = await db.pages.find({"job_id": job_id}, {"url": 1}).to_list(length=None)
    crawled = {normalize_url(p.get("url", "")) for p in pages if normalize_url(p.get("url", ""))}

    uncrawled = []
    for r in results:
        if r.get("valid"):
            text = await _fetch(r["url"])
            if text:
                for u in (await _parse_sitemap_urls(text) or []):
                    nu = normalize_url(u)
                    if nu and nu not in crawled and nu not in uncrawled:
                        uncrawled.append(nu)
                        if len(uncrawled) >= 200:
                            break

    summary = {
        "job_id": job_id,
        "sitemap_found": any(r.get("found") for r in results),
        "sitemap_valid": any(r.get("valid") for r in results),
        "sitemap_count": len(results),
        "url_count": sum(r.get("url_count", 0) for r in results),
        "uncrawled_urls_count": len(uncrawled),
        "uncrawled_urls": uncrawled[:20],
        "results": results,
        "generated_at": datetime.utcnow(),
    }
    await db.sitemap_audits.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("Sitemap audit job=%s found=%s valid=%s urls=%s", job_id, summary["sitemap_found"], summary["sitemap_valid"], summary["url_count"])
    return summary