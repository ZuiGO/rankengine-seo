import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("console", lambda msg: errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)
        
        await page.goto("http://localhost:8001/app", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        
        # Make comparison tab visible and click it
        await page.evaluate("""
            const btn = document.querySelector('.tab[data-tab="sandbox-comparison"]');
            if (btn) { btn.style.display = 'block'; btn.click(); }
        """)
        
        # Wait for comparison data to load
        await page.wait_for_timeout(3000)
        
        # Save screenshot
        await page.screenshot(
            path="/Users/macbook/.gemini/antigravity-ide/brain/585e8d16-3c23-45ea-a3e8-149c40fbe6bd/phase5_comparison.png",
            full_page=True
        )
        
        # Check content
        score_old = await page.evaluate("document.getElementById('comp-score-old') ? document.getElementById('comp-score-old').textContent : 'NOT FOUND'")
        score_new = await page.evaluate("document.getElementById('comp-score-new') ? document.getElementById('comp-score-new').textContent : 'NOT FOUND'")
        delta = await page.evaluate("document.getElementById('comp-score-delta') ? document.getElementById('comp-score-delta').textContent : 'NOT FOUND'")
        fields_count = await page.evaluate("document.querySelectorAll('#comp-fields-tbody tr').length")
        history_count = await page.evaluate("document.querySelectorAll('#comp-raw-history > div').length")
        
        print(f"Score old: {score_old}, new: {score_new}, delta: {delta}")
        print(f"Fields rows: {fields_count}")
        print(f"History items: {history_count}")
        print(f"Console errors: {errors}")
        
        await browser.close()

asyncio.run(main())
