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
        import os
        import pathlib
        sandbox_path = str(pathlib.Path(__file__).resolve().parent.parent.parent / "sandbox" / "static-replica")
        result = subprocess.run(
            ["npx", "vercel", "curl", url],
            cwd=sandbox_path,
            capture_output=True,
            text=True,
            check=True
        )
        html_content = result.stdout
    except subprocess.CalledProcessError as e:
        logger.error("Failed to fetch HTML via vercel curl: %s", e.stderr)
        raise

    # Inject a <base> tag so relative paths resolve to the actual domain when loaded from file://
    if "<head>" in html_content:
        html_content = html_content.replace("<head>", f"<head>\n    <base href=\"{url}\">", 1)
    else:
        # Fallback if no <head> is found
        html_content = f"<head><base href=\"{url}\"></head>\n" + html_content

    # Inline CSS and images to bypass Vercel SSO for static assets when loaded locally
    import re
    import base64
    from urllib.parse import urlparse

    parsed_url = urlparse(url)
    origin = f"{parsed_url.scheme}://{parsed_url.netloc}"

    # 1. Inline CSS
    css_links = re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+\.css)"', html_content)
    for css_path in css_links:
        try:
            css_result = subprocess.run(
                ["npx", "vercel", "curl", f"{origin}{css_path}"],
                cwd=sandbox_path, capture_output=True, text=True, check=True
            )
            css_content = css_result.stdout
            link_pattern = rf'<link[^>]*href="{re.escape(css_path)}"[^>]*>'
            html_content = re.sub(link_pattern, f"<style>{css_content}</style>", html_content)
        except Exception as e:
            logger.error("Failed to inline CSS %s: %s", css_path, e)

    # 2. Inline images (basic ones like the hero image)
    img_srcs = re.findall(r'<img[^>]*src="(/[^"]+\.(?:jpg|jpeg|png|webp|svg))"', html_content)
    for img_path in img_srcs:
        try:
            img_result = subprocess.run(
                ["npx", "vercel", "curl", f"{origin}{img_path}"],
                cwd=sandbox_path, capture_output=True, check=True
            )
            # determine mime type
            ext = img_path.split('.')[-1].lower()
            mime = "image/svg+xml" if ext == "svg" else f"image/{ext}"
            b64 = base64.b64encode(img_result.stdout).decode("utf-8")
            data_uri = f"data:{mime};base64,{b64}"
            # replace src
            html_content = html_content.replace(f'src="{img_path}"', f'src="{data_uri}"')
        except Exception as e:
            logger.error("Failed to inline Image %s: %s", img_path, e)

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
