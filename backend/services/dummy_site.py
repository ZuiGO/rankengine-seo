import asyncio
import io
import os
import zipfile
from datetime import datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("dummy_site")

DUMMY_ROOT = "dummy_site"
FETCH_CONCURRENCY = 5
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

MIRROR_SYMBOLIC = {
    "ok": "#16a34a",
    "redirect": "#d97706",
    "blocked": "#dc2626",
    "broken": "#dc2626",
    "timeout": "#dc2626",
    "error": "#dc2626",
    "unknown": "#6b7280",
}


def url_to_mirror_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return "index.html"
    last = path.split("/")[-1]
    if "." in last:
        return path
    return path + "/index.html"


def _normalize_page_url(url: str) -> str:
    """Normalize page URLs so '/', '/index.html' and ''-variants match."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith("/index.html"):
        path = path[:-len("/index.html")]
    return f"{parsed.scheme}://{parsed.netloc}{path}".lower()


def _sanitize_path(path: str) -> str:
    return path.replace("..", "").lstrip("/")


_shared_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.AsyncClient(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            },
            follow_redirects=True,
            timeout=httpx.Timeout(20, connect=10),
            limits=httpx.Limits(max_keepalive_connections=8),
        )
    return _shared_client


async def _fetch_html(url: str) -> tuple[str | None, int | None]:
    last_status: int | None = None
    for attempt in range(2):
        try:
            resp = await _get_client().get(url)
            last_status = resp.status_code
            if resp.status_code in (403, 429) or resp.status_code >= 500:
                if attempt == 0:
                    await asyncio.sleep(2 + attempt)
                    continue
            if resp.status_code >= 400:
                return None, resp.status_code
            return resp.text, resp.status_code
        except Exception:
            last_status = None
            if attempt == 0:
                await asyncio.sleep(2 + attempt)
    return None, last_status


async def _apply_changes(soup: BeautifulSoup, job_id: str, page_url: str) -> tuple[int, int]:
    """Apply approved content versions to the mirror. Returns (applied, pending_action_count)."""
    db = get_db()
    applied = 0
    versions = await db.content_versions.find({
        "job_id": job_id,
        "status": "approved",
        "after": {"$ne": None},
    }).to_list(length=1000)

    normalized = _normalize_page_url(page_url)
    for v in versions:
        if _normalize_page_url(v.get("page_url", "")) != normalized:
            continue
        field = v.get("field")
        after = v.get("after", "")
        if not after:
            continue
        comment = BeautifulSoup(f"<!-- SEO_CHANGE_APPLIED: {field} -->", "lxml")
        changed = False
        if field == "meta_description":
            meta = soup.find("meta", attrs={"name": "description"})
            if meta:
                meta["content"] = after
                meta.insert_before(comment)
                changed = True
        elif field == "title":
            title_tag = soup.find("title")
            if title_tag:
                title_tag.string = after
                title_tag.insert_before(comment)
                changed = True
        elif field == "alt_text":
            src = v.get("source_url", "")
            filename = src.split("/")[-1]
            img = (
                soup.find("img", src=src)
                or soup.find("img", src=lambda s: s and s.split("/")[-1] == filename)
            )
            if img:
                img["alt"] = after
                img.insert_before(comment)
                changed = True
        elif field == "link_text":
            href = v.get("source_url", "")
            filename = href.split("/")[-1]
            a_tag = (
                soup.find("a", href=href)
                or soup.find("a", href=lambda s: s and s.split("/")[-1] == filename)
            )
            if a_tag:
                a_tag.string = after
                a_tag.insert_before(comment)
                changed = True
        if changed:
            applied += 1

    pending_actions = await db.action_items.find({
        "job_id": job_id,
        "status": "pending",
    }).to_list(length=1000)
    pending = sum(
        1
        for a in pending_actions
        if _normalize_page_url(a.get("page_url", "")) == normalized
    )
    return applied, pending


async def _link_health_banner(soup: BeautifulSoup, job_id: str, page_url: str) -> str:
    db = get_db()
    issues = await db.link_health.find({
        "job_id": job_id,
        "status": {"$in": ["broken", "timeout", "error", "blocked"]},
        "pages": page_url,
    }).to_list(length=20)
    if not issues:
        return ""
    rows = "".join(
        f"<li><code>{i.get('url', '')}</code> - {i.get('status', '')}"
        f"{(' (' + str(i.get('status_code')) + ')') if i.get('status_code') else ''}</li>"
        for i in issues
    )
    return (
        '<div style="background:#fef2f2;color:#991b1b;border:1px solid #fecaca;padding:12px 16px;'
        'font-family:-apple-system,sans-serif;font-size:13px;margin-bottom:16px">'
        f'<strong>Link Health ({len(issues)} issue(s)):</strong><ul style="margin:8px 0 0;padding-left:20px">{rows}</ul></div>'
    )


async def _pending_suggestions_banner(soup: BeautifulSoup, job_id: str, page_url: str) -> str:
    db = get_db()
    normalized = _normalize_page_url(page_url)
    actions = await db.action_items.find({
        "job_id": job_id,
        "status": "pending",
    }).to_list(length=100)
    relevant = [
        a for a in actions
        if _normalize_page_url(a.get("page_url", "")) == normalized
    ]
    if not relevant:
        return ""
    seen = {}
    for a in relevant:
        first = (a.get("improvement_suggestions") or [""])[0]
        key = (a.get("content_type", ""), first)
        count, impact = seen.get(key, (0, a.get("impact_on_ranking", "medium")))
        seen[key] = (count + 1, impact)
    rows = ""
    for (ctype, first), (count, impact) in list(seen.items())[:10]:
        label = f"{count} item{'s' if count > 1 else ''}" if count > 1 else ""
        rows += (
            f"<li><strong>{ctype}</strong>"
            f"{(' — ' + first) if first else ''} "
            f"<a style=\"color:#92400e\" href=\"#\" onclick=\"return false\">"
            f"(suggested {impact} impact)</a>"
            f"{(' — ' + label) if label else ''}</li>"
        )
    return (
        '<div style="background:#fffbeb;color:#92400e;border:1px solid #fde68a;padding:12px 16px;'
        'font-family:-apple-system,sans-serif;font-size:13px;margin-bottom:16px">'
        f'<strong>Pending SEO Suggestions ({len(relevant)}):</strong>'
        f'<ul style="margin:8px 0 0;padding-left:20px">{rows}</ul>'
        '<div style="font-size:11px;margin-top:6px">Approve or reject these in the SEO Actions tab, '
        'then regenerate this dummy site to apply them.</div></div>'
    )


def _rewrite_internal_links(soup: BeautifulSoup, job_id: str, base_url: str, mirror_urls: set) -> int:
    base_host = urlparse(base_url).netloc
    rewritten = 0
    for tag in soup.find_all(["a", "img", "link", "script", "source"]):
        attr = "href" if tag.name in ("a", "link") else ("src" if tag.name in ("img", "script", "source") else None)
        if not attr or not tag.get(attr):
            continue
        raw = tag[attr].strip()
        if raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:", "//")):
            continue
        from urllib.parse import urljoin
        full = urljoin(base_url, raw)
        parsed = urlparse(full)
        if parsed.netloc != base_host:
            continue
        if _normalize_page_url(full) not in mirror_urls:
            continue
        tag[attr] = f"/dummy/{job_id}/" + url_to_mirror_path(full)
        rewritten += 1
    return rewritten


async def generate_dummy_site(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}).to_list(length=None)
    if not pages:
        return {"status": "error", "message": "No pages for this job"}

    base_url = (await db.analysis_jobs.find_one({"_id": job_id}) or {}).get("url", "")
    mirror_urls = {_normalize_page_url(p["url"]) for p in pages}
    target_dir = os.path.join(DUMMY_ROOT, job_id)
    os.makedirs(target_dir, exist_ok=True)

    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def fetch_and_build(page: dict):
        async with semaphore:
            url = page["url"]
            rel_path = _sanitize_path(url_to_mirror_path(url))
            html = page.get("html")
            status_code = page.get("status_code")
            if not html:
                html, status_code = await _fetch_html(url)
            if not html:
                html = (
                    f"<!DOCTYPE html><html><head><title>{page.get('title', '')}</title></head>"
                    f"<body><h1>Mirror unavailable</h1><p>Original page returned HTTP {status_code}.</p></body></html>"
                )
            soup = BeautifulSoup(html, "lxml")
            applied, pending = await _apply_changes(soup, job_id, url)
            rewritten = _rewrite_internal_links(soup, job_id, url, mirror_urls)
            banner = await _link_health_banner(soup, job_id, url)
            if banner:
                body = soup.find("body")
                if body:
                    body.insert(0, BeautifulSoup(banner, "lxml"))
            pending_banner = await _pending_suggestions_banner(soup, job_id, url)
            if pending_banner:
                body = soup.find("body")
                if body:
                    body.insert(0, BeautifulSoup(pending_banner, "lxml"))
            file_path = os.path.join(target_dir, rel_path)
            os.makedirs(os.path.dirname(file_path) or target_dir, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(str(soup))
            return {"page": url, "file": rel_path, "status_code": status_code, "changes_applied": applied, "pending_changes": pending, "links_rewritten": rewritten}

    results = []
    for chunk in [pages[i:i + FETCH_CONCURRENCY] for i in range(0, len(pages), FETCH_CONCURRENCY)]:
        chunk_results = await asyncio.gather(*[fetch_and_build(p) for p in chunk])
        results.extend(chunk_results)

    file_count = sum(1 for r in os.walk(target_dir) for _ in r[2])
    summary = {
        "job_id": job_id,
        "base_url": base_url,
        "generated_at": datetime.utcnow(),
        "file_count": file_count,
        "pages": len(pages),
        "changes_applied": sum(r["changes_applied"] for r in results),
        "pending_changes": sum(r["pending_changes"] for r in results),
        "links_rewritten": sum(r["links_rewritten"] for r in results),
    }
    await db.dummy_sites.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info(
        "Dummy site generated job=%s files=%s applied=%s pending=%s",
        job_id, file_count, summary["changes_applied"], summary["pending_changes"],
    )
    return summary


async def get_dummy_site(job_id: str) -> dict:
    db = get_db()
    doc = await db.dummy_sites.find_one({"job_id": job_id})
    if not doc:
        return {"status": "not_generated", "job_id": job_id}
    doc["id"] = str(doc.pop("_id"))
    doc["url"] = f"/dummy/{job_id}/index.html"
    generated_at = doc.get("generated_at")
    doc["stale"] = False
    if generated_at:
        newer_versions = await db.content_versions.count_documents({
            "job_id": job_id,
            "status": "approved",
            "reviewed_at": {"$gt": generated_at},
        })
        doc["stale"] = newer_versions > 0
    return doc


async def regenerate_after_change(job_id: str) -> None:
    """Rebuild the dummy site after an approve/reject if it already exists."""
    db = get_db()
    existing = await db.dummy_sites.find_one({"job_id": job_id})
    if not existing or not existing.get("file_count"):
        return
    try:
        await generate_dummy_site(job_id)
        logger.info("Dummy site auto-regenerated after review job=%s", job_id)
    except Exception as e:
        logger.warning("Dummy site auto-regeneration failed job=%s: %s", job_id, e)


async def dummy_site_zip(job_id: str) -> bytes | None:
    target_dir = os.path.join(DUMMY_ROOT, job_id)
    if not os.path.isdir(target_dir):
        return None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(target_dir):
            for name in files:
                full = os.path.join(root, name)
                arc = os.path.relpath(full, DUMMY_ROOT)
                zf.write(full, arc)
    buffer.seek(0)
    return buffer.read()
