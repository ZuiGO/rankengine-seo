import base64
import json
from datetime import datetime
from playwright.async_api import async_playwright

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("snapshot")

async def capture_snapshot(url: str, job_id: str | None = None, tag: str = "baseline", changes: list[dict] | None = None) -> dict:
    """
    Capture a Playwright full-page screenshot directly from the live URL.
    Optionally applies DOM changes via JavaScript injection before taking the snapshot.
    Persists to MongoDB collection `sandbox_snapshots` under the specified tag.
    Returns the snapshot document.
    """
    logger.info("Capturing %s snapshot for %s", tag, url)
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            # Set a standard desktop viewport
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 ZuiGO/1.0"
            )
            page = await context.new_page()
            
            # Navigate directly to the live URL
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # If changes are provided, inject them into the DOM
            if changes:
                inject_script = """
                (changes) => {
                    changes.forEach(change => {
                        const type = change.field_type;
                        const value = change.suggested_value;
                        if (!type || !value) return;
                        
                        if (type === 'title') {
                            document.title = value;
                        } else if (type === 'h1') {
                            const h1 = document.querySelector('h1');
                            if (h1) h1.innerText = value;
                        } else if (type === 'meta_description') {
                            let meta = document.querySelector('meta[name="description"]');
                            if (meta) meta.content = value;
                        } else if (type === 'alt_text') {
                            const images = document.querySelectorAll('img');
                            // Simple heuristic: apply to the first big image or hero image
                            if (images.length > 0) {
                                // Prefer images with classes like hero, banner, main
                                const hero = Array.from(images).find(img => img.className.toLowerCase().includes('hero') || img.src.toLowerCase().includes('hero'));
                                if (hero) hero.alt = value;
                                else images[0].alt = value;
                            }
                        } else if (type === 'h2') {
                            const h2 = document.querySelector('h2');
                            if (h2) h2.innerText = value;
                        } else if (type === 'p_text') {
                            const p = document.querySelector('p');
                            if (p) p.innerText = value;
                        }
                    });
                }
                """
                await page.evaluate(inject_script, changes)
                # Wait briefly for rendering to settle after DOM mutation
                import asyncio
                await asyncio.sleep(1)
            
            # Extract DOM
            dom = await page.evaluate("document.documentElement.outerHTML")
            
            # Extract meta tags
            meta_tags = await page.evaluate('''() => {
                const tags = document.querySelectorAll('meta');
                return Array.from(tags).map(tag => ({
                    name: tag.getAttribute('name') || tag.getAttribute('property') || '',
                    content: tag.getAttribute('content') || ''
                }));
            }''')
            
            # Extract title and H1
            title = await page.title()
            h1 = await page.evaluate("document.querySelector('h1') ? document.querySelector('h1').innerText : ''")
            
            # Full page screenshot
            screenshot_bytes = await page.screenshot(full_page=True, type="jpeg", quality=70)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            
            snapshot = {
                "url": url,
                "job_id": job_id,
                "tag": tag,
                "dom": dom,
                "meta_tags": meta_tags,
                "title": title,
                "h1": h1,
                "screenshot_b64": screenshot_b64,
                "created_at": datetime.utcnow()
            }
            
            db = get_db()
            result = await db.sandbox_snapshots.insert_one(snapshot)
            snapshot["_id"] = str(result.inserted_id)
            
            logger.info("Snapshot %s captured successfully for %s", tag, url)
            return snapshot
            
        except Exception as e:
            logger.error("Failed to capture snapshot for %s: %s", url, e)
            raise
        finally:
            await browser.close()
