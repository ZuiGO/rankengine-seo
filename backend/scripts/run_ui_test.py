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
        
        # wait a bit for fetch
        await page.wait_for_timeout(2000)
        
        html = await page.evaluate("document.getElementById('sandbox-approvals-queue').innerHTML")
        print("QUEUE HTML LENGTH:", len(html))
        
        # Execute scenario
        await page.evaluate('''() => {
            const h3s = Array.from(document.querySelectorAll('#sandbox-approvals-queue h3'));
            const altTextHeader = h3s.find(h => h.innerText.toLowerCase().includes('alt text'));
            if(altTextHeader) {
                const batchBtn = altTextHeader.parentElement.querySelector('button');
                if (batchBtn) batchBtn.click();
            }
        }''')
        await page.wait_for_timeout(500)

        # 2. individually approve the title refinement
        await page.evaluate('''() => {
            const h3s = Array.from(document.querySelectorAll('#sandbox-approvals-queue h3'));
            const titleHeader = h3s.find(h => h.innerText.toLowerCase().includes('title'));
            if(titleHeader) {
                const titleGroup = titleHeader.closest('.approval-group');
                const approveBtn = Array.from(titleGroup.querySelectorAll('button')).find(b => b.innerText.includes('Approve'));
                if (approveBtn) approveBtn.click();
            }
        }''')
        await page.wait_for_timeout(500)
        
        # 3. reject the schema.org suggestion
        await page.evaluate('''() => {
            const h3s = Array.from(document.querySelectorAll('#sandbox-approvals-queue h3'));
            const schemaHeader = h3s.find(h => h.innerText.toLowerCase().includes('schema markup'));
            if(schemaHeader) {
                const schemaGroup = schemaHeader.closest('.approval-group');
                const rejectBtn = Array.from(schemaGroup.querySelectorAll('button')).find(b => b.innerText.includes('Reject'));
                if (rejectBtn) rejectBtn.click();
            }
        }''')
        await page.wait_for_timeout(500)
        
        # 4. edit-then-approve the stale copyright fix
        await page.evaluate('''() => {
            window.prompt = function(msg) {
                return "© 2026 Fluid Controls Limited.";
            };
        }''')
        await page.evaluate('''() => {
            const h3s = Array.from(document.querySelectorAll('#sandbox-approvals-queue h3'));
            const footerHeader = h3s.find(h => h.innerText.toLowerCase().includes('footer copyright'));
            if(footerHeader) {
                const footerGroup = footerHeader.closest('.approval-group');
                const editBtn = Array.from(footerGroup.querySelectorAll('button')).find(b => b.innerText.includes('Edit'));
                if (editBtn) editBtn.click();
            }
        }''')
        
        await page.wait_for_timeout(2000)
        
        await page.screenshot(path="/Users/macbook/.gemini/antigravity-ide/brain/585e8d16-3c23-45ea-a3e8-149c40fbe6bd/sandbox_queue_post_test.png", full_page=True)
        print("Screenshot saved.")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
