"""Compare the analysed (original) site against the dummy site with suggested changes."""

import os
import re
from datetime import datetime

from bs4 import BeautifulSoup

from backend.db.mongo import get_db
from backend.services.dummy_site import (
    DUMMY_ROOT,
    _fetch_html,
    _normalize_page_url,
    get_dummy_site,
    generate_dummy_site,
    url_to_mirror_path,
)


def _title(soup: BeautifulSoup) -> str:
    t = soup.find("title")
    return (t.get_text(strip=True) if t else "") or ""


def _meta_description(soup: BeautifulSoup) -> str:
    m = soup.find("meta", attrs={"name": "description"})
    return (m.get("content") or "").strip() if m else ""


def _image_alt_map(soup: BeautifulSoup) -> dict:
    out = {}
    for img in soup.find_all("img"):
        src = (img.get("src") or "").split("/")[-1]
        if not src:
            continue
        out[src] = (img.get("alt") or "").strip()
    return out


def _link_health_after(job_id: str) -> dict:
    target_dir = os.path.join(DUMMY_ROOT, job_id)
    ok = 0
    broken = 0
    checked = 0
    if os.path.isdir(target_dir):
        pattern = re.compile(rf"/dummy/{re.escape(job_id)}/")
        for root, _dirs, files in os.walk(target_dir):
            for name in files:
                if not name.endswith(".html"):
                    continue
                with open(os.path.join(root, name), encoding="utf-8", errors="ignore") as f:
                    html = f.read()
                for match in re.finditer(r'(?:href|src)="(/dummy/[^"]+)"', html):
                    path = match.group(1).split("#")[0].split("?")[0].lstrip("/")
                    full = os.path.join(DUMMY_ROOT, path)
                    checked += 1
                    if os.path.isfile(full):
                        ok += 1
                    else:
                        broken += 1
    return {
        "checked": checked,
        "ok": ok,
        "broken": broken,
        "broken_rate": round(100 * broken / checked, 1) if checked else None,
    }


async def _fetch_page(url: str) -> tuple[str, BeautifulSoup | None]:
    html, _ = await _fetch_html(url)
    return url, (BeautifulSoup(html, "lxml") if html is not None else None)


async def compare_site_with_changes(job_id: str) -> dict:
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"status": "error", "message": "Job not found"}

    pages = await db.pages.find({"job_id": job_id}).to_list(length=None)
    if not pages:
        return {"status": "error", "message": "No pages for this job"}

    dummy = await get_dummy_site(job_id)
    if dummy.get("status") == "not_generated" or not dummy.get("file_count"):
        await generate_dummy_site(job_id)
        dummy = await get_dummy_site(job_id)

    target_dir = os.path.join(DUMMY_ROOT, job_id)
    per_page = []
    alt_added_before = 0
    alt_added_after = 0
    total_images_before = 0
    total_images_after = 0
    fetch_failures = []

    import asyncio
    sem = asyncio.Semaphore(8)
    fetch_map: dict[str, BeautifulSoup | None] = {}

    async def _bounded(url: str) -> None:
        async with sem:
            u, soup = await _fetch_page(url)
            fetch_map[u] = soup

    await asyncio.gather(*(_bounded(p["url"]) for p in pages))

    for page in pages:
        url = page["url"]
        before = fetch_map.get(url)
        if before is None:
            fetch_failures.append(url)
            continue
        rel = url_to_mirror_path(url)
        mirror_file = os.path.join(target_dir, rel)
        after = None
        if os.path.isfile(mirror_file):
            with open(mirror_file, encoding="utf-8", errors="ignore") as f:
                after = BeautifulSoup(f.read(), "lxml")

        before_alts = _image_alt_map(before)
        after_alts = _image_alt_map(after) if after else {}
        missing_before = sum(1 for a in before_alts.values() if not a)
        missing_after = sum(1 for a in after_alts.values() if not a)
        alt_changed = 0
        for src, alt in before_alts.items():
            if alt and after_alts.get(src) and after_alts[src] != alt and after_alts[src]:
                alt_changed += 1
        total_images_before += len(before_alts)
        total_images_after += len(after_alts)
        alt_added_before += missing_before
        alt_added_after += missing_after

        per_page.append({
            "url": url,
            "title_before": _title(before)[:200],
            "title_after": _title(after)[:200] if after else "",
            "title_changed": bool(after) and _title(before) != _title(after),
            "meta_before": _meta_description(before)[:200],
            "meta_after": _meta_description(after)[:200] if after else "",
            "meta_changed": bool(after) and _meta_description(before) != _meta_description(after),
            "images_before": len(before_alts),
            "images_after": len(after_alts) if after else 0,
            "alt_missing_before": missing_before,
            "alt_missing_after": missing_after,
            "alt_texts_changed": alt_changed,
        })

    link_health_before = await db.link_health_summaries.find_one({"job_id": job_id})
    before_counts = link_health_before or {}

    versions = await db.content_versions.count_documents({"job_id": job_id, "status": "approved", "after": {"$ne": None}})
    pending = await db.action_items.count_documents({"job_id": job_id, "status": "pending"})

    summary = {
        "job_id": job_id,
        "base_url": job.get("url", ""),
        "generated_at": datetime.utcnow(),
        "pages_compared": len(per_page),
        "pages_fetch_failed": len(fetch_failures),
        "fetch_error": f"Could not re-fetch {len(fetch_failures)} page(s): " + "; ".join(fetch_failures[:3]) if fetch_failures else None,
        "approved_changes": versions,
        "pending_suggestions": pending,
        "dummy": {k: dummy.get(k) for k in ("file_count", "changes_applied", "pending_changes", "generated_at")},
        "alt_text": {
            "images_before": total_images_before,
            "images_after": total_images_after,
            "missing_before": alt_added_before,
            "missing_after": alt_added_after,
            "coverage_before": round(100 * (total_images_before - alt_added_before) / total_images_before) if total_images_before else None,
            "coverage_after": round(100 * (total_images_after - alt_added_after) / total_images_after) if total_images_after else None,
        },
        "link_health_before": {
            "checked": before_counts.get("checked", 0),
            "ok": before_counts.get("ok", 0),
            "broken": before_counts.get("broken", 0) + before_counts.get("timeout", 0) + before_counts.get("error", 0) + before_counts.get("blocked", 0),
        },
        "link_health_after": _link_health_after(job_id),
        "per_page": per_page,
    }
    await db.site_comparisons.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    return summary


async def get_site_comparison(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.site_comparisons.find_one({"job_id": job_id})
    return doc
