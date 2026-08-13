import base64
import json
import os
import subprocess
from datetime import datetime
from playwright.async_api import async_playwright
import tempfile

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("snapshot")

async def capture_snapshot(url: str, job_id: str | None = None, tag: str = "baseline") -> dict:
    """
    Capture a Playwright full-page screenshot, DOM (outerHTML), and meta tags.
    Persist to MongoDB collection `sandbox_snapshots` under the specified tag.
    Returns the snapshot document.
    """
    logger.info("Capturing %s snapshot for %s", tag, url)
    
    # Use vercel curl to fetch the authenticated HTML, to bypass Vercel SSO
    # We must run this in the static-replica directory or a place where Vercel CLI knows the project, 
    # but vercel curl works anywhere if the URL is a vercel deployment.
    html_content = ""
    try:
        # call vercel curl
        result = subprocess.run(
            ["npx", "vercel", "curl", url],
            capture_output=True,
            text=True,
            check=True
        )
        html_content = result.stdout
    except subprocess.CalledProcessError as e:
        logger.error("Failed to fetch HTML via vercel curl: %s", e.stderr)
        raise

    # Write HTML to a temporary file
    temp_html_path = ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp:
        tmp.write(html_content.encode("utf-8"))
        temp_html_path = tmp.name

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = await browser.new_page()
            
            # Load the local HTML file
            file_url = f"file://{temp_html_path}"
            await page.goto(file_url, wait_until="networkidle")
            
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
            if os.path.exists(temp_html_path):
                os.unlink(temp_html_path)
