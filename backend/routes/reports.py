import html as _html_esc
import json
from datetime import datetime

from fastapi import APIRouter, Response

from backend.db.mongo import get_db
from backend.services.change_applier import get_content_versions
from backend.services.exec_summary import get_exec_summary
from backend.services.site_health import get_site_health
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


def _esc(value) -> str:
    return _html_esc.escape(str(value if value is not None else ""), quote=True)


def _sev_badge(impact: str) -> str:
    label = {"high": "High", "medium": "Medium", "low": "Low"}.get(impact, "Info")
    cls = "high" if impact == "high" else "medium" if impact == "medium" else "low"
    return '<span class="badge sev-%s">%s</span>' % (cls, _esc(label))


def _kpi(label, value, unit=""):
    unit_html = '<div class="kpi-unit">%s</div>' % _esc(unit) if unit else ""
    return (
        '<div class="kpi"><div class="kpi-label">%s</div>'
        '<div class="kpi-value">%s</div>%s</div>' % (_esc(label), _esc(value), unit_html)
    )


_REPORT_CSS = """
@page { size: A4; margin: 14mm 14mm 16mm 14mm; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  color: #1e293b; font-size: 13px; line-height: 1.55; margin: 0; }
.cover { background: linear-gradient(135deg, #1e1b4b, #312e81 60%, #4f46e5); color: #fff;
  border-radius: 14px; padding: 28px 30px; margin-bottom: 26px; }
.cover .brand { font-size: 12px; letter-spacing: 2px; text-transform: uppercase; opacity: .8; }
.cover h1 { font-size: 30px; margin: 6px 0 2px; letter-spacing: -0.5px; }
.cover .meta { display: flex; gap: 22px; flex-wrap: wrap; margin-top: 14px; font-size: 12.5px; opacity: .95; }
.cover .meta b { font-weight: 600; }
.grade-block { display: inline-flex; align-items: baseline; gap: 10px; margin-top: 14px;
  background: rgba(255,255,255,.12); padding: 8px 16px; border-radius: 999px; }
.grade-block .g { font-size: 26px; font-weight: 800; }
h2.section-title { font-size: 16px; margin: 26px 0 10px; padding-bottom: 6px; border-bottom: 2px solid #eef2f7;
  letter-spacing: -0.2px; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.kpi { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; }
.kpi-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .4px; }
.kpi-value { font-size: 22px; font-weight: 700; color: #111827; margin-top: 2px; }
.kpi-unit { font-size: 11px; color: #94a3b8; }
.narrative { background: #eef2ff; border-left: 3px solid #4f46e5; border-radius: 6px; padding: 12px 14px; margin: 12px 0 0; color: #312e81; }
.trend { font-weight: 600; }
.trend-up { color: #16a34a; } .trend-down { color: #dc2626; } .trend-stable { color: #64748b; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 16px; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid #eef2f7; vertical-align: top; }
th { background: #f8fafc; font-weight: 600; font-size: 12px; color: #475569; }
tr:nth-child(even) td { background: #fbfcfe; }
.card { border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; margin: 8px 0; }
.card-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; flex-wrap: wrap; }
.card-head strong { font-size: 14px; }
.card-body { color: #334155; }
.finding { border-left: 3px solid #e2e8f0; }
.badge { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 700; }
.sev-high { background: #fee2e2; color: #b91c1c; }
.sev-medium { background: #fef3c7; color: #b45309; }
.sev-low { background: #dcfce7; color: #15803d; }
.status { margin-left: auto; color: #64748b; font-size: 12px; text-transform: capitalize; }
.effort { display: inline-block; background: #eef2ff; color: #4338ca; border-radius: 6px; padding: 2px 8px; font-size: 11px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; word-break: break-all; }
.muted { color: #94a3b8; }
ol.fix, ul.evidence { margin: 6px 0 0; padding-left: 20px; }
ul.evidence { color: #64748b; font-size: 12px; }
.drive { font-weight: 600; color: #111827; }
.rec-note { font-size: 12px; color: #64748b; }
.page-break { page-break-before: always; }
.bar { height: 6px; border-radius: 3px; background: #e2e8f0; overflow: hidden; margin: 4px 0 10px; max-width: 480px; }
.bar div { height: 100%; border-radius: 3px; }
.checks { margin: 8px 0; }
.checks .row { display: flex; gap: 10px; padding: 7px 0; border-bottom: 1px solid #eef2f7; }
.checks .row .mark { font-weight: 700; flex: 0 0 18px; }
.checks .row.ok .mark { color: #16a34a; }
.checks .row.bad .mark { color: #dc2626; }
footer { margin-top: 26px; padding-top: 10px; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 11px; }
@media print { .cover { page-break-after: avoid; } }
"""


async def _report_html(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}

    page_count = await db.pages.count_documents({"job_id": job_id})
    content_count = await db.content_items.count_documents({"job_id": job_id})
    summary = job.get("summary", {})
    url = job.get("url", "")
    domain = url.split("//")[-1].split("/")[0] if "//" in url else url
    generated_at = datetime.utcnow().isoformat()

    content_breakdown = {}
    cursor = db.content_items.aggregate([
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$content_type", "count": {"$sum": 1}}},
    ])
    async for row in cursor:
        content_breakdown[str(row["_id"])] = row["count"]

    page_type_breakdown = {}
    cursor = db.pages.aggregate([
        {"$match": {"job_id": job_id}},
        {"$group": {"_id": "$page_type", "count": {"$sum": 1}}},
    ])
    async for row in cursor:
        page_type_breakdown[str(row["_id"])] = row["count"]

    action_items = []
    async for a in db.action_items.find({"job_id": job_id}):
        action_items.append({
            "content_type": a.get("content_type", ""),
            "impact": a.get("impact_on_ranking", ""),
            "issues": a.get("identified_issues", []),
            "improvements": a.get("improvement_suggestions", []),
            "status": a.get("status", "pending"),
        })

    health = await get_site_health(job_id)
    if isinstance(health, dict):
        health.pop("_id", None)
    exec_summ = await get_exec_summary(job_id)

    insights = {}
    cached_insights = await db.seo_insights_cache.find_one({"job_id": job_id})
    if cached_insights:
        insights = cached_insights.get("data", {})
    backlinks = insights.get("backlinks") or {}
    overview = insights.get("overview") or {}
    gsc = insights.get("gsc")
    keywords_source = insights.get("keywords_source") or "none"
    backlinks_source = insights.get("backlinks_source") or "none"
    overview_source = insights.get("overview_source") or "none"

    top_flows = []
    try:
        top_flows = await get_top_flows(job_id, limit=10)
    except Exception:
        pass
    versions = []
    try:
        versions_data = await get_content_versions(job_id, limit=200)
        versions = versions_data["versions"]
    except Exception:
        pass

    score = (health or {}).get("score")
    grade = (health or {}).get("grade")
    direction = (exec_summ or {}).get("direction")
    exec_overview = (exec_summ or {}).get("overview") or ""
    quick_wins = (exec_summ or {}).get("quick_wins") or []
    long_term = (exec_summ or {}).get("long_term") or []

    hm = (health or {}).get("metrics") or {}
    issues = (exec_summ or {}).get("all_issues") or []
    if not issues and isinstance(health, dict):
        issues = health.get("issues") or []

    kpis = "".join([
        _kpi("Pages Crawled", page_count),
        _kpi("Content Items", content_count),
        _kpi("Links", summary.get("total_links", 0)),
        _kpi("Broken", hm.get("broken_links", 0)),
        _kpi("Health Score", "%s/100" % score if score is not None else "N/A"),
        _kpi("Grade", grade or "N/A"),
        _kpi("Avg CWV", hm.get("avg_cwv_score") if hm.get("avg_cwv_score") is not None else "N/A"),
        _kpi("Pending Actions", hm.get("pending_action_items", 0)),
        _kpi("Organic Traffic", overview.get("estimated_organic_traffic")
             if overview.get("estimated_organic_traffic") is not None else "N/A"),
        _kpi("Organic Keywords", overview.get("organic_keywords_count")
             if overview.get("organic_keywords_count") is not None else "N/A"),
        _kpi("Backlinks", backlinks.get("backlinks") if backlinks.get("backlinks") is not None else "N/A"),
        _kpi("Referring Domains", backlinks.get("referring_domains")
             if backlinks.get("referring_domains") is not None else "N/A"),
    ])

    prev_txt = " (previous %s)" % previous if (previous := (exec_summ or {}).get("previous_score")) is not None else ""
    dir_cls = {"improved": "trend-up", "declined": "trend-down", "stable": "trend-stable"}.get(direction, "trend-stable")
    dir_text = (direction or "stable")
    exec_html = (
        '<div class="exec-meta"><span class="line">Site health: <strong>%s/100 · %s</strong>'
        ' <span class="trend %s">%s%s</span></span></div>'
        % (score if score is not None else "N/A", grade or "N/A", dir_cls, dir_text, prev_txt)
        + (f'<p class="narrative">{_esc(exec_overview)}</p>' if exec_overview else "")
    )

    flow_rows = "".join(
        "<tr><td>%s</td><td>%s hop(s)</td><td>%s</td><td class='mono'>%s</td></tr>"
        % (_esc(f.get("target_type")), _esc(f.get("depth")), _esc(f.get("flow_count")), _esc(f.get("target_url")))
        for f in top_flows
    ) or '<tr><td colspan="4">No user flows identified.</td></tr>'

    action_rows = "".join(
        '<div class="card"><div class="card-head"><strong>%s</strong>%s'
        '<span class="status">%s</span></div><div class="card-body">'
        "<strong>Issues:</strong> %s<br><strong>Improvements:</strong> %s</div></div>"
        % (_esc(a["content_type"] or "Page"), _sev_badge(a["impact"]), _esc(a["status"]),
           _esc(", ".join(a["issues"]) or "None"), _esc(", ".join(a["improvements"]) or "None"))
        for a in action_items
    ) or '<p class="muted">No action items generated.</p>'

    if not versions:
        version_html = '<p class="muted">No content changes applied yet. Approve SEO action items to generate improved content.</p>'
    else:
        rows = []
        for v in versions[:20]:
            color = "#16a34a" if v.get("status") == "approved" else "#dc2626"
            label = "Applied" if v.get("status") == "approved" else "Rejected"
            rows.append(
                '<div class="card"><div class="card-head"><strong>%s</strong> '
                '<span style="color:%s;font-weight:600">%s</span> '
                '<span class="muted">(%s)</span></div>'
                '<div class="muted mono">%s</div>'
                '<div class="card-body"><strong>Before:</strong> <span style="color:#dc2626">%s</span><br>'
                '<strong>After:</strong> <span style="color:#16a34a">%s</span></div></div>'
                % (_esc(v.get("content_type", "")), color, _esc(label), _esc(v.get("field", "")),
                   _esc(v.get("page_url", "")), _esc(v.get("before", "-")),
                   _esc(v.get("after", "Not generated (rejected)")))
            )
        version_html = "".join(rows)

    sev_order = {"high": 0, "medium": 1, "low": 2}
    def sev_key(i):
        return sev_order.get(i.get("impact") or i.get("severity", "low"), 3)
    issues_sorted = sorted(issues, key=lambda i: (sev_key(i), -len(i.get("evidence") or [])))

    findings = []
    for it in issues_sorted[:40]:
        title = it.get("title") or it.get("message", "Site issue")
        drive = it.get("drive") or it.get("message", "")
        explanation = it.get("explanation", "")
        how_to = it.get("how_to_fix") or []
        evidence = it.get("evidence") or []
        sev = it.get("impact") or it.get("severity", "low")
        fix_html = ""
        if how_to:
            fix_html = '<ol class="fix"><li>%s</li></ol>' % "</li><li>".join(_esc(h) for h in how_to)
        ev_html = ""
        if evidence:
            ev_html = '<ul class="evidence">%s</ul>' % "".join("<li>%s</li>" % _esc(e) for e in evidence[:5])
        findings.append(
            '<div class="card finding"><div class="card-head"><strong>%s</strong>%s</div>'
            '<div class="card-body">%s%s%s%s%s</div></div>'
            % (_esc(title), _sev_badge(sev),
               '<div class="drive">%s</div>' % _esc(drive) if drive else "",
               '<p>%s</p>' % _esc(explanation) if explanation else "",
               fix_html, ev_html, "")
        )
    findings_html = "".join(findings) or '<p class="muted">No issues found.</p>'

    def rec_list(items):
        rows = []
        for i in items:
            rows.append(
                '<div class="card rec"><div class="card-head"><strong>%s</strong>%s</div>'
                '<div class="card-body"><span class="effort">Effort: %s</span>%s</div></div>'
                % (_esc(i.get("title", "")), _sev_badge(i.get("impact")), _esc(i.get("effort")),
                   '<p>%s</p>' % _esc(i.get("next_step")) if i.get("next_step") else "")
            )
        return "".join(rows) or '<p class="muted">None at this time.</p>'

    rec_html = (
        '<h2 class="section-title">Quick Wins</h2>' + rec_list(quick_wins)
        + '<h2 class="section-title">Long-Term Improvements</h2>' + rec_list(long_term)
    )

    cwv_detail = (
        "%s page(s)" % hm.get("cwv_pages_checked") if hm.get("cwv_pages_checked") else "N/A"
    )
    kw_count = len(insights.get("keywords") or [])
    method_rows = "".join([
        "<tr><td>Pages Crawled</td><td>%s</td><td>measured</td><td>BFS crawl + XML sitemap seed</td></tr>" % _esc(page_count),
        "<tr><td>Links Checked</td><td>%s</td><td>measured</td><td>HEAD/GET checks with redirect + retry logic</td></tr>" % _esc((health or {}).get("links_checked", 0)),
        "<tr><td>Core Web Vitals</td><td>%s</td><td>field + lab</td><td>Google PageSpeed Insights (CrUX + Lighthouse)</td></tr>" % _esc(cwv_detail),
        "<tr><td>Keywords</td><td>%s</td><td>%s</td><td>DataForSEO / SERP API / on-page extraction</td></tr>" % (_esc(kw_count), _esc(keywords_source)),
        "<tr><td>Backlinks</td><td>%s</td><td>%s</td><td>DataForSEO or SERP discovery</td></tr>" % (_esc(backlinks.get("backlinks") if backlinks.get("backlinks") is not None else "N/A"), _esc(backlinks_source)),
        "<tr><td>Organic Traffic</td><td>%s</td><td>%s</td><td>Search Console / DataForSEO; N/A when unmeasured</td></tr>" % (_esc(overview.get("estimated_organic_traffic") if overview.get("estimated_organic_traffic") is not None else "N/A"), _esc(overview_source)),
        "<tr><td>Google Search Console</td><td>%s</td><td>real-user data</td><td>Search Analytics (last 28 days)</td></tr>" % (_esc((gsc or {}).get("property", "not connected")) if gsc else "not connected"),
    ])

    content_rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (_esc(k), _esc(v)) for k, v in sorted(content_breakdown.items())
    ) or '<tr><td colspan="2">-</td></tr>'
    page_type_rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (_esc(k), _esc(v)) for k, v in sorted(page_type_breakdown.items())
    ) or '<tr><td colspan="2">-</td></tr>'

    bl_extra = ""
    if backlinks.get("referring_ips") is not None or backlinks.get("rank") is not None:
        bl_extra = (
            "<tr><td>Referring IPs</td><td>%s</td></tr>" % _esc(backlinks.get("referring_ips", "N/A"))
            + "<tr><td>Domain Rank</td><td>%s</td></tr>" % _esc(backlinks.get("rank", "N/A"))
        )
    insights_html = "<div class='card'><div class='card-head'><strong>Backlinks</strong></div>%s</div>" % (
        "<table><tr><th>Metric</th><th>Value</th></tr>"
        "<tr><td>Total Backlinks</td><td>%s</td></tr>"
        "<tr><td>Referring Domains</td><td>%s</td></tr>%s</table>"
        % (_esc(backlinks.get("backlinks", "N/A")), _esc(backlinks.get("referring_domains", "N/A")), bl_extra)
        if backlinks else "<p class='muted'>No backlink data.</p>"
    )
    ov_html = ""
    if overview:
        ov_html = "<h2 class='section-title'>Domain Insights</h2>" + (
            "<table><tr><th>Metric</th><th>Value</th></tr>"
            "<tr><td>Organic Traffic</td><td>%s</td></tr>"
            "<tr><td>Organic Keywords</td><td>%s</td></tr>"
            "<tr><td>Paid Keywords</td><td>%s</td></tr></table>"
            % (_esc(overview.get("estimated_organic_traffic", "N/A")),
               _esc(overview.get("organic_keywords_count", "N/A")),
               _esc(overview.get("paid_keywords_count", "N/A")))
        )
    gsc_html = ""
    if gsc:
        q_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (_esc(q.get("query")), _esc(q.get("clicks")), _esc(q.get("position")))
        for q in (gsc.get("queries") or [])[:10]
    )
        gsc_html = (
            "<h2 class='section-title'>Search Console (28 days)</h2>"
            "<table><tr><th>Query</th><th>Clicks</th><th>Position</th></tr>%s</table>" % q_rows
        )

    def _bar(score, max_score=100):
        if score is None or max_score <= 0:
            return ""
        pct = max(0, min(100, int(score / max_score * 100)))
        color = "#16a34a" if pct >= 70 else "#d97706" if pct >= 40 else "#dc2626"
        return '<div class="bar"><div style="width:%d%%;background:%s"></div></div>' % (pct, color)

    def _checks_html(checks):
        if not checks:
            return ""
        rows = "".join(
            '<div class="row %s"><span class="mark">%s</span><div><b>%s</b>%s</div></div>'
            % ("ok" if c.get("passed") else "bad", "✔" if c.get("passed") else "✘",
               _esc(c.get("label", "")),
               ('<div class="muted">%s</div>' % _esc(c.get("detail", "")) if c.get("detail") else ""))
            for c in checks
        )
        return '<div class="checks">%s</div>' % rows

    sitemap_audit = await db.sitemap_audits.find_one({"job_id": job_id})
    ai_vis = await db.ai_visibility_summaries.find_one({"job_id": job_id})
    local_seo = await db.local_seo_summaries.find_one({"job_id": job_id})

    sitemap_html = ""
    if sitemap_audit:
        cov = sitemap_audit.get("crawled_coverage")
        uncrawled = sitemap_audit.get("uncrawled_urls_count") or 0
        sitemap_html = (
            "<h2 class='section-title'>Sitemap</h2>"
            "<table><tr><th>Found</th><th>Valid</th><th>URLs listed</th><th>Pages crawled</th><th>Coverage</th></tr>"
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr></table>"
            % (_esc(sitemap_audit.get("sitemap_found")), _esc(sitemap_audit.get("sitemap_valid")),
               _esc(sitemap_audit.get("pages_in_sitemap", "N/A")),
               _esc(sitemap_audit.get("pages_crawled", "N/A")),
               _esc(cov if cov is not None else "N/A"))
            + _bar(cov)
            + ('<p class="muted">%s listed URL(s) were not crawled, and %s URL(s) lack a<code>lastmod</code> date. '
                'Missing dates weaken freshness signals but indexing is unaffected.</p>'
               % (uncrawled, _esc(sitemap_audit.get("missing_lastmod", 0)))
               if uncrawled or sitemap_audit.get("missing_lastmod") else "")
        )

    ai_html = ""
    if ai_vis:
        subs = ai_vis.get("subscores") or {}
        agents = ai_vis.get("ai_agents") or []
        blocked = ai_vis.get("blocked_ai_agents") or []
        schema_types = ai_vis.get("schema_types") or {}
        agent_rows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (_esc(a.get("agent")), _esc(a.get("status")), _esc(a.get("disallow_rules", 0)),
               _esc(a.get("crawl_delay") or "—"))
            for a in agents
        ) or '<tr><td colspan="4" class="muted">No agent rules found.</td></tr>'
        ai_html = (
            "<h2 class='section-title'>AI-Search Visibility</h2>"
            "<p>Score: <b>%s</b> / 100%s</p>"
            % (_esc(ai_vis.get("score")), _bar(ai_vis.get("score")))
            + "<table><tr><th>Sitemap</th><th>llms.txt</th><th>Structured data</th><th>Extractable</th></tr>"
            "<tr><td>%s / 25</td><td>%s / 25</td><td>%s / 25</td><td>%s / 25</td></tr></table>"
            % (_esc(subs.get("sitemap") or 0), _esc(subs.get("llms_txt") or 0),
               _esc(subs.get("structured_data") or 0), _esc(subs.get("extractable_content") or 0))
            + ("<p>robots.txt: <b>%s</b> · llms.txt: <b>%s</b> · structured data on <b>%s</b> of <b>%s</b> pages · "
               "extractable content on <b>%s</b> of <b>%s</b> pages</p>"
               % (_esc(ai_vis.get("robots_status") or ("found" if ai_vis.get("robots_txt_found") else "missing")),
                  _esc(ai_vis.get("llms_txt_present") and "present" or "missing"),
                  _esc(ai_vis.get("structured_data_pages", 0)), _esc(ai_vis.get("total_pages", 0)),
                  _esc(ai_vis.get("extractable_pages", 0)), _esc(ai_vis.get("total_pages", 0))))
            + (('<p class="muted">robots.txt fully blocks: %s</p>' % _esc(", ".join(blocked))) if blocked else "")
            + ('<p class="muted">Schema types: %s</p>' % _esc(" · ".join("%s (%d)" % (k, v) for k, v in list(schema_types.items())[:8]))
               if schema_types else "")
            + "<p>AI agent robots.txt stance</p><table><tr><th>Agent</th><th>Status</th><th>Disallow rules</th><th>Crawl delay</th></tr>%s</table>" % agent_rows
            + _checks_html(ai_vis.get("checks"))
        )

    local_html = ""
    if local_seo:
        subs = local_seo.get("subscores") or {}
        nap = (local_seo.get("naps_found") or [{}])[0]
        signals = [("Geo,", local_seo.get("geo_pages")), ("Opening hours", local_seo.get("opening_hours_pages")),
                   ("Phone", local_seo.get("phone_pages")), ("Reviews", local_seo.get("reviews_pages")),
                   ("Address", local_seo.get("address_pages"))]
        sig_txt = " · ".join("%s: %d page(s)" % (l, n) for l, n in signals if n) or "none found"
        local_html = (
            "<h2 class='section-title'>Local SEO Readiness</h2>"
            "<p>Score: <b>%s</b> / 100%s</p>"
            % (_esc(local_seo.get("score")), _bar(local_seo.get("score")))
            + "<table><tr><th>LocalBusiness schema</th><th>On homepage</th><th>NAP consistent</th><th>Contact page</th></tr>"
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr></table>"
            % (_esc("✅" if local_seo.get("local_business_schema") else "❌"),
               _esc("✅" if local_seo.get("local_business_on_homepage") else "❌"),
               _esc("✅" if not local_seo.get("nap_inconsistent") else "⚠ mismatched"),
               _esc("✅" if local_seo.get("contact_page_present") else "❌"))
            + (('<p class="muted">NAP: <b>%s</b> · %s · %s</p>'
                % (_esc(nap.get("name") or "?"), _esc(nap.get("street_address") or nap.get("address") or "?"),
                   _esc(nap.get("telephone") or "?"))) if nap else "")
            + ('<p class="muted" style="color:#dc2626">⚠ Multiple differing NAP values across pages — keep one consistent Name, Address, Phone.</p>'
               if local_seo.get("nap_inconsistent") else "")
            + "<p class='muted'>Signals: %s</p>" % _esc(sig_txt)
            + "<table><tr><th>Area</th><th>Points</th><th>Max</th></tr>"
            "<tr><td>LocalBusiness schema</td><td>%s</td><td>40</td></tr>"
            "<tr><td>NAP data</td><td>%s</td><td>20</td></tr>"
            "<tr><td>Contact page</td><td>%s</td><td>15</td></tr>"
            "<tr><td>Address signals</td><td>%s</td><td>10</td></tr>"
            "<tr><td>Geo signals</td><td>%s</td><td>10</td></tr>"
            "<tr><td>Reviews</td><td>%s</td><td>5</td></tr></table>"
            % (_esc(subs.get("local_business_schema") or 0), _esc(subs.get("nap") or 0),
               _esc(subs.get("contact_page") or 0), _esc(subs.get("address_signals") or 0),
               _esc(subs.get("geo_signals") or 0), _esc(subs.get("reviews") or 0))
            + _checks_html(local_seo.get("checks"))
        )

    hreflang_audit = await db.hreflang_audits.find_one({"job_id": job_id})
    url_hygiene = await db.url_hygiene_audits.find_one({"job_id": job_id})
    indexation = await db.indexation_audits.find_one({"job_id": job_id})
    image_opt = await db.image_optimization_audits.find_one({"job_id": job_id})

    hreflang_html = ""
    if hreflang_audit:
        subs = hreflang_audit.get("subscores") or {}
        if hreflang_audit.get("applicable") is False:
            hreflang_html = (
                "<h2 class='section-title'>International SEO / hreflang</h2>"
                "<p class='muted'>Not applicable — no localized URL structure detected.</p>"
            )
        else:
            hreflang_html = (
                "<h2 class='section-title'>International SEO / hreflang</h2>"
                "<p>Score: <b>%s</b> / 100%s</p>"
                % (_esc(hreflang_audit.get("score")), _bar(hreflang_audit.get("score")))
                + "<p class='muted'>Locales: <b>%s</b> · pages with hreflang: <b>%s</b> · "
                "missing self-references: <b>%s</b> · missing x-default: <b>%s</b> · "
                "invalid codes: <b>%s</b> · one-way pairs: <b>%s</b> · canonical conflicts: <b>%s</b></p>"
                % (_esc(", ".join(hreflang_audit.get("locales") or []) or "none"),
                   _esc(hreflang_audit.get("pages_with_hreflang", 0)),
                   _esc(hreflang_audit.get("missing_self_ref", 0)),
                   _esc(hreflang_audit.get("missing_xdefault", 0)),
                   _esc(hreflang_audit.get("invalid_codes", 0)),
                   _esc(hreflang_audit.get("one_way_pairs_count", 0)),
                   _esc(hreflang_audit.get("canonical_conflicts_count", 0)))
                + "<table><tr><th>Area</th><th>Points</th><th>Max</th></tr>"
                "<tr><td>Self-referencing pages</td><td>%s</td><td>30</td></tr>"
                "<tr><td>x-default declared</td><td>%s</td><td>15</td></tr>"
                "<tr><td>Valid language/region codes</td><td>%s</td><td>15</td></tr>"
                "<tr><td>Reciprocal pairs</td><td>%s</td><td>25</td></tr>"
                "<tr><td>Locale-based URL structure</td><td>%s</td><td>15</td></tr></table>"
                % (_esc(subs.get("self_reference") or 0), _esc(subs.get("x_default") or 0),
                   _esc(subs.get("valid_codes") or 0), _esc(subs.get("reciprocal") or 0),
                   _esc(subs.get("locale_urls") or 0))
                + (('<p class="muted">Sitemap: %s "alternate" entries, codes: %s%s</p>'
                    % (_esc(hreflang_audit.get("sitemap_alt_entries", 0)),
                       _esc(", ".join(hreflang_audit.get("sitemap_alt_codes") or []) or "none",
                            ),
                       (' · <b>%s</b> invalid code(s), <b>%s</b> page(s) missing a self-reference in the sitemap'
                        % (_esc(hreflang_audit.get("sitemap_invalid_alt_codes", 0)),
                           _esc(hreflang_audit.get("sitemap_missing_self_ref", 0)))
                        if hreflang_audit.get("sitemap_invalid_alt_codes") or hreflang_audit.get("sitemap_missing_self_ref")
                        else "")))
                   if hreflang_audit.get("sitemap_alt_entries") else "")
                + _checks_html(hreflang_audit.get("checks"))
            )

    url_hygiene_html = ""
    if url_hygiene:
        subs = url_hygiene.get("subscores") or {}
        top_params = (url_hygiene.get("top_params") or [])
        url_hygiene_html = (
            "<h2 class='section-title'>URL Hygiene</h2>"
            "<p>Score: <b>%s</b> / 100%s</p>"
            % (_esc(url_hygiene.get("score")), _bar(url_hygiene.get("score")))
            + "<p class='muted'>%s page(s) with URL parameters (%s faceted/pagination, %s language-parameter) · "
            "%s uppercase-slug · %s underscore-slug · %s long-slug pages%s</p>"
            % (_esc(url_hygiene.get("param_pages", 0)), _esc(url_hygiene.get("facet_pages", 0)),
               _esc(url_hygiene.get("lang_param_pages", 0)), _esc(url_hygiene.get("uppercase_slugs", 0)),
               _esc(url_hygiene.get("underscore_slugs", 0)), _esc(url_hygiene.get("long_slugs", 0)),
               (' · top parameters: %s' % _esc(", ".join("%s (%d)" % (k, v) for k, v in top_params[:6]))) if top_params else "")
            + "<table><tr><th>Area</th><th>Points</th><th>Max</th></tr>"
            "<tr><td>Parameter control</td><td>%s</td><td>40</td></tr>"
            "<tr><td>Readable paths</td><td>%s</td><td>20</td></tr>"
            "<tr><td>Slug length</td><td>%s</td><td>20</td></tr>"
            "<tr><td>Slash consistency</td><td>%s</td><td>20</td></tr></table>"
            % (_esc(subs.get("parameter_control") or 0), _esc(subs.get("readable_paths") or 0),
               _esc(subs.get("slug_length") or 0), _esc(subs.get("slash_consistency") or 0))
            + _checks_html(url_hygiene.get("checks"))
        )

    indexation_html = ""
    if indexation:
        if indexation.get("status") == "unmeasured":
            indexation_html = (
                "<h2 class='section-title'>Indexation</h2>"
                "<p class='muted'>SERP indexation check not measured (no SERP API key configured or spend exhausted).</p>"
            )
        else:
            top_pages = (indexation.get("top_indexed_pages") or [])
            indexation_html = (
                "<h2 class='section-title'>Indexation</h2>"
                "<p>Estimate: <b>%s</b> of <b>%s</b> crawled pages indexed (adwords-indexed sample).</p>"
                % (_esc(indexation.get("indexed_estimate")),
                   _esc(indexation.get("crawled_pages") if indexation.get("crawled_pages") is not None else indexation.get("crawled", "N/A")))
                + (('<p class="muted">%s</p>' % _esc(indexation.get("message"))) if indexation.get("message") else "")
                + (('<p class="muted">Sample indexed pages: %s</p>'
                    % _esc(", ".join(str((p.get("url") if isinstance(p, dict) else p)) for p in top_pages[:10]))) if top_pages else "")
            )

    image_opt_html = ""
    if image_opt:
        subs = image_opt.get("subscores") or {}
        image_opt_html = (
            "<h2 class='section-title'>Image Optimization</h2>"
            "<p>Score: <b>%s</b> / 100%s</p>"
            % (_esc(image_opt.get("score")), _bar(image_opt.get("score")))
            + "<p class='muted'>%s images on page · %s WebP/AVIF · %s lazy-loaded · %s missing explicit dimensions</p>"
            % (_esc(image_opt.get("total_imgs", 0)), _esc(image_opt.get("modern", 0)),
               _esc(image_opt.get("lazy", 0)), _esc(image_opt.get("dims_missing", 0)))
            + "<table><tr><th>Area</th><th>Points</th><th>Max</th></tr>"
            "<tr><td>Modern formats (WebP/AVIF)</td><td>%s</td><td>40</td></tr>"
            "<tr><td>Lazy loading</td><td>%s</td><td>30</td></tr>"
            "<tr><td>Explicit dimensions</td><td>%s</td><td>30</td></tr></table>"
            % (_esc(subs.get("modern_formats") or 0), _esc(subs.get("lazy_loading") or 0),
               _esc(subs.get("dimensions") or 0))
            + _checks_html(image_opt.get("checks"))
        )

    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        "<title>ZuiGO Engine SEO Audit — %s</title><style>%s</style></head><body>"
        % (_esc(domain), _REPORT_CSS)
        + '<div class="cover"><div class="brand">ZuiGO Engine — SEO Audit</div>'
        '<h1>SEO Audit Report — %s</h1>'
        '<div class="grade-block"><span class="g">%s</span><span>Health grade</span>'
        '<span class="g">%s</span><span>/ 100</span></div>'
        '<div class="meta"><span>Domain: <b>%s</b></span><span>URL: <b>%s</b></span>'
        '<span>Analysis ID: <b>%s</b></span><span>Generated: %s</span></div></div>'
        % (_esc(domain), _esc(grade or "N/A"), _esc(score if score is not None else "N/A"),
           _esc(domain), _esc(url), _esc(job_id), _esc(generated_at))
        + '<h2 class="section-title">Key Performance Indicators</h2>'
        '<div class="kpis">%s</div>' % kpis
        + '<h2 class="section-title">Executive Summary</h2>' + exec_html
        + '<h2 class="section-title">Findings</h2>' + findings_html
        + rec_html
        + '<h2 class="section-title">Methodology</h2>'
        '<table><tr><th>Area</th><th>Scope</th><th>Source</th><th>Notes</th></tr>%s</table>'
        % method_rows
        + '<h2 class="section-title">Content Breakdown</h2>'
        '<table><tr><th>Content type</th><th>Count</th></tr>%s</table>' % content_rows
        + '<h2 class="section-title">Page-Type Breakdown</h2>'
        '<table><tr><th>Page type</th><th>Count</th></tr>%s</table>' % page_type_rows
        + insights_html + ov_html + gsc_html
        + sitemap_html + ai_html + local_html + hreflang_html + url_hygiene_html + indexation_html + image_opt_html
        + '<h2 class="section-title">User Flows</h2>'
        '<table><tr><th>Target type</th><th>Depth</th><th>Visits</th><th>Target URL</th></tr>%s</table>'
        % flow_rows
        + '<h2 class="section-title">SEO Action Items</h2>' + action_rows
        + '<h2 class="section-title">Content Versions</h2>' + version_html
        + '<footer>Generated by ZuiGO Engine on %s — all values measured from the '
        'crawl; "N/A" means a metric was not measured for this site.</footer>'
        % _esc(generated_at)
        + '</body></html>'
    )
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
