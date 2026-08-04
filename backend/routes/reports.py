import json
from datetime import datetime
from fastapi import APIRouter, Response

from backend.db.mongo import get_db
from backend.services.user_flow import get_top_flows

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/{job_id}")
async def generate_report(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}

    page_count = await db.pages.count_documents({"job_id": job_id})
    content_count = await db.content_items.count_documents({"job_id": job_id})

    content_pipeline = [
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$content_type", "count": {"$sum": 1}}}
    ]
    content_breakdown = {}
    cursor = db.content_items.aggregate(content_pipeline)
    async for row in cursor:
        content_breakdown[row["_id"]] = row["count"]

    page_type_pipeline = [
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$page_type", "count": {"$sum": 1}}}
    ]
    page_type_breakdown = {}
    cursor = db.pages.aggregate(page_type_pipeline)
    async for row in cursor:
        page_type_breakdown[row["_id"]] = row["count"]

    action_cursor = db.action_items.find({"job_id": job_id})
    action_items_list = []
    async for a in action_cursor:
        action_items_list.append({
            "content_type": a.get("content_type"),
            "impact_on_ranking": a.get("impact_on_ranking"),
            "identified_issues": a.get("identified_issues", []),
            "how_to_improve": a.get("improvement_suggestions", []),
            "status": a.get("status"),
        })

    cached_insights = await db.seo_insights_cache.find_one({"job_id": job_id})
    insights = cached_insights.get("data", {}) if cached_insights else {}

    try:
        top_flows = await get_top_flows(job_id, limit=10)
    except Exception:
        top_flows = []

    try:
        from backend.services.backlinks import get_backlinks
        backlink_sources = await get_backlinks(job_id, limit=20)
    except Exception:
        backlink_sources = {"backlinks": [], "total": 0, "referring_domains": 0}

    try:
        from backend.services.change_applier import get_content_versions
        content_versions = await get_content_versions(job_id, limit=200)
    except Exception:
        content_versions = {"versions": [], "total": 0, "applied": 0}

    summary = job.get("summary", {})
    report = {
        "report_title": f"SEO Analysis Report - {job.get('url', '')}",
        "generated_at": datetime.utcnow().isoformat(),
        "url": job.get("url", ""),
        "total_pages": page_count,
        "total_content_items": content_count,
        "total_links": summary.get("total_links", 0),
        "total_internal_links": summary.get("total_internal_links", 0),
        "total_external_links": summary.get("total_external_links", 0),
        "content_breakdown": content_breakdown,
        "page_type_breakdown": page_type_breakdown,
        "user_flows": top_flows,
        "backlink_sources": backlink_sources,
        "content_versions": content_versions,
        "seo_action_items": action_items_list,
        "seo_insights": insights,
        "geo_readiness": summary.get("geo_readiness"),
    }

    try:
        from backend.services.site_health import get_site_health
        health = await get_site_health(job_id)
        health.pop("_id", None)
        report["site_health"] = health
    except Exception:
        report["site_health"] = None

    return report


async def _report_html(job_id: str) -> str:
    from fastapi.responses import HTMLResponse  # noqa: F401 (kept for parity)

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}

    page_count = await db.pages.count_documents({"job_id": job_id})

    summary = job.get("summary", {})
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>SEO Report - {job.get('url', '')}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; color: #333; }}
h1 {{ color: #111; border-bottom: 3px solid #6366f1; padding-bottom: 10px; }}
table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #e5e7eb; }}
th {{ background: #f9fafb; font-weight: 600; }}
.section {{ margin: 30px 0; }}
.card {{ background: #f9fafb; border-radius: 8px; padding: 20px; margin: 10px 0; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
.badge-high {{ background: #fef2f2; color: #dc2626; }}
.badge-medium {{ background: #fffbeb; color: #d97706; }}
.badge-low {{ background: #f0fdf4; color: #16a34a; }}
</style>
</head>
<body>
<h1>SEO Analysis Report</h1>
<p>URL: <strong>{job.get('url', '')}</strong></p>
<p>Generated: {datetime.utcnow().isoformat()}</p>

<div class="section">
<h2>Overview</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Pages Crawled</td><td>{page_count}</td></tr>
<tr><td>Total Links</td><td>{summary.get('total_links', 0)}</td></tr>
<tr><td>Internal Links</td><td>{summary.get('total_internal_links', 0)}</td></tr>
<tr><td>External Links</td><td>{summary.get('total_external_links', 0)}</td></tr>
</table>
</div>

<div class="section">
<h2>Content Breakdown</h2>
<table>
<tr><th>Type</th><th>Count</th></tr>"""

    content_pipeline = [
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$content_type", "count": {"$sum": 1}}}
    ]
    cursor = db.content_items.aggregate(content_pipeline)
    async for row in cursor:
        html += f"<tr><td>{row['_id']}</td><td>{row['count']}</td></tr>"

    html += """</table></div>
<div class="section">
<h2>Page Types (Architecture)</h2>
<table>
<tr><th>Page Type</th><th>Count</th></tr>"""

    page_type_pipeline = [
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$page_type", "count": {"$sum": 1}}}
    ]
    cursor = db.pages.aggregate(page_type_pipeline)
    async for row in cursor:
        html += f"<tr><td>{row['_id']}</td><td>{row['count']}</td></tr>"

    html += """</table></div>
<div class="section">
<h2>User Flows</h2>"""

    try:
        from backend.services.user_flow import get_top_flows
        top_flows = await get_top_flows(job_id, limit=10)
    except Exception:
        top_flows = []

    if not top_flows:
        html += '<p class="section-desc">No user flows identified.</p>'
    else:
        html += """
<table>
<tr><th>Target Page Type</th><th>Depth</th><th>Flow Count</th><th>Target URL</th></tr>"""
        for flow in top_flows:
            html += (
                "<tr>"
                f"<td>{flow['target_type']}</td>"
                f"<td>{flow['depth']} hop(s)</td>"
                f"<td>{flow['flow_count']}</td>"
                f"<td>{flow['target_url']}</td>"
                "</tr>"
            )
        html += "</table>"

    html += """</div>
<div class="section">
<h2>SEO Action Items</h2>"""

    action_cursor = db.action_items.find({"job_id": job_id})
    async for a in action_cursor:
        impact_class = {"high": "badge-high", "medium": "badge-medium", "low": "badge-low"}.get(a.get("impact_on_ranking", ""), "")
        html += f"""
<div class="card">
<strong>{a.get('content_type', '')}</strong>
<span class="badge {impact_class}">{a.get('impact_on_ranking', 'N/A')} impact</span>
<p><strong>Issues:</strong> {', '.join(a.get('identified_issues', []))}</p>
<p><strong>Improvements:</strong> {', '.join(a.get('improvement_suggestions', []))}</p>
<p><strong>Status:</strong> {a.get('status', 'pending')}</p>
</div>"""

    try:
        from backend.services.change_applier import get_content_versions
        versions_data = await get_content_versions(job_id, limit=200)
        versions = versions_data["versions"]
    except Exception:
        versions = []

    html += f"""</div>
<div class="section">
<h2>Before / After Content Changes ({len(versions)})</h2>"""

    if not versions:
        html += '<p class="section-desc">No content changes applied yet. Approve SEO action items to generate improved content.</p>'
    else:
        for v in versions[:20]:
            status_label = "Applied" if v.get("status") == "approved" else "Rejected"
            color = "#16a34a" if v.get("status") == "approved" else "#dc2626"
            html += f"""
<div class="card">
<p><strong>{v.get('content_type', '')}</strong> - <span style="color:{color};font-weight:600">{status_label}</span>
<span style="color:#6b7280;font-size:12px">({v.get('field', '')})</span></p>
<p><small style="color:#6b7280">{v.get('page_url', '')}</small></p>
<p><strong>Before:</strong> <span style="color:#dc2626">{v.get('before', '-')}</span></p>
<p><strong>After:</strong> <span style="color:#16a34a">{v.get('after', 'Not generated (rejected)')}</span></p>
</div>"""

    html += "</div>"

    try:
        from backend.services.site_health import get_site_health
        health = await get_site_health(job_id)
        health.pop("_id", None)
    except Exception:
        health = None

    if health and health.get("score") is not None:
        html += f"""
<div class="section">
<h2>Site Health</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Grade</td><td><strong>{health.get('grade', 'N/A')}</strong></td></tr>
<tr><td>Score</td><td>{health.get('score')}/100</td></tr>
<tr><td>Broken Links</td><td>{health.get('broken_links', 0)}</td></tr>
<tr><td>Meta Description Coverage</td><td>{health.get('meta_description_coverage', 'N/A')}</td></tr>
<tr><td>Alt Text Coverage</td><td>{health.get('alt_text_coverage', 'N/A')}</td></tr>
<tr><td>Avg CWV Score</td><td>{health.get('avg_cwv_score', 'N/A')}</td></tr>
<tr><td>Thin Pages</td><td>{health.get('thin_pages', 0)}</td></tr>
<tr><td>Duplicate Pages</td><td>{health.get('duplicate_pages', 0)}</td></tr>
<tr><td>Canonical Conflicts</td><td>{health.get('canonical_conflicts', 0)}</td></tr>
</table>
"""
        issues = health.get("issues") or []
        if issues:
            html += "<h3>Issues</h3><ul>"
            for issue in issues[:20]:
                sev = issue.get("severity", "")
                html += f"<li>{sev.upper()}: {issue.get('message', '')}</li>"
            html += "</ul>"
        html += "</div>"

    geo = summary.get("geo_readiness") or {}
    if geo:
        blocked = ", ".join(geo.get("blocked_ai_crawlers") or []) or "none"
        allowed = ", ".join(geo.get("allowed_ai_crawlers") or []) or "none"
        html += f"""
<div class="section">
<h2>AI Search (GEO) Readiness</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Status</td><td><strong>{geo.get('status', 'unknown')}</strong>{f" ({geo.get('score', '')}/100)" if geo.get('score') is not None else ""}</td></tr>
<tr><td>robots.txt found</td><td>{"yes" if geo.get("robots_txt_found") else "no"}</td></tr>
<tr><td>Blocked AI crawlers</td><td>{blocked}</td></tr>
<tr><td>Allowed AI crawlers</td><td>{allowed}</td></tr>
<tr><td>AI agents checked</td><td>{", ".join(geo.get("ai_agents_scanned") or []) or "none"}</td></tr>
</table>
<p style="font-size:12px;color:var(--text-secondary)">Improves visibility in AI search (ChatGPT, Perplexity, etc.). Not required for Google AI Overviews or AI Mode.</p>
</div>
"""

    cached_insights = await db.seo_insights_cache.find_one({"job_id": job_id})
    insights = cached_insights.get("data", {}) if cached_insights else {}
    backlinks = insights.get("backlinks") or {}
    overview = insights.get("overview") or {}

    if backlinks or overview:
        html += """<div class="section">
<h2>External SEO Insights</h2>"""
        if backlinks:
            html += f"""
<table>
<tr><th>Backlink Metric</th><th>Value</th></tr>
<tr><td>Total Backlinks</td><td>{backlinks.get('backlinks', 'N/A')}</td></tr>
<tr><td>Referring Domains</td><td>{backlinks.get('referring_domains', 'N/A')}</td></tr>
<tr><td>Referring IPs</td><td>{backlinks.get('referring_ips', 'N/A')}</td></tr>
<tr><td>Domain Rank</td><td>{backlinks.get('rank', 'N/A')}</td></tr>
<tr><td>Broken Backlinks</td><td>{backlinks.get('broken_backlinks', 'N/A')}</td></tr>
</table>"""
        if overview:
            html += f"""
<table>
<tr><th>Domain Metric</th><th>Value</th></tr>
<tr><td>Organic Traffic</td><td>{overview.get('estimated_organic_traffic', 'N/A')}</td></tr>
<tr><td>Organic Keywords</td><td>{overview.get('organic_keywords_count', 'N/A')}</td></tr>
<tr><td>Paid Keywords</td><td>{overview.get('paid_keywords_count', 'N/A')}</td></tr>
</table>"""
        html += "</div>"

    html += """</div></body></html>"""
    return html


@router.get("/{job_id}/download")
async def download_report(job_id: str):
    from fastapi.responses import HTMLResponse

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}
    html = await _report_html(job_id)
    return HTMLResponse(html)


@router.get("/{job_id}/pdf")
async def download_report_pdf(job_id: str):
    from fastapi.responses import Response
    from playwright.async_api import async_playwright

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}

    html = await _report_html(job_id)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html, wait_until="load")
                pdf_bytes = await page.pdf(format="A4", print_background=True)
            finally:
                await browser.close()
    except Exception as e:
        from backend.logging_setup import get_logger
        get_logger("reports").error("PDF export failed job=%s: %s", job_id, e)
        return {"error": f"PDF export failed: {e}"}

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="seo-report-{job_id}.pdf"'},
    )


@router.get("/{job_id}/compare/pdf")
async def download_comparison_report_pdf(job_id: str):
    from fastapi.responses import Response
    from playwright.async_api import async_playwright

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}

    html = await _comparison_html(job_id)
    if isinstance(html, dict):
        return html
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html, wait_until="load")
                pdf_bytes = await page.pdf(format="A4", print_background=True)
            finally:
                await browser.close()
    except Exception as e:
        from backend.logging_setup import get_logger
        get_logger("reports").error("Comparison PDF export failed job=%s: %s", job_id, e)
        return {"error": f"Comparison PDF export failed: {e}"}

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="comparison-{job_id}.pdf"'},
    )


@router.get("/{job_id}/compare")
async def download_comparison_report(job_id: str):
    from fastapi.responses import HTMLResponse
    from backend.services.compare_service import get_site_comparison

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}

    comp = await get_site_comparison(job_id)
    if not comp:
        return {"error": "Comparison not generated yet. Use Compare & Report first."}

    html = await _comparison_html(job_id)
    if isinstance(html, dict):
        return html
    return HTMLResponse(html)


async def _comparison_html(job_id: str) -> str | dict:
    from backend.services.compare_service import get_site_comparison

    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}

    comp = await get_site_comparison(job_id)
    if not comp:
        return {"error": "Comparison not generated yet. Use Compare & Report first."}

    alt = comp.get("alt_text", {})
    lb = comp.get("link_health_before", {})
    la = comp.get("link_health_after", {})
    dummy = comp.get("dummy", {})
    health = comp.get("health", {})
    per_page = comp.get("per_page", [])

    rows = ""
    for p in per_page:
        rows += f"""
<tr>
<td style="max-width:220px;word-break:break-all">{p.get('url', '')}</td>
<td>{'<b style="color:#16a34a">changed</b>' if p.get('title_changed') else '<span style="color:#6b7280">same</span>'}</td>
<td>{'<b style="color:#16a34a">changed</b>' if p.get('meta_changed') else '<span style="color:#6b7280">same</span>'}</td>
<td>{p.get('images_before', 0)}</td>
<td>{p.get('images_after', 0)}</td>
<td>{p.get('alt_missing_before', 0)}</td>
<td>{p.get('alt_missing_after', 0)}</td>
<td>{p.get('alt_texts_changed', 0)}</td>
</tr>"""

    health_rows = ""
    if health.get("score") is not None:
        health_rows = f"""
<div class="section">
<h2>Site Health (original)</h2>
<div class="card">
Grade: <strong>{health.get('grade', 'N/A')}</strong> | Score: <strong>{health.get('score')}/100</strong>
</div>
<ul>
"""
        for issue in (health.get("issues") or [])[:20]:
            health_rows += f"<li>{issue.get('severity', '').upper()}: {issue.get('message', '')}</li>"
        health_rows += "</ul></div>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Before/After Comparison - {job.get('url', '')}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 1000px; margin: 40px auto; padding: 20px; color: #333; }}
h1 {{ color: #111; border-bottom: 3px solid #6366f1; padding-bottom: 10px; }}
table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #e5e7eb; font-size: 13px; }}
th {{ background: #f9fafb; }}
.section {{ margin: 30px 0; }}
.card {{ background: #f9fafb; border-radius: 8px; padding: 16px; margin: 8px 0; }}
.good {{ color: #16a34a; font-weight: 600; }}
.bad {{ color: #dc2626; font-weight: 600; }}
</style>
</head>
<body>
<h1>Original vs Suggested-Changes Comparison</h1>
<p>URL: <strong>{job.get('url', '')}</strong> — Generated: {comp.get('generated_at', datetime.utcnow().isoformat())}</p>

<div class="section">
<h2>Overall</h2>
<div class="card">
Pages compared: <strong>{comp.get('pages_compared', 0)}</strong> |
Approved changes applied to dummy site: <strong>{dummy.get('changes_applied', 0)}</strong> |
Suggestions previewed: <strong>{dummy.get('suggestions_applied', 0)}</strong> |
Remaining pending: <strong>{dummy.get('pending_changes', 0)}</strong>
</div>
</div>

{health_rows}

<div class="section">
<h2>On-Page Signals (before → after)</h2>
<table>
<tr><th>Metric</th><th>Original site</th><th>With suggested changes</th></tr>
<tr><td>Images</td><td>{alt.get('images_before', 0)}</td><td>{alt.get('images_after', 0)}</td></tr>
<tr><td>Images missing alt text</td><td>{alt.get('missing_before', 0)}</td><td>{alt.get('missing_after', 0)}</td></tr>
<tr><td>Alt text coverage</td>
<td>{alt.get('coverage_before', 'N/A')}%</td>
<td>{alt.get('coverage_after', 'N/A')}%</td></tr>
</table>
</div>

<div class="section">
<h2>Link Health (before → after)</h2>
<table>
<tr><th>Metric</th><th>Original site</th><th>Dummy site mirror</th></tr>
<tr><td>Links checked</td><td>{lb.get('checked', 0)}</td><td>{la.get('checked', 0)}</td></tr>
<tr><td>OK</td><td>{lb.get('ok', 0)}</td><td>{la.get('ok', 0)}</td></tr>
<tr><td>Broken</td>
<td>{lb.get('broken', 0)}</td>
<td>{la.get('broken', 0)}</td></tr>
</table>
</div>

<div class="section">
<h2>Per-Page Breakdown ({len(per_page)})</h2>
<table>
<tr><th>URL</th><th>Title</th><th>Meta Description</th><th>Images</th><th>After Images</th><th>Alt Missing</th><th>Alt Missing After</th><th>Alt Changed</th></tr>
{rows}
</table>
</div>
</body></html>"""
    return html
