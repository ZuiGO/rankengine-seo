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
      if (currentTab === "pages") loadPages(currentJobId);
      if (currentTab === "content") loadContent(currentJobId);
      if (currentTab === "links") loadLinks(currentJobId);
      if (currentTab === "graph") loadGraph(currentJobId);
      if (currentTab === "actions") loadActions(currentJobId);
      if (currentTab === "report") loadReport(currentJobId);
      if (currentTab === "chat") initChat();
      if (currentTab === "seo-insights") loadSeoInsights(currentJobId);
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

async function showResults(jobId) {
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
  loadGraph(jobId);
  loadActions(jobId);
  loadReport(jobId);
  initChat();

  // Switch to overview
  document.querySelector('.tab[data-tab="overview"]').click();
}

function loadOverview(summary) {
  const stats = document.getElementById("overview-stats");
  stats.innerHTML = `
    <div class="stat-card"><div class="stat-value">${summary.total_pages}</div><div class="stat-label">Pages Crawled</div></div>
    <div class="stat-card"><div class="stat-value">${summary.total_content_items}</div><div class="stat-label">Content Items</div></div>
    <div class="stat-card"><div class="stat-value">${summary.total_action_items}</div><div class="stat-label">SEO Action Items</div></div>
    <div class="stat-card"><div class="stat-value">${summary.summary?.total_links || 0}</div><div class="stat-label">Total Links Found</div></div>
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
        <th>URL</th><th>Title</th><th>Words</th><th>Links</th><th>Images</th><th>Schema</th><th>Indexable</th>
      </tr></thead>
      <tbody>${filtered.map(p => `
        <tr>
          <td class="page-url-cell" title="${p.url}">${p.url}</td>
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
  const filter = document.getElementById("content-type-filter").value;
  const params = new URLSearchParams({ limit: "500" });
  if (filter) params.set("content_type", filter);

  const resp = await fetch(`${API_BASE}/content/${jobId}?${params}`);
  const data = await resp.json();
  document.getElementById("content-count").textContent = `${data.total} items`;

  const table = document.getElementById("content-table");
  if (data.items.length === 0) {
    table.innerHTML = '<p class="section-desc">No content items found.</p>';
    return;
  }

  const typeIcons = { image: "🖼", pdf: "📄", video: "🎬", doc: "📝", xlsx: "📊", presentation: "📽", audio: "🎵", text: "📃" };

  table.innerHTML = `
    <table class="data-table">
      <thead><tr>
        <th>Type</th><th>Source URL</th><th>Page URL</th><th>Size</th><th>MIME</th>
      </tr></thead>
      <tbody>${data.items.map(c => `
        <tr style="cursor:pointer" onclick="showContentDetail('${c.id}')">
          <td>${typeIcons[c.content_type] || "📄"} ${c.content_type}</td>
          <td class="page-url-cell" title="${c.source_url}">${c.source_url}</td>
          <td class="page-url-cell" title="${c.page_url}">${c.page_url}</td>
          <td>${c.file_size ? formatSize(c.file_size) : "-"}</td>
          <td>${c.mime_type || "-"}</td>
        </tr>
      `).join("")}</tbody>
    </table>
  `;
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
        <div class="data-row"><span class="label">Type</span><span class="value">${c.content_type}</span></div>
        <div class="data-row"><span class="label">Source URL</span><span class="value" style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.source_url}</span></div>
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
    <div class="stat-card"><div class="stat-value">${data.total_links}</div><div class="stat-label">Total Links</div></div>
    <div class="stat-card"><div class="stat-value">${data.total_internal}</div><div class="stat-label">Internal Links</div></div>
    <div class="stat-card"><div class="stat-value">${data.total_external}</div><div class="stat-label">External Links</div></div>
    <div class="stat-card"><div class="stat-value">${data.total_links ? ((data.total_internal / data.total_links) * 100).toFixed(0) : 0}%</div><div class="stat-label">Internal Ratio</div></div>
  `;

  const backlinksResp = await fetch(`${API_BASE}/links/${jobId}/backlinks`);
  const blData = await backlinksResp.json();
  document.getElementById("backlinks-list").innerHTML = blData.backlinks.length === 0
    ? '<p class="section-desc">No backlinks data yet. Backlink discovery coming in Phase 6.</p>'
    : `<table class="data-table"><thead><tr><th>Source</th><th>Target</th></tr></thead>
       <tbody>${blData.backlinks.map(b => `<tr><td>${b.source || "-"}</td><td>${b.target || "-"}</td></tr>`).join("")}</tbody></table>`;
}

async function loadGraph(jobId) {
  const resp = await fetch(`${API_BASE}/graph/${jobId}`);
  const data = await resp.json();

  const stats = document.getElementById("graph-stats");
  stats.innerHTML = `
    <div class="stat-card"><div class="stat-value">${data.nodes.length}</div><div class="stat-label">Graph Nodes</div></div>
    <div class="stat-card"><div class="stat-value">${data.edges.length}</div><div class="stat-label">Relationships</div></div>
    <div class="stat-card"><div class="stat-value">${data.nodes.filter(n => n.type === 'page').length}</div><div class="stat-label">Page Nodes</div></div>
    <div class="stat-card"><div class="stat-value">${data.nodes.filter(n => n.type === 'content').length}</div><div class="stat-label">Content Nodes</div></div>
  `;

  const legend = document.getElementById("graph-legend");
  legend.innerHTML = `
    <div class="graph-legend-item"><div class="graph-legend-dot" style="background:#6366f1"></div> Pages</div>
    <div class="graph-legend-item"><div class="graph-legend-dot" style="background:#22c55e"></div> Content</div>
    <div class="graph-legend-item"><span style="color:#94a3b8">────</span> HAS_CONTENT</div>
    <div class="graph-legend-item"><span style="color:#f59e0b">────</span> LINKS_TO</div>
  `;

  renderForceGraph(data.nodes, data.edges);
}

function renderForceGraph(nodes, edges) {
  const canvas = document.getElementById("graph-canvas");
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = Math.min(rect.width - 16, 900);
  canvas.height = 500;
  const ctx = canvas.getContext("2d");

  if (nodes.length === 0) {
    ctx.fillStyle = "#94a3b8";
    ctx.font = "16px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("No graph data available. Run an analysis first.", canvas.width / 2, canvas.height / 2);
    return;
  }

  const centerX = canvas.width / 2;
  const centerY = canvas.height / 2;
  const radius = Math.min(canvas.width, canvas.height) * 0.35;

  const sim = nodes.map((n, i) => {
    const angle = (i / nodes.length) * Math.PI * 2;
    return {
      ...n,
      x: centerX + radius * Math.cos(angle) + (Math.random() - 0.5) * 40,
      y: centerY + radius * Math.sin(angle) + (Math.random() - 0.5) * 40,
      vx: 0, vy: 0,
    };
  });

  const nodeMap = {};
  sim.forEach(n => { nodeMap[n.id] = n; });

  let hoveredNode = null;
  let tooltipEl = null;

  function createTooltip() {
    tooltipEl = document.createElement("div");
    tooltipEl.className = "graph-tooltip";
    tooltipEl.style.display = "none";
    canvas.parentElement.appendChild(tooltipEl);
  }
  createTooltip();

  function tick() {
    const k = 0.05;
    const repulsion = 6000;
    const attraction = 0.005;

    for (let i = 0; i < sim.length; i++) {
      for (let j = i + 1; j < sim.length; j++) {
        let dx = sim[j].x - sim[i].x;
        let dy = sim[j].y - sim[i].y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        let force = repulsion / (dist * dist);
        let fx = (dx / dist) * force;
        let fy = (dy / dist) * force;
        sim[i].vx -= fx;
        sim[i].vy -= fy;
        sim[j].vx += fx;
        sim[j].vy += fy;
      }
    }

    for (const edge of edges) {
      const a = nodeMap[edge.source];
      const b = nodeMap[edge.target];
      if (!a || !b) continue;
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 1;
      let force = (dist - 120) * attraction;
      let fx = (dx / dist) * force;
      let fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }

    const damping = 0.85;
    for (const n of sim) {
      n.vx *= damping;
      n.vy *= damping;
      n.x += n.vx;
      n.y += n.vy;

      const margin = 30;
      if (n.x < margin) { n.x = margin; n.vx *= -0.5; }
      if (n.x > canvas.width - margin) { n.x = canvas.width - margin; n.vx *= -0.5; }
      if (n.y < margin) { n.y = margin; n.vy *= -0.5; }
      if (n.y > canvas.height - margin) { n.y = canvas.height - margin; n.vy *= -0.5; }
    }

    draw();
    requestAnimationFrame(tick);
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (const edge of edges) {
      const a = nodeMap[edge.source];
      const b = nodeMap[edge.target];
      if (!a || !b) continue;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = edge.type === "HAS_CONTENT" ? "#94a3b8" : "#f59e0b";
      ctx.lineWidth = edge.type === "HAS_CONTENT" ? 0.8 : 1.2;
      ctx.globalAlpha = 0.4;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    for (const n of sim) {
      ctx.beginPath();
      const isHover = hoveredNode && hoveredNode.id === n.id;
      const r = isHover ? 9 : (n.type === "page" ? 7 : 5);
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = n.type === "page" ? "#6366f1" : "#22c55e";
      ctx.fill();
      if (isHover) {
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }
  }

  canvas.addEventListener("mousemove", e => {
    const rect2 = canvas.getBoundingClientRect();
    const mx = e.clientX - rect2.left;
    const my = e.clientY - rect2.top;
    const scaleX = canvas.width / rect2.width;
    const scaleY = canvas.height / rect2.height;
    const cmx = mx * scaleX;
    const cmy = my * scaleY;

    hoveredNode = null;
    for (const n of sim) {
      const dx = cmx - n.x;
      const dy = cmy - n.y;
      if (dx * dx + dy * dy < 400) {
        hoveredNode = n;
        break;
      }
    }

    if (hoveredNode) {
      const label = hoveredNode.title || hoveredNode.id;
      tooltipEl.textContent = `${hoveredNode.type}: ${label.substring(0, 80)}`;
      tooltipEl.style.display = "block";
      tooltipEl.style.left = (e.clientX - rect2.left + 12) + "px";
      tooltipEl.style.top = (e.clientY - rect2.top - 30) + "px";
      canvas.style.cursor = "pointer";
    } else {
      tooltipEl.style.display = "none";
      canvas.style.cursor = "grab";
    }
  });

  canvas.addEventListener("mouseleave", () => {
    hoveredNode = null;
    if (tooltipEl) tooltipEl.style.display = "none";
  });

  tick();
}

async function loadActions(jobId) {
  const statusFilter = document.getElementById("action-status-filter").value;
  const params = statusFilter ? `?status_filter=${statusFilter}` : "";
  const resp = await fetch(`${API_BASE}/actions/${jobId}${params}`);
  const data = await resp.json();
  document.getElementById("actions-count").textContent = `${data.total} items`;

  const list = document.getElementById("actions-list");
  if (data.actions.length === 0) {
    list.innerHTML = '<p class="section-desc">No action items.</p>';
    return;
  }

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

document.getElementById("action-status-filter")?.addEventListener("change", () => {
  if (currentJobId) loadActions(currentJobId);
});

async function approveAction(actionId, status) {
  try {
    await fetch(`${API_BASE}/actions/${actionId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    showToast(`Action ${status}`);
    if (currentJobId) loadActions(currentJobId);
  } catch (err) {
    showToast("Error: " + err.message);
  }
}

async function loadReport(jobId) {
  const link = document.getElementById("report-download-link");
  link.href = `${API_BASE}/reports/${jobId}/download`;

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
      ${ov.estimated_organic_traffic !== undefined ? `<div class="stat-card"><div class="stat-value">${ov.estimated_organic_traffic}</div><div class="stat-label">Organic Traffic</div></div>` : ""}
    </div>` : ""}
    <h4 style="margin:20px 0 10px">SEO Action Items (${report.seo_action_items.length})</h4>
    ${report.seo_action_items.slice(0, 10).map(a => `
      <div style="padding:10px 0;border-bottom:1px solid var(--border)">
        <strong>${a.content_type}</strong> - <span class="action-impact impact-${a.impact_on_ranking}">${a.impact_on_ranking}</span>
        <div style="font-size:13px;color:var(--text-secondary)">${(a.identified_issues || []).slice(0, 2).join("; ")}</div>
      </div>
    `).join("")}
    ${report.seo_action_items.length > 10 ? `<p style="margin-top:10px;font-size:13px;color:var(--text-secondary)">...and ${report.seo_action_items.length - 10} more items</p>` : ""}
  `;
}

// Chat
function initChat() {
  document.getElementById("chat-input").disabled = false;
  document.getElementById("chat-send").disabled = false;
}

document.getElementById("chat-form").addEventListener("submit", async e => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const msg = input.value.trim();
  if (!msg || !currentJobId) return;

  const messages = document.getElementById("chat-messages");
  messages.innerHTML += `<div class="chat-message user">${escapeHtml(msg)}</div>`;
  input.value = "";
  messages.scrollTop = messages.scrollHeight;

  const section = document.getElementById("chat-section").value;

  try {
    const resp = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJobId, section, message: msg }),
    });
    const data = await resp.json();
    messages.innerHTML += `<div class="chat-message bot">${escapeHtml(data.reply)}</div>`;
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
    renderKeywords(data.keywords || []);
    renderBacklinks(data.backlinks);
    renderDomainOverview(data.overview);
    renderOnpage(data.onpage);
  } catch (err) {
    errDiv.textContent = "Error loading insights: " + err.message;
    errDiv.classList.remove("hidden");
  }
}

function renderKeywords(keywords) {
  const el = document.getElementById("keywords-list");
  if (!keywords || keywords.length === 0) {
    el.innerHTML = '<div class="insights-card">No keyword data available.</div>';
    return;
  }
  el.innerHTML = keywords.slice(0, 15).map(k => `
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
  `).join("");
}

function renderBacklinks(bl) {
  const el = document.getElementById("backlinks-summary");
  if (!bl) {
    el.innerHTML = '<div class="insights-card">No backlink data available.</div>';
    return;
  }
  el.innerHTML = `
    <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
      <div class="insights-card"><div class="insights-label">Total Backlinks</div><div class="insights-value">${bl.total_backlinks ?? "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">Referring Domains</div><div class="insights-value">${bl.referring_domains ?? "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">Referring IPs</div><div class="insights-value">${bl.referring_ips ?? "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">Domain Rank</div><div class="insights-value">${bl.rank ?? "N/A"}</div></div>
    </div>
  `;
}

function renderDomainOverview(ov) {
  const el = document.getElementById("domain-overview");
  if (!ov) {
    el.innerHTML = '<div class="insights-card">No domain overview data available.</div>';
    return;
  }
  el.innerHTML = `
    <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
      <div class="insights-card"><div class="insights-label">Organic Traffic</div><div class="insights-value">${ov.estimated_organic_traffic ?? "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">Organic Keywords</div><div class="insights-value">${ov.organic_keywords_count ?? "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">Paid Keywords</div><div class="insights-value">${ov.paid_keywords_count ?? "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">Domain Rank</div><div class="insights-value">${ov.domain_rank ?? "N/A"}</div></div>
    </div>
  `;
}

function renderOnpage(op) {
  const el = document.getElementById("onpage-summary");
  if (!op) {
    el.innerHTML = '<div class="insights-card">No on-page data available.</div>';
    return;
  }
  el.innerHTML = `
    <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
      <div class="insights-card"><div class="insights-label">Overall Score</div><div class="insights-value">${op.score ?? "N/A"}%</div></div>
      <div class="insights-card"><div class="insights-label">Title</div><div class="insights-value">${op.title ?? "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">Description</div><div class="insights-value">${op.description?.length > 60 ? escapeHtml(op.description.slice(0,60)) + "..." : escapeHtml(op.description || "N/A")}</div></div>
    </div>
  `;
}

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
    const resp = await fetch(`${API_BASE}/sites`);
    const data = await resp.json();
    const sites = data.sites || [];
    document.getElementById("sites-count").textContent = `${sites.length} site(s) analyzed`;
    if (sites.length === 0) {
      grid.innerHTML = '<div class="insights-card">No sites analyzed yet. Run an analysis first.</div>';
      updateCompareBtn();
      return;
    }
    grid.innerHTML = sites.map(s => `
      <div class="site-card ${s.status !== "completed" ? "site-card-muted" : ""}">
        <label class="site-select">
          <input type="checkbox" data-job="${s.job_id}" ${selectedSiteIds.has(s.job_id) ? "checked" : ""}>
          <div>
            <div class="site-domain">${escapeHtml(s.domain)}</div>
            <div class="site-url">${escapeHtml(s.url)}</div>
            <div class="site-status status-${s.status}">${s.status}</div>
          </div>
        </label>
        <div class="site-stats">
          <div class="site-stat"><span>${s.total_pages}</span> pages</div>
          <div class="site-stat"><span>${s.total_content_items}</span> content</div>
          <div class="site-stat"><span>${s.backlinks ?? "N/A"}</span> backlinks</div>
          <div class="site-stat"><span>${s.domain_rank ?? "N/A"}</span> rank</div>
        </div>
        <button class="btn-secondary site-open" data-job="${s.job_id}">Open</button>
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
    updateCompareBtn();
  } catch (err) {
    grid.innerHTML = `<div class="insights-card">Error loading sites: ${escapeHtml(err.message)}</div>`;
  }
}

function updateCompareBtn() {
  const btn = document.getElementById("compare-sites-btn");
  btn.disabled = selectedSiteIds.size < 2;
}

async function openSite(jobId) {
  stopPolling();
  currentJobId = jobId;
  const resp = await fetch(`${API_BASE}/analysis/${jobId}`);
  const job = await resp.json();
  if (job.status === "completed") {
    showResults(jobId);
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
          <div class="site-url">${escapeHtml(s.url)}</div>
          <div class="site-status status-completed" style="margin-top:6px">${s.enabled ? "Enabled" : "Disabled"}</div>
        </div>
        <div class="schedule-meta">
          <div>Every <strong>${s.interval_hours}h</strong></div>
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
  const interval = parseFloat(document.getElementById("schedule-interval").value);
  const maxPages = parseInt(document.getElementById("schedule-max-pages").value) || 50;
  if (!url) return;
  try {
    const resp = await fetch(`${API_BASE}/scheduler`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, interval_hours: interval, max_pages: maxPages }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      showToast("Error: " + (err.detail || resp.status));
      return;
    }
    document.getElementById("schedule-url").value = "";
    showToast("Schedule added — first crawl starts in " + interval + "h");
    loadSchedules();
  } catch (err) {
    showToast("Error: " + err.message);
  }
});

// Logs & Alerts
async function loadLogs() {
  const filter = document.getElementById("audit-event-filter").value;

  const alertsEl = document.getElementById("alerts-list");
  const auditEl = document.getElementById("audit-list");
  const logsEl = document.getElementById("app-logs");

  try {
    const [alertsResp, auditResp, logsResp] = await Promise.all([
      fetch(`${API_BASE}/logs/alerts`),
      fetch(`${API_BASE}/logs/audit?limit=100${filter ? `&event=${encodeURIComponent(filter)}` : ""}`),
      fetch(`${API_BASE}/logs/app?limit=100`),
    ]);
    const alerts = await alertsResp.json();
    const audit = await auditResp.json();
    const appLogs = await logsResp.json();

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
