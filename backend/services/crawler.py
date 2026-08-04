import asyncio
import email.utils
from datetime import datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from backend.config import settings
from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.content_classifier import detect_content_types
from backend.services.content_downloader import download_content
from backend.services.seo_analyzer import analyze_content_item
from backend.services.page_classifier import classify_page_type, page_role
from backend.services.url_normalizer import normalize_url

logger = get_logger("crawler")

MAX_HTML_STORED = 300_000
USER_AGENT = "ZuiGO.ai/1.0 (+https://zuigo.ai)"


async def _robots_delay(origin: str) -> float:
    """Crawl-delay from robots.txt (clamped), falling back to the configured default."""
    delay = settings.crawl_politeness_delay
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(origin + "/robots.txt", headers={"User-Agent": USER_AGENT})
        if resp.status_code == 200:
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            for agent in (USER_AGENT.split("/")[0], "*"):
                d = rp.crawl_delay(agent)
                if d is not None:
                    try:
                        delay = min(max(float(d), 0.2), settings.crawl_robots_delay_max)
                    except ValueError:
                        pass
                    break
    except Exception as e:
        logger.warning("robots.txt fetch failed for %s: %s", origin, e)
    return delay


async def _goto_polite(page, url: str, gate: asyncio.Lock, delay: float, timeout: int = 30000):
    """Sequential-min-interval gate + one retry on 429."""
    async with gate:
        await asyncio.sleep(delay)
    resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    if resp is not None and resp.status == 429:
        logger.warning("429 for %s; backing off before retry", url)
        await asyncio.sleep(min(15, 2 * delay + 2))
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    return resp


async def crawl_site(job_id: str, target_url: str, max_pages: int = 50, concurrency: int = 5):
    db = get_db()
    target_url = normalize_url(target_url) or target_url
    parsed = urlparse(target_url)
    base_domain = parsed.netloc.lower()

    visited = set()
    queue = [target_url]
    crawled_pages = []
    total_internal = 0
    total_external = 0
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(concurrency)
    downloaded_urls = set()
    delay = await _robots_delay(f"{parsed.scheme}://{parsed.netloc}")
    gate = asyncio.Lock()
    logger.info("Crawl politeness job=%s delay=%.2fs", job_id, delay)

    async def update_progress(crawled: int, msg: str):
        await db.analysis_jobs.update_one(
            {"_id": job_id},
            {"$set": {
                "progress": int((crawled / max_pages) * 100),
                "progress_message": msg,
            }}
        )

    async def crawl_and_process(browser, url: str):
        nonlocal total_internal, total_external
        async with semaphore:
            try:
                page = await browser.new_page()
                await page.set_extra_http_headers({
                    "User-Agent": USER_AGENT
                })
                resp = await _goto_polite(page, url, gate, delay)
                if resp is None:
                    await page.close()
                    return None

                html = await page.content()
                await page.close()

                soup = BeautifulSoup(html, "lxml")

                title_tag = soup.find("title")
                title = title_tag.get_text(strip=True) if title_tag else ""
                meta_desc = soup.find("meta", attrs={"name": "description"})
                meta_description = meta_desc.get("content", "") if meta_desc else ""
                body_text = soup.get_text(separator=" ", strip=True)
                word_count = len(body_text.split())
                h1_count = len(soup.find_all("h1"))

                images = soup.find_all("img")
                image_count = len(images)
                images_missing_alt = sum(1 for img in images if not img.get("alt"))

                internal_urls = []
                external_urls = []
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"].strip()
                    full_url = urljoin(url, href)
                    norm = normalize_url(full_url)
                    if not norm:
                        continue
                    full_parsed = urlparse(norm)
                    if full_parsed.netloc == base_domain or not full_parsed.netloc:
                        internal_urls.append(norm)
                    elif full_parsed.netloc and full_parsed.netloc != base_domain:
                        external_urls.append(norm)

                has_structured_data = bool(soup.find("script", type="application/ld+json"))
                noindex = False
                robots_meta = soup.find("meta", attrs={"name": "robots"})
                if robots_meta:
                    noindex = "noindex" in robots_meta.get("content", "").lower()

                page_type = classify_page_type(url, soup, title, meta_description)

                last_modified = None
                try:
                    lm = resp.headers.get("last-modified") if resp and resp.headers else None
                    if lm:
                        last_modified = datetime.fromtimestamp(email.utils.parsedate_to_datetime(lm).timestamp())
                except Exception:
                    last_modified = None

                items = detect_content_types(url, html)

                downloaded_types = set()
                download_sem = asyncio.Semaphore(settings.download_concurrency)

                async def _fetch_one(item):
                    if item["source_url"] in downloaded_urls:
                        return None
                    downloaded_urls.add(item["source_url"])
                    async with download_sem:
                        dl = await download_content(item["source_url"], job_id, url)
                    if not dl:
                        downloaded_urls.discard(item["source_url"])
                    return (item, dl)

                fetched = await asyncio.gather(*[_fetch_one(item) for item in items])

                for item, dl in [f for f in fetched if f is not None]:
                    doc = {
                        "job_id": job_id,
                        "page_url": url,
                        "content_type": item["type"],
                        "source_url": item["source_url"],
                        "file_path": dl.get("file_path") if dl else None,
                        "file_size": dl.get("file_size") if dl else None,
                        "mime_type": dl.get("mime_type") if dl else None,
                        "alt": item.get("alt", ""),
                        "link_text": item.get("text", ""),
                        "width": item.get("width"),
                        "height": item.get("height"),
                    }
                    result = await db.content_items.insert_one(doc)
                    doc["_id"] = str(result.inserted_id)
                    await analyze_content_item(doc, url, job_id)
                    downloaded_types.add(item["type"])

                async with lock:
                    total_internal += len(internal_urls)
                    total_external += len(external_urls)

                return {
                    "url": url,
                    "title": title,
                    "meta_description": meta_description,
                    "page_type": page_type,
                    "page_role": page_role(page_type),
                    "word_count": word_count,
                    "status_code": resp.status,
                    "h1_count": h1_count,
                    "image_count": image_count,
                    "images_missing_alt": images_missing_alt,
                    "internal_links": len(internal_urls),
                    "external_links": len(external_urls),
                    "has_structured_data": has_structured_data,
                    "is_indexable": not noindex,
                    "content_types": list(downloaded_types),
                    "last_modified": last_modified,
                    "internal_link_urls": internal_urls,
                    "external_link_urls": external_urls,
                    "html": html[:MAX_HTML_STORED],
                }

            except Exception as e:
                logger.error("Crawl error for %s: %s", url, e)
                return None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        crawled = 0
        while queue and crawled < max_pages:
            batch_size = min(concurrency, max_pages - crawled)
            batch = queue[:batch_size]
            queue[:] = queue[concurrency:]

            tasks = []
            urls_to_crawl = []
            for u in batch:
                if u not in visited:
                    visited.add(u)
                    urls_to_crawl.append(u)

            for u in urls_to_crawl:
                tasks.append(crawl_and_process(browser, u))

            results = await asyncio.gather(*tasks)

            for result in results:
                if result:
                    crawled += 1
                    crawled_pages.append(result)

                    new_urls = []
                    for link in result.get("internal_link_urls", []):
                        clean = normalize_url(link)
                        if not clean:
                            continue
                        if clean not in visited and clean not in queue:
                            new_urls.append(clean)
                    queue.extend(new_urls)

                    page_for_db = dict(result)
                    page_for_db.pop("internal_link_urls", None)
                    page_for_db.pop("external_link_urls", None)
                    await db.pages.insert_one({"job_id": job_id, **page_for_db})

                    await db.page_links.insert_one({
                        "job_id": job_id,
                        "url": result["url"],
                        "internal_link_urls": result.get("internal_link_urls", []),
                        "external_link_urls": result.get("external_link_urls", []),
                    })

                    await update_progress(crawled, f"Crawled {urlparse(result['url']).path or '/'}")

        await browser.close()

        mobile_ok = 0
        try:
            mobile_browser = await pw.chromium.launch(headless=True)
            iphone = pw.devices["iPhone 13"]
            mobile_sem = asyncio.Semaphore(settings.mobile_crawl_concurrency)
            mobile_lock = asyncio.Lock()

            async def mobile_pass(url: str):
                nonlocal mobile_ok
                async with mobile_sem:
                    try:
                        page = await mobile_browser.new_page(**iphone)
                        await page.set_extra_http_headers({"User-Agent": USER_AGENT})
                        resp = await _goto_polite(page, url, gate, delay)
                        mhtml = await page.content()
                        await page.close()
                        status = resp.status if resp is not None else None
                        await db.pages.update_one(
                            {"job_id": job_id, "url": url},
                            {"$set": {
                                "html_mobile": mhtml[:MAX_HTML_STORED],
                                "mobile_status_code": status,
                                "viewport": "mobile",
                            }},
                        )
                        async with mobile_lock:
                            mobile_ok += 1
                    except Exception as me:
                        logger.error("Mobile crawl error for %s: %s", url, me)

            await asyncio.gather(*[mobile_pass(result["url"]) for result in crawled_pages])
            await mobile_browser.close()
        except Exception as mb_err:
            logger.error("Mobile crawl pass failed job=%s: %s", job_id, mb_err)

    total_links = total_internal + total_external
    summary = {
        "total_pages": len(crawled_pages),
        "total_links": total_links,
        "total_internal_links": total_internal,
        "total_external_links": total_external,
        "mobile_pages": mobile_ok,
    }

    return summary
