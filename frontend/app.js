const API_BASE = "/api";
let currentJobId = null;
let pollInterval = null;
let currentTab = "overview";

// DOM refs
const form = document.getElementById("analyze-form");
const urlInput = document.getElementById("url-input");
const analyzeBtn = document.getElementById("analyze-btn");
const inputSection = document.getElementById("input-section");
const progressSection = document.getElementById("progress-section");
const progressBar = document.getElementById("progress-bar");
const progressMessage = document.getElementById("progress-message");
const progressTitle = document.getElementById("progress-title");
const statusBadge = document.getElementById("status-badge");
const resultsSection = document.getElementById("results-section");
const resultsUrl = document.getElementById("results-url");
const resultsStatus = document.getElementById("results-status");
const newBtn = document.getElementById("new-analysis-btn");
const toast = document.getElementById("toast");

// Example links
document.querySelectorAll(".examples a[data-url]").forEach(a => {
  a.addEventListener("click", e => {
    e.preventDefault();
    urlInput.value = a.dataset.url;
    form.dispatchEvent(new Event("submit"));
  });
});

// Form submit
form.addEventListener("submit", async e => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;

  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "Analyzing...";
  showProgress();
  showToast("Starting analysis...");

  try {
    const resp = await fetch(`${API_BASE}/analysis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await resp.json();
    currentJobId = data.job_id;
    history.replaceState(null, "", "#job/" + data.job_id);
    resultsUrl.textContent = data.url;
    startPolling(data.job_id);
  } catch (err) {
    showToast("Error: " + err.message);
    hideProgress();
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "Analyze";
  }
});

// New analysis
newBtn.addEventListener("click", () => {
  stopPolling();
  currentJobId = null;
  history.replaceState(null, "", location.pathname + location.search);
  resultsSection.classList.add("hidden");
  inputSection.classList.remove("hidden");
  urlInput.value = "";
  analyzeBtn.disabled = false;
  analyzeBtn.textContent = "Analyze";
});

// Tab switching
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".tab-content").forEach(tc => tc.classList.add("hidden"));
    const target = document.getElementById(`tab-${tab.dataset.tab}`);
    if (target) target.classList.remove("hidden");
    currentTab = tab.dataset.tab;

    if (currentJobId) {
      history.replaceState(null, "", `#job/${currentJobId}/${currentTab}`);
    }

    if (currentJobId) {
      if (currentTab === "pages") loadPages(currentJobId);
      if (currentTab === "content") loadContent(currentJobId);
      if (currentTab === "links") loadLinks(currentJobId);
      if (currentTab === "actions") loadActions(currentJobId);
      if (currentTab === "report") loadReport(currentJobId);
      if (currentTab === "analytics") loadAnalytics(currentJobId);
      if (currentTab === "chat") initChat();
      if (currentTab === "seo-insights") loadSeoInsights(currentJobId);
      if (currentTab === "competitors") loadCompetitors(currentJobId);
      if (currentTab === "quality") loadQuality(currentJobId);
      if (currentTab === "sites") loadSites();
      if (currentTab === "schedules") loadSchedules();
      if (currentTab === "logs") loadLogs();
    } else if (["sites", "schedules", "logs"].includes(currentTab)) {
      if (currentTab === "sites") loadSites();
      if (currentTab === "schedules") loadSchedules();
      if (currentTab === "logs") loadLogs();
    }
  });
});

// Polling
function startPolling(jobId) {
  pollInterval = setInterval(() => pollJob(jobId), 1500);
  pollJob(jobId);
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

async function pollJob(jobId) {
  try {
    const resp = await fetch(`${API_BASE}/analysis/${jobId}`);
    const job = await resp.json();

    progressBar.style.width = `${job.progress || 0}%`;
    progressMessage.textContent = job.progress_message || "";
    statusBadge.textContent = job.status;
    statusBadge.className = `status-badge status-${job.status}`;

    if (job.status === "completed") {
      stopPolling();
      showResults(jobId);
    } else if (job.status === "failed") {
      stopPolling();
      progressTitle.textContent = "Analysis Failed";
      progressMessage.textContent = job.error_message || "Unknown error";
      statusBadge.className = "status-badge status-failed";
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = "Analyze";
      showToast("Analysis failed: " + (job.error_message || "Unknown error"));
    }
  } catch (err) {
    // keep polling
  }
}

async function showResults(jobId, opts = {}) {
  hideProgress();
  resultsSection.classList.remove("hidden");
  inputSection.classList.add("hidden");

  const summaryResp = await fetch(`${API_BASE}/analysis/${jobId}/summary`);
  const summary = await summaryResp.json();

  resultsUrl.textContent = summary.url;
  resultsStatus.textContent = `Pages: ${summary.total_pages} | Content Items: ${summary.total_content_items}`;

  loadOverview(summary);
  loadPages(jobId);
  loadContent(jobId);
  loadLinks(jobId);
  loadReport(jobId);
  initChat();
  loadExecSummary(jobId);
  loadSiteHealth(jobId);
  loadTracking(jobId);
  loadTrends(jobId);

  // Switch to overview unless restoring a specific tab from the URL
  if (!opts.preserveTab) {
    document.querySelector('.tab[data-tab="overview"]').click();
  }
}

function loadOverview(summary) {
  const stats = document.getElementById("overview-stats");
  const geo = summary.geo_readiness || {};
  const geoCard = geo.status
    ? `<div class="stat-card"><div class="stat-value" style="font-size:16px">${geo.blocked_ai_crawlers?.length ? "⛔ " + escapeHtml(geo.blocked_ai_crawlers.join(", ")) : "✅ AI crawlers OK"}</div><div class="stat-label">AI Search Readiness${geo.score !== undefined && geo.score !== null ? " (" + geo.score + "/100)" : ""}</div></div>`
    : "";
  const ai = summary.ai_visibility || {};
  const aiCard = ai.score !== undefined && ai.score !== null
    ? `<div class="stat-card"><div class="stat-value" style="font-size:16px">${ai.score}/100</div><div class="stat-label">AI Visibility${ai.blocked_ai_agents?.length ? " ⛔ blocked" : ""}${ai.llms_txt_present ? " · llms.txt" : ""}</div></div>`
    : "";
  const local = summary.local_seo || {};
  const localCard = local.score !== undefined && local.score !== null
    ? `<div class="stat-card"><div class="stat-value" style="font-size:16px">${local.score}/100</div><div class="stat-label">Local SEO${local.local_business_schema ? " ✅" : ""}</div></div>`
    : "";
  const cannib = summary.cannibalization_groups || 0;
  const cannibCard = cannib
    ? `<div class="stat-card"><div class="stat-value" style="font-size:16px">${cannib}</div><div class="stat-label">Cannibalized Keywords</div></div>`
    : "";
  stats.innerHTML = `
    <div class="stat-card"><div class="stat-value">${summary.total_pages}</div><div class="stat-label">Pages Crawled</div></div>
    <div class="stat-card"><div class="stat-value">${summary.total_content_items}</div><div class="stat-label">Content Items</div></div>
    <div class="stat-card"><div class="stat-value">${summary.total_action_items}</div><div class="stat-label">SEO Action Items</div></div>
    <div class="stat-card"><div class="stat-value">${summary.summary?.total_links || 0}</div><div class="stat-label">Total Links Found</div></div>
    ${geoCard}${aiCard}${localCard}${cannibCard}
  `;

  const breakdown = document.getElementById("content-breakdown");
  const types = summary.content_breakdown || {};
  const icons = { image: "🖼", pdf: "📄", video: "🎬", doc: "📝", xlsx: "📊", presentation: "📽", audio: "🎵", text: "📃" };
  const colors = { image: "#fef3c7", pdf: "#dbeafe", video: "#ede9fe", doc: "#d1fae5", xlsx: "#fce7f3", presentation: "#e0e7ff", audio: "#fae8ff", text: "#f1f5f9" };
  breakdown.innerHTML = Object.entries(types).map(([type, count]) => `
    <div class="content-type-card">
      <div class="content-type-icon" style="background:${colors[type] || '#f1f5f9'}">${icons[type] || "📄"}</div>
      <div><div class="ct-count">${count}</div><div class="ct-name">${type}</div></div>
    </div>
  `).join("");

  const flows = document.getElementById("overview-flows");
  if (flows) {
    flows.innerHTML = `
      <div class="stat-card"><div class="stat-value">${summary.total_user_flows || 0}</div><div class="stat-label">User Flows Identified</div></div>
    `;
  }
}

async function loadExecSummary(jobId) {
  const el = document.getElementById("overview-exec");
  if (!el) return;
  try {
    const resp = await fetch(`${API_BASE}/exec/${jobId}`);
    if (!resp.ok) {
      el.innerHTML = "";
      return;
    }
    const s = await resp.json();
    const dirColor = s.direction === "improved" ? "#16a34a" : s.direction === "declined" ? "#dc2626" : "#6b7280";
    const dirArrow = s.direction === "improved" ? "▲" : s.direction === "declined" ? "▼" : "■";
    const badge = it => `<span style="padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;background:${it.impact === "high" ? "#fee2e2" : it.impact === "medium" ? "#fef3c7" : "#dcfce7"};color:${it.impact === "high" ? "#b91c1c" : it.impact === "medium" ? "#b45309" : "#15803d"}">${it.impact}</span>`;
    const effortBadge = it => `<span style="padding:2px 8px;border-radius:10px;font-size:11px;background:#e0e7ff;color:#4338ca">${it.effort} effort</span>`;
    const row = it => `
      <div style="border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:8px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <strong>${escapeHtml(it.title)}</strong> ${badge(it)} ${effortBadge(it)}
          <span style="margin-left:auto;color:var(--text-secondary);font-size:12px">${escapeHtml(it.drive)}</span>
        </div>
        <div style="font-size:12px;color:var(--text-secondary);margin-top:4px">→ ${escapeHtml(it.next_step)}</div>
        <details style="margin-top:8px">
          <summary style="font-size:12px;color:var(--accent);cursor:pointer">Why it matters + how to fix</summary>
          <div style="margin-top:8px;font-size:13px;line-height:1.5">${escapeHtml(it.explanation || "")}</div>
          ${(it.how_to_fix || []).length ? `<ol style="margin:8px 0 0;padding-left:20px;font-size:13px;color:var(--text-secondary)">${it.how_to_fix.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ol>` : ""}
          ${(it.evidence || []).length ? `<div style="margin-top:8px;font-size:12px"><strong style="color:var(--text-secondary)">Evidence:</strong><ul style="margin:4px 0 0;padding-left:20px;color:var(--text-secondary)">${it.evidence.map(e => `<li>${linkifyText(e, 120)}</li>`).join("")}</ul></div>` : ""}
        </details>
      </div>`;
    const section = (title, items) => items.length ? `
      <div style="margin-bottom:12px"><strong style="font-size:13px;color:var(--text-secondary)">${title}</strong>
      ${items.map(row).join("")}</div>` : "";
    const allSection = (s.all_issues || []).length > 5 ? `
      <div style="margin-top:14px"><details>
        <summary style="font-size:13px;color:var(--text-secondary);cursor:pointer">All ${s.all_issues.length} issues (full list)</summary>
        <div style="margin-top:10px">${s.all_issues.map(row).join("")}</div>
      </details></div>` : "";
    el.innerHTML = `
      <h3>Executive Summary <span class="count-label">(score ${s.score ?? "N/A"}${s.previous_score != null ? `, previous ${s.previous_score}` : ""} ${dirArrow} ${s.direction})</span></h3>
      ${s.overview ? `<p style="font-size:13px;line-height:1.5;margin:8px 0 14px;color:var(--text-secondary)">${escapeHtml(s.overview)}</p>` : ""}
      ${section("Priority issues", s.top_issues || [])}
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
        <div class="insights-card" style="min-width:0">${section("Quick wins", s.quick_wins || []) || '<div style="font-size:13px;color:var(--text-secondary)">No quick wins</div>'}</div>
        <div class="insights-card" style="min-width:0">${section("Long-term work", s.long_term || []) || '<div style="font-size:13px;color:var(--text-secondary)">No long-term items</div>'}</div>
      </div>
      ${allSection}
    `;
    const hl = document.querySelector(".tab[data-tab='overview'] .count-label");
    if (hl) hl.style.color = dirColor;
  } catch (err) {
    el.innerHTML = "";
  }
}

async function loadSiteHealth(jobId) {
  const el = document.getElementById("overview-health");
  if (!el) return;
  el.innerHTML = '<div class="insights-card">Loading site health...</div>';
  try {
    const resp = await fetch(`${API_BASE}/sites/${jobId}/health`);
    if (!resp.ok) {
      el.innerHTML = serviceErrorHtml("Site health", `Failed to load: ${resp.status}`);
      return;
    }
    const h = await resp.json();
    const m = h.metrics || {};
    const issues = h.issues || [];
    const gradeColor = { A: "#16a34a", B: "#84cc16", C: "#d97706", D: "#dc2626", F: "#b91c1c" }[h.grade] || "#6b7280";
    el.innerHTML = `
      <h3>Site Health <span class="count-label">(grade ${h.grade}, ${h.score}/100)</span></h3>
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
        <div class="insights-card"><div class="insights-label">Grade</div><div class="insights-value" style="color:${gradeColor};font-size:28px;font-weight:700">${h.grade || "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Health Score</div><div class="insights-value">${h.score ?? "N/A"}/100</div></div>
        <div class="insights-card"><div class="insights-label">Broken Links</div><div class="insights-value">${m.broken_links ?? "N/A"}${m.broken_link_rate != null ? ` (${m.broken_link_rate}%)` : ""}</div></div>
        <div class="insights-card"><div class="insights-label">Meta Description</div><div class="insights-value">${m.meta_description_coverage ?? "N/A"}%</div></div>
        <div class="insights-card"><div class="insights-label">Alt Text Coverage</div><div class="insights-value">${m.alt_text_coverage ?? "N/A"}%</div></div>
        <div class="insights-card"><div class="insights-label">Core Web Vitals</div><div class="insights-value">${m.avg_cwv_score ?? "N/A"}<span style="font-size:11px">${m.cwv_pages_checked ? ` (${m.cwv_pages_checked} pages)` : ""}</span></div></div>
        <div class="insights-card"><div class="insights-label">Thin Pages</div><div class="insights-value">${m.thin_pages ?? 0}</div></div>
        <div class="insights-card"><div class="insights-label">Pending Actions</div><div class="insights-value">${m.pending_action_items ?? 0}</div></div>
      </div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:10px">
        <div class="insights-card" style="min-width:180px"><div class="insights-label">Duplicate Pages</div><div class="insights-value">${m.duplicate_pages ?? "N/A"}</div></div>
        <div class="insights-card" style="min-width:180px"><div class="insights-label">Canonical Conflicts</div><div class="insights-value">${m.canonical_conflicts ?? "N/A"}</div></div>
        <div class="insights-card" style="min-width:180px"><div class="insights-label">Structured Data Valid</div><div class="insights-value">${m.structured_data_valid ?? "N/A"}</div></div>
      </div>
      ${issues.length ? `
        <h3 style="margin-top:16px">Health Issues (${issues.length})</h3>
        <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr))">
          ${issues.map(i => `
            <div class="insights-card" style="border-left:3px solid ${i.severity === "high" ? "#dc2626" : i.severity === "medium" ? "#d97706" : "#6b7280"}">
              <div class="insights-label" style="text-transform:capitalize">${i.severity}</div>
              <div style="font-size:13px;color:var(--text-secondary)">${escapeHtml(i.message)}</div>
            </div>`).join("")}
        </div>` : ""}
    `;
  } catch (err) {
    el.innerHTML = serviceErrorHtml("Site health", err.message);
  }
}

async function loadTracking(jobId) {
  const el = document.getElementById("overview-tracking");
  if (!el) return;
  try {
    const resp = await fetch(`${API_BASE}/tracking/${jobId}`);
    if (resp.status === 404) {
      el.innerHTML = "";
      return;
    }
    const data = await resp.json();
    const latest = data.latest;
    if (!latest) {
      el.innerHTML = "";
      return;
    }
    const results = latest.results || [];
    el.innerHTML = `
      <h3>Keyword Tracking <span class="count-label">(last check ${latest.checked_at ? new Date(latest.checked_at).toLocaleString() : "N/A"})</span></h3>
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr))">
        ${results.map(r => {
          const delta = r.delta;
          const arrow = delta > 0 ? `<span style="color:var(--success)">▲ +${delta}</span>` : delta < 0 ? `<span style="color:var(--danger)">▼ ${delta}</span>` : "";
          return `<div class="insights-card">
            <div class="insights-label">${escapeHtml(r.keyword)}</div>
            <div class="insights-value">${r.rank ? `#${r.rank}` : "Not ranked"} <span style="font-size:12px">${arrow}</span></div>
            <div style="font-size:12px;color:var(--text-secondary)">${r.approved_action_types && r.approved_action_types.length ? "Approved changes: " + r.approved_action_types.join(", ") : ""}</div>
          </div>`;
        }).join("")}
      </div>
      <button class="btn-approve" style="margin-top:12px;padding:6px 14px;font-size:13px" onclick="runTrackingCheck('${jobId}')">Check Rankings Now</button>
    `;
  } catch (err) {
    el.innerHTML = "";
  }
}

async function runTrackingCheck(jobId) {
  try {
    const resp = await fetch(`${API_BASE}/tracking/${jobId}/check`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    showToast(`Keyword check done: ${data.ranked ?? 0} ranked, ${data.moved_up ?? 0} moved up`);
    loadTracking(jobId);
  } catch (err) {
    showToast("Keyword check failed: " + err.message);
  }
}

async function loadTrends(jobId) {
  const el = document.getElementById("overview-trends");
  if (!el) return;
  el.innerHTML = "";
  try {
    const summaryResp = await fetch(`${API_BASE}/analysis/${jobId}/summary`);
    const summary = await summaryResp.json();
    const domain = (summary.url || "").split("//").pop().split("/")[0];
    if (!domain) return;
    const resp = await fetch(`${API_BASE}/trends/${encodeURIComponent(domain)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    const points = data.points || [];
    if (points.length < 2) return;
    const keywordCell = p => {
      const ranked = p.keyword_ranked;
      if (ranked === null || ranked === undefined) {
        return `<span class="badge badge-warn" title="Connect a SERP API key in .env, then run Keyword Check">Unconfigured</span>`;
      }
      return ranked;
    };
    const brokenCell = p => {
      const broken = p.broken_link_count ?? p.broken_links;
      const scanned = p.total_links_scanned;
      return (broken ?? "—") + (scanned ? ` / ${scanned}` : "");
    };
    const deltaCell = (p, key, inverse = false) => {
      const d = (p.deltas && p.deltas[key]) ?? (p === points[0] ? null : undefined);
      if (d === null || d === undefined || d === 0) return "—";
      const good = inverse ? d < 0 : d > 0;
      const color = good ? "#16a34a" : "#dc2626";
      const arrow = d > 0 ? "▲" : "▼";
      return `<span style="color:${color};font-size:12px" title="vs previous analysis">${arrow} ${d > 0 ? "+" : ""}${d}</span>`;
    };
    const rows = points.map(p => {
      const score = p.health_score;
      const bar = score !== null && score !== undefined
        ? `<div style="background:var(--bg-secondary);border-radius:4px;height:8px;width:120px;display:inline-block;vertical-align:middle"><div style="background:${score >= 80 ? "#16a34a" : score >= 60 ? "#d97706" : "#dc2626"};width:${score}%;height:8px;border-radius:4px"></div></div>`
        : "";
      return `<tr>
        <td style="white-space:nowrap">${new Date(p.completed_at).toLocaleDateString()}</td>
        <td>${escapeHtml(p.health_grade || "—")}</td>
        <td>${bar} ${score !== null && score !== undefined ? score : "—"}</td>
        <td>${deltaCell(p, "health_score")}</td>
        <td>${p.avg_cwv_score ?? "—"}</td>
        <td>${keywordCell(p)}</td>
        <td>${brokenCell(p)}</td>
        <td>${deltaCell(p, "broken_link_count", true)}</td>
        <td>${p.total_pages ?? "—"}</td>
      </tr>`;
    }).join("");
    el.innerHTML = `
      <h3>Longitudinal Trends <span class="count-label">(${points.length} analyses of ${escapeHtml(domain)})</span></h3>
      <div class="table-container">
        <table class="data-table">
          <thead><tr><th>Date</th><th>Grade</th><th>Health Score</th><th>Δ Score</th><th>Avg CWV</th><th>Keywords Ranked</th><th>Broken Links</th><th>Δ Broken</th><th>Pages</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  } catch {
    el.innerHTML = "";
  }
}

let chartInstances = [];

function destroyCharts() {
  chartInstances.forEach(c => { try { c.destroy(); } catch (e) {} });
  chartInstances = [];
}

function makeLineChart(canvasId, labels, datasets, yAxis = null) {
  if (typeof Chart === "undefined") return null;
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;
  const chart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: datasets.length > 1,
          labels: { color: "#64748b", boxWidth: 12, font: { size: 11 } },
        },
      },
      scales: {
        x: {
          ticks: { color: "#64748b", maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
          grid: { color: "rgba(148,163,184,0.12)" },
        },
        y: yAxis || { ticks: { color: "#64748b" }, grid: { color: "rgba(148,163,184,0.12)" } },
      },
    },
  });
  chartInstances.push(chart);
  return chart;
}

async function loadAnalytics(jobId) {
  destroyCharts();
  const el = document.getElementById("tab-analytics");
  if (!el) return;
  try {
    if (typeof Chart === "undefined") {
      el.innerHTML = '<p class="section-desc">Chart.js failed to load (check internet connection).</p>';
      return;
    }
    Chart.defaults.color = "#64748b";
    Chart.defaults.borderColor = "rgba(148,163,184,0.12)";
    const summaryResp = await fetch(`${API_BASE}/analysis/${jobId}/summary`);
    const summary = await summaryResp.json();
    const domain = (summary.url || "").split("//").pop().split("/")[0];
    if (!domain) return;
    const resp = await fetch(`${API_BASE}/trends/${encodeURIComponent(domain)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    const points = (data.points || []).filter(p => p.health_score !== null && p.health_score !== undefined);
    if (points.length < 2) {
      el.innerHTML = '<p class="section-desc">Need at least two completed analyses to chart trends.</p>';
      return;
    }
    const labels = points.map(p => new Date(p.completed_at).toLocaleDateString());
    makeLineChart("chart-health", labels, [{
      label: "Health score",
      data: points.map(p => p.health_score),
      borderColor: "#16a34a", backgroundColor: "rgba(22,163,74,0.15)", fill: true, tension: 0.3,
    }]);
    makeLineChart("chart-broken", labels, [{
      label: "Broken links",
      data: points.map(p => p.broken_link_count ?? p.broken_links),
      borderColor: "#dc2626", backgroundColor: "rgba(220,38,38,0.15)", fill: true, tension: 0.3,
    }]);
    makeLineChart("chart-pages", labels, [{
      label: "Pages",
      data: points.map(p => p.total_pages),
      borderColor: "#0ea5e9", backgroundColor: "rgba(14,165,233,0.15)", fill: true, tension: 0.3,
    }]);

    const trackResp = await fetch(`${API_BASE}/tracking/${jobId}`);
    const track = await trackResp.json();
    const history = (track.history || []).slice().sort((a, b) => new Date(a.checked_at) - new Date(b.checked_at));
    const kwBox = document.getElementById("chart-keywords");
    if (history.length >= 2 && kwBox) {
      const kLabels = history.map(h => new Date(h.checked_at).toLocaleDateString());
      const keywordOrder = [];
      history.forEach(h => (h.results || []).forEach(r => {
        if (r.keyword && !keywordOrder.includes(r.keyword)) keywordOrder.push(r.keyword);
      }));
      const palette = ["#6366f1", "#0ea5e9", "#f59e0b", "#ec4899", "#10b981", "#8b5cf6", "#ef4444", "#14b8a6"];
      const datasets = keywordOrder.slice(0, 8).map((kw, i) => ({
        label: kw.length > 24 ? kw.slice(0, 24) + "…" : kw,
        data: history.map(h => {
          const r = (h.results || []).find(x => x.keyword === kw);
          return r && r.rank !== null && r.rank !== undefined ? r.rank : null;
        }),
        borderColor: palette[i % palette.length],
        backgroundColor: palette[i % palette.length],
        spanGaps: true, tension: 0.3, borderWidth: 2,
      }));
      makeLineChart("chart-keywords", kLabels, datasets, {
        reverse: true,
        ticks: { color: "#64748b" },
        grid: { color: "rgba(148,163,184,0.12)" },
        title: { display: true, text: "Rank (lower is better)", color: "#64748b" },
      });
    } else if (kwBox) {
      kwBox.parentElement.innerHTML = '<p class="section-desc">Run Keyword Check at least twice to chart ranking trends.</p>';
    }
  } catch {
    el.innerHTML = '<p class="section-desc">Analytics unavailable for this site.</p>';
  }
}

async function loadPages(jobId) {
  const resp = await fetch(`${API_BASE}/pages/${jobId}?limit=500`);
  const data = await resp.json();
  document.getElementById("pages-count").textContent = `${data.total} pages`;

  const search = document.getElementById("pages-search").value.toLowerCase();
  const filtered = data.pages.filter(p =>
    p.url.toLowerCase().includes(search) ||
    (p.title || "").toLowerCase().includes(search)
  );

  const table = document.getElementById("pages-table");
  if (filtered.length === 0) {
    table.innerHTML = '<p class="section-desc">No pages found.</p>';
    return;
  }

  table.innerHTML = `
    <table class="data-table">
      <thead><tr>
        <th>URL</th><th>Type</th><th>Title</th><th>Words</th><th>Links</th><th>Images</th><th>Schema</th><th>Indexable</th>
      </tr></thead>
      <tbody>${filtered.map(p => `
        <tr>
          <td class="page-url-cell" title="${p.url}">${linkify(p.url, 90)}</td>
          <td><span class="page-type-badge">${p.page_type || "other"}</span></td>
          <td>${(p.title || "-").substring(0, 50)}</td>
          <td>${p.word_count || 0}</td>
          <td>${p.internal_links || 0}i / ${p.external_links || 0}e</td>
          <td>${p.image_count || 0}</td>
          <td>${p.has_structured_data ? "✅" : "❌"}</td>
          <td>${p.is_indexable ? "✅" : "❌"}</td>
        </tr>
      `).join("")}</tbody>
    </table>
  `;
}

// Search binding
document.getElementById("pages-search")?.addEventListener("input", () => {
  if (currentJobId) loadPages(currentJobId);
});

async function loadContent(jobId) {
  const table = document.getElementById("content-table");
  table.innerHTML = '<div class="insights-card">Loading content...</div>';
  const filter = document.getElementById("content-type-filter").value;
  const params = new URLSearchParams({ limit: "500" });
  if (filter) params.set("content_type", filter);

  let data;
  try {
    const resp = await fetch(`${API_BASE}/content/${jobId}?${params}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    document.getElementById("content-count").textContent = "0 items";
    table.innerHTML = `<div class="insights-card">Failed to load content: ${escapeHtml(err.message)}</div>`;
    return;
  }

  document.getElementById("content-count").textContent = `${data.total} items`;

  const items = data.items || [];
  if (items.length === 0) {
    table.innerHTML = '<div class="insights-card">No content items found.</div>';
    return;
  }

  const typeIcons = { image: "🖼", pdf: "📄", video: "🎬", doc: "📝", xlsx: "📊", presentation: "📽", audio: "🎵", text: "📃" };

  table.innerHTML = `
    <table class="data-table">
      <thead><tr>
        <th>Type</th><th>Preview</th><th>Source URL</th><th>Page URL</th><th>Size</th><th>MIME</th>
      </tr></thead>
      <tbody>${items.map(c => `
        <tr style="cursor:pointer" onclick="showContentDetail('${c.id}')">
          <td>${typeIcons[c.content_type] || "📄"} ${escapeHtml(c.content_type)}</td>
          <td>${contentPreview(c)}</td>
          <td class="page-url-cell" title="${escapeHtml(c.source_url)}">${linkify(c.source_url, 60)}</td>
          <td class="page-url-cell" title="${escapeHtml(c.page_url)}">${linkify(c.page_url, 60)}</td>
          <td>${c.file_size ? formatSize(c.file_size) : "-"}</td>
          <td>${escapeHtml(c.mime_type) || "-"}</td>
        </tr>
      `).join("")}</tbody>
    </table>
  `;
}

function contentPreview(c) {
  if (!c.file_url) return '<span class="count-label">not cached</span>';
  if (c.content_type === "image") {
    return `<img src="${c.file_url}" loading="lazy" style="width:56px;height:56px;object-fit:cover;border-radius:6px;border:1px solid var(--border)" title="${escapeHtml(c.source_url)}">`;
  }
  return `<a href="${c.file_url}" target="_blank" rel="noopener" class="btn-secondary" style="font-size:11px;padding:3px 8px">View</a>`;
}

async function showContentDetail(contentId) {
  showModal("Content Detail", '<div class="loading">Loading...</div>');
  try {
    const resp = await fetch(`${API_BASE}/content/${currentJobId}/detail/${contentId}`);
    const data = await resp.json();
    const c = data.content;
    const ext = data.extraction;

    let html = `
      <div class="content-detail-section">
        <h4>Content Info</h4>
        ${c.file_url ? (c.content_type === "image"
          ? `<div style="margin-bottom:12px"><img src="${c.file_url}" style="max-width:320px;max-height:240px;border-radius:8px;border:1px solid var(--border)" alt="Content preview"></div>`
          : `<div style="margin-bottom:12px"><a href="${c.file_url}" target="_blank" rel="noopener" class="btn-primary" style="display:inline-block">Open file</a></div>`) : ""}
        <div class="data-row"><span class="label">Type</span><span class="value">${c.content_type}</span></div>
        <div class="data-row"><span class="label">Source URL</span><span class="value" style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${linkify(c.source_url, 100)}</span></div>
        <div class="data-row"><span class="label">Page URL</span><span class="value" style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.page_url}</span></div>
        <div class="data-row"><span class="label">File Size</span><span class="value">${c.file_size ? formatSize(c.file_size) : "-"}</span></div>
        <div class="data-row"><span class="label">MIME Type</span><span class="value">${c.mime_type || "-"}</span></div>
        <div class="data-row"><span class="label">File Path</span><span class="value">${c.file_path || "-"}</span></div>
      </div>
    `;

    if (ext) {
      html += `<div class="content-detail-section"><h4>Extraction Results (${ext.content_type})</h4>`;

      if (ext.statistics) {
        const s = ext.statistics;
        html += `
          <div class="data-row"><span class="label">Total Words</span><span class="value">${s.total_words || 0}</span></div>
          <div class="data-row"><span class="label">Tables Found</span><span class="value">${s.total_tables || 0}</span></div>
          <div class="data-row"><span class="label">Images Found</span><span class="value">${s.total_images_extracted || 0}</span></div>
          <div class="data-row"><span class="label">Text Chunks</span><span class="value">${s.total_text_chunks || 0}</span></div>
        `;
      }

      if (ext.text_chunks && ext.text_chunks.length > 0) {
        html += `<h4 style="margin-top:12px">Extracted Text (${ext.text_chunks.length} chunks)</h4>`;
        for (const chunk of ext.text_chunks.slice(0, 3)) {
          const text = (chunk.text || "").trim().substring(0, 500);
          if (!text) continue;
          html += `<div style="background:var(--bg-secondary);border-radius:6px;padding:10px;margin-top:6px;font-size:12px;color:var(--text-secondary);white-space:pre-wrap">${escapeHtml(text)}${text.length >= 500 ? "…" : ""}</div>`;
        }
      }

      if (ext.tables && ext.tables.length > 0) {
        html += `<h4 style="margin-top:12px">Tables (${ext.tables.length})</h4>`;
        for (const tab of ext.tables.slice(0, 3)) {
          html += `<p style="font-size:12px;color:var(--text-secondary)">Page ${tab.page}, ${tab.rows}x${tab.cols}</p>`;
          if (tab.data_preview && tab.data_preview.length > 0) {
            html += `<table><thead><tr>${(tab.headers||[]).map(h => `<th>${escapeHtml(h)}</th>`).join("") || '<th>Data</th>'}</tr></thead><tbody>`;
            for (const row of tab.data_preview.slice(0, 5)) {
              html += `<tr>${row.map(cell => `<td>${escapeHtml(String(cell).substring(0, 100))}</td>`).join("")}</tr>`;
            }
            html += `</tbody></table>`;
          }
        }
      }

      if (ext.images && ext.images.length > 0) {
        html += `<h4 style="margin-top:12px">Extracted Images (${ext.images.length})</h4>`;
        for (const img of ext.images.slice(0, 5)) {
          html += `<div class="data-row"><span class="label">Page ${img.page} #${img.index}</span><span class="value">${img.width}x${img.height} ${img.format} (${formatSize(img.size_bytes)})</span></div>`;
        }
      }

      if (ext.metadata) {
        html += `<h4 style="margin-top:12px">Metadata</h4>`;
        for (const [k, v] of Object.entries(ext.metadata)) {
          html += `<div class="data-row"><span class="label">${k}</span><span class="value">${v ?? "-"}</span></div>`;
        }
      }

      html += `</div>`;
    }

    html += `<div class="data-row"><span class="label">Action Items</span><span class="value">${data.action_count}</span></div>`;

    document.getElementById("modal-body").innerHTML = html;
  } catch (err) {
    document.getElementById("modal-body").innerHTML = `<p>Error: ${err.message}</p>`;
  }
}

function showModal(title, bodyHtml) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = bodyHtml;
  document.getElementById("modal-overlay").classList.remove("hidden");
}

function closeModal() {
  document.getElementById("modal-overlay").classList.add("hidden");
}

document.getElementById("modal-overlay")?.addEventListener("click", e => {
  if (e.target === e.currentTarget) closeModal();
});

document.getElementById("content-type-filter")?.addEventListener("change", () => {
  if (currentJobId) loadContent(currentJobId);
});

async function loadLinks(jobId) {
  const resp = await fetch(`${API_BASE}/links/${jobId}`);
  const data = await resp.json();
  document.getElementById("links-stats").innerHTML = `
    <div class="stat-card"><div class="stat-value">${data.total_links}</div><div class="stat-label">Total Links (unique targets)</div></div>
    <div class="stat-card"><div class="stat-value">${data.total_internal}</div><div class="stat-label">Internal Links</div></div>
    <div class="stat-card"><div class="stat-value">${data.total_external}</div><div class="stat-label">External Links</div></div>
    <div class="stat-card"><div class="stat-value">${data.total_links ? ((data.total_internal / data.total_links) * 100).toFixed(0) : 0}%</div><div class="stat-label">Internal Ratio</div></div>
    <div class="stat-card"><div class="stat-value">${data.total_link_occurrences ?? 0}</div><div class="stat-label">Link Occurrences</div></div>
  `;

  const backlinksResp = await fetch(`${API_BASE}/links/${jobId}/backlinks`);
  const blData = await backlinksResp.json();
  document.getElementById("backlinks-list").innerHTML = !blData.backlinks || blData.backlinks.length === 0
    ? '<p class="section-desc">No backlink sources discovered. See SEO Insights tab to run discovery.</p>'
    : `<p class="section-desc">${blData.total} source page(s) from ${blData.referring_domains} referring domain(s)</p>
       <table class="data-table"><thead><tr><th>Source URL</th><th>Domain</th><th>Anchor</th></tr></thead>
       <tbody>${blData.backlinks.map(b => `<tr><td class="page-url-cell" title="${b.source_url}">${linkify(b.source_url, 60)}</td><td>${b.source_domain || "-"}</td><td>${(b.anchor || "-").substring(0, 60)}</td></tr>`).join("")}</tbody></table>`;
  loadLinkHealth(jobId);
  loadDummySite(jobId);
}

async function loadLinkHealth(jobId) {
  const summaryEl = document.getElementById("link-health-summary");
  const issuesEl = document.getElementById("link-health-issues");
  try {
    const resp = await fetch(`${API_BASE}/links/${jobId}/health`);
    const data = await resp.json();
    const s = data.summary || {};
    const ls = data.length_stats || {};
    summaryEl.innerHTML = `
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr))">
        <div class="insights-card"><div class="insights-label">Checked</div><div class="insights-value">${s.checked ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">OK</div><div class="insights-value" style="color:var(--success)">${s.ok ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Broken (4xx/5xx)</div><div class="insights-value" style="color:var(--danger)">${s.broken ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Redirects</div><div class="insights-value" style="color:#d97706">${s.redirect ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Blocked (401/403)</div><div class="insights-value" style="color:#b45309">${s.blocked ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Unreachable</div><div class="insights-value">${s.unreachable ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Avg Link Length</div><div class="insights-value">${ls.avg ?? "-"} chars</div></div>
      </div>
      ${s.status === "not_checked" ? '<p class="section-desc" style="margin-top:10px">Links not checked yet for this job. Run Check or re-run analysis.</p>' : ""}
      ${(ls.longest || []).length ? `
      <div style="margin-top:12px">
        <p class="section-desc"><strong>Longest links:</strong></p>
        <ul style="margin:6px 0 0;padding-left:20px;font-size:13px;color:var(--text-secondary)">
          ${ls.longest.map(l => `<li>${l.length} chars - ${linkify(l.url, 100)}</li>`).join("")}
        </ul>
      </div>` : ""}
    `;
    const issues = data.issues || [];
    issuesEl.innerHTML = issues.length === 0
      ? '<p class="section-desc">No link issues found.</p>'
      : `<p class="section-desc">${issues.length} problematic unique link(s):</p>
         <table class="data-table"><thead><tr><th>Status</th><th>Code</th><th>Length</th><th>URL</th><th>Linked From</th></tr></thead>
         <tbody>${issues.map(i => `<tr>
           <td><span class="page-type-badge" style="background:#fee2e2;color:#b91c1c">${i.status}</span></td>
           <td>${i.status_code ?? "-"}</td>
           <td>${i.length_chars ?? "-"}</td>
           <td class="page-url-cell" title="${i.url}">${linkify(i.url, 70)}</td>
           <td style="font-size:12px;color:var(--text-secondary)">${(i.pages || []).slice(0, 3).map(pg => linkify(pg, 40)).join("<br>") || "-"}</td>
         </tr>`).join("")}</tbody></table>`;
    loadAllLinks(jobId);
  } catch (err) {
    summaryEl.innerHTML = `<p class="section-desc">Error loading link health: ${escapeHtml(err.message)}</p>`;
  }
}

let allLinksOffset = 0;
let allLinksStatus = "";

async function loadAllLinks(jobId, { reset } = {}) {
  const el = document.getElementById("all-links-card");
  if (!el) return;
  if (reset) {
    allLinksOffset = 0;
    allLinksStatus = document.getElementById("all-links-filter")?.value || "";
  }
  const params = new URLSearchParams({ limit: "200", offset: String(allLinksOffset) });
  if (allLinksStatus) params.set("status", allLinksStatus);
  try {
    const resp = await fetch(`${API_BASE}/links/${jobId}/all?${params}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const rows = (data.links || []).map(l => `<tr>
      <td><span class="page-type-badge" style="background:${l.status === "ok" ? "#dcfce7" : "#fee2e2"};color:${l.status === "ok" ? "#15803d" : "#b91c1c"}">${l.status}</span></td>
      <td>${l.status_code ?? "-"}</td>
      <td class="page-url-cell" title="${l.url}">${linkify(l.url, 60)}</td>
      <td style="font-size:12px;color:var(--text-secondary)">${(l.pages || []).slice(0, 2).map(pg => linkify(pg, 30)).join("<br>") || "-"}</td>
    </tr>`).join("");
    el.innerHTML = `
      <p class="section-desc">${data.total} unique link target(s)${allLinksStatus ? ` (filter: ${allLinksStatus})` : ""}</p>
      <table class="data-table"><thead><tr><th>Status</th><th>Code</th><th>URL</th><th>Linked From</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="4" style="text-align:center;color:var(--text-secondary)">No links for this filter</td></tr>'}</tbody></table>
      ${allLinksOffset + (data.links || []).length < data.total
        ? `<button id="all-links-more" class="btn-secondary" style="margin-top:10px">Load more (${data.total - allLinksOffset - (data.links || []).length} remaining)</button>`
        : ""}
    `;
    document.getElementById("all-links-more")?.addEventListener("click", () => {
      allLinksOffset += 200;
      loadAllLinks(jobId);
    });
  } catch (err) {
    el.innerHTML = `<p class="section-desc">Error loading links: ${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById("all-links-filter")?.addEventListener("change", () => {
  if (currentJobId) loadAllLinks(currentJobId, { reset: true });
});

async function loadDummySite(jobId) {
  const el = document.getElementById("dummy-site-card");
  try {
    const resp = await fetch(`${API_BASE}/dummy/${jobId}`);
    const data = await resp.json();
    if (data.status === "not_generated" || !data.file_count) {
      el.innerHTML = `<p class="section-desc">No dummy site generated yet. Generate a static mirror with approved changes applied.</p>
        <button id="generate-dummy-btn" class="btn-secondary" style="margin-top:8px">Generate Dummy Site</button>`;
      document.getElementById("generate-dummy-btn").onclick = async () => {
        el.innerHTML = '<p class="section-desc">Generating mirror (fetches each page)...</p>';
        try {
          const g = await fetch(`${API_BASE}/dummy/${jobId}/generate`, { method: "POST" });
          const gd = await g.json();
          showToast(`Dummy site generated: ${gd.file_count} files, ${gd.changes_applied} changes applied`);
        } catch (e2) {
          showToast("Generation failed: " + e2.message);
        }
        loadDummySite(jobId);
      };
      return;
    }
      el.innerHTML = `
      ${data.stale ? `<div class="service-error" style="background:#fffbeb;border-color:#fde68a"><div class="service-error-title" style="color:#92400e">Mirror is out of date</div><div class="service-error-msg" style="color:#78350f">SEO actions were reviewed after this mirror was generated. Regenerate to apply the latest approved changes.</div></div>` : ""}
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr))">
        <div class="insights-card"><div class="insights-label">Files</div><div class="insights-value">${data.file_count}</div></div>
        <div class="insights-card"><div class="insights-label">Pages Mirrored</div><div class="insights-value">${data.pages}</div></div>
        <div class="insights-card"><div class="insights-label">Changes Applied</div><div class="insights-value" style="color:var(--success)">${data.changes_applied}</div></div>
        <div class="insights-card"><div class="insights-label">Suggestions Previewed</div><div class="insights-value" style="color:#d97706">${data.suggestions_applied ?? 0}</div></div>
        <div class="insights-card"><div class="insights-label">Pending Suggestions</div><div class="insights-value">${data.pending_changes ?? 0}</div></div>
        <div class="insights-card"><div class="insights-label">Links Rewritten</div><div class="insights-value">${data.links_rewritten}</div></div>
      </div>
      <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap">
        <a class="btn-primary" href="${data.url}" target="_blank" rel="noopener">Open Dummy Site</a>
        <a class="btn-secondary" href="${API_BASE}/dummy/${jobId}/download">Download ZIP</a>
        <button id="regenerate-dummy-btn" class="btn-secondary">Regenerate</button>
        <button id="compare-dummy-btn" class="btn-secondary">Compare & Report</button>
        <a class="btn-secondary" href="${API_BASE}/reports/${jobId}/compare" target="_blank" rel="noopener">Comparison HTML</a>
        <a class="btn-secondary" href="${API_BASE}/reports/${jobId}/compare/pdf" target="_blank" rel="noopener">Comparison PDF</a>
      </div>`;
    document.getElementById("regenerate-dummy-btn").onclick = async () => {
      await fetch(`${API_BASE}/dummy/${jobId}/generate`, { method: "POST" });
      showToast("Dummy site regenerated");
      loadDummySite(jobId);
    };
    document.getElementById("compare-dummy-btn").onclick = async () => {
      const btn = document.getElementById("compare-dummy-btn");
      btn.disabled = true;
      btn.textContent = "Comparing...";
      try {
        const resp = await fetch(`${API_BASE}/sites/${jobId}/compare-changes`, { method: "POST" });
        const c = await resp.json();
        if (!resp.ok) {
          showToast("Comparison failed: " + (c.detail || resp.status));
          return;
        }
        const alt = c.alt_text || {};
        const lb = c.link_health_before || {};
        const la = c.link_health_after || {};
        const dummy = c.dummy || {};
        const health = c.health || {};
        showModal("Original vs Suggested-Changes", `
          <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr))">
            <div class="insights-card"><div class="insights-label">Pages Compared</div><div class="insights-value">${c.pages_compared}</div></div>
            <div class="insights-card"><div class="insights-label">Changes Applied</div><div class="insights-value" style="color:var(--success)">${dummy.changes_applied ?? 0}</div></div>
            <div class="insights-card"><div class="insights-label">Suggestions Previewed</div><div class="insights-value" style="color:#d97706">${dummy.suggestions_applied ?? 0}</div></div>
            <div class="insights-card"><div class="insights-label">Pending Suggestions</div><div class="insights-value">${c.pending_suggestions ?? 0}</div></div>
            ${health.score !== undefined ? `<div class="insights-card"><div class="insights-label">Site Health</div><div class="insights-value">${health.grade ?? "N/A"} (${health.score}/100)</div></div>` : ""}
          </div>
          <h4 style="margin-top:16px">Alt text coverage: ${alt.coverage_before ?? "N/A"}% → <b style="color:var(--success)">${alt.coverage_after ?? "N/A"}%</b></h4>
          <div class="data-row"><span class="label">Images without alt (before)</span><span class="value">${alt.missing_before ?? "N/A"}</span></div>
          <div class="data-row"><span class="label">Images without alt (after)</span><span class="value" style="color:${(alt.missing_after ?? 999) < (alt.missing_before ?? 0) ? "var(--success)" : ""}">${alt.missing_after ?? "N/A"}</span></div>
          <div class="data-row"><span class="label">Broken links (original)</span><span class="value">${lb.broken ?? 0} / ${lb.checked ?? 0}</span></div>
          <div class="data-row"><span class="label">Broken links (dummy mirror)</span><span class="value">${la.broken ?? 0} / ${la.checked ?? 0}</span></div>
          <p class="section-desc" style="margin-top:12px"><a href="${API_BASE}/reports/${jobId}/compare" target="_blank" rel="noopener">Full comparison report (HTML)</a> · <a href="${API_BASE}/reports/${jobId}/compare/pdf" target="_blank" rel="noopener">PDF</a></p>
        `);
      } catch (err) {
        showToast("Comparison failed: " + err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = "Compare & Report";
      }
    };
  } catch (err) {
    el.innerHTML = `<p class="section-desc">Error: ${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById("check-links-btn").addEventListener("click", async () => {
  document.getElementById("link-health-summary").innerHTML = '<p class="section-desc">Checking links...</p>';
  try {
    const resp = await fetch(`${API_BASE}/links/${currentJobId}/check`, { method: "POST" });
    const data = await resp.json();
    showToast(`Link check done: ${data.checked} checked, ${data.broken} broken`);
  } catch (err) {
    showToast("Link check failed: " + err.message);
  }
  loadLinkHealth(currentJobId);
});


async function loadActions(jobId) {
  const statusFilter = document.getElementById("action-status-filter").value;
  const severity = document.getElementById("action-severity-filter").value;
  const sort = document.getElementById("action-sort-filter").value;
  const params = new URLSearchParams();
  if (statusFilter) params.set("status_filter", statusFilter);
  if (severity) params.set("severity", severity);
  if (sort) params.set("sort", sort);
  const resp = await fetch(`${API_BASE}/actions/${jobId}?${params.toString()}`);
  const data = await resp.json();
  document.getElementById("actions-count").textContent = `${data.total} items`;

  const list = document.getElementById("actions-list");
  if (data.actions.length === 0) {
    list.innerHTML = '<p class="section-desc">No action items.</p>';
  } else {
    list.innerHTML = data.actions.map(a => `
      <div class="action-card" data-id="${a.id}">
        <div class="action-header">
          <span class="action-type">${a.content_type}</span>
          <span class="action-impact impact-${a.impact_on_ranking}">${a.impact_on_ranking} impact</span>
        </div>
        <div class="action-issues"><strong>Issues:</strong> ${(a.identified_issues || []).join("; ")}</div>
        <div class="action-improvements"><strong>Improve:</strong> ${(a.improvement_suggestions || []).join("; ")}</div>
        ${a.status === "pending" ? `
          <div class="action-approve">
            <button class="btn-approve" onclick="approveAction('${a.id}', 'approved')">Approve</button>
            <button class="btn-reject" onclick="approveAction('${a.id}', 'rejected')">Reject</button>
          </div>
        ` : `<span style="font-size:13px;color:${a.status === 'approved' ? 'var(--success)' : 'var(--danger)'}">${a.status}</span>`}
      </div>
    `).join("");
  }
  loadVersions(jobId);
}

async function loadVersions(jobId) {
  const el = document.getElementById("versions-list");
  try {
    const resp = await fetch(`${API_BASE}/actions/${jobId}/versions`);
    const data = await resp.json();
    if (!data.versions || data.versions.length === 0) {
      el.innerHTML = '<p class="section-desc">No changes applied yet. Approve action items to generate improved content.</p>';
      return;
    }
    el.innerHTML = data.versions.map(v => `
      <div class="action-card" style="border-left:3px solid ${v.status === 'approved' ? 'var(--success)' : 'var(--danger)'}">
        <div class="action-header">
          <span class="action-type">${v.content_type}</span>
          <span style="font-size:12px;color:${v.status === 'approved' ? 'var(--success)' : 'var(--danger)'};font-weight:600;text-transform:capitalize">${v.status === 'approved' ? 'Applied' : 'Rejected'}</span>
          <span style="font-size:12px;color:var(--text-secondary)">${v.field}</span>
        </div>
        <div class="action-issues"><strong>Before:</strong> <span style="color:var(--danger)">${escapeHtml((v.before || "-").substring(0, 200))}</span></div>
        <div class="action-improvements"><strong>After:</strong> <span style="color:var(--success)">${escapeHtml((v.after || "Not generated (rejected)").substring(0, 200))}</span></div>
        <div style="font-size:12px;color:var(--text-secondary);margin-top:6px">${linkify(v.page_url || "", 80)} · ${v.generated_by || ""}</div>
      </div>
    `).join("");
  } catch (err) {
    el.innerHTML = `<p class="section-desc">Error loading versions: ${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById("action-status-filter")?.addEventListener("change", () => {
  if (currentJobId) loadActions(currentJobId);
});

document.getElementById("action-severity-filter")?.addEventListener("change", () => {
  if (currentJobId) loadActions(currentJobId);
});

document.getElementById("action-sort-filter")?.addEventListener("change", () => {
  if (currentJobId) loadActions(currentJobId);
});

document.getElementById("reject-filtered-btn")?.addEventListener("click", async () => {
  if (!currentJobId) return;
  const severity = document.getElementById("action-severity-filter").value;
  const scope = severity ? ` (severity: ${severity})` : " (pending)";
  if (!confirm(`Reject all pending actions${scope}? This cannot be undone per-item.`)) return;
  const btn = document.getElementById("reject-filtered-btn");
  btn.disabled = true;
  btn.textContent = "Working...";
  try {
    const resp = await fetch(`${API_BASE}/actions/${currentJobId}/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "rejected", status_filter: "pending", severity: severity || null }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    showToast(`Rejected ${data.updated} action(s)`);
  } catch (err) {
    showToast("Reject failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Reject Filtered";
    if (currentJobId) loadActions(currentJobId);
  }
});

async function downloadPatch(fmt) {
  if (!currentJobId) return;
  try {
    const resp = await fetch(`${API_BASE}/actions/${currentJobId}/patch?format=${fmt}`);
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || resp.statusText);
    const text = await resp.text();
    const blob = new Blob([text], { type: fmt === "md" ? "text/markdown" : "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `seo-patch-${currentJobId}.${fmt}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    showToast("Patch exported");
  } catch (err) {
    showToast("Export failed: " + err.message);
  }
}

document.getElementById("patch-json-btn")?.addEventListener("click", () => downloadPatch("json"));
document.getElementById("patch-md-btn")?.addEventListener("click", () => downloadPatch("md"));

document.getElementById("approve-all-btn")?.addEventListener("click", async () => {
  if (!currentJobId) return;
  if (!confirm("Approve ALL pending SEO changes? This generates improved content for every pending action and rebuilds the dummy site. This cannot be undone per-item.")) return;
  const btn = document.getElementById("approve-all-btn");
  btn.disabled = true;
  btn.textContent = "Working...";
  try {
    const resp = await fetch(`${API_BASE}/actions/${currentJobId}/approve-all`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    showToast(`Approving ${data.pending ?? data.approved ?? 0} change(s) in the background...`);
    const started = Date.now();
    const poll = setInterval(async () => {
      try {
        const r = await fetch(`${API_BASE}/actions/${currentJobId}?status_filter=pending`);
        const d = await r.json();
        const timedOut = Date.now() - started > 20 * 60 * 1000;
        if ((d.total || 0) === 0 || timedOut) {
          clearInterval(poll);
          btn.disabled = false;
          btn.textContent = "Approve All";
          if (currentJobId) loadActions(currentJobId);
          showToast(timedOut ? "Approve all is still running - check the Actions tab shortly" : "All changes approved. Dummy site rebuilding...");
        }
      } catch (err) {
        clearInterval(poll);
        btn.disabled = false;
        btn.textContent = "Approve All";
      }
    }, 4000);
  } catch (err) {
    showToast("Approve all failed: " + err.message);
    btn.disabled = false;
    btn.textContent = "Approve All";
  }
});

async function approveAction(actionId, status) {
  const btn = document.querySelector(`.action-card[data-id="${actionId}"] .action-approve`);
  if (btn) btn.innerHTML = '<span style="font-size:13px;color:var(--text-secondary)">Processing...</span>';
  try {
    const resp = await fetch(`${API_BASE}/actions/${actionId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const data = await resp.json();
    if (status === "approved" && data.version?.after) {
      showToast(`Approved - change generated: ${data.version.after.substring(0, 60)}...`);
    } else {
      showToast(`Action ${status}`);
    }
    if (currentJobId) loadActions(currentJobId);
  } catch (err) {
    showToast("Error: " + err.message);
    if (currentJobId) loadActions(currentJobId);
  }
}

document.getElementById("refresh-report-btn")?.addEventListener("click", () => {
  if (currentJobId) loadReport(currentJobId);
});

async function loadReport(jobId) {
  const link = document.getElementById("report-download-link");
  link.href = `${API_BASE}/reports/${jobId}/download`;
  document.getElementById("report-pdf-link").href = `${API_BASE}/reports/${jobId}/pdf`;

  const resp = await fetch(`${API_BASE}/reports/${jobId}`);
  const report = await resp.json();

  const preview = document.getElementById("report-preview");
  const insights = report.seo_insights || {};
  const bl = insights.backlinks || {};
  const ov = insights.overview || {};
  const hasInsights = bl.backlinks !== undefined || ov.estimated_organic_traffic !== undefined;
  preview.innerHTML = `
    <h3>${report.report_title}</h3>
    <p style="color:var(--text-secondary);margin-bottom:16px;font-size:13px;">Generated: ${report.generated_at}</p>
    <div class="stats-grid" style="grid-template-columns:repeat(3,1fr)">
      <div class="stat-card"><div class="stat-value">${report.total_pages}</div><div class="stat-label">Pages</div></div>
      <div class="stat-card"><div class="stat-value">${report.total_links}</div><div class="stat-label">Links</div></div>
      <div class="stat-card"><div class="stat-value">${report.total_internal_links} / ${report.total_external_links}</div><div class="stat-label">Internal / External</div></div>
    </div>
    ${hasInsights ? `
    <h4 style="margin:20px 0 10px">External SEO Insights</h4>
    <div class="stats-grid" style="grid-template-columns:repeat(4,1fr)">
      ${bl.backlinks !== undefined ? `<div class="stat-card"><div class="stat-value">${bl.backlinks}</div><div class="stat-label">Backlinks</div></div>` : ""}
      ${bl.referring_domains !== undefined ? `<div class="stat-card"><div class="stat-value">${bl.referring_domains}</div><div class="stat-label">Referring Domains</div></div>` : ""}
      ${bl.rank !== undefined ? `<div class="stat-card"><div class="stat-value">${bl.rank}</div><div class="stat-label">Domain Rank</div></div>` : ""}
      ${ov.estimated_organic_traffic !== undefined && ov.estimated_organic_traffic !== null ? `<div class="stat-card"><div class="stat-value">${ov.estimated_organic_traffic}</div><div class="stat-label">Organic Traffic</div></div>` : ""}
    </div>` : ""}
    ${Object.keys(report.page_type_breakdown || {}).length ? `
    <h4 style="margin:20px 0 10px">Page Architecture (${report.total_pages} pages)</h4>
    <div class="content-types-grid">
      ${Object.entries(report.page_type_breakdown).map(([type, count]) => `
        <div class="content-type-card">
          <div><div class="ct-count">${count}</div><div class="ct-name">${type}</div></div>
        </div>
      `).join("")}
    </div>` : ""}
    ${(report.user_flows || []).length ? `
    <h4 style="margin:20px 0 10px">Top User Flows</h4>
    <table class="data-table">
      <thead><tr><th>Target Type</th><th>Depth</th><th>Flow Count</th><th>Target URL</th></tr></thead>
      <tbody>${report.user_flows.map(f => `
        <tr>
          <td>${f.target_type}</td>
          <td>${f.depth} hop(s)</td>
          <td>${f.flow_count}</td>
          <td class="page-url-cell" title="${f.target_url}">${linkify(f.target_url, 70)}</td>
        </tr>`).join("")}
      </tbody>
    </table>` : ""}
    <h4 style="margin:20px 0 10px">SEO Action Items (${report.seo_action_items.length})</h4>
    ${report.seo_action_items.slice(0, 10).map(a => `
      <div style="padding:10px 0;border-bottom:1px solid var(--border)">
        <strong>${a.content_type}</strong> - <span class="action-impact impact-${a.impact_on_ranking}">${a.impact_on_ranking}</span>
        <div style="font-size:13px;color:var(--text-secondary)">${(a.identified_issues || []).slice(0, 2).join("; ")}</div>
      </div>
    `).join("")}
    ${report.seo_action_items.length > 10 ? `<p style="margin-top:10px;font-size:13px;color:var(--text-secondary)">...and ${report.seo_action_items.length - 10} more items</p>` : ""}
  `;
  loadReportExtras(jobId, preview);
}

async function loadReportExtras(jobId, preview) {
  const kv = (label, value) => `<div class="stat-card"><div class="stat-value" style="font-size:14px">${value}</div><div class="stat-label">${label}</div></div>`;
  try {
    const sm = await fetch(`${API_BASE}/quality/${jobId}/sitemap`);
    if (sm.ok) {
      const d = await sm.json();
      preview.insertAdjacentHTML("beforeend", `
        <h4 style="margin:20px 0 10px">Sitemap</h4>
        <div class="stats-grid" style="grid-template-columns:repeat(3,1fr)">
          ${kv("Found", d.sitemap_found ? "✅" : "❌")}
          ${kv("Valid", d.sitemap_valid ? "✅" : "❌")}
          ${kv("URLs", d.url_count ?? "N/A")}
          ${kv("Uncrawled URLs", d.uncrawled_urls_count ?? 0)}
        </div>
        ${d.uncrawled_urls?.length ? `<p style="font-size:12px;color:var(--text-secondary);margin-top:6px">Sample: ${d.uncrawled_urls.slice(0, 5).map(escapeHtml).join(", ")}</p>` : ""}`);
    }
  } catch (_) {}
  try {
    const ai = await fetch(`${API_BASE}/quality/${jobId}/ai-visibility`);
    if (ai.ok) {
      const d = await ai.json();
      preview.insertAdjacentHTML("beforeend", `
        <h4 style="margin:20px 0 10px">AI-Search Visibility</h4>
        <div class="stats-grid" style="grid-template-columns:repeat(3,1fr)">
          ${kv("Score", (d.score ?? "N/A") + "/100")}
          ${kv("llms.txt", d.llms_txt_present ? "✅" : "❌")}
          ${kv("Blocked AI agents", d.blocked_ai_agents?.length ? d.blocked_ai_agents.join(", ") : "none")}
          ${kv("Pages w/ structured data", d.structured_data_pages + "/" + d.total_pages)}
        </div>`);
    }
  } catch (_) {}
  try {
    const lo = await fetch(`${API_BASE}/quality/${jobId}/local-seo`);
    if (lo.ok) {
      const d = await lo.json();
      preview.insertAdjacentHTML("beforeend", `
        <h4 style="margin:20px 0 10px">Local SEO Readiness</h4>
        <div class="stats-grid" style="grid-template-columns:repeat(3,1fr)">
          ${kv("Score", (d.score ?? "N/A") + "/100")}
          ${kv("LocalBusiness schema", d.local_business_schema ? "✅" : "❌")}
          ${kv("NAP schema", d.nap_schema_present ? "✅" : "❌")}
          ${kv("Contact page", d.contact_page_present ? "✅" : "❌")}
        </div>`);
    }
  } catch (_) {}
  try {
    const ca = await fetch(`${API_BASE}/quality/${jobId}/cannibalization`);
    if (ca.ok) {
      const d = await ca.json();
      if (d.groups) {
        preview.insertAdjacentHTML("beforeend", `
          <h4 style="margin:20px 0 10px">Keyword Cannibalization (${d.groups} keyword groups)</h4>
          <table class="data-table">
            <thead><tr><th>Keyword</th><th>Competing Pages</th></tr></thead>
            <tbody>${d.cannibalized_keywords.slice(0, 10).map(kw => `
              <tr><td>${escapeHtml(kw)}</td><td>${d.affected_pages || "N/A"}</td></tr>`).join("")}
            </tbody>
          </table>`);
      }
    }
  } catch (_) {}
}

// Chat
function initChat() {
  document.getElementById("chat-input").disabled = false;
  document.getElementById("chat-send").disabled = false;
  const hint = document.getElementById("chat-context-hint");
  if (hint) hint.textContent = currentJobId
    ? "Asking about the open site (all sections)."
    : "Global assistant — open a site to ask about it in full context.";
}

initChat();

document.getElementById("chat-toggle").addEventListener("click", () => {
  const panel = document.getElementById("chat-panel");
  panel.classList.toggle("hidden");
  if (!panel.classList.contains("hidden")) {
    const messages = document.getElementById("chat-messages");
    messages.scrollTop = messages.scrollHeight;
    document.getElementById("chat-input").focus();
  }
});

document.getElementById("chat-close").addEventListener("click", () => {
  document.getElementById("chat-panel").classList.add("hidden");
});

document.getElementById("chat-form").addEventListener("submit", async e => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const msg = input.value.trim();
  if (!msg) return;

  const messages = document.getElementById("chat-messages");
  messages.innerHTML += `<div class="chat-message user">${escapeHtml(msg)}</div>`;
  input.value = "";
  messages.scrollTop = messages.scrollHeight;

  const section = "";
  const payload = currentJobId
    ? { job_id: currentJobId, message: msg }
    : { message: msg };

  try {
    const resp = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      messages.innerHTML += `<div class="chat-message bot">Error: ${escapeHtml(data.detail || ("Service error (" + resp.status + ")"))}</div>`;
    } else {
      messages.innerHTML += `<div class="chat-message bot">${escapeHtml(data.reply)}</div>`;
    }
    messages.scrollTop = messages.scrollHeight;
  } catch (err) {
    messages.innerHTML += `<div class="chat-message bot">Error: ${err.message}</div>`;
  }
});

// Helpers
function showProgress() {
  inputSection.classList.add("hidden");
  progressSection.classList.remove("hidden");
  progressBar.style.width = "0%";
  progressMessage.textContent = "Starting...";
  progressTitle.textContent = "Crawling...";
  statusBadge.className = "status-badge status-queued";
  statusBadge.textContent = "Queued";
}

function hideProgress() {
  progressSection.classList.add("hidden");
}

function showToast(msg) {
  toast.textContent = msg;
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 3000);
}

// SEO Insights
function serviceErrorHtml(service, message, hint) {
  return `<div class="service-error">
    <div class="service-error-title">${escapeHtml(service || "Service")} unavailable</div>
    <div class="service-error-msg">${escapeHtml(message || "Unknown error")}</div>
    ${hint ? `<div class="service-error-hint">${escapeHtml(hint)}</div>` : ""}
  </div>`;
}

function insightErrorHtml(error) {
  const msg = String(error || "");
  if (/402|credits|fund|payment|quota/i.test(msg)) {
    return `<div class="service-error" style="background:#fffbeb;border-color:#fde68a">
      <div class="service-error-title" style="color:#92400e">DataForSEO unavailable (no credits)</div>
      <div class="service-error-msg" style="color:#78350f">Showing data from local crawl analysis instead. Add credits to DataForSEO for live keyword, backlink and domain data.</div>
    </div>`;
  }
  return serviceErrorHtml("External service", msg);
}

function sourceLabel(source) {
  const map = { dataforseo: "DataForSEO", serp: "SERP API", local: "local crawl data", none: "not available" };
  return map[source] || source || "not available";
}

function renderInsightSection(el, { data, error, source, emptyText, render }) {
  let html = "";
  if (error) html += insightErrorHtml(error);
  if (data && render) {
    html += `<p class="source-note">Source: ${sourceLabel(source)}</p>`;
    html += render(data);
  }
  if (!data && !error) html += `<div class="insights-card">${emptyText}</div>`;
  el.innerHTML = html;
}

async function loadQuality(jobId) {
  const el = document.getElementById("quality-content");
  if (!el) return;
  el.innerHTML = '<div class="insights-card">Loading quality audits...</div>';
  const [dup, sd, perf, geo, orphans, spend, summary, decay] = await Promise.all([
    clientGet(`${API_BASE}/quality/${jobId}/duplicates`),
    clientGet(`${API_BASE}/quality/${jobId}/structured-data`),
    clientGet(`${API_BASE}/quality/${jobId}/performance`),
    clientGet(`${API_BASE}/quality/${jobId}/geo-alignment`),
    clientGet(`${API_BASE}/quality/${jobId}/orphans`),
    clientGet(`${API_BASE}/spend/${jobId}`),
    clientGet(`${API_BASE}/analysis/${jobId}/summary`),
    clientGet(`${API_BASE}/quality/${jobId}/decay?months=6`),
  ]);
  el.innerHTML = renderQuality(dup, sd, perf, geo, orphans, summary?.geo_readiness, decay) + renderSpend(spend);
}

function renderSpend(spend) {
  if (!spend) return "";
  const rows = (spend.services || []).map(s => `
    <div style="display:flex;justify-content:space-between;gap:10px;padding:4px 0;font-size:13px">
      <span>${escapeHtml(s.service)}</span>
      <span class="count-label">${s.requests} req · ${s.tokens || 0} tokens · $${(s.est_cost || 0).toFixed(5)}</span>
    </div>`).join("");
  return `<div class="insights-card" style="margin-bottom:14px"><h3>API Spend & Usage</h3>
    <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr))">
      <div class="insights-card"><div class="insights-label">Total Requests</div><div class="insights-value">${spend.total_requests ?? 0}</div></div>
      <div class="insights-card"><div class="insights-label">Est. Cost</div><div class="insights-value">$${(spend.total_est_cost || 0).toFixed(5)}</div></div>
    </div>${rows}</div>`;
}

async function clientGet(url) {
  try {
    const resp = await fetch(url);
    if (resp.status === 404) return null;
    return resp.ok ? await resp.json() : null;
  } catch { return null; }
}

function qualitySection(title, inner) {
  return `<div class="insights-card" style="margin-bottom:14px"><h3>${title}</h3>${inner}</div>`;
}

function renderQuality(dup, sd, perf, geo, orphans, geoReadiness, decay) {
  let html = "";

  html += qualitySection("AI Search (GEO) Readiness", geoReadiness
    ? `<div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr))">
         <div class="insights-card"><div class="insights-label">Status</div><div class="insights-value">${escapeHtml(geoReadiness.status || "unknown")}${geoReadiness.score !== null && geoReadiness.score !== undefined ? ` (${geoReadiness.score}/100)` : ""}</div></div>
         <div class="insights-card"><div class="insights-label">robots.txt</div><div class="insights-value">${geoReadiness.robots_txt_found ? "found" : "not found"}</div></div>
         <div class="insights-card"><div class="insights-label">Blocked AI crawlers</div><div class="insights-value">${escapeHtml((geoReadiness.blocked_ai_crawlers || []).join(", ") || "none")}</div></div>
         <div class="insights-card"><div class="insights-label">Allowed AI crawlers</div><div class="insights-value">${escapeHtml((geoReadiness.allowed_ai_crawlers || []).join(", ") || "none")}</div></div>
       </div>
       <div class="insights-label" style="margin-top:8px">Checked: ${escapeHtml((geoReadiness.ai_agents_scanned || []).join(", ") || "none")}</div>
       <div class="insights-label" style="margin-top:4px;color:var(--text-secondary)">Improves visibility in AI search (ChatGPT, Perplexity, etc.). Not required for Google AI Overviews or AI Mode.</div>`
    : '<div class="insights-label">Covered in Overview for this job.</div>');

  html += qualitySection("Duplicate Content & Canonicals", dup
    ? `<div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr))">
         <div class="insights-card"><div class="insights-label">Duplicate Groups</div><div class="insights-value">${dup.duplicate_groups?.length ?? 0}</div></div>
         <div class="insights-card"><div class="insights-label">Duplicate Pages</div><div class="insights-value">${dup.duplicate_pages ?? 0}</div></div>
         <div class="insights-card"><div class="insights-label">Canonical Missing</div><div class="insights-value">${dup.canonical_missing ?? 0}</div></div>
         <div class="insights-card"><div class="insights-label">Canonical Conflicts</div><div class="insights-value">${(dup.canonical_conflicting ?? 0) + (dup.canonical_cross_domain ?? 0)}</div></div>
       </div>
       ${(dup.duplicate_groups || []).map(g => `<div style="margin-top:8px;font-size:13px;color:var(--text-secondary)">${escapeHtml(g.urls.join("  ≈  "))} <span class="count-label">(${escapeHtml(g.similarity)})</span></div>`).join("")}
       ${(dup.canonical_flags || []).filter(f => f.canonical_conflicting || f.canonical_cross_domain).map(f => `<div style="margin-top:6px;font-size:13px">${f.canonical_cross_domain ? "cross-domain canonical" : "conflicting canonical"} → ${escapeHtml(f.page_url)}${f.canonical_target ? " → " + escapeHtml(f.canonical_target) : ""}</div>`).join("")}`.trim()
    : '<div class="insights-label">Not run for this job yet.</div>');

  html += qualitySection("Structured Data", sd
    ? `<div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr))">
         <div class="insights-card"><div class="insights-label">Valid Pages</div><div class="insights-value">${sd.valid ?? 0}</div></div>
         <div class="insights-card"><div class="insights-label">No Structured Data</div><div class="insights-value">${sd.no_structured_data ?? 0}</div></div>
         <div class="insights-card"><div class="insights-label">Invalid Markup</div><div class="insights-value">${sd.invalid_types ?? 0}</div></div>
       </div>
       ${Object.entries(sd.type_counts || {}).map(([t, c]) => `<span class="count-label" style="margin-right:10px">${escapeHtml(t)}: ${c}</span>`).join("")}`
    : '<div class="insights-label">Not run for this job yet.</div>');

  html += qualitySection("Core Web Vitals", perf
    ? `<div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr))">
         <div class="insights-card"><div class="insights-label">Pages Measured</div><div class="insights-value">${perf.checked ?? 0}</div></div>
         <div class="insights-card"><div class="insights-label">Avg CWV Score</div><div class="insights-value">${perf.avg_cwv_score ?? "N/A"}</div></div>
       </div>
       ${(perf.errors || []).slice(0, 3).map(e => `<div style="margin-top:6px;font-size:12px;color:var(--danger)">${escapeHtml(e)}</div>`).join("")}`
    : '<div class="insights-label">Not run for this job yet.</div>');

  html += qualitySection("Industry Alignment (GEO)", geo
    ? `<div class="insights-label" style="margin-bottom:8px">Core industry keywords: <span class="count-label">${(geo.industry_keywords || []).map(escapeHtml).join(", ")}</span></div>
       <div class="insights-label">Off-topic pages: ${geo.off_topic_pages ?? 0} of ${geo.pages_analyzed ?? 0}</div>
       ${(geo.pages || []).filter(p => p.off_topic).slice(0, 12).map(p => `
         <div style="margin-top:8px;display:flex;align-items:center;gap:8px">
           <div style="flex:1;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(p.page_url)}">${escapeHtml(p.title || p.page_url)}</div>
           <div class="bar-track" style="width:120px"><div class="bar-fill" style="width:${Math.max(2, Math.round((p.alignment || 0) * 100))}%;background:var(--danger)"></div></div>
           <span class="count-label">${(p.alignment || 0).toFixed(2)}</span>
         </div>`).join("")}`
    : '<div class="insights-label">Not run for this job yet.</div>');

  html += qualitySection("Orphan Pages", orphans
    ? `<div class="insights-label">Pages with no internal links pointing to them: ${orphans.orphan_pages ?? 0}</div>
       ${(orphans.pages || []).slice(0, 20).map(p => `<div style="margin-top:6px;font-size:13px;color:var(--text-secondary)">• ${linkify(p.page_url, 70)}${(p.suggested_link_sources || []).length ? `<div style="margin-left:12px;font-size:12px">↳ link from: ${p.suggested_link_sources.map(s => linkify(s, 50)).join(", ")}</div>` : ""}</div>`).join("")}`
    : '<div class="insights-label">Not run for this job yet.</div>');

  html += qualitySection("Content Decay", decay && decay.pages_with_last_modified > 0
    ? `<div class="insights-label">Pages with a Last-Modified header: ${decay.pages_with_last_modified} · stale (>${decay.stale_after_days} days): <strong>${decay.stale_pages}</strong></div>
       ${(decay.pages || []).slice(0, 20).map(p => `<div style="margin-top:6px;font-size:13px;color:var(--text-secondary)">• ${linkify(p.page_url, 70)} — ${p.stale_days} days old</div>`).join("")}`
    : '<div class="insights-label">Not available (site does not send Last-Modified headers, or not run).</div>');

  return html;
}

async function loadSeoInsights(jobId) {
  const errDiv = document.getElementById("insights-error");
  errDiv.classList.add("hidden");
  try {
    const resp = await fetch(`${API_BASE}/seo-insights/${jobId}`);
    if (!resp.ok) {
      errDiv.textContent = `Failed to load insights: ${resp.status}`;
      errDiv.classList.remove("hidden");
      return;
    }
    const data = await resp.json();
    if (data.cached) showToast("Insights loaded from cache");
    renderKeywords(data.keywords || [], data.keywords_error, data.keywords_source);
    renderBacklinks(data.backlinks, data.backlinks_error, data.backlinks_source);
    renderDomainOverview(data.overview, data.overview_error, data.overview_source);
    renderOnpage(data.onpage, data.onpage_error, data.onpage_source);
    renderSerp(data.serp_rankings || [], data.serp_error, data.serp_source);
    renderGscData(data.gsc, data.gsc_error);
    loadGsc(jobId);
  } catch (err) {
    errDiv.textContent = "Error loading insights: " + err.message;
    errDiv.classList.remove("hidden");
  }
  loadBacklinkSources(jobId);
}

async function loadGsc(jobId) {
  const badge = document.getElementById("gsc-status-badge");
  const connectEl = document.getElementById("gsc-connect");
  const dataEl = document.getElementById("gsc-data");
  try {
    const resp = await fetch(`${API_BASE}/gsc/status/${jobId}`);
    const status = resp.ok ? await resp.json() : { connected: false, configured: false };
    if (badge) {
      badge.innerHTML = status && status.connected
        ? `<span class="count-label" style="color:#16a34a">Connected${status.property ? " · " + escapeHtml(status.property) : ""}</span>`
        : "";
    }
    const refreshBtn = document.getElementById("gsc-refresh-btn");
    const disconnectBtn = document.getElementById("gsc-disconnect-btn");
    if (refreshBtn) refreshBtn.classList.toggle("hidden", !(status && status.connected));
    if (disconnectBtn) disconnectBtn.classList.toggle("hidden", !(status && status.connected));
    if (connectEl) {
      if (status && status.connected) {
        connectEl.innerHTML = "";
      } else if (status && status.configured === false) {
        connectEl.innerHTML = `<div class="service-error">
          <div class="service-error-title">Google Search Console not configured</div>
          <div class="service-error-msg">Add GSC_CLIENT_ID and GSC_CLIENT_SECRET (Google Cloud OAuth client with the Search Console API enabled) to .env and restart the server, then Connect.</div>
        </div>`;
      } else {
        connectEl.innerHTML = `<p class="section-desc" style="margin-bottom:8px">Connect Google Search Console to pull real organic clicks, impressions and top queries for this domain (the domain must be a verified Search Console property).</p>
          <button id="gsc-connect-btn" class="btn-secondary">Connect GSC</button>`;
      }
    }
    if (window.location.hash.includes("gsc=connected")) {
      showToast("Google Search Console connected");
      history.replaceState(null, "", location.pathname + location.search + "#job/" + jobId + "/seo-insights");
    }
  } catch (err) {
    if (connectEl) connectEl.innerHTML = `<p class="section-desc">Error checking GSC status: ${escapeHtml(err.message)}</p>`;
  }
  if (!dataEl || dataEl.textContent.trim() === "") {
    renderGscData(null, null);
  }
}

function renderGscData(gsc, error) {
  const el = document.getElementById("gsc-data");
  if (!el) return;
  let html = "";
  if (error) html += serviceErrorHtml("Google Search Console", error);
  if (gsc) {
    html += `<p class="source-note">Source: Google Search Console (${escapeHtml(gsc.property || "property")}) — last ${escapeHtml(String(gsc.days || 28))} days</p>`;
    html += `<div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
      <div class="insights-card"><div class="insights-label">Clicks</div><div class="insights-value">${gsc.clicks ?? "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">Impressions</div><div class="insights-value">${gsc.impressions ?? "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">CTR</div><div class="insights-value">${gsc.ctr != null ? (gsc.ctr * 100).toFixed(2) + "%" : "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">Avg Position</div><div class="insights-value">${gsc.position ?? "N/A"}</div></div>
    </div>`;
    const qs = gsc.queries || [];
    const ps = gsc.pages || [];
    if (qs.length) {
      html += `<h4 style="margin:14px 0 6px">Top Queries</h4><div style="overflow-x:auto">
        <table class="data-table"><thead><tr><th>Query</th><th>Clicks</th><th>Impressions</th><th>CTR</th><th>Position</th></tr></thead>
        <tbody>${qs.map(q => `<tr>
          <td>${escapeHtml(q.query)}</td>
          <td>${q.clicks}</td><td>${q.impressions}</td>
          <td>${q.ctr != null ? (q.ctr * 100).toFixed(1) + "%" : "-"}</td>
          <td>${q.position ?? "-"}</td>
        </tr>`).join("")}</tbody></table></div>`;
    }
    if (ps.length) {
      html += `<h4 style="margin:14px 0 6px">Top Pages</h4><div style="overflow-x:auto">
        <table class="data-table"><thead><tr><th>Page</th><th>Clicks</th><th>Impressions</th><th>CTR</th><th>Position</th></tr></thead>
        <tbody>${ps.map(p => `<tr>
          <td class="page-url-cell" title="${escapeHtml(p.page)}">${linkify(p.page, 70)}</td>
          <td>${p.clicks}</td><td>${p.impressions}</td>
          <td>${p.ctr != null ? (p.ctr * 100).toFixed(1) + "%" : "-"}</td>
          <td>${p.position ?? "-"}</td>
        </tr>`).join("")}</tbody></table></div>`;
    }
  } else if (!error) {
    html = '<div class="insights-card">No Search Console data yet. Connect GSC above, then click Refresh Data.</div>';
  }
  el.innerHTML = html;
}

document.getElementById("gsc-connect")?.addEventListener("click", async (e) => {
  if (e.target.id !== "gsc-connect-btn") return;
  try {
    const resp = await fetch(`${API_BASE}/gsc/auth/${currentJobId}`);
    const data = await resp.json();
    if (data.auth_url) {
      window.location.href = data.auth_url;
    } else {
      showToast("GSC not configured: " + (data.hint || "missing OAuth client"));
    }
  } catch (err) {
    showToast("GSC connect failed: " + err.message);
  }
});

document.getElementById("gsc-refresh-btn")?.addEventListener("click", async () => {
  const el = document.getElementById("gsc-data");
  el.innerHTML = '<p class="section-desc">Fetching Search Console data...</p>';
  try {
    const resp = await fetch(`${API_BASE}/gsc/${currentJobId}/fetch`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) {
      el.innerHTML = serviceErrorHtml("Google Search Console", data.detail || `HTTP ${resp.status}`);
      return;
    }
    renderGscData(data, null);
    loadSeoInsights(currentJobId);
    showToast("GSC data refreshed");
  } catch (err) {
    el.innerHTML = `<p class="section-desc">Error: ${escapeHtml(err.message)}</p>`;
  }
});

document.getElementById("gsc-disconnect-btn")?.addEventListener("click", async () => {
  try {
    const resp = await fetch(`${API_BASE}/gsc/${currentJobId}`, { method: "DELETE" });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      showToast("GSC disconnect failed: " + (data.detail || resp.status));
      return;
    }
    renderGscData(null, null);
    loadGsc(currentJobId);
    loadSeoInsights(currentJobId);
    showToast("Google Search Console disconnected");
  } catch (err) {
    showToast("GSC disconnect failed: " + err.message);
  }
});

async function loadBacklinkSources(jobId) {
  const el = document.getElementById("backlink-sources-list");
  el.innerHTML = '<p class="section-desc">Loading backlink sources...</p>';
  try {
    const resp = await fetch(`${API_BASE}/seo-insights/${jobId}/backlinks?limit=100`);
    if (!resp.ok) {
      el.innerHTML = `<p class="section-desc">Failed to load backlink sources: ${resp.status}</p>`;
      return;
    }
    const data = await resp.json();
    if (!data.backlinks || data.backlinks.length === 0) {
      el.innerHTML = (data.error ? serviceErrorHtml("Backlink discovery", data.error, "Click Refresh to retry discovery.") : "") +
        '<p class="section-desc">No backlink sources discovered yet. Click Refresh to run discovery.</p>';
      return;
    }
    el.innerHTML = `
      ${data.error ? serviceErrorHtml("Backlink discovery", data.error, "Showing previously discovered sources.") : ""}
      <p class="section-desc">${data.total} source page(s) from ${data.referring_domains} referring domain(s)${data.source_api ? ` via ${sourceLabel(data.source_api)}` : ""}</p>
      <div style="overflow-x:auto">
        <table class="data-table">
          <thead><tr><th>Source URL</th><th>Domain</th><th>Anchor</th><th>Links</th><th>Rank</th></tr></thead>
          <tbody>${data.backlinks.map(b => `
            <tr>
              <td class="page-url-cell" title="${b.source_url}"><a href="${escapeHtml(b.source_url)}" target="_blank" rel="noopener">${b.source_url}</a></td>
              <td>${escapeHtml(b.source_domain || "")}</td>
              <td>${escapeHtml((b.anchor || "-").substring(0, 60))}</td>
              <td>${b.backlinks_count ?? "-"}</td>
              <td>${b.page_from_rank ?? "-"}</td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
  } catch (err) {
    el.innerHTML = `<p class="section-desc">Error loading backlink sources: ${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById("refresh-backlinks-btn").addEventListener("click", async () => {
  const el = document.getElementById("backlink-sources-list");
  el.innerHTML = '<p class="section-desc">Discovering backlinks...</p>';
  try {
    const resp = await fetch(`${API_BASE}/seo-insights/${currentJobId}/backlinks/refresh`, { method: "POST" });
    const data = await resp.json();
    showToast(`Discovered ${data.total} backlink sources (${data.source_api || "none"})`);
  } catch (err) {
    showToast("Backlink discovery failed: " + err.message);
  }
  loadBacklinkSources(currentJobId);
});

function renderKeywords(keywords, error, source) {
  renderInsightSection(document.getElementById("keywords-list"), {
    data: keywords.length ? keywords : null,
    error,
    source,
    emptyText: "No keyword data available.",
    render: kws => kws.slice(0, 15).map(k => `
      <div class="insights-card">
        <div class="insights-label">${escapeHtml(k.keyword || "")}</div>
        <div class="insights-value">
          Vol: ${k.keyword_data?.keyword_info?.search_volume ?? "N/A"}
        </div>
        <div class="insights-value">
          CPC: $${(k.keyword_data?.keyword_info?.cpc ?? 0).toFixed(2)}
        </div>
        <div class="insights-value">
          Difficulty: ${k.keyword_data?.keyword_properties?.keyword_difficulty ?? "N/A"}
        </div>
      </div>
    `).join(""),
  });
}

function renderBacklinks(bl, error, source) {
  renderInsightSection(document.getElementById("backlinks-summary"), {
    data: bl,
    error,
    source,
    emptyText: "No backlink data available.",
    render: b => `
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
        <div class="insights-card"><div class="insights-label">Total Backlinks</div><div class="insights-value">${b.backlinks ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Referring Domains</div><div class="insights-value">${b.referring_domains ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Referring IPs</div><div class="insights-value">${b.referring_ips ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Domain Rank</div><div class="insights-value">${b.rank ?? "N/A"}</div></div>
      </div>
    `,
  });
}

function renderDomainOverview(ov, error, source) {
  renderInsightSection(document.getElementById("domain-overview"), {
    data: ov,
    error,
    source,
    emptyText: "No domain overview data available.",
    render: o => `
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
        <div class="insights-card"><div class="insights-label">Organic Traffic</div><div class="insights-value">${o.estimated_organic_traffic ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Organic Keywords</div><div class="insights-value">${o.organic_keywords_count ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Paid Keywords</div><div class="insights-value">${o.paid_keywords_count ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Domain Rank</div><div class="insights-value">${o.domain_rank ?? "N/A"}</div></div>
      </div>
    `,
  });
}

function renderOnpage(op, error, source) {
  const entries = op ? Object.entries(op).filter(([k]) => !["source"].includes(k)) : null;
  renderInsightSection(document.getElementById("onpage-summary"), {
    data: op,
    error,
    source,
    emptyText: "No on-page data available.",
    render: o => `
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
        ${entries.map(([k, v]) => `
          <div class="insights-card">
            <div class="insights-label">${escapeHtml(k.replace(/_/g, " "))}</div>
            <div class="insights-value">${typeof v === "number" ? v : escapeHtml(String(v ?? "N/A").substring(0, 60))}</div>
          </div>`).join("")}
      </div>
    `,
  });
}

function renderSerp(rankings, error, source) {
  const el = document.getElementById("serp-rankings");
  let html = "";
  if (error) html += serviceErrorHtml("SERP API", error);
  if (rankings.length) {
    html += `<p class="source-note">Source: ${sourceLabel(source)} — rankings for keywords extracted from your content</p>`;
    html += rankings.map(r => `
      <div class="insights-card" style="margin-top:8px">
        <strong>${escapeHtml(r.keyword || "")}</strong> — Rank: ${r.rank ?? "Not in top 100"} | Total Results: ${r.total_results ?? "N/A"}
        ${r.top_results && r.top_results.length ? r.top_results.slice(0, 3).map(t => `<div style="font-size:13px;margin-top:4px">#${t.position}: <a href="${escapeHtml(t.url)}" target="_blank" rel="noopener">${escapeHtml(t.title)}</a></div>`).join("") : ""}
      </div>`).join("");
  }
  if (!rankings.length && !error) {
    html += '<div class="insights-card">No SERP ranking data available. Use "Suggest Keywords" to add keywords.</div>';
  }
  el.innerHTML = html;
}

function renderCompetitorGaps(data, isSingle) {
  const resultsEl = document.getElementById("competitor-gap-results");
  if (!data || !data.results || !data.results.length) {
    resultsEl.innerHTML = '<div class="insights-card">No competitor analyses yet. Enter competitor domains and click Analyze.</div>';
    return;
  }
  resultsEl.innerHTML = data.results.map(c => {
    const status = c.status || "queued";
    if (status === "queued") return `<div class="insights-card"><h4>${escapeHtml(c.competitor)}</h4><div class="insights-label">Queued for full-page crawl...</div></div>`;
    if (status === "running") return `<div class="insights-card"><h4>${escapeHtml(c.competitor)}</h4><div class="insights-label">Analyzing... (${escapeHtml(c.pages_crawled || 0)} pages so far)</div></div>`;
    if (status === "error") return `<div class="insights-card"><h4>${escapeHtml(c.competitor)}</h4><div class="insights-error">${escapeHtml((c.errors || []).join("; "))}</div></div>`;

    const kwGaps = (c.keyword_gap && c.keyword_gap.gaps || []).length;
    const contentGaps = c.content_gap ? c.content_gap.missing_count : 0;
    const blGaps = (c.backlink_gap && c.backlink_gap.gaps || []).length;
    const schemaGaps = (c.schema_gap && c.schema_gap.missing_from_target || []).length;
    const featureGaps = Object.keys(c.serp_features_gap && c.serp_features_gap.comp_only || {}).length;

    const gapStats = [
      ["Keyword", kwGaps], ["Content", contentGaps], ["Backlink", blGaps],
      ["Schema", schemaGaps], ["SERP Features", featureGaps],
    ].map(([label, n]) => `<div class="insights-card"><div class="insights-label">${label} Gaps</div><div class="insights-value">${n}</div></div>`).join("");

    const tech = c.technical_gap || {};
    const techRows = Object.entries(tech).filter(([k]) => k !== "sitemap").map(([k, v]) => {
      const label = k.replace(/_/g, " ").replace(/\b\w/g, m => m.toUpperCase());
      const d = v && v.delta !== undefined ? ` (Δ ${escapeHtml(String(v.delta))})` : "";
      return `<div class="insights-card" style="font-size:13px"><strong>${escapeHtml(label)}</strong>${d}<div style="opacity:.8">Target: ${escapeHtml(String(v.target))} | Competitor: ${escapeHtml(String(v.competitor))}</div></div>`;
    }).join("");

    const ux = c.ux_gap || {};
    const uxRows = Object.entries(ux).map(([k, v]) => {
      const label = k.replace(/_/g, " ").replace(/\b\w/g, m => m.toUpperCase());
      const d = v && v.delta !== undefined ? ` (Δ ${escapeHtml(String(v.delta))})` : "";
      return `<div class="insights-card" style="font-size:13px"><strong>${escapeHtml(label)}</strong>${d}<div style="opacity:.8">Target: ${escapeHtml(String(v.target))} | Competitor: ${escapeHtml(String(v.competitor))}</div></div>`;
    }).join("");

    return `<div class="insights-card" style="margin-top:10px">
      <h4 style="display:flex;justify-content:space-between;align-items:center">${escapeHtml(c.competitor)}
        <span class="count-label">${escapeHtml(c.pages_crawled || 0)} pages crawled</span></h4>
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(130px,1fr));margin:8px 0">${gapStats}</div>
      ${kwGaps ? `<div class="insights-label">Keywords they rank for that you don't:</div><div style="font-size:13px;margin-top:4px">${c.keyword_gap.gaps.slice(0, 15).map(k => `• ${escapeHtml(k)}`).join(" ")}</div>` : ""}
      ${contentGaps ? `<div class="insights-label" style="margin-top:8px">Content they have that you don't (top ${Math.min(contentGaps, 10)}):</div><div style="font-size:13px;margin-top:4px">${c.content_gap.missing.slice(0, 10).map(m => `• <a href="${escapeHtml(m.url)}" target="_blank" rel="noopener">${escapeHtml(m.title)}</a>`).join("<br>")}</div>` : ""}
      ${blGaps ? `<div class="insights-label" style="margin-top:8px">Backlink sources they have that you don't (top 20):</div><div style="font-size:13px;margin-top:4px">${c.backlink_gap.gaps.map(d => `• ${escapeHtml(d)}`).join(" ")}</div>` : ""}
      ${schemaGaps ? `<div class="insights-label" style="margin-top:8px">Schema types on their pages missing from yours:</div><div style="font-size:13px;margin-top:4px">${c.schema_gap.missing_from_target.map(t => `• ${escapeHtml(t)}`).join(" ")}</div>` : ""}
      ${featureGaps ? `<div class="insights-label" style="margin-top:8px">SERP features they appear in that you don't:</div><div style="font-size:13px;margin-top:4px">${Object.entries(c.serp_features_gap.comp_only).map(([kw, feats]) => `${escapeHtml(kw)} → ${escapeHtml(feats.join(", "))}`).join("<br>")}</div>` : ""}
      <div class="insights-label" style="margin-top:10px">Technical / On-page / UX deltas (competitor − target)</div>
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin:8px 0">${techRows}</div>
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin:8px 0">${uxRows}</div>
    </div>`;
  }).join("");
}

function renderCompetitorStatus(rows) {
  return rows.some(r => ["queued", "running"].includes(r.status));
}

async function loadCompetitors(jobId) {
  const resultsEl = document.getElementById("competitor-gap-results");
  try {
    const resp = await fetch(`${API_BASE}/competitors/${jobId}`);
    const data = await resp.json();
    if (!resp.ok) {
      resultsEl.innerHTML = `<div class="insights-error">Error: ${escapeHtml(data.detail || resp.status)}</div>`;
      return;
    }
    renderCompetitorGaps(data, false);
    if (data.results && renderCompetitorStatus(data.results)) {
      setTimeout(() => loadCompetitors(jobId), 4000);
    }
  } catch (err) {
    resultsEl.innerHTML = `<div class="insights-error">Error: ${escapeHtml(err.message)}</div>`;
  }
}

document.getElementById("competitor-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("competitor-gap-btn");
  const input = document.getElementById("competitor-input");
  const resultsEl = document.getElementById("competitor-gap-results");
  if (!currentJobId) return;
  const competitors = (input.value || "").split(",").map(s => s.trim()).filter(Boolean);
  if (!competitors.length) {
    resultsEl.innerHTML = '<div class="insights-label">Enter at least one competitor domain.</div>';
    return;
  }
  btn.disabled = true;
  btn.textContent = "Analyzing...";
  resultsEl.innerHTML = '<div class="insights-label">Crawling every page of each competitor (free tools: Playwright crawl, PSI, SERP API)...</div>';
  try {
    const resp = await fetch(`${API_BASE}/competitors/${currentJobId}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJobId, competitors }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      resultsEl.innerHTML = `<div class="insights-label">Error: ${escapeHtml(data.detail || resp.status)}</div>`;
    } else {
      showToast("Competitor analysis queued");
      loadCompetitors(currentJobId);
    }
  } catch (err) {
    resultsEl.innerHTML = `<div class="insights-label">Error: ${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Analyze";
  }
});

document.getElementById("competitor-refresh-btn")?.addEventListener("click", () => {
  if (currentJobId) loadCompetitors(currentJobId);
});

document.getElementById("refresh-insights-btn")?.addEventListener("click", async () => {
  if (!currentJobId) return;
  const btn = document.getElementById("refresh-insights-btn");
  btn.disabled = true;
  btn.textContent = "Refreshing...";
  try {
    await fetch(`${API_BASE}/seo-insights/refresh/${currentJobId}`, { method: "POST" });
    await loadSeoInsights(currentJobId);
    showToast("Insights refreshed");
  } catch (err) {
    showToast("Error: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh Insights";
  }
});

document.getElementById("suggest-keywords-btn")?.addEventListener("click", async () => {
  if (!currentJobId) return;
  try {
    const resp = await fetch(`${API_BASE}/seo-insights/${currentJobId}/suggested-keywords`);
    const data = await resp.json();
    const kws = data.keywords || [];
    if (kws.length === 0) { showToast("No keywords to suggest"); return; }
    const serpContainer = document.getElementById("serp-rankings");
    serpContainer.innerHTML = kws.map(kw => `<span class="serp-chip" data-keyword="${escapeHtml(kw)}">${escapeHtml(kw)}</span>`).join("") +
      '<div style="margin-top:8px;font-size:13px;color:var(--text-secondary)">Click a keyword to check its SERP ranking</div>';
    document.querySelectorAll(".serp-chip").forEach(chip => {
      chip.addEventListener("click", async () => {
        const kw = chip.dataset.keyword;
        try {
          chip.style.opacity = "0.5";
          const resp = await fetch(`${API_BASE}/seo-insights/keyword-search`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ job_id: currentJobId, keyword: kw }),
          });
          const result = await resp.json();
          chip.style.opacity = "1";
          if (!resp.ok) {
            serpContainer.innerHTML += `<div class="service-error"><div class="service-error-title">SERP API unavailable</div><div class="service-error-msg">${escapeHtml(result.detail || resp.status)}</div></div>`;
            return;
          }
          serpContainer.innerHTML += `<div class="insights-card" style="margin-top:8px">
            <strong>${escapeHtml(kw)}</strong> — Rank: ${result.rank ?? "Not in top 100"} | Total Results: ${result.total_results ?? "N/A"}
            ${result.top_results ? result.top_results.slice(0, 3).map(r => `<div style="font-size:13px;margin-top:4px">#${r.position}: <a href="${escapeHtml(r.url)}" target="_blank" rel="noopener">${escapeHtml(r.title)}</a></div>`).join("") : ""}
          </div>`;
        } catch (err) {
          chip.style.opacity = "1";
          showToast("Error: " + err.message);
        }
      });
    });
    showToast(`Found ${kws.length} suggested keywords`);
  } catch (err) {
    showToast("Error: " + err.message);
  }
});

document.getElementById("serp-search-btn")?.addEventListener("click", async () => {
  const input = document.getElementById("serp-keyword-input");
  const kw = input.value.trim();
  if (!kw || !currentJobId) return;
  try {
    const resp = await fetch(`${API_BASE}/seo-insights/keyword-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJobId, keyword: kw }),
    });
    const result = await resp.json();
    const el = document.getElementById("serp-rankings");
    if (!resp.ok) {
      el.innerHTML += `<div class="service-error"><div class="service-error-title">SERP API unavailable</div><div class="service-error-msg">${escapeHtml(result.detail || resp.status)}</div></div>`;
      return;
    }
    el.innerHTML += `<div class="insights-card" style="margin-top:8px">
      <strong>${escapeHtml(kw)}</strong> — Rank: ${result.rank ?? "Not in top 100"} | Total Results: ${result.total_results ?? "N/A"}
      ${result.top_results ? result.top_results.slice(0, 5).map(r => `<div style="font-size:13px;margin-top:4px">#${r.position}: <a href="${escapeHtml(r.url)}" target="_blank" rel="noopener">${escapeHtml(r.title)}</a></div>`).join("") : ""}
    </div>`;
    input.value = "";
  } catch (err) {
    showToast("Error: " + err.message);
  }
});

document.getElementById("serp-keyword-input")?.addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("serp-search-btn")?.click();
});

// Sites dashboard
let selectedSiteIds = new Set();

async function loadSites() {
  const grid = document.getElementById("sites-grid");
  grid.innerHTML = '<div class="insights-card">Loading sites...</div>';
  try {
    const includeArchived = document.getElementById("show-archived-toggle")?.checked || false;
    const resp = await fetch(`${API_BASE}/sites?include_archived=${includeArchived}`);
    const data = await resp.json();
    const sites = data.sites || [];
    document.getElementById("sites-count").textContent = `${sites.length} site(s) analyzed`;
    if (sites.length === 0) {
      grid.innerHTML = '<div class="insights-card">No sites analyzed yet. Run an analysis first.</div>';
      updateCompareBtn();
      return;
    }
    grid.innerHTML = sites.map(s => `
      <div class="site-card ${s.status !== "completed" ? "site-card-muted" : ""} ${s.archived ? "site-card-archived" : ""}">
        <label class="site-select">
          <input type="checkbox" data-job="${s.job_id}" ${selectedSiteIds.has(s.job_id) ? "checked" : ""} ${s.archived ? "disabled" : ""}>
          <div>
            <div class="site-domain">${escapeHtml(s.domain)}</div>
            <div class="site-url">${linkify(s.url, 80)}</div>
            <div class="site-status status-${s.status}">${s.status}${s.health_grade ? ` · Health ${s.health_grade}` : ""}${s.archived ? " · archived" : ""}</div>
          </div>
        </label>
        <div class="site-stats">
          <div class="site-stat"><span>${s.total_pages}</span> pages</div>
          <div class="site-stat"><span>${s.total_content_items}</span> content</div>
          <div class="site-stat"><span>${s.backlinks ?? "N/A"}</span> backlinks</div>
          <div class="site-stat"><span>${s.domain_rank ?? "N/A"}</span> rank</div>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          ${s.archived
            ? `<button class="btn-secondary site-restore" data-job="${s.job_id}" style="padding:6px 10px;font-size:12px">Restore</button>`
            : `<button class="btn-secondary site-open" data-job="${s.job_id}">Open</button>
               <button class="btn-secondary site-delete" data-job="${s.job_id}" style="padding:6px 10px;font-size:12px;color:#dc2626">Archive</button>`}
          <button class="btn-secondary site-hard-delete" data-job="${s.job_id}" data-url="${escapeHtml(s.url)}" style="padding:6px 10px;font-size:12px;color:#dc2626;border-color:#fecaca">Delete</button>
        </div>
      </div>
    `).join("");

    grid.querySelectorAll('input[data-job]').forEach(cb => {
      cb.addEventListener("change", () => {
        const jid = cb.dataset.job;
        if (cb.checked) selectedSiteIds.add(jid);
        else selectedSiteIds.delete(jid);
        updateCompareBtn();
      });
    });
    grid.querySelectorAll(".site-open").forEach(btn => {
      btn.addEventListener("click", () => {
        openSite(btn.dataset.job);
      });
    });
    grid.querySelectorAll(".site-delete").forEach(btn => {
      btn.addEventListener("click", async () => {
        const jid = btn.dataset.job;
        if (!confirm("Archive this site? Its data is kept and can be restored from the archived view.")) return;
        await fetch(`${API_BASE}/sites/${jid}`, { method: "DELETE" });
        showToast("Site archived");
        loadSites();
      });
    });
    grid.querySelectorAll(".site-restore").forEach(btn => {
      btn.addEventListener("click", async () => {
        await fetch(`${API_BASE}/sites/${btn.dataset.job}/restore`, { method: "POST" });
        showToast("Site restored");
        loadSites();
      });
    });
    grid.querySelectorAll(".site-hard-delete").forEach(btn => {
      btn.addEventListener("click", async () => {
        const jid = btn.dataset.job;
        const url = btn.dataset.url;
        if (!confirm(`Permanently delete ${url}?\n\nThis removes ALL data for this site: pages, content, action items, reports, dummy site, downloads, insights and vectors. This cannot be undone.`)) return;
        try {
          const resp = await fetch(`${API_BASE}/sites/${jid}/hard`, { method: "DELETE" });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
          selectedSiteIds.delete(jid);
          showToast(`Site deleted (${(data.deleted && Object.values(data.deleted).reduce((a, b) => a + b, 0)) || 0} records purged)`);
        } catch (err) {
          showToast("Delete failed: " + err.message);
        }
        loadSites();
      });
    });
    updateCompareBtn();
  } catch (err) {
    grid.innerHTML = `<div class="insights-card">Error loading sites: ${escapeHtml(err.message)}</div>`;
  }
}

document.getElementById("show-archived-toggle")?.addEventListener("change", () => {
  selectedSiteIds.clear();
  loadSites();
});

function updateCompareBtn() {
  const btn = document.getElementById("compare-sites-btn");
  btn.disabled = selectedSiteIds.size < 2;
}

async function openSite(jobId, opts = {}) {
  stopPolling();
  currentJobId = jobId;
  history.replaceState(null, "", "#job/" + jobId);
  const resp = await fetch(`${API_BASE}/analysis/${jobId}`);
  const job = await resp.json();
  if (job.status === "completed") {
    showResults(jobId, opts);
  } else {
    resultsUrl.textContent = job.url;
    resultsStatus.textContent = `Status: ${job.status}`;
    resultsSection.classList.remove("hidden");
    inputSection.classList.add("hidden");
    showProgress();
    startPolling(jobId);
  }
  window.scrollTo(0, 0);
}

function switchTab(name) {
  document.querySelector('.tab[data-tab="' + name + '"]').click();
}

async function compareSelected() {
  if (selectedSiteIds.size < 2) return;
  const resp = await fetch(`${API_BASE}/sites/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_ids: [...selectedSiteIds] }),
  });
  const data = await resp.json();
  const sites = data.sites || [];
  const comp = data.comparison || {};

  document.getElementById("sites-comparison").classList.remove("hidden");
  document.getElementById("comparison-table").innerHTML = `
    <table class="data-table">
      <thead><tr><th>Metric</th>${sites.map(s => `<th>${escapeHtml(s.domain)}</th>`).join("")}</tr></thead>
      <tbody>
        <tr><td>Status</td>${sites.map(s => `<td>${s.status}</td>`).join("")}</tr>
        <tr><td>Pages</td>${sites.map(s => `<td>${s.total_pages}</td>`).join("")}</tr>
        <tr><td>Content Items</td>${sites.map(s => `<td>${s.total_content_items}</td>`).join("")}</tr>
        <tr><td>Vectors</td>${sites.map(s => `<td>${s.total_vectors}</td>`).join("")}</tr>
        <tr><td>Backlinks</td>${sites.map(s => `<td>${s.backlinks ?? "N/A"}</td>`).join("")}</tr>
        <tr><td>Referring Domains</td>${sites.map(s => `<td>${s.referring_domains ?? "N/A"}</td>`).join("")}</tr>
        <tr><td>Domain Rank</td>${sites.map(s => `<td>${s.domain_rank ?? "N/A"}</td>`).join("")}</tr>
        <tr><td>Action Items</td>${sites.map(s => `<td>${s.total_action_items}</td>`).join("")}</tr>
      </tbody>
    </table>
  `;

  const byType = comp.most_content_by_type || {};
  const typeEntries = Object.entries(byType);
  document.getElementById("comparison-insights").innerHTML = typeEntries.length ? `
    <div class="insights-card"><strong>Largest site:</strong> ${escapeHtml(comp.largest_site || "N/A")}</div>
    <div class="insights-card"><strong>Most backlinks:</strong> ${escapeHtml(comp.most_backlinks || "N/A")}</div>
    ${typeEntries.map(([t, v]) => `<div class="insights-card"><strong>Most ${escapeHtml(t)}:</strong> ${escapeHtml(v.domain)} (${v.count})</div>`).join("")}
  ` : `<div class="insights-card"><strong>Largest site:</strong> ${escapeHtml(comp.largest_site || "N/A")}</div>
    <div class="insights-card"><strong>Most backlinks:</strong> ${escapeHtml(comp.most_backlinks || "N/A")}</div>`;
}

document.getElementById("compare-sites-btn")?.addEventListener("click", compareSelected);
document.getElementById("refresh-sites-btn")?.addEventListener("click", loadSites);

// Schedules
async function loadSchedules() {
  const list = document.getElementById("schedules-list");
  try {
    const resp = await fetch(`${API_BASE}/scheduler`);
    const data = await resp.json();
    const schedules = data.schedules || [];
    if (schedules.length === 0) {
      list.innerHTML = '<div class="insights-card">No schedules yet. Add one above to auto-crawl a site on an interval.</div>';
      return;
    }
    list.innerHTML = schedules.map(s => `
      <div class="schedule-card">
        <div>
          <div class="schedule-domain">${escapeHtml(s.domain)}</div>
          <div class="site-url">${linkify(s.url, 80)}</div>
          <div class="site-status ${s.enabled ? "status-completed" : ""}" style="margin-top:6px">${s.enabled ? "Enabled" : "Disabled"}${s.kind === "keyword_check" ? " · keyword re-check" : ""}</div>
        </div>
        <div class="schedule-meta">
          <div>Every <strong>${formatInterval(s.interval_hours)}</strong></div>
          <div>Max <strong>${s.max_pages}</strong> pages</div>
          <div>Runs: <strong>${s.history?.length || 0}</strong></div>
          <div class="schedule-next">Next: ${s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}</div>
        </div>
        <div class="schedule-actions">
          <button class="btn-secondary schedule-history" data-id="${s.id}">History</button>
          <button class="btn-secondary schedule-delete" data-id="${s.id}">Delete</button>
        </div>
      </div>
    `).join("");

    list.querySelectorAll(".schedule-delete").forEach(btn => {
      btn.addEventListener("click", async () => {
        await fetch(`${API_BASE}/scheduler/${btn.dataset.id}`, { method: "DELETE" });
        showToast("Schedule deleted");
        loadSchedules();
      });
    });
    list.querySelectorAll(".schedule-history").forEach(btn => {
      btn.addEventListener("click", async () => {
        const resp = await fetch(`${API_BASE}/scheduler/${btn.dataset.id}/history`);
        const data = await resp.json();
        const history = data.history || [];
        const body = history.length === 0
          ? "<p>No runs yet.</p>"
          : history.map(h => `
            <div class="data-row">
              <span class="label">${new Date(h.created_at).toLocaleString()}</span>
              <span class="value">${h.status} ${h.summary ? `(${h.summary.total_pages} pages)` : ""}</span>
            </div>
          `).join("");
        showModal(`History (${history.length} runs)`, body);      });
    });
  } catch (err) {
    list.innerHTML = `<div class="insights-card">Error: ${escapeHtml(err.message)}</div>`;
  }
}

document.getElementById("schedule-form")?.addEventListener("submit", async e => {
  e.preventDefault();
  const url = document.getElementById("schedule-url").value.trim();
  const value = parseFloat(document.getElementById("schedule-interval").value);
  const unit = document.getElementById("schedule-unit").value;
  let intervalHours = unit === "minutes" ? value / 60 : unit === "days" ? value * 24 : value;
  if (!(intervalHours >= 0.1)) intervalHours = 0.1;
  const maxPages = parseInt(document.getElementById("schedule-max-pages").value) || 50;
  if (!url) return;
  try {
    const resp = await fetch(`${API_BASE}/scheduler`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, interval_hours: intervalHours, max_pages: maxPages }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      showToast("Error: " + (err.detail || resp.status));
      return;
    }
    document.getElementById("schedule-url").value = "";
    showToast("Schedule added — first crawl starts in " + formatInterval(intervalHours));
    loadSchedules();
  } catch (err) {
    showToast("Error: " + err.message);
  }
});

document.getElementById("keyword-schedule-form")?.addEventListener("submit", async e => {
  e.preventDefault();
  const url = document.getElementById("keyword-schedule-url").value.trim();
  const value = parseFloat(document.getElementById("keyword-schedule-interval").value);
  const unit = document.getElementById("keyword-schedule-unit").value;
  let intervalHours = unit === "days" ? value * 24 : value;
  if (!(intervalHours >= 0.1)) intervalHours = 0.1;
  try {
    const resp = await fetch(`${API_BASE}/scheduler`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, interval_hours: intervalHours, kind: "keyword_check" }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast("Error: " + (data.detail || resp.status));
      return;
    }
    document.getElementById("keyword-schedule-url").value = "";
    showToast("Keyword re-check scheduled — every " + formatInterval(intervalHours));
    loadSchedules();
  } catch (err) {
    showToast("Error: " + err.message);
  }
});

function formatInterval(hours) {
  if (!hours || hours <= 0) return "—";
  if (hours < 1) return Math.round(hours * 60) + " minute" + (Math.round(hours * 60) === 1 ? "" : "s");
  if (hours % 24 === 0) return Math.round(hours / 24) + " day" + (Math.round(hours / 24) === 1 ? "" : "s");
  if (hours % 1 === 0) return hours + " hour" + (hours === 1 ? "" : "s");
  return Math.round(hours * 60) + " minutes";
}

// Logs & Alerts
async function loadLogs() {
  const filter = document.getElementById("audit-event-filter").value;

  const alertsEl = document.getElementById("alerts-list");
  const auditEl = document.getElementById("audit-list");

  try {
    const [alertsResp, auditResp] = await Promise.all([
      fetch(`${API_BASE}/logs/alerts`),
      fetch(`${API_BASE}/logs/audit?limit=100${filter ? `&event=${encodeURIComponent(filter)}` : ""}`),
    ]);
    const alerts = await alertsResp.json();
    const audit = await auditResp.json();

    const failed = alerts.failed_analyses || [];
    const broken = alerts.broken_schedules || [];
    alertsEl.innerHTML = [
      ...failed.map(a => `
        <div class="alert-card alert-error">
          <strong>Analysis failed</strong> — ${escapeHtml(a.url || a.job_id || "")} ${a.scheduled ? '<span class="site-status status-running">scheduled</span>' : ""}
          <div style="font-size:12px;color:var(--text-secondary);margin-top:4px">${escapeHtml(a.error || "")}</div>
          <div style="font-size:11px;color:var(--text-secondary);margin-top:2px">${new Date(a.timestamp).toLocaleString()}</div>
        </div>
      `),
      ...broken.map(b => `
        <div class="alert-card alert-error">
          <strong>Broken schedule</strong> — ${escapeHtml(b.domain || "")} last run failed
          <div style="font-size:12px;color:var(--text-secondary);margin-top:4px">${escapeHtml(b.last_error || "")}</div>
        </div>
      `),
      ...(failed.length === 0 && broken.length === 0 ? ['<div class="insights-card">No alerts in the last 24h. All clear.</div>'] : []),
    ].join("");

    const entries = audit.entries || [];
    auditEl.innerHTML = entries.length === 0
      ? '<div class="insights-card">No audit entries.</div>'
      : `<table class="data-table">
          <thead><tr><th>Timestamp</th><th>Event</th><th>Job</th><th>Details</th></tr></thead>
          <tbody>
            ${entries.map(e => `
              <tr>
                <td style="white-space:nowrap">${new Date(e.timestamp).toLocaleString()}</td>
                <td><span class="site-status ${e.event.includes("failed") ? "status-failed" : e.event.includes("completed") ? "status-completed" : "status-running"}">${escapeHtml(e.event)}</span></td>
                <td style="font-size:12px">${e.job_id ? e.job_id.slice(0, 8) + "…" : "—"}</td>
                <td style="font-size:12px;color:var(--text-secondary)">${escapeHtml(JSON.stringify(e.details || {}).slice(0, 120))}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>`;

    logsEl.textContent = (appLogs.lines || []).join("\n") || "No log output yet.";
    document.getElementById("app-log-path").textContent = appLogs.path ? `(${appLogs.path})` : "";
    logsEl.textContent = (appLogs.lines || []).join("\n") || "No log output yet.";
    document.getElementById("app-log-path").textContent = appLogs.path ? `(${appLogs.path})` : "";
  } catch (err) {
    alertsEl.innerHTML = `<div class="insights-card">Error: ${escapeHtml(err.message)}</div>`;
  }
}

document.getElementById("refresh-logs-btn")?.addEventListener("click", loadLogs);
document.getElementById("audit-event-filter")?.addEventListener("change", loadLogs);

function formatSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function linkify(url, maxLen) {
  const u = url || "";
  if (!u) return "-";
  const safe = escapeHtml(u);
  const label = maxLen && u.length > maxLen ? escapeHtml(u.substring(0, maxLen)) + "…" : safe;
  return `<a href="${safe}" target="_blank" rel="noopener noreferrer" title="${safe}">${label}</a>`;
}

function linkifyText(text, maxLen) {
  const raw = text || "";
  let label = raw;
  if (maxLen && raw.length > maxLen) label = raw.substring(0, maxLen) + "…";
  return escapeHtml(label).replace(/(https?:\/\/[^\s<>"']+)/g, m => `<a href="${m}" target="_blank" rel="noopener noreferrer">${m}</a>`);
}

const VALID_TABS = new Set(["sites", "overview", "pages", "content", "links", "actions", "report", "analytics", "seo-insights", "competitors", "quality", "schedules", "logs"]);

function parseHash() {
  const m = window.location.hash.match(/^#job\/([a-zA-Z0-9-]+)(?:\/([a-z-]+))?/);
  if (!m) return null;
  return { jobId: m[1], tab: m[2] || null };
}

async function restoreFromHash() {
  const state = parseHash();
  if (!state) return;
  try {
    const resp = await fetch(`${API_BASE}/analysis/${state.jobId}`);
    if (!resp.ok) {
      history.replaceState(null, "", location.pathname + location.search);
      return;
    }
    const job = await resp.json();
    if (!job || !job.id) return;
    await openSite(job.id, { preserveTab: true });
    if (state.tab && VALID_TABS.has(state.tab)) switchTab(state.tab);
  } catch (err) {
    console.error("Failed to restore job from URL", err);
  }
}

window.addEventListener("hashchange", restoreFromHash);
document.addEventListener("DOMContentLoaded", restoreFromHash);
