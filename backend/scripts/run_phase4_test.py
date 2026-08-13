import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()
        
        page.on("pageerror", lambda err: print("JS Error:", err))
        page.on("console", lambda msg: print("Console:", msg.text))
        
        await page.goto("http://localhost:8001/app#sandbox-approvals", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        
        async def wait_for_api(action_str):
            async with page.expect_response(lambda r: action_str in r.url, timeout=90000) as response_info:
                response = await response_info.value
                data = await response.json()
                print(f"API {action_str} response: {data}")
                await page.wait_for_timeout(2000)
                
        # Helper to get the apply button by field name
        async def click_apply(field_name):
            print(f"Applying {field_name}...")
            await page.evaluate(f'''() => {{
                const h3s = Array.from(document.querySelectorAll('#sandbox-approvals-queue h3'));
                const header = h3s.find(h => h.innerText.toLowerCase().includes('{field_name.lower()}'));
                if(header) {{
                    const group = header.closest('.approval-group');
                    const btn = Array.from(group.querySelectorAll('button')).find(b => b.innerText.includes('Apply to Sandbox') || b.innerText.includes('Retry Apply'));
                    if (btn) btn.click();
                }}
            }}''')
            try:
                await wait_for_api('/apply')
            except Exception as e:
                print(f"Error waiting for apply API: {e}")
            
        async def click_rollback(field_name):
            print(f"Rolling back {field_name}...")
            await page.evaluate(f'''() => {{
                const h3s = Array.from(document.querySelectorAll('#sandbox-approvals-queue h3'));
                const header = h3s.find(h => h.innerText.toLowerCase().includes('{field_name.lower()}'));
                if(header) {{
                    const group = header.closest('.approval-group');
                    const btn = Array.from(group.querySelectorAll('button')).find(b => b.innerText.includes('Rollback'));
                    if (btn) btn.click();
                }}
            }}''')
            try:
                await wait_for_api('/rollback')
            except Exception as e:
                print(f"Error waiting for rollback API: {e}")
            
        # a. Apply title refinement
        await click_apply('title')
        await page.screenshot(path="/Users/macbook/.gemini/antigravity-ide/brain/585e8d16-3c23-45ea-a3e8-149c40fbe6bd/phase4_a_title.png")
        
        # b. Apply alt-text fix
        await click_apply('alt text')
        await page.screenshot(path="/Users/macbook/.gemini/antigravity-ide/brain/585e8d16-3c23-45ea-a3e8-149c40fbe6bd/phase4_b_alt.png")
        
        # c. Rollback alt-text
        await click_rollback('alt text')
        await page.screenshot(path="/Users/macbook/.gemini/antigravity-ide/brain/585e8d16-3c23-45ea-a3e8-149c40fbe6bd/phase4_c_rollback_alt.png")
        
        # d. Re-apply alt-text, then apply footer copyright
        await click_apply('alt text')
        await click_apply('footer copyright')
        await page.screenshot(path="/Users/macbook/.gemini/antigravity-ide/brain/585e8d16-3c23-45ea-a3e8-149c40fbe6bd/phase4_d_reapply_alt_footer.png")
        
        print("Done Phase 4 testing")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
