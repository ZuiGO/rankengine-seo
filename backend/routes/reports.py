import json
from datetime import datetime
from fastapi import APIRouter

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
        "seo_action_items": action_items_list,
        "seo_insights": insights,
    }

    return report


@router.get("/{job_id}/download")
async def download_report(job_id: str):
    from fastapi.responses import HTMLResponse

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
    return HTMLResponse(html)
