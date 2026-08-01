"""End-to-end smoke test for the RankEngine API.

Usage:
    .venv/bin/python scripts/smoke_test.py [--url https://example.com] [--host http://localhost:8001]

Crawls a site, exercises every endpoint, and reports PASS/FAIL per step.
Exits non-zero if any step fails.
"""

import argparse
import asyncio
import sys
import time

import httpx

RESULTS = []
FAILURES = 0


def report(name: str, ok: bool, detail: str = ""):
    global FAILURES
    status = "PASS" if ok else "FAIL"
    if not ok:
        FAILURES += 1
    RESULTS.append(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


async def wait_for_completion(client: httpx.AsyncClient, job_id: str, timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        resp = await client.get(f"/api/analysis/{job_id}")
        job = resp.json()
        last = job
        if job.get("status") in ("completed", "failed"):
            return job
        await asyncio.sleep(2)
    return last or {}


async def main(host: str, url: str):
    async with httpx.AsyncClient(base_url=host, timeout=60) as client:
        # 1. Analysis
        report("start analysis", True, url)
        resp = await client.post("/api/analysis", json={"url": url})
        if resp.status_code not in (200, 201):
            report("POST /api/analysis", False, f"HTTP {resp.status_code}")
            return 1
        job_id = resp.json().get("job_id")
        report("analysis created", bool(job_id), job_id or "")
        job = await wait_for_completion(client, job_id)
        report("analysis completed", job.get("status") == "completed", job.get("status", ""))

        # 2. Summary
        summary = (await client.get(f"/api/analysis/{job_id}/summary")).json()
        report("summary totals", summary.get("total_pages", 0) > 0, f"pages={summary.get('total_pages')} content={summary.get('total_content_items')}")
        ssum = summary.get("summary") or {}
        report("summary phase-1 keys", all(k in ssum for k in ("cwv_pages", "duplicate_pages", "canonical_issues", "structured_data_valid")),
               f"cwv={ssum.get('cwv_pages')} dup={ssum.get('duplicate_pages')} canon={ssum.get('canonical_issues')} sd={ssum.get('structured_data_valid')}")

        # 3. Pages
        pages = (await client.get(f"/api/pages/{job_id}?limit=500")).json()
        report("pages endpoint", pages.get("total", 0) > 0, f"total={pages.get('total')}")
        mobile_pages = sum(1 for p in pages.get("pages", []) if p.get("mobile_status_code") == 200)
        report("mobile crawl pass", mobile_pages > 0, f"mobile_ok={mobile_pages}")

        # 4. Content
        content = (await client.get(f"/api/content/{job_id}?limit=500")).json()
        report("content endpoint", content.get("total", 0) > 0, f"total={content.get('total')}")
        if content.get("items"):
            cid = content["items"][0]["id"]
            detail = (await client.get(f"/api/content/{job_id}/detail/{cid}")).json()
            report("content detail", "content" in detail, "")
            file_url = detail.get("content", {}).get("file_url")
            if file_url:
                fr = await client.get(file_url)
                report("content file serving", fr.status_code == 200, f"{file_url} -> {fr.status_code}")

        # 5. Graph flows
        flows = (await client.get(f"/api/graph/{job_id}/flows")).json()
        report("user flows", "flows" in flows, f"count={len(flows.get('flows', []))}")

        # 6. Links + health
        links = (await client.get(f"/api/links/{job_id}")).json()
        health = (await client.get(f"/api/links/{job_id}/health")).json()
        report("links endpoint", links.get("total_links", 0) > 0, f"links={links.get('total_links')}")
        report("link health", "summary" in health and "issues" in health, "")

        # 7. Actions + approve
        actions = (await client.get(f"/api/actions/{job_id}")).json()
        report("actions endpoint", actions.get("total", 0) > 0, f"total={actions.get('total')}")
        action_id = actions["actions"][0]["id"]
        approv = (await client.post(f"/api/actions/{action_id}/approve", json={"status": "approved"})).json()
        version = approv.get("version") or {}
        report("action approve + version", bool(version), f"field={version.get('field')} qa={version.get('qa')}")
        versions = (await client.get(f"/api/actions/{job_id}/versions")).json()
        report("versions endpoint", versions.get("applied", 0) >= 1, f"applied={versions.get('applied')}")
        bulk = (await client.post(f"/api/actions/{job_id}/approve-all")).json()
        report("approve all starts", bulk.get("status") in ("started", "ok", "running"), f"status={bulk.get('status')} pending={bulk.get('pending')}")

        # 8. Quality endpoints (Phase 1)
        for ep in ("duplicates", "structured-data", "performance", "embeddings"):
            qr = await client.get(f"/api/quality/{job_id}/{ep}")
            ok = qr.status_code == 200
            detail = qr.json() if qr.status_code == 200 else f"HTTP {qr.status_code}"
            report(f"quality {ep}", ok, f"{detail if ep != 'embeddings' else 'indexed=' + str((detail or {}).get('indexed'))}" if not isinstance(detail, str) else str(detail)[:60])

        # 9. Keyword tracking (Phase 1)
        kcheck = (await client.post(f"/api/tracking/{job_id}/check")).json()
        report("tracking check runs", kcheck.get("status") in ("ok", "error") or "ranked" in kcheck, f"status={kcheck.get('status')} ranked={kcheck.get('ranked')}")
        ktrack = (await client.get(f"/api/tracking/{job_id}")).json()
        report("tracking endpoint", "summary" in ktrack and "latest" in ktrack, "")

        # 10. Dummy site
        gen = (await client.post(f"/api/dummy/{job_id}/generate")).json()
        report("dummy site generated", gen.get("file_count", 0) > 0, f"files={gen.get('file_count')} applied={gen.get('changes_applied')}")
        report("dummy has changes", gen.get("changes_applied", 0) >= 1, "")
        report("dummy pending count", gen.get("pending_changes", 0) > 0, f"pending={gen.get('pending_changes')}")
        dstatus = (await client.get(f"/api/dummy/{job_id}")).json()
        report("dummy status endpoint", dstatus.get("status") != "not_generated", "")
        zip_resp = await client.get(f"/api/dummy/{job_id}/download")
        report("dummy zip", zip_resp.status_code == 200 and len(zip_resp.content) > 100, f"{len(zip_resp.content)} bytes")

        # 11. Compare changes
        comp = (await client.post(f"/api/sites/{job_id}/compare-changes")).json()
        report("compare-changes", comp.get("pages_compared", 0) > 0 and "per_page" in comp, f"pages={comp.get('pages_compared')} approved={comp.get('approved_changes')}")
        chtml = (await client.get(f"/api/reports/{job_id}/compare"))
        report("compare report html", chtml.status_code == 200 and b"Comparison" in chtml.content, "")

        # 12. SEO insights (no blank sections — data OR explicit error)
        insights = (await client.get(f"/api/seo-insights/{job_id}")).json()
        for section in ("keywords", "backlinks", "onpage", "overview", "serp"):
            data_key = "serp_rankings" if section == "serp" else section
            has_data = bool(insights.get(data_key))
            has_error = bool(insights.get(f"{section}_error"))
            report(f"insights {data_key}", has_data or has_error,
                   f"data={'yes' if has_data else 'no'} error={'yes' if has_error else 'no'} source={insights.get(section + '_source')}")
        bl = (await client.get(f"/api/seo-insights/{job_id}/backlinks")).json()
        report("insights backlinks list", "backlinks" in bl, f"total={bl.get('total')}")

        # 13. Site health
        health_doc = (await client.get(f"/api/sites/{job_id}/health")).json()
        report("site health", "grade" in health_doc and "score" in health_doc, f"grade={health_doc.get('grade')} score={health_doc.get('score')}")

        # 14. Report JSON + HTML + PDF
        rep = (await client.get(f"/api/reports/{job_id}")).json()
        report("report json", rep.get("total_pages", 0) > 0, "")
        rh = (await client.get(f"/api/reports/{job_id}/download"))
        report("report html", rh.status_code == 200 and b"SEO Analysis Report" in rh.content, "")
        pdf = (await client.get(f"/api/reports/{job_id}/pdf"))
        report("report pdf", pdf.status_code == 200 and pdf.headers.get("content-type", "").startswith("application/pdf"), f"{pdf.headers.get('content-type')} {len(pdf.content)} bytes")

        # 15. Chat
        chat = (await client.post("/api/chat", json={"job_id": job_id, "section": "overview", "message": "Summarize this analysis in one sentence."})).json()
        report("chat reply", bool(chat.get("reply")) and not chat.get("reply", "").startswith("Error"), (chat.get("reply") or "")[:80])

        # 16. Schedules
        sched = (await client.post("/api/scheduler", json={"url": url, "interval_hours": 0.5, "max_pages": 5})).json()
        sid = sched.get("id")
        report("schedule create", bool(sid), f"interval={sched.get('interval_hours')}h")
        scheds = (await client.get("/api/scheduler")).json()
        report("schedule list", any(s.get("id") == sid for s in scheds.get("schedules", [])), "")
        sdel = (await client.delete(f"/api/scheduler/{sid}"))
        report("schedule delete", sdel.status_code == 200, "")

        # 17. Sites list + soft delete + restore
        sites = (await client.get("/api/sites")).json()
        report("sites list", any(s.get("job_id") == job_id for s in sites.get("sites", [])), f"total={sites.get('total')}")
        dresp = (await client.delete(f"/api/sites/{job_id}")).json()
        report("site soft delete", dresp.get("archived") is True, "")
        sites2 = (await client.get("/api/sites")).json()
        report("site hidden after delete", not any(s.get("job_id") == job_id for s in sites2.get("sites", [])), "")
        arch = (await client.get("/api/sites?include_archived=true")).json()
        report("site visible in archived", any(s.get("job_id") == job_id for s in arch.get("sites", [])), "")
        rresp = (await client.post(f"/api/sites/{job_id}/restore")).json()
        report("site restore", rresp.get("archived") is False, "")
        sites3 = (await client.get("/api/sites")).json()
        report("site visible after restore", any(s.get("job_id") == job_id for s in sites3.get("sites", [])), "")

    print("\n" + "=" * 60)
    print(f"RESULT: {len(RESULTS) - FAILURES}/{len(RESULTS)} steps passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RankEngine API smoke test")
    parser.add_argument("--host", default="http://localhost:8001")
    parser.add_argument("--url", default="https://books.toscrape.com")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.host, args.url)))
