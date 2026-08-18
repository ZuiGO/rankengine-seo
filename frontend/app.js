const API_BASE = "/api";
let currentJobId = null;
let pollInterval = null;
let currentTab = "overview";

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("zui-theme", theme); } catch (e) {}
}

function initTheme() {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
}
// Applied on parse; the inline <head> snippet pre-applies the saved theme to avoid a flash.
initTheme();

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function countAnimate(el) {
  if (el._counting) return;
  el._counting = true;
  const target = parseFloat(el.dataset.count) || 0;
  const decimals = parseInt(el.dataset.decimals || "0", 10);
  const suffix = el.dataset.suffix || "";
  if (reducedMotion) {
    el.textContent = target.toFixed(decimals) + suffix;
    return;
  }
  const start = performance.now();
  const duration = 900;
  function frame(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = (target * eased).toFixed(decimals) + suffix;
    if (t < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function applyCounts(root) {
  root.querySelectorAll("[data-count]").forEach(countAnimate);
}

function skeletonHTML(kind, count) {
  const rows = [];
  for (let i = 0; i < (count || 3); i++) rows.push('<div class="skeleton-row"></div>');
  return '<div class="skeleton skeleton-' + (kind || "card") + '">' + rows.join("") + "</div>";
}

function emptyState(title, msg, ctaHtml) {
  return (
    '<div class="empty-state"><div class="empty-state-icon">' +
    "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"11\" cy=\"11\" r=\"7\"/><path d=\"M21 21l-4.3-4.3\"/></svg></div>" +
    (title ? "<h4>" + title + "</h4>" : "") +
    (msg ? "<p>" + msg + "</p>" : "") +
    (ctaHtml || "") +
    "</div>"
  );
}

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
      body: JSON.stringify({ url, email: (document.getElementById("email-input")?.value || "").trim() }),
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
  document.body.classList.remove("jobless");
  history.replaceState(null, "", location.pathname + location.search);
  resultsSection.classList.add("hidden");
  inputSection.classList.remove("hidden");
  urlInput.value = "";
  analyzeBtn.disabled = false;
  analyzeBtn.textContent = "Analyze";
  setDashboardVisible(false);
});

// Tab switching
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".tab-content").forEach(tc => tc.classList.add("hidden"));
    const target = document.getElementById(`tab-${tab.dataset.tab}`);
    if (target) {
      target.classList.remove("hidden");
      target.style.animation = 'none';
      void target.offsetWidth;
      target.style.animation = '';
      applyCounts(target);
    }
    currentTab = tab.dataset.tab;
    updateRailExplain(currentTab);

    if (currentJobId) {
      history.replaceState(null, "", `#job/${currentJobId}/${currentTab}`);
    }

    if (currentJobId) {
      if (currentTab === "pages") loadPages(currentJobId);
      if (currentTab === "content") loadContent(currentJobId);
      if (currentTab === "links") loadLinks(currentJobId);
      if (currentTab === "actions") loadActions(currentJobId);
      if (currentTab === "report") loadReport(currentJobId);
      if (currentTab === "chat") initChat();
      if (currentTab === "seo-insights") loadSeoInsights(currentJobId);
      if (currentTab === "competitors") loadCompetitors(currentJobId);
      if (currentTab === "quality") loadQuality(currentJobId);
      if (currentTab === "sites") loadSites();
      if (currentTab === "schedules") loadSchedules();
      if (currentTab === "logs") loadLogs();
      if (currentTab === "settings") loadSettings();
    } else if (["sites", "schedules", "logs", "settings"].includes(currentTab)) {
      if (currentTab === "sites") loadSites();
      if (currentTab === "schedules") loadSchedules();
      if (currentTab === "logs") loadLogs();
      if (currentTab === "settings") loadSettings();
    }
  });
});

// Dashboard rails: context, quick nav, activity feed, docked chat
const RAIL_TAB_LABELS = {
  sites: "Sites", overview: "Overview", pages: "Pages", content: "Content",
  links: "Links", actions: "SEO Actions", report: "Report", "seo-insights": "SEO Insights",
  competitors: "Competitors", quality: "Quality", schedules: "Schedules",
  logs: "Alerts", settings: "Settings",
};
const TAB_GUIDES = {
  overview: "Site-level health: pages, content, actions, user flows, the execution summary and deltas vs previous analyses.",
  sites: "Every analyzed site with health grades. Select two or more and compare them side by side.",
  pages: "All crawled pages with search, type filter and sorting.",
  content: "Every extracted content item (images, PDFs, video, documents...) with preview and the page it lives on.",
  links: "Link health, the full link list (OK / broken / redirect / blocked / unreachable / external), backlinks and honest redirect counts.",
  actions: "Impact-ranked SEO actions with evidence. Approve or reject — approved changes become versioned before/after snippets.",
  report: "The full branded analysis: KPIs, findings with evidence, quick wins, methodology, download and email options.",
  "seo-insights": "Live keyword, SERP, backlink and competitor data (SE Ranking) merged with what the crawl found locally.",
  competitors: "Crawl competitor sites and diff 8 gap dimensions against this site. Blocked crawls still yield a partial SE Ranking + SERP report.",
  quality: "The Site Health & Audits dashboard: each measured audit with pass / attention / fail and expandable checks.",
  schedules: "Recurring crawls and keyword re-checks. Each run creates a new analysis job in Sites.",
  logs: "Alerts from the last 24h: failed analyses and broken schedules.",
  settings: "Provider credentials (GSC, SE Ranking, GitHub, SMTP) stored in the app database.",
};
const RAIL_TIPS = [
  "URL slugs do double duty for search engines: keep them short, lowercase and keyword-first instead of using long IDs or dates.",
  "Alt text is an image-search signal — describe what the image shows in 5–10 words instead of stuffing keywords.",
  "Internal links pass authority: every key page should be reachable within 2–3 clicks from the homepage.",
  "Duplicate titles make search engines pick one URL per query — a unique title per page is a quick win.",
  "An XML sitemap only helps if it is listed in robots.txt and kept up to date with lastMod dates.",
  "Core Web Vitals are field-measured: metrics from real visitors matter more than lab tests.",
];

const railNavEl = document.getElementById("rail-nav");
const railExplainEl = document.getElementById("rail-explain");
const railTipEl = document.getElementById("rail-tip");
const railActivityEl = document.getElementById("rail-activity");
const railJobEl = document.getElementById("rail-job");
let chatUserClosed = false;
const crawlTick = { startedAt: 0, lastPages: 0, lastAt: 0, lastMsg: "" };

function buildRailNav() {
  if (!railNavEl) return;
  railNavEl.innerHTML = Object.keys(RAIL_TAB_LABELS).map(key => `
    <button type="button" class="rail-nav-btn" data-tab="${key}">
      <span>${RAIL_TAB_LABELS[key]}</span>
      <span class="rail-badge hidden-badge" data-badge-for="${key}"></span>
    </button>
  `).join("");
  railNavEl.querySelectorAll(".rail-nav-btn").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });
  if (railTipEl) {
    const idx = new Date().getDate() % RAIL_TIPS.length;
    railTipEl.innerHTML = `<small>Tip of the day</small>${escapeHtml(RAIL_TIPS[idx])}`;
  }
  updateRailExplain(currentTab);
}

function updateRailExplain(tab) {
  if (railExplainEl) {
    railExplainEl.textContent = TAB_GUIDES[tab] || "Pick a section to see what it covers.";
  }
  if (railNavEl) {
    railNavEl.querySelectorAll(".rail-nav-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
  }
}

function setTabBadge(tab, count) {
  const badge = railNavEl ? railNavEl.querySelector(`.rail-badge[data-badge-for="${tab}"]`) : null;
  if (!badge) return;
  if (count === null || count === undefined) {
    badge.classList.add("hidden-badge");
    return;
  }
  badge.textContent = count > 999 ? "999+" : String(count);
  badge.classList.toggle("hidden-badge", count <= 0);
  badge.title = count + " in " + (RAIL_TAB_LABELS[tab] || tab);
}

function renderRailJob(summary) {
  if (!railJobEl || !summary) return;
  const nested = summary.summary || {};
  const score = typeof nested.score === "number" ? nested.score
    : typeof nested.metrics?.score === "number" ? nested.metrics.score : null;
  let ring = "";
  if (score !== null) {
    const pct = Math.max(0, Math.min(100, score));
    const color = score >= 70 ? "#16a34a" : score >= 40 ? "#d97706" : "#dc2626";
    ring = `<div class="health-ring" style="--pct:${pct};background:conic-gradient(${color} ${pct}%, var(--surface-hover) 0)"><span>${score}</span></div>`;
  }
  const lines = [
    ["Pages crawled", summary.total_pages ?? "—"],
    ["Content items", summary.total_content_items ?? "—"],
    ["SEO actions", summary.total_action_items ?? "—"],
  ];
  railJobEl.innerHTML = `<div class="ring-wrap">${ring}<div>
      <div class="rail-domain">${escapeHtml(summary.url || "")}</div>
      <div class="rail-sub">Analysis · complete</div>
    </div></div>
    ${lines.map(([l, v]) => `<div class="rail-job-line"><span>${l}</span><b>${v}</b></div>`).join("")}`;
}

function pushActivity(severity, text) {
  if (!railActivityEl) return;
  const empty = railActivityEl.querySelector(".rail-empty");
  if (empty) empty.remove();
  const time = new Date().toLocaleTimeString([], { hour12: false });
  const item = document.createElement("div");
  item.className = "activity-item";
  item.innerHTML = `<span class="a-dot ${severity}"></span><span class="a-time">${time}</span><span class="a-text">${escapeHtml(text)}</span>`;
  railActivityEl.prepend(item);
  while (railActivityEl.children.length > 20) {
    railActivityEl.lastElementChild.remove();
  }
}

function setDashboardVisible(visible) {
  const grid = document.getElementById("dashboard-grid");
  if (!grid) return;
  grid.classList.toggle("hidden", !visible);
  document.body.classList.toggle("no-dashboard", !visible);
  applyRailMode();
}

function applyRailMode() {
  const wide = window.matchMedia("(min-width: 1280px)").matches && !document.body.classList.contains("no-dashboard");
  document.body.classList.toggle("app-wide", wide);
  const chat = document.getElementById("chat-widget");
  if (!chat) return;
  const dock = document.getElementById("chat-dock");
  const panel = document.getElementById("chat-panel");
  if (wide && dock && chat.parentElement !== dock) {
    dock.appendChild(chat);
    if (panel && !chatUserClosed) panel.classList.remove("hidden");
  } else if (!wide) {
    if (chat.parentElement !== document.body) document.body.appendChild(chat);
    if (panel && document.body.classList.contains("no-dashboard")) panel.classList.add("hidden");
  }
}

buildRailNav();
applyRailMode();
const railModeQuery = window.matchMedia("(min-width: 1280px)");
if (railModeQuery.addEventListener) railModeQuery.addEventListener("change", applyRailMode);
else railModeQuery.addListener(applyRailMode);

document.getElementById("rail-links")?.addEventListener("click", e => {
  const btn = e.target.closest("button[data-go]");
  if (!btn) return;
  if (btn.dataset.go === "new") {
    document.getElementById("new-analysis-btn")?.click();
  } else {
    switchTab(btn.dataset.go);
  }
});

async function loadSettings() {
  const clientId = document.getElementById("gsc-client-id");
  const redirectUri = document.getElementById("gsc-redirect-uri");
  const status = document.getElementById("gsc-settings-status");
  const hint = document.getElementById("gsc-settings-hint");
  const current = document.getElementById("gsc-redirect-current");
  if (hint) hint.style.display = "none";
  try {
    const resp = await fetch(`${API_BASE}/settings/gsc`);
    const s = resp.ok ? await resp.json() : {};
    if (clientId) clientId.placeholder = s.client_id_set ? s.client_id + " (saved)" : clientId.placeholder;
    if (redirectUri) {
      redirectUri.placeholder = s.redirect_uri || `${location.protocol}//${location.host}/api/gsc/callback`;
      if (current) current.textContent = s.redirect_uri ? `Current: ${s.redirect_uri}` : "";
    }
    if (status) status.textContent = s.client_id_set ? "Configured" : "Not configured yet";
  } catch (err) {
    if (status) status.textContent = "Settings unavailable: " + err.message;
  }
  const seStatus = document.getElementById("se-ranking-settings-status");
  const seRegion = document.getElementById("se-ranking-region");
  const seHint = document.getElementById("se-ranking-settings-hint");
  if (seHint) seHint.style.display = "none";
  try {
    const seResp = await fetch(`${API_BASE}/settings/se-ranking`);
    const se = seResp.ok ? await seResp.json() : {};
    if (seRegion) seRegion.placeholder = se.region || "us";
    if (seStatus) seStatus.textContent = se.api_key_set ? "Configured" : "Not configured yet";
  } catch (err) {
    if (seStatus) seStatus.textContent = "Settings unavailable: " + err.message;
  }
  const ghStatus = document.getElementById("github-settings-status");
  const ghHint = document.getElementById("github-settings-hint");
  if (ghHint) ghHint.style.display = "none";
  try {
    const ghResp = await fetch(`${API_BASE}/settings/github`);
    const gh = ghResp.ok ? await ghResp.json() : {};
    if (ghStatus) ghStatus.textContent = gh.token_set ? "Configured" : "Not configured yet";
  } catch (err) {
    if (ghStatus) ghStatus.textContent = "Settings unavailable: " + err.message;
  }
  const smtpStatus = document.getElementById("smtp-settings-status");
  const smtpHost = document.getElementById("smtp-host");
  const smtpPort = document.getElementById("smtp-port");
  const smtpFrom = document.getElementById("smtp-from");
  const smtpTls = document.getElementById("smtp-tls");
  const smtpHint = document.getElementById("smtp-settings-hint");
  if (smtpHint) smtpHint.style.display = "none";
  try {
    const smtpResp = await fetch(`${API_BASE}/settings/smtp`);
    const smtp = smtpResp.ok ? await smtpResp.json() : {};
    if (smtpHost) smtpHost.placeholder = smtp.host || "smtp.gmail.com";
    if (smtpPort) smtpPort.placeholder = smtp.port ? String(smtp.port) : "587";
    if (smtpFrom) smtpFrom.placeholder = smtp.from_email || "no-reply@yourdomain.com";
    if (smtpTls) smtpTls.checked = smtp.use_tls !== undefined ? smtp.use_tls : true;
    if (smtpStatus) smtpStatus.textContent = smtp.host_set ? "Configured" : "Not configured yet";
  } catch (err) {
    if (smtpStatus) smtpStatus.textContent = "Settings unavailable: " + err.message;
  }
}

document.getElementById("smtp-settings-save")?.addEventListener("click", async () => {
  const host = document.getElementById("smtp-host");
  const port = document.getElementById("smtp-port");
  const user = document.getElementById("smtp-user");
  const password = document.getElementById("smtp-password");
  const from = document.getElementById("smtp-from");
  const tls = document.getElementById("smtp-tls");
  const status = document.getElementById("smtp-settings-status");
  const hint = document.getElementById("smtp-settings-hint");
  try {
    const resp = await fetch(`${API_BASE}/settings/smtp`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        host: host ? host.value.trim() : "",
        port: port && port.value ? parseInt(port.value, 10) : null,
        user: user ? user.value.trim() : "",
        password: password ? password.value.trim() : "",
        from_email: from ? from.value.trim() : "",
        use_tls: tls ? tls.checked : true,
      }),
    });
    const s = await resp.json();
    if (!resp.ok) throw new Error(s.detail || resp.status);
    if (hint) {
      hint.textContent = "Saved. Emails now come from your SMTP server when a report is requested.";
      hint.style.display = "block";
    }
    if (host) host.value = "";
    if (user) user.value = "";
    if (password) password.value = "";
    if (from) from.value = "";
    if (status) status.textContent = "Configured";
    showToast("Email settings saved");
    loadSettings();
  } catch (err) {
    if (hint) {
      hint.textContent = "Failed to save: " + err.message;
      hint.style.display = "block";
    }
  }
});

document.getElementById("smtp-test-send")?.addEventListener("click", async () => {
  const toInput = document.getElementById("smtp-test-to");
  const status = document.getElementById("smtp-test-status");
  const errBox = document.getElementById("smtp-test-error");
  const btn = document.getElementById("smtp-test-send");
  const to = toInput ? toInput.value.trim() : "";
  if (!to || !to.includes("@")) {
    if (errBox) {
      errBox.textContent = "Enter a valid recipient email address first.";
      errBox.style.display = "block";
    }
    return;
  }
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Sending…";
  }
  if (errBox) errBox.style.display = "none";
  if (status) status.textContent = "";
  try {
    const resp = await fetch(`${API_BASE}/settings/smtp/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to }),
    });
    const data = await resp.json();
    if (resp.ok && data.sent) {
      if (status) status.textContent = "Test email sent — check the inbox.";
      showToast("Test email sent");
    } else {
      if (errBox) {
        errBox.textContent = "Test email failed: " + (data.error || "Unknown error");
        errBox.style.display = "block";
      }
    }
  } catch (err) {
    if (errBox) {
      errBox.textContent = "Test email failed: " + err.message;
      errBox.style.display = "block";
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Send Test Email";
    }
  }
});

document.getElementById("gsc-settings-save")?.addEventListener("click", async () => {
  const clientId = document.getElementById("gsc-client-id");
  const secret = document.getElementById("gsc-client-secret");
  const redirectUri = document.getElementById("gsc-redirect-uri");
  const status = document.getElementById("gsc-settings-status");
  const hint = document.getElementById("gsc-settings-hint");
  try {
    const resp = await fetch(`${API_BASE}/settings/gsc`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: clientId ? clientId.value.trim() : "",
        client_secret: secret ? secret.value.trim() : "",
        redirect_uri: redirectUri ? redirectUri.value.trim() : "",
      }),
    });
    const s = await resp.json();
    if (!resp.ok) throw new Error(s.detail || resp.status);
    if (hint) {
      hint.textContent = "Saved. This redirect URI must be registered in your Google Cloud OAuth client: " +
        (s.redirect_uri || `${location.protocol}//${location.host}/api/gsc/callback`);
      hint.style.display = "block";
    }
    if (clientId) clientId.value = "";
    if (secret) secret.value = "";
    if (status) status.textContent = "Configured";
    showToast("GSC settings saved");
    loadSettings();
  } catch (err) {
    if (hint) {
      hint.textContent = "Failed to save: " + err.message;
      hint.style.display = "block";
    }
  }
});

document.getElementById("se-ranking-settings-save")?.addEventListener("click", async () => {
  const apiKey = document.getElementById("se-ranking-api-key");
  const region = document.getElementById("se-ranking-region");
  const status = document.getElementById("se-ranking-settings-status");
  const hint = document.getElementById("se-ranking-settings-hint");
  try {
    const resp = await fetch(`${API_BASE}/settings/se-ranking`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: apiKey ? apiKey.value.trim() : "",
        region: region ? region.value.trim() : "",
      }),
    });
    const s = await resp.json();
    if (!resp.ok) throw new Error(s.detail || resp.status);
    if (hint) {
      hint.textContent = "Saved. SE Ranking now powers keywords, overview, competitors and the backlink profile.";
      hint.style.display = "block";
    }
    if (apiKey) apiKey.value = "";
    if (status) status.textContent = "Configured";
    showToast("SE Ranking settings saved");
    loadSettings();
  } catch (err) {
    if (hint) {
      hint.textContent = "Failed to save: " + err.message;
      hint.style.display = "block";
    }
  }
});

document.getElementById("github-settings-save")?.addEventListener("click", async () => {
  const token = document.getElementById("github-token");
  const status = document.getElementById("github-settings-status");
  const hint = document.getElementById("github-settings-hint");
  try {
    const resp = await fetch(`${API_BASE}/settings/github`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: token ? token.value.trim() : "" }),
    });
    const s = await resp.json();
    if (!resp.ok) throw new Error(s.detail || resp.status);
    if (hint) {
      hint.textContent = "Saved. The Actions tab can now push approved changes as a GitHub PR.";
      hint.style.display = "block";
    }
    if (token) token.value = "";
    if (status) status.textContent = "Configured";
    showToast("GitHub settings saved");
    loadSettings();
  } catch (err) {
    if (hint) {
      hint.textContent = "Failed to save: " + err.message;
      hint.style.display = "block";
    }
  }
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
    if (resp.status === 404) {
      showCancelledCard();
      return;
    }
    const job = await resp.json();

    progressBar.style.width = `${job.progress || 0}%`;
    progressMessage.textContent = job.progress_message || "";
    statusBadge.textContent = job.status;
    statusBadge.className = `status-badge status-${job.status}`;
    const progressPercent = document.getElementById("progress-percent");
    if (progressPercent) progressPercent.textContent = `${job.progress || 0}%`;
    if (job.status === "running" && /^Crawled /.test(job.progress_message || "")) {
      progressTitle.textContent = "Crawling...";
    } else if (job.status === "running") {
      progressTitle.textContent = "Running audit...";
    }
    updateCrawlPhase(job.status, job.current_stage || "");
    const pages = job.pages_crawled || 0;
    const csPages = document.getElementById("cs-pages");
    const csRate = document.getElementById("cs-rate");
    const csElapsed = document.getElementById("cs-elapsed");
    const csLast = document.getElementById("cs-last");
    if (csPages) csPages.textContent = String(pages);
    if (!crawlTick.startedAt) crawlTick.startedAt = Date.now();
    const nowMs = Date.now();
    if (csElapsed) {
      const secs = Math.round((nowMs - crawlTick.startedAt) / 1000);
      csElapsed.textContent = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
    }
    if (csRate && crawlTick.lastAt && pages > crawlTick.lastPages) {
      const mins = (nowMs - crawlTick.lastAt) / 60000;
      csRate.textContent = String(Math.max(1, Math.round((pages - crawlTick.lastPages) / (mins || 1))));
    }
    const lastUrl = (job.progress_message || "").match(/https?:\/\/[^\s'"<>]+/);
    if (csLast) csLast.textContent = lastUrl ? lastUrl[0].replace(/[.]+$/, "") : "—";
    if (job.progress_message && job.progress_message !== crawlTick.lastMsg) {
      pushActivity("info", job.progress_message);
      crawlTick.lastMsg = job.progress_message;
    }
    crawlTick.lastAt = nowMs;
    crawlTick.lastPages = pages;

    if (job.status === "completed") {
      stopPolling();
      pushActivity("ok", "Analysis completed — opening the dashboard.");
      showResults(jobId);
    } else if (job.status === "cancelled") {
      showCancelledCard();
    } else if (job.status === "failed") {
      stopPolling();
      progressTitle.textContent = "Analysis Failed";
      progressMessage.textContent = job.error_message || "Unknown error";
      statusBadge.className = "status-badge status-failed";
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = "Analyze";
      pushActivity("err", "Analysis failed: " + (job.error_message || "Unknown error"));
      showToast("Analysis failed: " + (job.error_message || "Unknown error"));
    }
  } catch (err) {
    if (err && err.message && /404/.test(err.message)) {
      showCancelledCard();
    }
    // keep polling
  }
}

function showCancelledCard() {
  stopPolling();
  const stopBtn = document.getElementById("stop-analysis-btn");
  const stopNote = document.getElementById("stop-analysis-note");
  if (stopBtn) {
    stopBtn.disabled = false;
    stopBtn.textContent = "Back to Analyze";
    stopBtn.className = "btn-secondary btn-sm";
    stopBtn.onclick = () => document.getElementById("new-analysis-btn")?.click();
  }
  if (stopNote) stopNote.textContent = "The cancelled analysis and its partial data were removed.";
  progressTitle.textContent = "Analysis Cancelled";
  progressMessage.textContent = "You stopped the analysis. Its partial data was removed.";
  statusBadge.textContent = "cancelled";
  statusBadge.className = "status-badge status-cancelled";
  pushActivity("warn", "Analysis cancelled by user.");
}

function updateCrawlPhase(status, stage) {
  const chips = document.getElementById("phase-chips");
  if (!chips) return;
  const order = ["queued", "crawling", "analyzing", "done"];
  let phase = "queued";
  if (status === "running") phase = stage === "crawling" ? "crawling" : "analyzing";
  else if (status === "completed") phase = "done";
  const activeIdx = order.indexOf(phase);
  chips.querySelectorAll(".phase-chip").forEach(c => {
    const i = order.indexOf(c.dataset.phase);
    c.classList.toggle("active", i === activeIdx);
    c.classList.toggle("done", i >= 0 && i < activeIdx);
    c.classList.toggle("fail", status === "failed" && c.dataset.phase === "analyzing");
  });
}

async function showResults(jobId, opts = {}) {
  hideProgress();
  document.body.classList.remove("jobless");
  resultsSection.classList.remove("hidden");
  inputSection.classList.add("hidden");
  setDashboardVisible(true);

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
  const nested = summary.summary || {};
  const geo = (summary.summary?.geo_readiness) || {};
  const geoCard = geo.status
    ? `<div class="stat-card"><div class="stat-value" style="font-size:16px">${geo.blocked_ai_crawlers?.length ? "Blocked: " + escapeHtml(geo.blocked_ai_crawlers.join(", ")) : "AI crawlers OK"}</div><div class="stat-label">AI Search Readiness${geo.score !== undefined && geo.score !== null ? " (" + geo.score + "/100)" : ""}</div></div>`
    : "";
  const ai = (summary.summary?.ai_visibility) || {};
  const scoreBar = s => (s !== undefined && s !== null)
    ? `<div style="height:5px;border-radius:3px;background:var(--border);margin-top:6px;overflow:hidden"><div style="width:${Math.max(0, Math.min(100, s))}%;height:100%;background:${s >= 70 ? "#16a34a" : s >= 40 ? "#d97706" : "#dc2626"}"></div></div>`
    : "";
  const aiCard = ai.score !== undefined && ai.score !== null
    ? `<div class="stat-card"><div class="stat-value" style="font-size:16px">${ai.score}/100</div><div class="stat-label">AI Visibility${ai.blocked_ai_agents?.length ? " · blocked" : ""}${ai.llms_txt_present ? " · llms.txt" : ""}</div>${scoreBar(ai.score)}</div>`
    : "";
  const local = (summary.summary?.local_seo) || {};
  const localCard = local.score !== undefined && local.score !== null
    ? `<div class="stat-card"><div class="stat-value" style="font-size:16px">${local.score}/100</div><div class="stat-label">Local SEO${local.local_business_schema ? " ✓" : ""}${local.nap_inconsistent ? " · NAP mismatch" : ""}</div>${scoreBar(local.score)}</div>`
    : "";
  const failedCard = nested.failed_urls_count
    ? `<div class="stat-card"><div class="stat-value" style="font-size:16px;color:#dc2626">${nested.failed_urls_count}</div><div class="stat-label">Pages Failed to Fetch</div></div>`
    : "";
  stats.innerHTML = `
    <div class="stat-card"><div class="stat-value" data-count="${summary.total_pages}">0</div><div class="stat-label">Pages Crawled</div></div>
    <div class="stat-card"><div class="stat-value" data-count="${summary.total_content_items}">0</div><div class="stat-label">Content Items</div></div>
    <div class="stat-card"><div class="stat-value" data-count="${summary.total_action_items}">0</div><div class="stat-label">SEO Action Items</div></div>
    <div class="stat-card"><div class="stat-value" data-count="${summary.summary?.total_links || 0}">0</div><div class="stat-label">Total Links Found</div></div>
    ${geoCard}${aiCard}${localCard}${failedCard}
  `;
  applyCounts(stats);

  const breakdown = document.getElementById("content-breakdown");
  const types = summary.content_breakdown || {};
  const icons = { image: "🖼", pdf: "📄", video: "🎬", video_embed: "🎬", doc: "📝", xlsx: "📊", presentation: "📽", audio: "🎵", text: "📃" };
  const colors = { image: "#fef3c7", pdf: "#dbeafe", video: "#ede9fe", video_embed: "#e9d5ff", doc: "#d1fae5", xlsx: "#fce7f3", presentation: "#e0e7ff", audio: "#fae8ff", text: "#f1f5f9" };
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

  renderRailJob(summary);
  breakdown.querySelectorAll(".content-type-card").forEach(card => {
    card.classList.add("clickable");
    card.addEventListener("click", () => {
      const type = card.querySelector(".ct-name").textContent.trim();
      const select = document.getElementById("content-type-filter");
      if (select && [...select.options].some(o => o.value === type)) {
        select.value = type;
        switchTab("content");
        if (currentJobId) loadContent(currentJobId);
      }
    });
  });
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

let pagesOffset = 0;

function yesNo(v) {
  return v ? '<span class="check-mark ok">Yes</span>' : '<span class="check-mark issue">No</span>';
}

function populatePageTypeFilter(types) {
  const sel = document.getElementById("pages-type-filter");
  if (!sel || sel.dataset.built) return;
  const opts = Object.entries(types || {}).sort((a, b) => b[1] - a[1]);
  opts.forEach(([t, n]) => {
    const o = document.createElement("option");
    o.value = t;
    o.textContent = t + " (" + n + ")";
    sel.appendChild(o);
  });
  sel.dataset.built = "1";
}

async function loadPages(jobId) {
  const table = document.getElementById("pages-table");
  const search = document.getElementById("pages-search").value.trim();
  const pageType = document.getElementById("pages-type-filter").value;
  const sort = document.getElementById("pages-sort").value;
  const order = document.getElementById("pages-order").value;
  const params = new URLSearchParams({ limit: "50", offset: String(pagesOffset) });
  if (search) params.set("search", search);
  if (pageType) params.set("page_type", pageType);
  if (sort) params.set("sort", sort);
  if (order) params.set("order", order);

  let data;
  try {
    const resp = await fetch(`${API_BASE}/pages/${jobId}/all?${params}`);
    data = resp.ok ? await resp.json() : null;
  } catch { data = null; }
  if (!data) {
    table.innerHTML = '<div class="insights-card">Failed to load pages.</div>';
    return;
  }

  populatePageTypeFilter(data.types);
  document.getElementById("pages-count").textContent = `${data.total} pages`;
  setTabBadge("pages", data.total);
  const prevBtn = document.getElementById("pages-prev-btn");
  const nextBtn = document.getElementById("pages-next-btn");
  if (prevBtn) prevBtn.disabled = pagesOffset <= 0;
  if (nextBtn) nextBtn.disabled = pagesOffset + data.pages.length >= data.total;

  if (data.pages.length === 0) {
    table.innerHTML = '<div class="insights-card">No pages match the current search and filters.</div>';
    return;
  }

  table.innerHTML = `
    <table class="data-table">
      <thead><tr>
        <th>URL</th><th>Type</th><th>Title</th><th>Words</th><th>Images</th><th>Schema</th><th>Depth</th><th>Indexable</th>
      </tr></thead>
      <tbody>${data.pages.map(p => `
        <tr>
          <td class="page-url-cell" title="${escapeHtml(p.url)}">${linkify(p.url, 80)}</td>
          <td><span class="page-type-badge">${escapeHtml(p.page_type || "other")}</span></td>
          <td>${escapeHtml((p.title || "-").substring(0, 55))}</td>
          <td>${p.word_count || 0}</td>
          <td>${p.image_count || 0}</td>
          <td>${yesNo(p.has_structured_data)}</td>
          <td>${p.click_depth ?? "-"}</td>
          <td>${yesNo(p.is_indexable)}</td>
        </tr>
      `).join("")}</tbody>
    </table>
  `;
}

// Pages bindings
document.getElementById("pages-search")?.addEventListener("input", () => {
  pagesOffset = 0;
  if (currentJobId) loadPages(currentJobId);
});
document.getElementById("pages-type-filter")?.addEventListener("change", () => {
  pagesOffset = 0;
  if (currentJobId) loadPages(currentJobId);
});
document.getElementById("pages-sort")?.addEventListener("change", () => {
  pagesOffset = 0;
  if (currentJobId) loadPages(currentJobId);
});
document.getElementById("pages-order")?.addEventListener("change", () => {
  pagesOffset = 0;
  if (currentJobId) loadPages(currentJobId);
});
document.getElementById("pages-prev-btn")?.addEventListener("click", () => {
  pagesOffset = Math.max(0, pagesOffset - 50);
  if (currentJobId) loadPages(currentJobId);
});
document.getElementById("pages-next-btn")?.addEventListener("click", () => {
  pagesOffset += 50;
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
  setTabBadge("content", data.total);

  const items = data.items || [];
  if (items.length === 0) {
    table.innerHTML = '<div class="insights-card">No content items found.</div>';
    return;
  }

  const typeIcons = { image: "🖼", pdf: "📄", video: "🎬", video_embed: "🎬", doc: "📝", xlsx: "📊", presentation: "📽", audio: "🎵", text: "📃", iframe: "🖼" };

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
  `;

  const backlinksResp = await fetch(`${API_BASE}/links/${jobId}/backlinks`);
  const blData = await backlinksResp.json();
  document.getElementById("backlinks-list").innerHTML = !blData.backlinks || blData.backlinks.length === 0
    ? '<p class="section-desc">No backlink sources discovered. See SEO Insights tab to run discovery.</p>'
    : `<p class="section-desc">${blData.total} source page(s) from ${blData.referring_domains} referring domain(s)</p>
       <table class="data-table"><thead><tr><th>Source URL</th><th>Domain</th><th>Anchor</th></tr></thead>
       <tbody>${blData.backlinks.map(b => `<tr><td class="page-url-cell" title="${b.source_url}">${linkify(b.source_url, 60)}</td><td>${b.source_domain || "-"}</td><td>${(b.anchor || "-").substring(0, 60)}</td></tr>`).join("")}</tbody></table>`;
  loadLinkHealth(jobId);
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
        <div class="insights-card"><div class="insights-label">Ends in redirect (301/302)</div><div class="insights-value" style="color:#d97706">${s.redirect ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Followed redirects</div><div class="insights-value" style="color:#d97706">${s.redirected_links ?? "N/A"}</div><div class="insights-label" style="font-size:10px;font-weight:400">links that redirected then resolved</div></div>
        <div class="insights-card"><div class="insights-label">Blocked (401/403)</div><div class="insights-value" style="color:#b45309">${s.blocked ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Unreachable</div><div class="insights-value">${s.unreachable ?? "N/A"}</div></div>
        <div class="insights-card"><div class="insights-label">Avg Link Length</div><div class="insights-value">${ls.avg ?? "-"} chars</div></div>
      </div>
      <p class="section-desc" style="margin-top:8px;font-size:12px">Last checked: ${s.checked_at ? new Date(s.checked_at).toLocaleString() : "never"}</p>
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
let allLinksExternal = null;

async function loadAllLinks(jobId, { reset } = {}) {
  const el = document.getElementById("all-links-card");
  if (!el) return;
  if (reset) {
    allLinksOffset = 0;
    const raw = document.getElementById("all-links-filter")?.value || "";
    if (raw === "__external__") {
      allLinksStatus = "";
      allLinksExternal = true;
    } else {
      allLinksStatus = raw;
      allLinksExternal = null;
    }
  }
  const params = new URLSearchParams({ limit: "200", offset: String(allLinksOffset) });
  if (allLinksStatus) params.set("status", allLinksStatus);
  if (allLinksExternal != null) params.set("external", String(allLinksExternal));
  try {
    const resp = await fetch(`${API_BASE}/links/${jobId}/all?${params}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const rows = (data.links || []).map(l => `<tr>
      <td><span class="page-type-badge" style="background:${l.status === "ok" ? "#dcfce7" : l.status === "unchecked" ? "#f1f5f9" : "#fee2e2"};color:${l.status === "ok" ? "#15803d" : l.status === "unchecked" ? "#64748b" : "#b91c1c"}">${l.status}</span></td>
      <td>${l.status_code ?? "-"}</td>
      <td class="page-url-cell" title="${l.url}">${l.external ? '<span class="page-type-badge" style="background:#e0e7ff;color:#4338ca">external</span> ' : ""}${linkify(l.url, 60)}</td>
      <td style="font-size:12px;color:var(--text-secondary)">${(l.redirect_count || 0) > 0
        ? (l.final_url ? `<span class="page-url-cell" title="${escapeHtml((l.redirect_chain || []).join(" -> ")) || ""}">${linkify(l.final_url, 45)}</span>` : "-")
        : "-"}</td>
      <td style="font-size:12px;color:var(--text-secondary)">${(l.pages || []).slice(0, 2).map(pg => linkify(pg, 30)).join("<br>") || "-"}</td>
    </tr>`).join("");
    el.innerHTML = `
      <p class="section-desc">${data.total} unique link target(s)${allLinksStatus ? ` (filter: ${allLinksStatus})` : allLinksExternal ? " (external links)" : ""}</p>
      ${(data.unchecked_count || 0) > 0
        ? `<p class="section-desc" style="font-size:12px;background:#fef9c3;border:1px solid #fde68a;border-radius:6px;padding:8px 10px;margin:8px 0;color:#854d0e">${data.unchecked_count} link(s) haven't had their HTTP status verified yet — they were recovered from the crawl (mostly external links). Click <strong>Check Links</strong> above to verify them.</p>`
        : ""}
      <table class="data-table"><thead><tr><th>Status</th><th>Code</th><th>URL</th><th>Redirected to</th><th>Linked From</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" style="text-align:center;color:var(--text-secondary)">No links for this filter</td></tr>'}</tbody></table>
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


document.getElementById("check-links-btn").addEventListener("click", async (e) => {
  e.preventDefault();
  e.stopPropagation();
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


let actionsOffset = 0;
const ACTIONS_PAGE = 200;

function evidenceHtml(value) {
  if (Array.isArray(value)) {
    const items = value.slice(0, 8).map(v => {
      const s = String(v);
      return /^https?:\/\//.test(s) ? linkify(s, 60) : escapeHtml(s);
    });
    return items.join(", ");
  }
  const s = String(value);
  return /^https?:\/\//.test(s) ? linkify(s, 60) : escapeHtml(s);
}

function actionCardHtml(a) {
  return `
    <div class="action-card action-card-collapsible" data-id="${a.id}">
      <div class="action-row" onclick="toggleActionCard(this)">
        <span class="action-type">${escapeHtml(a.content_type)}</span>
        <span class="action-impact impact-${a.impact_on_ranking}">${a.impact_on_ranking} impact</span>
        <span class="action-summary-text">${escapeHtml((a.identified_issues || []).join("; ").substring(0, 110) || "(no issues listed)")}</span>
        <span class="action-expand-icon">▸</span>
      </div>
      <div class="action-details" style="display:none">
        <div class="action-issues"><strong>Issues:</strong> ${escapeHtml((a.identified_issues || []).join("; "))}</div>
        <div class="action-improvements"><strong>Improve:</strong> ${escapeHtml((a.improvement_suggestions || []).join("; "))}</div>
        ${a.evidence && Object.keys(a.evidence).length ? `<div class="action-evidence"><strong>Evidence (from crawl):</strong> ${Object.entries(a.evidence).map(([k, v]) => `<span class="evidence-chip"><strong>${escapeHtml(String(k))}:</strong> ${evidenceHtml(v)}</span>`).join("")}</div>` : `<div class="action-evidence" style="color:var(--danger)"><strong>No evidence recorded — exclude this action before relying on it.</strong></div>`}
        ${a.status === "pending" ? `
          <div class="action-approve">
            <button class="btn-approve" onclick="approveAction('${a.id}', 'approved')">Approve</button>
            <button class="btn-reject" onclick="approveAction('${a.id}', 'rejected')">Reject</button>
          </div>
        ` : `<span style="font-size:13px;color:${a.status === 'approved' ? 'var(--success)' : 'var(--danger)'}">${a.status}</span>`}
      </div>
    </div>`;
}

function toggleActionCard(rowEl) {
  const details = rowEl.parentElement.querySelector(".action-details");
  const icon = rowEl.querySelector(".action-expand-icon");
  if (details) {
    const open = details.style.display !== "none";
    details.style.display = open ? "none" : "block";
    if (icon) icon.textContent = open ? "▸" : "▾";
  }
}

function toggleGroupExtra(gi) {
  const wrap = document.getElementById(`group-extra-${gi}`);
  const btn = document.getElementById(`group-more-${gi}`);
  if (!wrap) return;
  const open = wrap.style.display !== "none";
  wrap.style.display = open ? "none" : "block";
  if (btn) btn.textContent = open ? `Show all ${wrap.children.length} more` : "Show fewer";
}

async function groupBatch(jobId, contentType, status, issueKey) {
  const label = status === "approved" ? "Approve" : "Reject";
  const issueTxt = issueKey ? ` \`${issueKey}\`` : "";
  if (!confirm(`${label} ALL pending ${contentType}${issueTxt} actions? This generates content for every one and cannot be undone per-item.`)) return;
  const btn = document.querySelector(`[data-group-btn="${contentType}"][data-group-issue="${issueKey || ""}"][data-group-status="${status}"]`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Working...";
  }
  try {
    const resp = await fetch(`${API_BASE}/actions/${jobId}/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, status_filter: "pending", content_type: contentType, issue_key: issueKey || undefined }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    showToast(`${label}d ${data.updated} ${contentType} action(s)`);
  } catch (err) {
    showToast(`${label} failed: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = `${label} group`;
    }
    if (currentJobId) loadActions(currentJobId, { reset: true });
  }
}

async function loadActions(jobId, { reset } = {}) {
  if (reset) actionsOffset = 0;
  const statusFilter = document.getElementById("action-status-filter").value;
  const severity = document.getElementById("action-severity-filter").value;
  const sort = document.getElementById("action-sort-filter").value;
  const params = new URLSearchParams({
    limit: String(ACTIONS_PAGE),
    offset: String(actionsOffset),
    grouped: "true",
  });
  if (statusFilter) params.set("status_filter", statusFilter);
  if (severity) params.set("severity", severity);
  if (sort) params.set("sort", sort);
  const resp = await fetch(`${API_BASE}/actions/${jobId}?${params.toString()}`);
  const data = await resp.json();

  const s = data.summary || {};
  const countEl = document.getElementById("actions-count");
  countEl.textContent = `${data.total} items${s.pending != null ? ` · ${s.pending} pending · ${s.approved} approved · ${s.rejected} rejected` : ""}`;
  setTabBadge("actions", data.total);

  const list = document.getElementById("actions-list");
  if (data.actions.length === 0) {
    list.innerHTML = '<p class="section-desc">No action items.</p>';
    document.getElementById("actions-more-wrap")?.remove();
    loadVersions(jobId);
    return;
  }

  const groups = new Map();
  for (const a of data.actions) {
    const t = a.content_type || "other";
    const k = a.issue_key || "other";
    const gkey = `${t}|${k}`;
    if (!groups.has(gkey)) groups.set(gkey, []);
    groups.get(gkey).push(a);
  }

  const issueCounts = s.by_issue || {};
  const GROUP_PREVIEW = 8;
  let html = "";
  let gi = 0;
  for (const [gkey, items] of groups) {
    const [type, issueKey] = gkey.split("|");
    const groupTotal = issueCounts[gkey] ?? items.length;
    const first = items[0];
    const suggest = escapeHtml(
      (first.improvement_suggestions || []).join("; ") ||
      (first.identified_issues || []).join("; ") ||
      "improve this item"
    );
    const preview = items.slice(0, GROUP_PREVIEW).map(actionCardHtml).join("");
    const extra = items.slice(GROUP_PREVIEW);
    const extraWrap = extra.length
      ? `<div id="group-extra-${gi}" style="display:none">${extra.map(actionCardHtml).join("")}</div>
         <button id="group-more-${gi}" class="btn-secondary" style="margin:6px 0 2px" onclick="toggleGroupExtra(${gi})">Show all ${extra.length} more</button>`
      : "";
    html += `
      <details class="action-group" open data-group="${escapeHtml(gkey)}">
        <summary class="action-group-header">
          <span class="action-type">${escapeHtml(type)}</span>
          <span class="action-summary-text" style="flex:1;min-width:0">${suggest}</span>
          <span class="count-label">${items.length} shown / ${groupTotal} total</span>
          ${statusFilter !== "approved" && statusFilter !== "rejected" ? `
            <button class="btn-approve" style="padding:3px 10px;font-size:12px" data-group-btn="${escapeHtml(type)}" data-group-issue="${escapeHtml(issueKey)}" data-group-status="approved" onclick="event.preventDefault();event.stopPropagation();groupBatch('${jobId}', '${escapeHtml(type)}', 'approved', '${escapeHtml(issueKey)}')">Approve group</button>
            <button class="btn-reject" style="padding:3px 10px;font-size:12px" data-group-btn="${escapeHtml(type)}" data-group-issue="${escapeHtml(issueKey)}" data-group-status="rejected" onclick="event.preventDefault();event.stopPropagation();groupBatch('${jobId}', '${escapeHtml(type)}', 'rejected', '${escapeHtml(issueKey)}')">Reject group</button>
          ` : ""}
        </summary>
        <div class="action-group-body">${preview}${extraWrap}</div>
      </details>`;
    gi++;
  }
  list.innerHTML = html;

  const hasMore = actionsOffset + data.actions.length < data.total;
  document.getElementById("actions-more-wrap")?.remove();
  if (hasMore) {
    const wrap = document.createElement("div");
    wrap.id = "actions-more-wrap";
    wrap.style.marginTop = "12px";
    wrap.innerHTML = `<button id="actions-more-btn" class="btn-secondary">Load more (${data.total - actionsOffset - data.actions.length} remaining)</button>`;
    list.appendChild(wrap);
    document.getElementById("actions-more-btn").addEventListener("click", async () => {
      actionsOffset += ACTIONS_PAGE;
      await loadActions(jobId);
    });
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
          ${v.status === 'approved' && v.after ? `<span style="font-size:11px;color:var(--text-secondary)">${v.qa === 'suggestion' ? '(suggestion)' : v.qa === 'fallback' ? '(template fallback)' : ''} ${v.generated_by || ''}</span>` : ""}
        </div>
        <div class="action-issues"><strong>Before:</strong> <span style="color:var(--danger)">${escapeHtml((v.before || "-").substring(0, 200))}</span></div>
        <div class="action-improvements"><strong>After:</strong> <span style="color:var(--success)">${v.status === 'approved' ? escapeHtml((v.after || "").substring(0, 200) || "No content generated") : "Not generated (rejected)"}</span></div>
        <div style="font-size:12px;color:var(--text-secondary);margin-top:6px">${linkify(v.page_url || "", 80)} · ${v.generated_by || ""}</div>
        ${v.status === 'approved' && v.qa === 'suggestion' ? `<button class="btn-secondary" style="font-size:12px;padding:4px 10px;margin-top:8px" onclick="regenerateVersion('${v.action_id || v.id}')">Regenerate</button>` : ""}
      </div>
    `).join("");
  } catch (err) {
    el.innerHTML = `<p class="section-desc">Error loading versions: ${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById("action-status-filter")?.addEventListener("change", () => {
  if (currentJobId) loadActions(currentJobId, { reset: true });
});

document.getElementById("action-severity-filter")?.addEventListener("change", () => {
  if (currentJobId) loadActions(currentJobId, { reset: true });
});

document.getElementById("action-sort-filter")?.addEventListener("change", () => {
  if (currentJobId) loadActions(currentJobId, { reset: true });
});

document.getElementById("expand-all-actions-btn")?.addEventListener("click", () => {
  document.querySelectorAll(".action-group").forEach(g => { g.open = true; });
  document.querySelectorAll(".action-details").forEach(d => { d.style.display = "block"; });
  document.querySelectorAll(".action-expand-icon").forEach(i => { i.textContent = "▾"; });
});

document.getElementById("collapse-all-actions-btn")?.addEventListener("click", () => {
  document.querySelectorAll(".action-group").forEach(g => { g.open = false; });
  document.querySelectorAll(".action-details").forEach(d => { d.style.display = "none"; });
  document.querySelectorAll(".action-expand-icon").forEach(i => { i.textContent = "▸"; });
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
    if (currentJobId) loadActions(currentJobId, { reset: true });
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

function renderApplyGuide(guide) {
  const card = document.getElementById("apply-guide-card");
  if (!card) return;
  card.style.display = "block";
  const safe = escapeHtml(guide || "");
  card.innerHTML = `<pre style="white-space:pre-wrap;font-family:monospace;font-size:12px;line-height:1.6;margin:0;max-height:420px;overflow:auto">${safe}</pre>`;
}

document.getElementById("apply-sandbox-btn")?.addEventListener("click", () => {
  const tab = document.querySelector('.tab[data-tab="sandbox-approvals"]');
  if (tab) tab.click();
});

document.getElementById("apply-changes-btn")?.addEventListener("click", async () => {
  if (!currentJobId) return;
  if (!confirm("Apply approved SEO changes? Approved content is sent to GitHub as a pull request (or you get an in-repo guide to apply manually).")) return;
  const btn = document.getElementById("apply-changes-btn");
  const status = document.getElementById("apply-changes-status");
  btn.disabled = true;
  btn.textContent = "Applying...";
  if (status) status.textContent = "";
  try {
    const resp = await fetch(`${API_BASE}/actions/${currentJobId}/apply`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    if (data.ok) {
      showToast("Approved changes sent to GitHub PR");
      if (data.html_url) {
        if (status) status.innerHTML = `<a href="${data.html_url}" target="_blank" rel="noopener">PR created: ${data.html_url}</a>`;
      }
    } else if (data.reason === "no_approved") {
      if (status) status.textContent = data.message || "No approved changes yet.";
    } else {
      if (status) status.textContent = data.message || "Apply failed — see guide below.";
    }
    renderApplyGuide(data.guide);
  } catch (err) {
    showToast("Apply failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Apply via GitHub PR";
  }
});

document.getElementById("approve-all-btn")?.addEventListener("click", async () => {
  if (!currentJobId) return;
  if (!confirm("Approve ALL pending SEO changes? This generates improved content for every pending action. This cannot be undone per-item.")) return;
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
          if (currentJobId) loadActions(currentJobId, { reset: true });
          showToast(timedOut ? "Approve all is still running - check the Actions tab shortly" : "All changes approved. Export the patch or apply via GitHub.");
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
    if (currentJobId) loadActions(currentJobId, { reset: true });
  } catch (err) {
    showToast("Error: " + err.message);
    if (currentJobId) loadActions(currentJobId, { reset: true });
  }
}

async function regenerateVersion(actionId) {
  showToast("Regenerating change content...");
  try {
    const resp = await fetch(`${API_BASE}/actions/${actionId}/regenerate`, {
      method: "POST",
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    showToast(data.version?.after ? `Regenerated: ${data.version.after.substring(0, 60)}...` : "Regenerated - still empty");
    if (currentJobId) loadActions(currentJobId, { reset: true });
  } catch (err) {
    showToast("Regenerate failed: " + err.message);
  }
}

document.getElementById("refresh-report-btn")?.addEventListener("click", () => {
  if (currentJobId) loadReport(currentJobId);
});

document.getElementById("report-email-btn")?.addEventListener("click", async () => {
  if (!currentJobId) return;
  const input = document.getElementById("report-email-input");
  if (!input) return;
  const to = input.value.trim();
  if (!to) {
    input.focus();
    showToast("Enter a recipient email address first");
    return;
  }
  const btn = document.getElementById("report-email-btn");
  btn.disabled = true;
  btn.textContent = "Sending...";
  try {
    const resp = await fetch(`${API_BASE}/reports/${currentJobId}/email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      const detail = data.detail && typeof data.detail === "object" ? data.detail.error : data.detail;
      throw new Error(detail || resp.statusText);
    }
    showToast(data.message || `Report emailed to ${to}`);
  } catch (err) {
    showToast("Email failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Email report";
  }
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
  `;
  loadReportExtras(jobId, preview);
}

async function loadReportExtras(jobId, preview) {
  const kv = (label, value) => `<div class="stat-card"><div class="stat-value" style="font-size:14px">${value}</div><div class="stat-label">${label}</div></div>`;
  const bar = (label, score, max = 100) => {
    const pct = Math.max(0, Math.min(100, max ? (score / max) * 100 : 0));
    return `
      <div style="margin:8px 0">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">
          <span style="color:var(--text-secondary)">${label}</span><strong>${score}${max !== 100 ? "/" + max : ""}</strong>
        </div>
        <div style="height:6px;border-radius:3px;background:var(--border);overflow:hidden">
          <div style="width:${pct}%;height:100%;background:${pct >= 70 ? "#16a34a" : pct >= 40 ? "#d97706" : "#dc2626"}"></div>
        </div>
      </div>`;
  };
  const checksList = checks => (checks || []).length
    ? `<div style="margin-top:10px">${checks.map(c => `
        <div style="display:flex;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);font-size:13px">
          <span style="flex:0 0 18px;text-align:center;color:${c.passed ? "#16a34a" : "#dc2626"}">${c.passed ? "✓" : "✗"}</span>
          <div><div>${escapeHtml(c.label)}</div>
          ${c.detail ? `<div style="color:var(--text-secondary);font-size:12px;margin-top:2px">${linkifyText(c.detail, 140)}</div>` : ""}</div>
        </div>`).join("")}</div>`
    : "";
  try {
    const sm = await fetch(`${API_BASE}/quality/${jobId}/sitemap`);
    if (sm.ok) {
      const d = await sm.json();
      const coverage = d.crawled_coverage ?? null;
      const pagesIn = d.pages_in_sitemap ?? d.url_count ?? "N/A";
      const uncrawledList = (d.uncrawled_urls || []).slice(0, 8);
      preview.insertAdjacentHTML("beforeend", `
        <h4 style="margin:20px 0 10px">Sitemap</h4>
        <div class="stats-grid" style="grid-template-columns:repeat(3,1fr)">
          ${kv("Found", d.sitemap_found ? "✅" : "❌")}
          ${kv("Valid", d.sitemap_valid ? "✅" : "❌")}
          ${kv("URLs in sitemap", pagesIn)}
          ${kv("Pages crawled", d.pages_crawled ?? "N/A")}
          ${kv("Coverage", coverage !== null ? coverage + "%" : "N/A")}
          ${kv("No lastmod", d.missing_lastmod ?? "N/A")}
        </div>
        ${coverage !== null ? bar("Sitemap coverage (crawled / listed)", coverage) : ""}
        ${(d.http_plain_urls || []).length ? `<p style="font-size:12px;color:var(--text-secondary);margin-top:6px">⚠ Non-HTTPS URLs in sitemap: ${d.http_plain_urls.length} (<code>${escapeHtml(d.http_plain_urls.slice(0, 4).join(", "))}</code>${d.http_plain_urls.length > 4 ? "…" : ""})</p>` : ""}
        ${(d.missing_lastmod || 0) > 0 ? `<p style="font-size:12px;color:var(--text-secondary);margin-top:6px">⚠ ${d.missing_lastmod} URL(s) lack a <code>lastmod</code> date — search engines can still index them, but freshness signals are weaker.</p>` : ""}
        ${uncrawledList.length ? `
          <p style="font-size:12px;color:var(--text-secondary);margin-top:6px"><strong>${d.uncrawled_urls_count || uncrawledList.length} URL(s) not crawled</strong>: ${uncrawledList.map(escapeHtml).join(", ")}${(d.uncrawled_urls_count || 0) > uncrawledList.length ? ` +${(d.uncrawled_urls_count || 0) - uncrawledList.length} more` : ""}</p>` : ""}`);
    }
  } catch (_) {}
  try {
    const ai = await fetch(`${API_BASE}/quality/${jobId}/ai-visibility`);
    if (ai.ok) {
      const d = await ai.json();
      const subs = d.subscores || {};
      const types = d.schema_types || {};
      preview.insertAdjacentHTML("beforeend", `
        <h4 style="margin:20px 0 10px">AI-Search Visibility</h4>
        <div class="stats-grid" style="grid-template-columns:repeat(3,1fr)">
          ${kv("Score", (d.score ?? "N/A") + "/100")}
          ${kv("robots.txt", d.robots_txt_found ? (d.robots_status || "OK") : "missing")}
          ${kv("llms.txt", d.llms_txt_present ? "✅ published" : "❌ missing")}
          ${kv("Structured data pages", (d.structured_data_pages ?? 0) + "/" + (d.total_pages ?? "N/A"))}
          ${kv("Blocked AI agents", d.blocked_ai_agents?.length ? d.blocked_ai_agents.join(", ") : "none")}
          ${kv("Extractable content", (d.extractable_pages ?? 0) + "/" + (d.total_pages ?? "N/A") + " pages")}
          ${kv("AI files", [d.llms_txt_present && "llms.txt", d.pricing_md_present && "pricing.md", d.okf_present && "OKF"].filter(Boolean).join(", ") || "none")}
          ${kv("Author attribution", d.scanned_pages ? (d.author_pages ?? 0) + "/" + d.scanned_pages + " pages" : "N/A")}
        </div>
        ${d.scanned_pages ? `<p style="font-size:12px;color:var(--text-secondary);margin-top:6px">Scanned ${d.scanned_pages} pages — answer blocks: ${d.answer_block_pages ?? 0} · FAQ headings: ${d.faq_heading_pages ?? 0} · comparison tables: ${d.comparison_table_pages ?? 0} · freshly updated: ${d.fresh_pages ?? 0}</p>` : ""}
        ${d.blocked_training_agents?.length ? `<p style="font-size:12px;color:#d97706;margin-top:6px">⚠ robots.txt blocks training-only crawler(s): ${d.blocked_training_agents.join(", ")} — OK if intentional (blocks training, allows citation).</p>` : ""}
        <div style="max-width:460px">
          ${bar("XML sitemap", subs.sitemap ?? 0, 25)}
          ${bar("llms.txt", subs.llms_txt ?? 0, 25)}
          ${bar("Structured data", subs.structured_data ?? 0, 25)}
          ${bar("Extractable content", subs.extractable_content ?? 0, 25)}
        </div>
        ${(d.ai_agents || []).length ? `
        <table class="data-table" style="margin-top:10px">
          <thead><tr><th>AI Agent</th><th>Status</th><th>Disallow rules</th><th>Crawl delay</th></tr></thead>
          <tbody>${d.ai_agents.map(a => `
            <tr>
              <td>${escapeHtml(a.agent)}</td>
              <td>${a.status === "blocked" ? "⛔ blocked" : a.status === "partial" ? "⚠ partial" : "✅ allowed"}</td>
              <td>${a.disallow_rules || 0}</td>
              <td>${a.crawl_delay ? a.crawl_delay + "s" : "—"}</td>
            </tr>`).join("")}
          </tbody>
        </table>` : ""}
        ${Object.keys(types).length ? `<p style="font-size:12px;color:var(--text-secondary);margin-top:6px">Schema types: ${Object.entries(types).map(([t, n]) => `${escapeHtml(t)} (${n})`).join(" · ")}</p>` : ""}
        ${checksList(d.checks)}`);
    }
  } catch (_) {}
  try {
    const lo = await fetch(`${API_BASE}/quality/${jobId}/local-seo`);
    if (lo.ok) {
      const d = await lo.json();
      const subs = d.subscores || {};
      const nap = (d.naps_found || [])[0];
      preview.insertAdjacentHTML("beforeend", `
        <h4 style="margin:20px 0 10px">Local SEO Readiness</h4>
        <div class="stats-grid" style="grid-template-columns:repeat(3,1fr)">
          ${kv("Score", (d.score ?? "N/A") + "/100")}
          ${kv("LocalBusiness schema", d.local_business_schema ? "✅" : "❌")}
          ${kv("On homepage", d.local_business_on_homepage ? "✅" : "❌")}
          ${kv("NAP consistency", d.nap_inconsistent ? "⚠ mismatched" : "✅ consistent")}
          ${kv("Contact page", d.contact_page_present ? "✅" : "❌")}
          ${kv("Schema pages", d.pages_with_local_schema ?? 0)}
        </div>
        <div style="max-width:460px">
          ${bar("LocalBusiness schema", subs.local_business_schema ?? 0, 40)}
          ${bar("NAP data", subs.nap ?? 0, 20)}
          ${bar("Contact page", subs.contact_page ?? 0, 15)}
          ${bar("Address signals", subs.address_signals ?? 0, 10)}
          ${bar("Geo signals", subs.geo_signals ?? 0, 10)}
          ${bar("Reviews", subs.reviews ?? 0, 5)}
        </div>
        ${d.nap_inconsistent ? `<p style="font-size:12px;color:#dc2626;margin-top:6px">⚠ Multiple different business names / phone numbers / addresses were found in structured data — keep one consistent NAP across all pages.</p>` : ""}
        ${nap ? `<p style="font-size:12px;color:var(--text-secondary);margin-top:6px">NAP: <strong>${escapeHtml(nap.name || "?")}</strong> · ${escapeHtml(nap.street_address || nap.address || "?")} · ${escapeHtml(nap.telephone || "?")}</p>` : ""}
        <p style="font-size:12px;color:var(--text-secondary);margin-top:6px">Signals: ${[["geo", d.geo_pages], ["opening hours", d.opening_hours_pages], ["phone", d.phone_pages], ["reviews", d.reviews_pages], ["address", d.address_pages]].filter(([, n]) => n).map(([l, n]) => `${l}: ${n} page(s)`).join(" · ") || "none found"}</p>
        ${checksList(d.checks)}`);
    }
  } catch (_) {}
  try {
    const hr = await fetch(`${API_BASE}/quality/${jobId}/hreflang`);
    if (hr.ok) {
      const d = await hr.json();
      preview.insertAdjacentHTML("beforeend", `
        <h4 style="margin:20px 0 10px">International SEO / hreflang ${d.score != null ? `(${d.score}/100)` : ""}</h4>
        ${d.applicable === false
          ? `<p style="font-size:12px;color:var(--text-secondary)">Not applicable — no localized URL structure detected on this site.</p>`
          : `
        <div class="stat-grid">
          ${kv("Locales", (d.locales || []).join(", ") || "none")}
          ${kv("Pages with hreflang", d.pages_with_hreflang ?? 0)}
          ${kv("Missing self-references", d.missing_self_ref ?? 0)}
          ${kv("Missing x-default", d.missing_xdefault ?? 0)}
          ${kv("Invalid language codes", d.invalid_codes ?? 0)}
          ${kv("One-way pairs", d.one_way_pairs_count ?? 0)}
          ${kv("Canonical conflicts", d.canonical_conflicts_count ?? 0)}
          ${kv("Lang-parameter pages", d.lang_param_pages ?? 0)}
          <div class="stat-card"><div class="stat-label">Sitemap "alternate" entries / codes</div><div class="stat-value" style="font-size:14px">${d.sitemap_alt_entries ?? 0} / ${(d.sitemap_alt_codes || []).length}</div></div>
          </div>
          ${bar("Self-referencing pages", d.subscores && d.subscores.self_reference)}
          ${bar("x-default declared", d.subscores && d.subscores.x_default)}
          ${bar("Valid language/region codes", d.subscores && d.subscores.valid_codes)}
          ${bar("Reciprocal pairs", d.subscores && d.subscores.reciprocal)}
          ${bar("Locale-based URL structure", d.subscores && d.subscores.locale_urls)}
          ${checksList(d.checks)}`}
      `);
    }
  } catch (_) {}
  try {
    const uh = await fetch(`${API_BASE}/quality/${jobId}/url-hygiene`);
    if (uh.ok) {
      const d = await uh.json();
      preview.insertAdjacentHTML("beforeend", `
        <h4 style="margin:20px 0 10px">URL Hygiene (${d.score}/100)</h4>
        <div class="stat-grid">
          ${kv("Parameter pages", d.param_pages ?? 0)}
          ${kv("Faceted / pagination pages", d.facet_pages ?? 0)}
          ${kv("Distinct parameters", (d.top_params ? Object.keys(d.top_params).length : 0))}
          ${kv("Uppercase slugs", d.uppercase_paths ?? d.uppercase_slugs ?? 0)}
          ${kv("Underscore slugs", d.underscore_paths ?? d.underscore_slugs ?? 0)}
          ${kv("Long slugs (>80)", d.long_slugs ?? 0)}
          ${kv("Lang parameter pages", d.lang_param_pages ?? 0)}
        </div>
        ${(() => { const tp = d.top_params; if (!tp) return ""; const pairs = Array.isArray(tp) ? tp : Object.entries(tp); if (!pairs.length) return ""; return `<p style="font-size:12px;color:var(--text-secondary);margin-top:6px">Top URL parameters: ${pairs.slice(0, 6).map(t => `${escapeHtml(t[0])} (${t[1]})`).join(" · ")}</p>`; })()}
        ${bar("Parameter control", d.subscores && d.subscores.parameter_control)}
        ${bar("Readable paths", d.subscores && d.subscores.readable_paths)}
        ${bar("Slug length", d.subscores && d.subscores.slug_length)}
        ${bar("Slash consistency", d.subscores && d.subscores.slash_consistency)}
        ${checksList(d.checks)}`);
    }
  } catch (_) {}
  try {
    const im = await fetch(`${API_BASE}/quality/${jobId}/image-optimization`);
    if (im.ok) {
      const d = await im.json();
      preview.insertAdjacentHTML("beforeend", `
        <h4 style="margin:20px 0 10px">Image Optimization (${d.score}/100)</h4>
        <div class="stat-grid">
          ${kv("Unique images", d.total_images ?? d.total_imgs ?? 0)}
          ${kv("WebP / AVIF", d.modern_images ?? d.modern ?? 0)}
          ${kv("Without dimensions", d.missing_dimensions ?? d.dims_missing ?? 0)}
          ${kv("Lazy-loaded", d.lazy_images ?? d.lazy ?? 0)}
        </div>
        ${bar("Modern formats (WebP/AVIF)", d.subscores && d.subscores.modern_formats)}
        ${bar("Lazy loading", d.subscores && d.subscores.lazy_loading)}
        ${bar("Explicit dimensions", d.subscores && d.subscores.dimensions)}
        ${checksList(d.checks)}`);
    }
  } catch (_) {}
  try {
    const ps = await fetch(`${API_BASE}/quality/${jobId}/programmatic-seo`);
    if (ps.ok) {
      const d = await ps.json();
      const subs = d.subscores || {};
      const clusters = d.clusters || [];
      preview.insertAdjacentHTML("beforeend", `
        <h4 style="margin:20px 0 10px">Programmatic SEO</h4>
        <div class="stats-grid" style="grid-template-columns:repeat(3,1fr)">
          ${kv("Score", (d.score ?? "N/A") + "/100")}
          ${kv("Template pages", (d.template_pages ?? 0) + " / " + (d.total_pages ?? 0))}
          ${kv("Template share", (d.template_page_share ?? 0) + "%")}
          ${kv("Thin template pages", d.thin_template_pages ?? 0)}
          ${kv("Near-duplicate pages", d.duplicate_template_pages ?? 0)}
          ${kv("Unlinked (orphan spokes)", d.unlinked_template_pages ?? 0)}
        </div>
        <div style="max-width:460px">
          ${bar("Structure detected", subs.structure ?? 0, 25)}
          ${bar("Content uniqueness", subs.content_uniqueness ?? 0, 25)}
          ${bar("Internal linking", subs.internal_linking ?? 0, 25)}
          ${bar("Indexation / sitemap", subs.indexation ?? 0, 25)}
        </div>
        ${clusters.length ? `
        <table class="data-table" style="margin-top:10px">
          <thead><tr><th>Template pattern</th><th>Pages</th><th>Thin</th><th>Near-dup</th><th>Unlinked</th><th>Sample</th></tr></thead>
          <tbody>${clusters.slice(0, 8).map(c => `
            <tr>
              <td>${escapeHtml(c.pattern)}</td>
              <td>${c.page_count || 0}</td>
              <td>${c.thin_pages || 0}</td>
              <td>${c.duplicate_pages || 0}</td>
              <td>${c.unlinked_pages || 0}</td>
              <td>${(c.sample_urls || []).slice(0, 2).map(linkifyText).join(", ")}</td>
            </tr>`).join("")}
          </tbody>
        </table>` : `<p style="font-size:12px;color:var(--text-secondary)">No template page clusters detected (fewer than 3 pages share a URL pattern).</p>`}
        ${checksList(d.checks)}`);
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
  chatUserClosed = panel.classList.contains("hidden");
  if (!panel.classList.contains("hidden")) {
    const messages = document.getElementById("chat-messages");
    messages.scrollTop = messages.scrollHeight;
    document.getElementById("chat-input").focus();
  }
});

document.getElementById("chat-close").addEventListener("click", () => {
  document.getElementById("chat-panel").classList.add("hidden");
  chatUserClosed = true;
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
      messages.innerHTML += `<div class="chat-message bot"><div class="chat-render">${renderBotReply(data.reply)}</div></div>`;
    }
    messages.scrollTop = messages.scrollHeight;
  } catch (err) {
    messages.innerHTML += `<div class="chat-message bot">Error: ${err.message}</div>`;
  }
});

// Helpers
function showProgress() {
  document.body.classList.remove("jobless");
  inputSection.classList.add("hidden");
  progressSection.classList.remove("hidden");
  setDashboardVisible(false);
  progressBar.style.width = "0%";
  progressMessage.textContent = "Starting...";
  progressTitle.textContent = "Crawling...";
  statusBadge.className = "status-badge status-queued";
  const progressPercent = document.getElementById("progress-percent");
  if (progressPercent) progressPercent.textContent = "0%";
  statusBadge.textContent = "Queued";
  crawlTick.startedAt = 0;
  crawlTick.lastPages = 0;
  crawlTick.lastAt = 0;
  crawlTick.lastMsg = "";
  const csRate = document.getElementById("cs-rate");
  if (csRate) csRate.textContent = "—";
  const csElapsed = document.getElementById("cs-elapsed");
  if (csElapsed) csElapsed.textContent = "0:00";
  const csLast = document.getElementById("cs-last");
  if (csLast) csLast.textContent = "—";
  const csPages = document.getElementById("cs-pages");
  if (csPages) csPages.textContent = "0";
  const stopBtn = document.getElementById("stop-analysis-btn");
  if (stopBtn) {
    stopBtn.textContent = "Stop";
    stopBtn.className = "btn-danger btn-sm";
    stopBtn.onclick = stopCurrentAnalysis;
  }
  const stopNote = document.getElementById("stop-analysis-note");
  if (stopNote) stopNote.textContent = "Stops the crawl and removes partial data.";
  if (railActivityEl) {
    railActivityEl.innerHTML = '<p class="rail-empty">Crawl events, alerts and lifecycle messages will appear here.</p>';
  }
  updateCrawlPhase("queued", "");
  pushActivity("info", "Analysis queued for " + (resultsUrl.textContent || "this site") + ".");
}

function hideProgress() {
  progressSection.classList.add("hidden");
}

function showToast(msg) {
  toast.textContent = msg;
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 3000);
}

async function stopCurrentAnalysis() {
  if (!currentJobId) return;
  const stopBtn = document.getElementById("stop-analysis-btn");
  if (stopBtn) {
    stopBtn.disabled = true;
    stopBtn.textContent = "Stopping...";
  }
  try {
    const resp = await fetch(`${API_BASE}/analysis/${currentJobId}/cancel`, { method: "POST" });
    if (resp.ok) {
      progressMessage.textContent = "Cancelling...";
      showToast("Stopping the analysis…");
    } else {
      const data = await resp.json().catch(() => ({}));
      showToast("Could not stop: " + (data.detail || resp.statusText));
      if (stopBtn) {
        stopBtn.disabled = false;
        stopBtn.textContent = "Stop";
      }
    }
  } catch (err) {
    showToast("Could not stop: " + err.message);
    if (stopBtn) {
      stopBtn.disabled = false;
      stopBtn.textContent = "Stop";
    }
  }
}

// SEO Insights
function serviceErrorHtml(service, message, hint) {
  return `<div class="service-error">
    <div class="service-error-title">${escapeHtml(service || "Service")} unavailable</div>
    <div class="service-error-msg">${escapeHtml(message || "Unknown error")}</div>
    ${hint ? `<div class="service-error-hint">${escapeHtml(hint)}</div>` : ""}
  </div>`;
}

function insightErrorKind(msg) {
  const m = String(msg || "");
  if (/402|40200|credits|fund|payment|quota/i.test(m)) return { kind: "credits", title: "Live data unavailable (no credits)" };
  if (/\b404\b|not enabled|not on .*plan|not present/i.test(m)) return { kind: "disabled", title: "Live data endpoint not enabled" };
  if (/\b429\b|rate.paused|rate.limit/i.test(m)) return { kind: "rate", title: "Data service temporarily rate-limited" };
  if (/\b(500|502|503|504)\b|\btemporarily issue/i.test(m)) return { kind: "retry", title: "Data service temporarily unavailable" };
  if (/keyword check(s)? failed/i.test(m)) return { kind: "partial", title: "Some keyword checks failed" };
  return { kind: "other", title: "External data source unavailable" };
}

function insightWarningHtml(error) {
  const k = insightErrorKind(error);
  return `<div class="source-note" style="color:var(--warning, #b45309)">
    <strong>${escapeHtml(k.title)}</strong> — showing fallback data instead.
    <details style="display:inline-block;margin-left:6px"><summary>details</summary><div style="font-size:12px;color:var(--text-secondary);white-space:pre-wrap">${escapeHtml(String(error || ""))}</div></details>
  </div>`;
}

function insightErrorHtml(error) {
  const k = insightErrorKind(error);
  if (k.kind === "credits") {
    return `<div class="service-error" style="background:#fffbeb;border-color:#fde68a">
      <div class="service-error-title" style="color:#92400e">Live data unavailable (no credits)</div>
      <div class="service-error-msg" style="color:#78350f">This data couldn't be fetched and no local fallback is available. Top up SE Ranking credits (or connect SE Ranking in Settings) to enable live keyword, competitor, backlink and domain data.</div>
    </div>`;
  }
  if (k.kind === "disabled") {
    return `<div class="service-error" style="background:#fefce8;border-color:#fde047">
      <div class="service-error-title" style="color:#713f12">Live data endpoint not enabled</div>
      <div class="service-error-msg" style="color:#713f12">Your current SE Ranking plan does not include this endpoint, so live data isn't available for it. It's not an error — upgrade the plan or check the API key in Settings to fill it in.</div>
    </div>`;
  }
  if (k.kind === "rate" || k.kind === "retry") {
    return `<div class="service-error" style="background:#fefce8;border-color:#fde047">
      <div class="service-error-title" style="color:#713f12">${escapeHtml(k.title)}</div>
      <div class="service-error-msg" style="color:#713f12">This is temporary — use Refresh Insights to retry in a minute and the data should come back.</div>
    </div>`;
  }
  return serviceErrorHtml(k.title, String(error || "Unknown error"));
}

function sourceLabel(source) {
  const map = { gsc: "Google Search Console", serp: "SERP API", "se-ranking": "SE Ranking", local: "local crawl data", none: "not available" };
  return map[source] || source || "not available";
}

function renderInsightSection(el, { data, error, source, emptyText, render }) {
  let html = "";
  if (error) {
    if (data && render) {
      html += `<p class="source-note">Source: ${sourceLabel(source)}</p>`;
      html += render(data);
      html += insightWarningHtml(error);
    } else {
      html += insightErrorHtml(error);
    }
  } else if (data && render) {
    html += `<p class="source-note">Source: ${sourceLabel(source)}</p>`;
    html += render(data);
  } else {
    html += `<div class="insights-card">${emptyText}</div>`;
  }
  el.innerHTML = html;
}

async function loadQuality(jobId) {
  const el = document.getElementById("quality-content");
  if (!el) return;
  el.innerHTML = '<div class="insights-card">Loading site health & audits...</div>';
  const [dup, sd, perf, geo, orphans, spend, summary, decay, hl, uh, idx, imgOpt, sitemap, aiVis, local, links, health] = await Promise.all([
    clientGet(`${API_BASE}/quality/${jobId}/duplicates`),
    clientGet(`${API_BASE}/quality/${jobId}/structured-data`),
    clientGet(`${API_BASE}/quality/${jobId}/performance`),
    clientGet(`${API_BASE}/quality/${jobId}/geo-alignment`),
    clientGet(`${API_BASE}/quality/${jobId}/orphans`),
    clientGet(`${API_BASE}/spend/${jobId}`),
    clientGet(`${API_BASE}/analysis/${jobId}/summary`),
    clientGet(`${API_BASE}/quality/${jobId}/decay?months=6`),
    clientGet(`${API_BASE}/quality/${jobId}/hreflang`),
    clientGet(`${API_BASE}/quality/${jobId}/url-hygiene`),
    clientGet(`${API_BASE}/quality/${jobId}/indexation`),
    clientGet(`${API_BASE}/quality/${jobId}/image-optimization`),
    clientGet(`${API_BASE}/quality/${jobId}/sitemap`),
    clientGet(`${API_BASE}/quality/${jobId}/ai-visibility`),
    clientGet(`${API_BASE}/quality/${jobId}/local-seo`),
    clientGet(`${API_BASE}/links/${jobId}`),
    clientGet(`${API_BASE}/sites/${jobId}/health`),
  ]);
  const nested = summary?.summary || summary || {};
  renderSiteHealth(health, nested);
  el.innerHTML = renderQuality(dup, sd, perf, geo, orphans, nested, decay, hl, uh, idx, imgOpt, sitemap, aiVis, local, links);
  setTabBadge("quality", el.querySelectorAll(".audit-card").length);
  const spendEl = document.getElementById("quality-spend");
  if (spendEl) spendEl.innerHTML = renderSpend(spend);
}

document.getElementById("quality-expand-btn")?.addEventListener("click", () => {
  document.querySelectorAll("#quality-content .audit-card").forEach(d => d.setAttribute("open", ""));
});
document.getElementById("quality-collapse-btn")?.addEventListener("click", () => {
  document.querySelectorAll("#quality-content .audit-card").forEach(d => d.removeAttribute("open"));
});

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

function statusChip(status, label) {
  const cls = { pass: "chip-pass", attention: "chip-attention", fail: "chip-fail", na: "chip-na", notconfigured: "chip-notconfigured" }[status] || "chip-na";
  return `<span class="status-chip ${cls}">${escapeHtml(label)}</span>`;
}

function scoreFrom(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  const v = Number(value);
  return v >= 70 ? "pass" : v >= 40 ? "attention" : "fail";
}

function auditCard(title, { status, label, score, verdict, detail, checks, evidence }) {
  return `<div class="audit-card">
    <div class="audit-card-head"><span class="audit-title">${escapeHtml(title)}</span>${statusChip(status, label)}</div>
    ${score !== null && score !== undefined ? `<div class="bar-track" style="margin:6px 0"><div class="bar-fill" style="width:${Math.max(0, Math.min(100, score))}%;background:${score >= 70 ? "#16a34a" : score >= 40 ? "#d97706" : "#dc2626"}"></div></div>` : ""}
    <div class="audit-verdict">${verdict}</div>
    ${detail ? `<div class="audit-detail">${detail}</div>` : ""}
    ${evidence || ""}
    ${checks && checks.length ? `<details class="audit-checks"><summary>Checks (${checks.length})</summary>${checks.map(c => `<div class="audit-check"><span class="check-mark ${c.passed ? "ok" : "issue"}">${c.passed ? "Pass" : "Issue"}</span> ${escapeHtml(c.label)}${c.detail ? ` <span class="count-label">— ${escapeHtml(c.detail)}</span>` : ""}</div>`).join("")}</details>` : ""}
  </div>`;
}

function renderSiteHealth(health, nested) {
  const el = document.getElementById("quality-health-card");
  if (!el) return;
  const h = health || {};
  if (!h.score && !h.grade && !(h.issues || []).length) {
    el.innerHTML = "";
    return;
  }
  const score = h.score !== undefined && h.score !== null ? Number(h.score) : null;
  const issues = (h.issues || []).slice(0, 6);
  el.innerHTML = `<div class="audit-card" style="grid-column:1/-1">
    <div class="audit-card-head">
      <span class="audit-title">Overall Site Health</span>
      <span class="status-chip ${scoreFrom(score) || "na"}">Grade ${escapeHtml(h.grade || "N/A")}</span>
    </div>
    ${score !== null ? `<div class="bar-track" style="margin:6px 0"><div class="bar-fill" style="width:${score}%;background:${score >= 70 ? "#16a34a" : score >= 40 ? "#d97706" : "#dc2626"}"></div></div>
    <div class="audit-verdict">Overall health score: ${score}/100 (grade ${escapeHtml(h.grade || "N/A")}).</div>` : `<div class="audit-verdict">Site health not computed for this job yet.</div>`}
    ${issues.length ? `<div class="audit-detail">${issues.map(i => `<div class="audit-check"><span class="check-mark issue">Issue</span> ${escapeHtml(i.message || i)}</div>`).join("")}</div>` : ""}
  </div>`;
}

function renderQuality(dup, sd, perf, geo, orphans, nested, decay, hl, uh, idx, imgOpt, sitemap, aiVis, local, links) {
  const cards = [];

  const dupCount = (dup?.duplicate_groups?.length) ?? 0;
  cards.push(auditCard("Duplicate Content & Canonicals", dup
    ? (() => {
        const conflicts = (dup.canonical_conflicting ?? 0) + (dup.canonical_cross_domain ?? 0);
        const status = dupCount === 0 && conflicts === 0 ? "pass" : dupCount <= 5 && conflicts === 0 ? "attention" : "fail";
        const groupsHtml = dupCount
          ? `<details class="audit-checks" style="margin-top:8px"><summary>Duplicate groups (${dupCount}) — pages with near-identical content</summary>${(dup.duplicate_groups || []).map(g => `
            <div class="audit-check" style="flex-direction:column;align-items:flex-start;gap:4px">
              <span class="check-mark issue">Duplicate</span>
              <div style="font-size:12px;line-height:1.5">${(g.urls || []).slice(0, 5).map(u => linkify(u, 90)).join("<span style='color:var(--text-secondary)'> ↔ </span>")}${(g.urls || []).length > 5 ? ` <span class="count-label">+${g.urls.length - 5} more</span>` : ""}</div>
              <span class="count-label">similarity: ${escapeHtml(g.similarity || "high")}</span>
            </div>`).join("")}</details>`
          : "";
        return {
          status, label: status === "pass" ? "Pass" : status === "attention" ? "Attention" : "Fail",
          score: dupCount === 0 && conflicts === 0 ? 100 : Math.max(0, 100 - dupCount * 10 - conflicts * 15),
          verdict: dupCount === 0 && conflicts === 0
            ? "No duplicate or near-duplicate page groups found."
            : `${dupCount} duplicate group(s) and ${conflicts} canonical conflict(s) found — consolidate to one canonical URL per topic.`,
          detail: `${dup.duplicate_pages ?? 0} pages involved · ${dup.canonical_missing ?? 0} pages missing a canonical tag`,
          checks: (dup.canonical_flags || []).filter(f => f.canonical_conflicting || f.canonical_cross_domain).map(f => ({ passed: false, label: f.page_url, detail: f.canonical_target })),
          evidence: groupsHtml,
        };
      })()
    : { status: "na", label: "Not run", verdict: "Duplicate-content audit not run for this job." }));

  const sdInvalid = (sd?.invalid_types ?? 0);
  cards.push(auditCard("Structured Data", sd
    ? (() => {
        const status = sdInvalid === 0 ? "pass" : "attention";
        return {
          status, label: status === "pass" ? "Pass" : "Attention",
          score: sdInvalid === 0 ? 100 : Math.max(0, 100 - sdInvalid * 20),
          verdict: sdInvalid === 0
            ? `Valid structured data on ${sd.valid ?? 0} page(s); ${sd.no_structured_data ?? 0} pages have none.`
            : `${sdInvalid} page(s) have invalid or unsupported markup — fix to enable rich results.`,
          detail: Object.entries(sd.type_counts || {}).map(([t, c]) => `${t}: ${c}`).join(" · "),
        };
      })()
    : { status: "na", label: "Not run", verdict: "Structured-data audit not run for this job." }));

  const perfScore = perf?.avg_cwv_score ?? null;
  cards.push(auditCard("Core Web Vitals", perf && perfScore !== null
    ? (() => {
        const status = scoreFrom(perfScore) || "attention";
        return {
          status, label: status === "pass" ? "Pass" : status === "attention" ? "Attention" : "Fail",
          score: perfScore,
          verdict: `${perfScore}/100 average CWV score across ${perf.checked ?? 0} page(s) — field + lab data via PageSpeed Insights.`,
          detail: (perf.errors || []).slice(0, 3).join(" · ") || undefined,
        };
      })()
    : perf && perf.errors && perf.errors.length
      ? { status: "notconfigured", label: "Not measured", verdict: `PageSpeed Insights unavailable: ${escapeHtml(perf.errors[0])}`, score: null }
      : { status: "notconfigured", label: "Not measured", verdict: "Core Web Vitals not measured for this job (needs PageSpeed Insights).", score: null }));

  const offTopic = geo?.off_topic_pages ?? 0;
  cards.push(auditCard("Industry Alignment (GEO)", geo
    ? {
        status: offTopic === 0 ? "pass" : "attention",
        label: offTopic === 0 ? "Pass" : "Attention",
        score: offTopic === 0 ? 100 : Math.max(0, 100 - offTopic * 10),
        verdict: offTopic === 0
          ? `All ${geo.pages_analyzed ?? 0} analyzed page(s) match the core industry topic.`
          : `${offTopic} of ${geo.pages_analyzed ?? 0} page(s) look off-topic — align titles/body with core industry keywords.`,
        detail: `Core keywords: ${(geo.industry_keywords || []).join(", ") || "none"}`,
        checks: (geo.pages || []).filter(p => p.off_topic).slice(0, 10).map(p => ({ passed: false, label: p.title || p.page_url, detail: "alignment " + (p.alignment ?? 0).toFixed(2) })),
      }
    : { status: "na", label: "Not run", verdict: "Industry-alignment audit not run for this job." }));

  const orphanCount = orphans?.orphan_pages ?? 0;
  cards.push(auditCard("Orphan Pages", orphans
    ? {
        status: orphanCount === 0 ? "pass" : "attention",
        label: orphanCount === 0 ? "Pass" : "Attention",
        score: orphanCount === 0 ? 100 : Math.max(0, 100 - orphanCount * 3),
        verdict: orphanCount === 0
          ? "Every crawled page has at least one internal link pointing to it."
          : `${orphanCount} page(s) have no internal links — add links from related pages to make them crawlable.`,
        checks: (orphans.pages || []).slice(0, 15).map(p => ({ passed: false, label: p.page_url, detail: (p.suggested_link_sources || []).slice(0, 2).join(", ") })),
      }
    : { status: "na", label: "Not run", verdict: "Orphan-page audit not run for this job." }));

  cards.push(auditCard("Content Decay", decay && decay.pages_with_last_modified > 0
    ? (() => {
        const stale = decay.stale_pages ?? 0;
        return {
          status: stale === 0 ? "pass" : "attention",
          label: stale === 0 ? "Pass" : "Attention",
          score: stale === 0 ? 100 : Math.max(0, 100 - stale * 3),
          verdict: stale === 0
            ? `${decay.pages_with_last_modified} page(s) send Last-Modified; none are stale.`
            : `${stale} of ${decay.pages_with_last_modified} page(s) are stale (>${decay.stale_after_days ?? 180} days since last modified) — refresh outdated content.`,
          checks: (decay.pages || []).slice(0, 10).map(p => ({ passed: false, label: p.page_url, detail: `${p.stale_days} days old` })),
        };
      })()
    : { status: "na", label: "No data", verdict: "Site does not send Last-Modified headers, so content decay cannot be measured.", score: null }));

  const geoReadiness = nested.geo_readiness || {};
  cards.push(auditCard("AI Search (GEO) Readiness", geoReadiness.status
    ? (() => {
        const status = scoreFrom(geoReadiness.score) || "attention";
        return {
          status, label: status === "pass" ? "Pass" : status === "attention" ? "Attention" : "Fail",
          score: geoReadiness.score,
          verdict: `robots.txt: ${geoReadiness.robots_txt_found ? "found" : "missing"} · blocked AI crawlers: ${(geoReadiness.blocked_ai_crawlers || []).join(", ") || "none"} · checked: ${(geoReadiness.ai_agents_scanned || []).join(", ") || "none"}`,
          checks: (geoReadiness.blocked_ai_crawlers || []).map(c => ({ passed: false, label: c, detail: "blocked in robots.txt" })),
        };
      })()
    : { status: "na", label: "No data", verdict: "AI-search readiness data not available for this job.", score: null }));

  cards.push(auditCard("International SEO (hreflang)", hl && hl.applicable === false
    ? { status: "na", label: "Not applicable", verdict: "Site appears monolingual — hreflang not needed.", score: null, detail: `${hl.total_pages ?? 0} pages checked` }
    : hl && hl.score !== null && hl.score !== undefined
      ? (() => {
          const status = scoreFrom(hl.score) || "attention";
          return {
            status, label: status === "pass" ? "Pass" : status === "attention" ? "Attention" : "Fail",
            score: hl.score,
            verdict: `${hl.locales && hl.locales.length ? hl.locales.join(", ") + " locales · " : ""}${hl.hreflang_errors ?? 0} hreflang error(s) across ${hl.total_pages ?? 0} pages.`,
            checks: (hl.errors || []).slice(0, 10).map(e => ({ passed: false, label: String(e.message || e), detail: String(e.url || "") })),
          };
        })()
      : { status: "na", label: "Not run", verdict: "Hreflang audit not run for this job.", score: null }));

  cards.push(auditCard("URL Hygiene", uh && uh.score !== undefined && uh.score !== null
    ? (() => {
        const status = scoreFrom(uh.score) || "attention";
        return {
          status, label: status === "pass" ? "Pass" : status === "attention" ? "Attention" : "Fail",
          score: uh.score,
          verdict: `Parameter pages: ${uh.param_pages ?? 0} · long slugs: ${uh.long_slugs ?? 0} · uppercase/underscore paths: ${(uh.uppercase_paths ?? 0) + (uh.underscore_paths ?? 0)}`,
          checks: Object.entries(uh.top_params || {}).slice(0, 5).map(([k, v]) => ({ passed: false, label: `?${k} (${v} pages)` })),
        };
      })()
    : { status: "na", label: "Not run", verdict: "URL-hygiene audit not run for this job.", score: null }));

  cards.push(auditCard("Indexation", idx && idx.status === "unmeasured"
    ? { status: "notconfigured", label: "Not measured", verdict: idx.message || "Indexation estimate requires SERP credits — not run for this job.", score: null, detail: `${idx.crawled_pages ?? 0} pages crawled locally` }
    : idx && idx.status === "measured"
      ? {
          status: "pass", label: "Measured", score: null,
          verdict: `Estimated indexed pages: ${idx.indexed_estimate ?? "n/a"} via live SERP sample.`,
          checks: (idx.top_indexed_pages || []).slice(0, 5).map(p => ({ passed: true, label: p.url || String(p) })),
        }
      : { status: "na", label: "Not run", verdict: "Indexation check not run for this job.", score: null }));

  const imgScore = imgOpt?.score;
  cards.push(auditCard("Image Optimization", imgOpt && imgOpt.score !== undefined && imgOpt.score !== null
    ? (() => {
        const status = scoreFrom(imgScore) || "attention";
        return {
          status, label: status === "pass" ? "Pass" : status === "attention" ? "Attention" : "Fail",
          score: imgScore,
          verdict: `${imgOpt.total_images ?? 0} unique image(s) · ${imgOpt.modern_images ?? 0} WebP/AVIF · ${imgOpt.lazy_images ?? 0} lazy-loaded · ${imgOpt.missing_dimensions ?? 0} missing dimensions.`,
          checks: (imgOpt.checks || []).map(c => ({ passed: !!c.passed, label: c.label, detail: c.detail })),
        };
      })()
    : { status: "na", label: "Not run", verdict: "Image-optimization audit not run for this job.", score: null }));

  const sm = sitemap || nested.sitemap || {};
  cards.push(auditCard("Sitemap", sitemap || nested.sitemap
    ? (() => {
        const found = sm.sitemap_found ?? sm.found ?? false;
        const valid = sm.sitemap_valid ?? sm.valid ?? false;
        const coverage = sm.crawled_coverage ?? (sm.crawled_in_sitemap && sm.pages_in_sitemap ? Math.round(100 * sm.crawled_in_sitemap / sm.pages_in_sitemap) : null);
        const status = !found ? "fail" : !valid ? "attention" : coverage !== null && coverage < 60 ? "attention" : "pass";
        return {
          status, label: !found ? "Fail" : status === "pass" ? "Pass" : "Attention",
          score: !found ? 0 : valid ? (coverage ?? 100) : 40,
          verdict: !found
            ? "No XML sitemap found — create one and submit it in Search Console."
            : `${sm.url_count ?? sm.pages_in_sitemap ?? 0} URL(s) listed${coverage !== null ? ` · ${coverage}% crawled coverage` : ""}${valid ? "" : " · sitemap markup invalid"}.`,
          detail: `${sm.uncrawled_urls_count ?? 0} listed URL(s) not crawled`,
        };
      })()
    : { status: "na", label: "Not run", verdict: "Sitemap audit not run for this job.", score: null }));

  const aiScore = aiVis?.score;
  cards.push(auditCard("AI Visibility", aiVis && aiScore !== undefined && aiScore !== null
    ? (() => {
        const status = scoreFrom(aiScore) || "attention";
        return {
          status, label: status === "pass" ? "Pass" : status === "attention" ? "Attention" : "Fail",
          score: aiScore,
          verdict: `${(aiVis.blocked_ai_agents || []).length} AI crawler(s) blocked · llms.txt: ${aiVis.llms_txt_present ? "present" : "absent"} · sitemap: ${aiVis.sitemap_valid ? "valid" : "invalid/missing"}.`,
          checks: (aiVis.checks || []).slice(0, 8).map(c => ({ passed: !!c.passed, label: c.label || c.check, detail: c.detail })),
        };
      })()
    : { status: "na", label: "Not run", verdict: "AI-visibility audit not run for this job.", score: null }));

  const localScore = local?.score;
  cards.push(auditCard("Local SEO", local && localScore !== undefined && localScore !== null
    ? (() => {
        const status = scoreFrom(localScore) || "attention";
        return {
          status, label: status === "pass" ? "Pass" : status === "attention" ? "Attention" : "Fail",
          score: localScore,
          verdict: `LocalBusiness schema: ${local.local_business_on_homepage ? "on homepage" : "not on homepage"} · NAP consistent: ${local.nap_inconsistent ? "no" : "yes"} · geo signals: ${(local.geo_pages ?? 0)} page(s).`,
          checks: (local.checks || []).slice(0, 8).map(c => ({ passed: !!c.passed, label: c.label || c.check, detail: c.detail })),
        };
      })()
    : { status: "na", label: "Not run", verdict: "Local-SEO audit not run for this job.", score: null }));

  const blChecked = links?.total_links_scanned ?? links?.links_checked ?? 0;
  const blBroken = links?.broken_link_count ?? 0;
  const blRate = blChecked ? Math.round(100 * blBroken / blChecked) : null;
  cards.push(auditCard("Broken Links", links && blChecked
    ? {
        status: blBroken === 0 ? "pass" : blRate > 10 ? "fail" : "attention",
        label: blBroken === 0 ? "Pass" : blRate > 10 ? "Fail" : "Attention",
        score: blRate !== null ? Math.max(0, 100 - blRate * 2) : null,
        verdict: blBroken === 0
          ? `All ${blChecked} checked links resolve.`
          : `${blBroken} of ${blChecked} checked link(s) are broken (${blRate}%) — fix or redirect them.`,
        detail: `${links.total_link_occurrences ?? blChecked} total link occurrences on the site`,
      }
    : { status: "na", label: "Not checked", verdict: "Link health not checked for this job.", score: null }));

  return `<div class="audit-grid">${cards.join("")}</div>`;
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
    const lastChecked = document.getElementById("insights-last-checked");
    if (lastChecked) {
      lastChecked.textContent = data.last_fetched
        ? "Last checked: " + new Date(data.last_fetched).toLocaleString()
        : "Last checked: just now";
    }
    renderKeywords(data.keywords || [], data.keywords_error, data.keywords_source);
    renderBacklinks(data.backlinks, data.backlinks_error, data.backlinks_source);
    renderDomainOverview(data.overview, data.overview_error, data.overview_source);
    renderOverviewHistory(data.overview_history || [], data.overview_history_error);
    renderCompetitors(data.competitors || [], data.competitors_error);
    renderBacklinkProfile(data);
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
        <div class="insights-label">${escapeHtml(k.keyword || "")}${k.site_derived ? ' <span class="kws-site-chip" title="Derived from your site\'s own URL slugs, titles and product pages">site term</span>' : ""}</div>
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

function sparkline(values, w, h) {
  const nums = (values || []).map(Number).filter(v => Number.isFinite(v));
  if (nums.length < 2) return '<span class="count-label">—</span>';
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const step = w / (nums.length - 1);
  const pts = nums.map((v, i) =>
    `${(i * step).toFixed(1)},${(h - 3 - ((v - min) / span) * (h - 6)).toFixed(1)}`).join(" ");
  return `<svg class="sparkline" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="traffic trend">
    <polyline points="${pts}" fill="none" stroke="var(--primary)" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

function renderOverviewHistory(rows, error) {
  const el = document.getElementById("overview-history");
  if (!el) return;
  let html = "";
  if (error && !rows.length) html += insightErrorHtml(error);
  if (rows.length) {
    const traffic = rows.map(r => Number(r.traffic_sum)).filter(v => Number.isFinite(v));
    html += `<p class="source-note">Monthly organic traffic & keyword history (SE Ranking)${traffic.length > 1 ? " — line shows the traffic trend" : ""}</p>`;
    if (traffic.length > 1) {
      html += `<div style="margin:8px 0 12px">${sparkline(traffic, 320, 54)}</div>`;
    }
    html += `<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Month</th><th>Organic Traffic</th><th>Organic Keywords</th><th>Est. Value</th></tr></thead><tbody>${rows.map(r => `<tr>
      <td>${escapeHtml(r.month)}</td>
      <td>${r.traffic_sum ?? "-"}</td>
      <td>${r.keywords_count ?? "-"}</td>
      <td>${r.price_sum != null ? "$" + Number(r.price_sum).toLocaleString() : "-"}</td>
    </tr>`).join("")}</tbody></table></div>`;
    if (error) html += insightWarningHtml(error);
  } else if (!error) {
    html = '<div class="insights-card">No overview history available.</div>';
  }
  el.innerHTML = html;
}

function renderCompetitors(rows, error) {
  const el = document.getElementById("competitors-list");
  if (!el) return;
  let html = "";
  if (error && !rows.length) html += insightErrorHtml(error);
  if (rows.length) {
    html += `<p class="source-note">Top organic competitors — SE Ranking domains plus the competitors you track in the Competitors tab (marked "tracked").</p>`;
    html += rows.slice(0, 12).map(c => {
      const tracked = !!c.tracked;
      const chips = (c.shared_keywords || []).slice(0, 8);
      const chipHtml = chips.length
        ? `<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px">${chips.map(s => `<span class="keyword-chip">${escapeHtml(String(s).substring(0, 34))}</span>`).join("")}</div>`
        : "";
      const noOverlap = !chips.length && !(c.common_keywords > 0);
      const overlapNote = noOverlap
        ? `<div class="insights-value" style="font-size:11px;color:#b45309;margin-top:4px">No keyword-overlap data — not verified as an organic competitor; check the Competitors tab.</div>`
        : "";
      const statusBadge = tracked && c.status
        ? `<span class="badge" style="${c.status === "blocked" ? "background:#fef3c7;color:#92400e" : c.status === "partial" ? "background:#fef3c7;color:#92400e" : "background:#dcfce7;color:#15803d"}">${escapeHtml(c.status)}</span>`
        : "";
      return `<div class="insights-card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap">
          <span class="insights-label" style="margin:0">${escapeHtml(c.domain)}${tracked ? ' <span class="badge" style="background:rgba(99,102,241,.12);color:#6366f1">tracked</span>' : ""}</span>
          ${statusBadge}
        </div>
        <div class="insights-value" title="Keyword overlap">${c.common_keywords ?? "N/A"} shared keywords</div>
        ${tracked ? "" : `<div class="insights-value">Relevance: ${c.domain_relevance != null ? c.domain_relevance + "%" : "N/A"}</div>
        <div class="insights-value">Traffic: ${c.traffic_sum != null ? Number(c.traffic_sum).toLocaleString() : "N/A"}</div>`}
        ${overlapNote}
        ${chipHtml}
      </div>`;
    }).join("");
    if (error) html += insightWarningHtml(error);
  } else if (!error) {
    html = '<div class="insights-card">No competitor data available.</div>';
  }
  el.innerHTML = html;
}

function renderBacklinkProfile(data) {
  renderBacklinkAuthority(data.backlink_authority, data.backlink_authority_error);
  renderBacklinkTable("backlink-refdomains", "Referring domains by authority", ["domain_inlink_rank", "backlinks"],
    data.backlink_refdomains || [], data.backlink_refdomains_error,
    r => `<a href="https://${escapeHtml(r.refdomain)}" target="_blank" rel="noopener">${escapeHtml(r.refdomain)}</a>`);
  renderBacklinkTable("backlink-anchors", "Most-used anchor texts", ["backlinks", "refdomains"],
    data.backlink_anchors || [], data.backlink_anchors_error,
    r => escapeHtml((r.anchor || "-").substring(0, 80)), "Anchor Text");
  renderBacklinkTable("backlink-top-pages", "Top pages by backlinks", ["backlinks", "refdomains"],
    data.backlink_top_pages || [], data.backlink_top_pages_error,
    r => linkify(r.url, 70), "Page");
  renderAuthorityHistory(data.authority_history || [], data.authority_history_error);
  renderBacklinkNewLost(data.backlink_new_lost || [], data.backlink_new_lost_error, data.backlink_new_lost_counts || []);
}

function renderBacklinkAuthority(auth, error) {
  const el = document.getElementById("backlink-authority");
  if (!el) return;
  let html = "";
  if (error && !auth) html += insightErrorHtml(error);
  if (auth) {
    html += `<p class="source-note">Domain & page authority (SE Ranking InLink Rank)</p>`;
    html += `<div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
      <div class="insights-card"><div class="insights-label">Domain Authority</div><div class="insights-value">${auth.domain_rank ?? "N/A"}</div></div>
      <div class="insights-card"><div class="insights-label">Page Authority</div><div class="insights-value">${auth.page_rank ?? "N/A"}</div></div>
    </div>`;
    if (error) html += insightWarningHtml(error);
  } else if (!error) {
    html = '<div class="insights-card">No authority data available.</div>';
  }
  el.innerHTML = html;
}

function renderAuthorityHistory(rows, error) {
  const el = document.getElementById("authority-history");
  if (!el) return;
  let html = "";
  if (error && !rows.length) html += insightErrorHtml(error);
  if (rows.length) {
    html += `<p class="source-note">Domain authority history (monthly, SE Ranking)</p>`;
    html += `<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Month</th><th>Domain Authority</th></tr></thead><tbody>${rows.slice(0, 12).map(r => `<tr>
      <td>${escapeHtml(r.date)}</td>
      <td>${r.domain_rank ?? "-"}</td>
    </tr>`).join("")}</tbody></table></div>`;
    if (error) html += insightWarningHtml(error);
  } else if (!error) {
    html = '<div class="insights-card">No authority history available.</div>';
  }
  el.innerHTML = html;
}

function renderBacklinkNewLost(rows, error, counts) {
  const el = document.getElementById("backlink-new-lost");
  if (!el) return;
  let html = "";
  if (error && !rows.length) html += insightErrorHtml(error);
  if (rows.length) {
    const totalNew = counts.reduce((s, c) => s + (c.new || 0), 0);
    const totalLost = counts.reduce((s, c) => s + (c.lost || 0), 0);
    html += `<p class="source-note">New & lost backlinks over the last 30 days (SE Ranking)${counts.length ? ` — <strong>${totalNew} new / ${totalLost} lost</strong>` : ""}</p>`;
    html += `<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Date</th><th>Type</th><th>Source</th><th>Target</th><th>Anchor</th><th>Reason</th></tr></thead><tbody>${rows.slice(0, 50).map(b => `<tr>
      <td>${escapeHtml(b.date || "-")}</td>
      <td><span class="status-chip ${b.type === "new" ? "chip-pass" : "chip-attention"}">${escapeHtml(b.type || "-")}</span></td>
      <td class="page-url-cell" title="${escapeHtml(b.url_from)}">${linkify(b.url_from, 55)}</td>
      <td class="page-url-cell" title="${escapeHtml(b.url_to)}">${linkify(b.url_to, 40)}</td>
      <td>${escapeHtml((b.anchor || "-").substring(0, 50))}</td>
      <td>${escapeHtml(b.reason_lost || "-")}</td>
    </tr>`).join("")}</tbody></table></div>`;
    if (counts.length) {
      html += `<div style="overflow-x:auto;margin-top:10px"><table class="data-table"><thead><tr><th>Date</th><th>New</th><th>Lost</th></tr></thead><tbody>${counts.slice(0, 30).map(c => `<tr>
        <td>${escapeHtml(c.date)}</td>
        <td>${c.new ?? 0}</td>
        <td>${c.lost ?? 0}</td>
      </tr>`).join("")}</tbody></table></div>`;
    }
    if (error) html += insightWarningHtml(error);
  } else if (!error) {
    html = '<div class="insights-card">No new/lost backlink activity in the last 30 days.</div>';
  }
  el.innerHTML = html;
}

function renderBacklinkTable(elId, title, extraCols, rows, error, cellRender, firstLabel) {
  const el = document.getElementById(elId);
  if (!el) return;
  let html = "";
  if (error && !rows.length) html += insightErrorHtml(error);
  if (rows.length) {
    html += `<p class="source-note">${escapeHtml(title)} (SE Ranking)</p>`;
    const cols = [firstLabel || "Domain", ...extraCols.map(c => c.replace(/_/g, " "))];
    html += `<div style="overflow-x:auto"><table class="data-table"><thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead><tbody>`;
    for (const r of rows) {
      const cells = extraCols.map(c => `<td>${r[c] ?? "-"}</td>`).join("");
      html += `<tr><td>${cellRender(r)}</td>${cells}</tr>`;
    }
    html += `</tbody></table></div>`;
    if (error) html += insightWarningHtml(error);
  } else if (!error) {
    html = '<div class="insights-card">No data available.</div>';
  }
  el.innerHTML = html;
}

function renderOnpage(op, error, source) {
  const el = document.getElementById("onpage-summary");
  if (!el) return;
  const entries = op ? Object.entries(op).filter(([k]) => !["source"].includes(k)) : null;
  const imageKeys = ["images_total", "images_missing_alt", "pages_with_images"];
  let html = "";
  if (error && !op) {
    html += `<p class="source-note">Source: ${sourceLabel(source)}</p>`;
    html += insightErrorHtml(error);
  }
  if (op) {
    html += `<p class="source-note">Source: ${sourceLabel(source || op.source)}</p>`;
    const total = op.images_total ?? null;
    const missing = op.images_missing_alt ?? null;
    const pagesWith = op.pages_with_images ?? null;
    const altShare = (typeof total === "number" && typeof missing === "number")
      ? (total > 0 ? Math.max(0, Math.round(100 * (1 - missing / total))) : 100)
      : null;
    const imgCards = [
      ["Images (unique)", total],
      ["Missing alt text", missing],
      ["Alt text coverage", altShare != null ? altShare + "%" : null],
      ["Pages with images", pagesWith],
    ].map(([lbl, val]) => `<div class="insights-card">
      <div class="insights-label">${escapeHtml(lbl)}</div>
      <div class="insights-value">${val === null || val === undefined ? "N/A" : escapeHtml(String(val))}</div>
    </div>`).join("");
    html += `<h4 style="margin:0 0 8px">Image accessibility</h4>
      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">${imgCards}</div>`;
    const rest = entries.filter(([k]) => !imageKeys.includes(k));
    if (rest.length) {
      html += `<h4 style="margin:16px 0 8px">Page signals</h4>
        <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
          ${rest.map(([k, v]) => `
            <div class="insights-card">
              <div class="insights-label">${escapeHtml(k.replace(/_/g, " "))}</div>
              <div class="insights-value">${typeof v === "number" ? v : escapeHtml(String(v ?? "N/A").substring(0, 60))}</div>
            </div>`).join("")}
        </div>`;
    }
    if (error) html += insightWarningHtml(error);
  } else if (!error) {
    html = '<div class="insights-card">No on-page data available.</div>';
  }
  el.innerHTML = html;
}

function renderSerp(rankings, error, source) {
  const el = document.getElementById("serp-rankings");
  const errMsg = String(error || "");
  let html = "";
  if (!rankings.length && error) {
    if (insightErrorKind(error).kind === "credits") {
      html += `<div class="service-error" style="background:#fffbeb;border-color:#fde68a">
        <div class="service-error-title" style="color:#92400e">SERP API unavailable (no credits)</div>
        <div class="service-error-msg" style="color:#78350f">Rankings couldn't be fetched and no local fallback is available. Add a valid serp_api_key or top up SERP API credits.</div>
      </div>`;
    } else {
      html += serviceErrorHtml("SERP API", errMsg);
    }
  }
  if (rankings.length) {
    html += `<p class="source-note">Source: ${sourceLabel(source)} — rankings for keywords extracted from your content</p>`;
    html += rankings.map(r => `
      <div class="insights-card" style="margin-top:8px">
        <strong>${escapeHtml(r.keyword || "")}</strong> — Rank: ${r.rank ?? "Not in top 100"} | Total Results: ${r.total_results ?? "N/A"}
        ${r.top_results && r.top_results.length ? r.top_results.slice(0, 3).map(t => `<div style="font-size:13px;margin-top:4px">#${t.position}: <a href="${escapeHtml(t.url)}" target="_blank" rel="noopener">${escapeHtml(t.title)}</a></div>`).join("") : ""}
      </div>`).join("");
    if (error) html += insightWarningHtml(error);
  }
  if (!rankings.length && !error) {
    html += '<div class="insights-card">No SERP ranking data available. Use "Suggest Keywords" to add keywords.</div>';
  }
  el.innerHTML = html;
}

function _fmtNum(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return v.toLocaleString();
  return String(v);
}

function _fmtMoney(v) {
  if (v === null || v === undefined || v === "") return "—";
  return "$" + Number(v).toLocaleString();
}

function _oppBadge(score) {
  if (score === null || score === undefined) return '<span class="badge">No score</span>';
  const cls = score >= 60 ? "background:#dcfce7;color:#15803d" : score >= 40 ? "background:#fef3c7;color:#b45309" : "background:#fee2e2;color:#b91c1c";
  return `<span class="badge" style="${cls}">Opportunity ${score}/100</span>`;
}

function _pairRow(label, target, comp) {
  const t = _fmtNum(target), c = _fmtNum(comp);
  let status = "—";
  if (typeof target === "number" && typeof comp === "number") {
    status = comp > target ? "competitor ahead" : target > comp ? "you lead" : "tie";
  }
  return `<tr><td style="text-align:left">${escapeHtml(label)}</td><td>${t}</td><td>${c}</td><td>${status}</td></tr>`;
}

function _deltaCard(label, value) {
  let inner = "—";
  if (value && typeof value === "object") {
    inner = `You: ${_fmtNum(value.target)} · They: ${_fmtNum(value.competitor)}`;
    if (value.delta !== undefined && value.delta !== "n/a" && value.delta !== null) {
      const d = Number(value.delta);
      const pos = d >= 0;
      inner += ` <span class="badge" style="background:${pos ? "#dcfce7" : "#fee2e2"};color:${pos ? "#15803d" : "#b91c1c"}">Δ ${pos ? "+" : ""}${_fmtNum(d)}</span>`;
    }
  } else if (typeof value === "number") {
    inner = _fmtNum(value);
  }
  return `<div class="insights-card" style="font-size:13px"><strong>${escapeHtml(label)}</strong><div style="opacity:.85">${inner}</div></div>`;
}

function _deltaGrid(obj) {
  if (!obj) return "";
  return `<div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin:8px 0">${
    Object.entries(obj).filter(([k]) => k !== "sitemap").map(([k, v]) => _deltaCard(k, v)).join("")
  }</div>`;
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
    if (status === "running") {
      const err = (c.errors || []).filter(Boolean).join("; ");
      return `<div class="insights-card"><h4>${escapeHtml(c.competitor)}</h4><div class="insights-label">Analyzing... (${escapeHtml(c.pages_crawled || 0)} pages so far — big sites can take ~20 min)</div>${err ? `<div class="insights-error" style="margin-top:6px">${escapeHtml(err)}</div>` : ""}</div>`;
    }
    if (status === "error") return `<div class="insights-card"><h4>${escapeHtml(c.competitor)}</h4><div class="insights-error">${escapeHtml((c.errors || []).join("; "))}</div><button class="btn-secondary" style="margin-top:8px" onclick="retryCompetitor('${escapeHtml(c.competitor)}')">Retry</button></div>`;

    const sr = c.se_rich || {};
    const ka = sr.keyword_analysis || {};
    const ta = sr.traffic_analysis || {};
    const ba = sr.backlink_analysis || {};
    const aa = sr.authority_analysis || {};
    const recs = sr.recommendations || [];
    const errs = (sr.errors || c.errors || []).filter(Boolean);
    const opp = sr.opportunity_score;
    const tTraffic = ta.target_traffic;
    const cTraffic = ta.competitor_traffic;
    const tKws = ta.target_keywords;
    const cKws = ta.competitor_keywords;

    const kpis = [
      ["Opportunity score", _oppBadge(opp)],
      ["Competitor pages crawled", _fmtNum(c.pages_crawled)],
      ["Est. organic traffic", `${_fmtNum(tTraffic)} → ${_fmtNum(cTraffic)}`],
      ["Organic keywords", `${_fmtNum(tKws)} → ${_fmtNum(cKws)}`],
      ["Gap count", _fmtNum(c.gap_count)],
    ].map(([lbl, val]) => `<div class="insights-card"><div class="insights-label">${escapeHtml(lbl)}</div><div class="insights-value">${val}</div></div>`).join("");

    const trafficRows = [
      _pairRow("Organic traffic", tTraffic, cTraffic),
      _pairRow("Organic keywords", tKws, cKws),
      _pairRow("Est. traffic value", null, ta.traffic_value_estimate),
    ].join("");

    const kwRows = (ka.top_opportunities || []).slice(0, 10)
      .map(k => `<tr><td style="text-align:left">${escapeHtml(k.keyword)}</td><td>${_fmtNum(k.volume)}</td><td>${_fmtMoney(k.cpc)}</td><td>${_fmtNum(k.difficulty)}</td></tr>`).join("");
    const sharedRows = (ka.shared_detail || []).slice(0, 10)
      .map(s => `<tr><td style="text-align:left">${escapeHtml(s.keyword)}</td><td>${_fmtNum(s.comp ? s.comp.volume : null)}</td><td>${_fmtNum(s.target ? s.target.volume : null)}</td></tr>`).join("");
    const serpWords = (c.keyword_gap && c.keyword_gap.gaps || []).slice(0, 15);

    const tBl = ba.target || {};
    const cBl = ba.competitor || {};
    const abRows = [
      _pairRow("Backlinks", tBl.backlinks, cBl.backlinks),
      _pairRow("Referring domains", tBl.referring_domains, cBl.referring_domains),
      _pairRow("Domain authority", aa.target_domain_rank, aa.comp_domain_rank),
      _pairRow("Page authority", aa.target_page_rank, aa.comp_page_rank),
    ].join("");

    const contentMissing = (c.content_gap && c.content_gap.missing || []).slice(0, 10);
    const schemaMissing = (c.schema_gap && c.schema_gap.missing_from_target || []).slice(0, 10);
    const highAuth = (ba.high_authority_sources || []).slice(0, 8);
    const blSerp = (c.backlink_gap && c.backlink_gap.gaps || []).slice(0, 10);
    const featureEntries = Object.entries(c.serp_features_gap && c.serp_features_gap.comp_only || {}).slice(0, 10);

    const techCards = _deltaGrid(c.technical_gap);
    const onpageCards = _deltaGrid(c.onpage_gap);
    const uxCards = _deltaGrid(c.ux_gap);

    const recsHtml = recs.map(r => `<div class="insights-card" style="border-left:3px solid ${r.priority === "high" ? "#dc2626" : r.priority === "medium" ? "#d97706" : "#6b7280"};margin-top:6px">
      <strong>${escapeHtml(r.title)}</strong>${r.count != null ? ` <span class="badge">${_fmtNum(r.count)}</span>` : ""}
      <div style="font-size:13px;opacity:.9;margin-top:4px">${escapeHtml(r.detail)}</div>
    </div>`).join("");

    const blockedNote = status === "blocked"
      ? `<div class="insights-error" style="margin-top:6px">Crawl blocked — robots.txt/sitemap.xml returned 403; report below is SE Ranking + SERP data only. <button class="btn-secondary" style="margin-top:4px" onclick="retryCompetitor('${escapeHtml(c.competitor)}')">Retry</button></div>`
      : status === "partial"
        ? `<div class="insights-error" style="margin-top:6px">Partial crawl — analysis timed out before every page was measured; results below cover the ${_fmtNum(c.pages_crawled)} page(s) fetched plus SE Ranking + SERP data. <button class="btn-secondary" style="margin-top:4px" onclick="retryCompetitor('${escapeHtml(c.competitor)}')">Retry</button></div>`
        : "";

    return `<div class="insights-card" style="margin-top:12px">
      ${status === "blocked" ? '<div style="display:inline-block;background:#fef3c7;border:1px solid #f59e0b;color:#92400e;font-size:12px;font-weight:600;border-radius:4px;padding:3px 8px;margin-bottom:8px">Blocked crawl — partial report</div>' : ""}
      ${status === "partial" ? '<div style="display:inline-block;background:#fef3c7;border:1px solid #f59e0b;color:#92400e;font-size:12px;font-weight:600;border-radius:4px;padding:3px 8px;margin-bottom:8px">Partial crawl — timed out</div>' : ""}
      <h4 style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <span>${escapeHtml(c.competitor)} <span class="count-label">${_fmtNum(c.pages_crawled)} pages</span></span>
        <span>${_oppBadge(opp)}</span>
      </h4>
      ${blockedNote}

      <div class="insights-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:10px 0">${kpis}</div>

      <h5 style="margin:14px 0 6px">Keyword Analysis</h5>
      <div class="insights-card">
        <div class="insights-label">Top opportunities — they rank, you don't (by volume)</div>
        ${kwRows ? `<table class="data-table" style="width:100%"><thead><tr><th style="text-align:left">Keyword</th><th>Volume</th><th>CPC</th><th>Difficulty</th></tr></thead><tbody>${kwRows}</tbody></table>` : '<div class="insights-label">No SE Ranking keyword data available</div>'}
        ${sharedRows ? `<div class="insights-label" style="margin-top:10px">Overlap — keywords you both rank for</div><table class="data-table" style="width:100%"><thead><tr><th style="text-align:left">Keyword</th><th>Competitor vol</th><th>Your vol</th></tr></thead><tbody>${sharedRows}</tbody></table>` : ""}
        ${serpWords.length ? `<div class="insights-label" style="margin-top:10px">SERP-derived keywords they rank for</div><div style="font-size:13px;margin-top:4px">${serpWords.map(k => `<a href="https://www.google.com/search?q=${encodeURIComponent(k)}" target="_blank" rel="noopener">${escapeHtml(k)}</a>`).join(" · ")}</div>` : ""}
      </div>

      <h5 style="margin:14px 0 6px">Traffic</h5>
      <div class="insights-card"><table class="data-table" style="width:100%">
        <thead><tr><th style="text-align:left">Metric</th><th>You</th><th>Competitor</th><th>Status</th></tr></thead>
        <tbody>${trafficRows}</tbody></table>
      </div>

      <h5 style="margin:14px 0 6px">Backlinks &amp; Authority</h5>
      <div class="insights-card"><table class="data-table" style="width:100%">
        <thead><tr><th style="text-align:left">Metric</th><th>You</th><th>Competitor</th><th>Status</th></tr></thead>
        <tbody>${abRows}</tbody></table>
        ${highAuth.length ? `<div class="insights-label" style="margin-top:10px">Strong-authority sources they link from (top ${highAuth.length}):</div><div style="font-size:13px;margin-top:4px">${highAuth.map(s => `• ${escapeHtml(s.source_domain || s)}`).join(" ")}</div>` : ""}
        ${blSerp.length ? `<div class="insights-label" style="margin-top:10px">SERP-derived backlink sources they have that you don't:</div><div style="font-size:13px;margin-top:4px">${blSerp.map(d => `• ${escapeHtml(d)}`).join(" ")}</div>` : ""}
      </div>

      <h5 style="margin:14px 0 6px">Content</h5>
      <div class="insights-card">
        ${contentMissing.length ? `<div class="insights-label">Pages they have that you don't (top ${contentMissing.length}):</div><div style="font-size:13px;margin-top:4px">${contentMissing.map(m => `• <a href="${escapeHtml(m.url)}" target="_blank" rel="noopener">${escapeHtml(m.title)}</a>`).join("<br>")}</div>` : '<div class="insights-label">No content gaps detected in this crawl</div>'}
        ${schemaMissing.length ? `<div class="insights-label" style="margin-top:8px">Schema types on their pages missing from yours:</div><div style="font-size:13px;margin-top:4px">${schemaMissing.map(t => `• ${escapeHtml(t)}`).join(" ")}</div>` : ""}
      </div>

      <h5 style="margin:14px 0 6px">SERP Features</h5>
      <div class="insights-card">${featureEntries.length ? featureEntries.map(([kw, feats]) => `<div style="font-size:13px;margin-top:4px"><strong>${escapeHtml(kw)}</strong> → ${escapeHtml((feats || []).join(", "))}</div>`).join("") : '<div class="insights-label">No SERP feature gaps detected</div>'}</div>

      <h5 style="margin:14px 0 6px">Technical / On-page / UX (competitor − you)</h5>
      ${techCards}
      ${onpageCards}
      ${uxCards}

      ${recsHtml ? `<h5 style="margin:16px 0 6px">Insights &amp; Recommendations</h5>${recsHtml}` : ""}
      ${errs.length ? `<div class="insights-error" style="margin-top:10px">${errs.map(e => escapeHtml(e)).join("; ")}</div>` : ""}
      <div class="count-label" style="margin-top:10px">Data: SE Ranking (live competitor metrics) + local crawl. Generated ${c.generated_at ? new Date(String(c.generated_at)).toLocaleString() : "recently"}.</div>
    </div>`;
  }).join("");
}

function renderCompetitorStatus(rows) {
  return rows.some(r => ["queued", "running"].includes(r.status));
}

let competitorPollDeadline = 0;

function retryCompetitor(domain) {
  if (!currentJobId) return;
  const input = document.getElementById("competitor-input");
  if (input) input.value = domain;
  document.getElementById("competitor-form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
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
    setTabBadge("competitors", (data.results || []).length);
    if (data.results && renderCompetitorStatus(data.results)) {
      if (!competitorPollDeadline) competitorPollDeadline = Date.now() + 60 * 60 * 1000;
      if (Date.now() < competitorPollDeadline) {
        setTimeout(() => loadCompetitors(jobId), 4000);
      } else {
        resultsEl.insertAdjacentHTML("beforeend", '<p class="insights-label" style="margin-top:8px">Polling stopped after 60 minutes — big sites can take up to ~20 min each; refresh to re-check live status.</p>');
      }
    } else {
      competitorPollDeadline = 0;
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
  resultsEl.innerHTML = '<div class="insights-label">Crawling every page of each competitor up to ~400 pages (HTTP-first, ~20 min cap each)...</div>';
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
      competitorPollDeadline = 0;
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
  if (currentJobId) {
    competitorPollDeadline = 0;
    loadCompetitors(currentJobId);
  }
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
    setTabBadge("sites", sites.length);
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
        if (!confirm(`Permanently delete ${url}?\n\nThis removes ALL data for this site: pages, content, action items, reports, downloads, insights and vectors. This cannot be undone.`)) return;
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

function openPastAnalyses() {
  stopPolling();
  currentJobId = null;
  hideProgress();
  resultsSection.classList.remove("hidden");
  inputSection.classList.add("hidden");
  resultsUrl.textContent = "Past Analyses";
  currentTab = "sites";
  updateRailExplain("sites");
  document.body.classList.add("jobless");
  setDashboardVisible(true);
  loadSites();
  switchTab('sites');
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
    setTabBadge("schedules", schedules.length);
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
  const alertsEl = document.getElementById("alerts-list");

  try {
    const alertsResp = await fetch(`${API_BASE}/logs/alerts`);
    const alerts = await alertsResp.json();

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
    setTabBadge("logs", failed.length + broken.length);
    [...failed, ...broken].slice(0, 3).forEach(a => {
      pushActivity("err", (a.url || a.domain || "") + " — " + String(a.error || a.last_error || "").slice(0, 140));
    });
  } catch (err) {
    alertsEl.innerHTML = `<div class="insights-card">Error: ${escapeHtml(err.message)}</div>`;
  }
}

document.getElementById("refresh-logs-btn")?.addEventListener("click", loadLogs);

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

const VALID_TABS = new Set(["sites", "overview", "pages", "content", "links", "actions", "report", "seo-insights", "competitors", "quality", "schedules", "logs", "settings", "sandbox-approvals", "sandbox-comparison", "style-guide"]);

function parseHash() {
  const m = window.location.hash.match(/^#job\/([a-zA-Z0-9-]+)(?:\/([a-z-]+))?/);
  if (!m) return null;
  return { jobId: m[1], tab: m[2] || null };
}

async function restoreFromHash() {
  const state = parseHash();
  if (!state) {
    const tab = (window.location.hash || "").replace(/^#/, "");
    if (tab === "sites") {
      openPastAnalyses();
    } else if (tab === "style-guide") {
      resultsSection.classList.remove("hidden");
      inputSection.classList.add("hidden");
      resultsUrl.textContent = "ZuiGO Style Guide";
      resultsStatus.textContent = "Internal style guide: design tokens, semantic status colors, tabular typography, and motion fallbacks.";
      document.body.classList.add("jobless");
      setDashboardVisible(true);
      switchTab("style-guide");
      initStyleGuideControls();
    } else if (tab === "sandbox-approvals") {
      resultsSection.classList.remove("hidden");
      inputSection.classList.add("hidden");
      resultsUrl.textContent = "Sandbox Approvals";
      resultsStatus.textContent = "Review and approve suggestions for the auto-apply sandbox.";
      document.body.classList.add("jobless");
      setDashboardVisible(true);
      switchTab("sandbox-approvals");
      loadSandboxApprovals();
    } else if (tab === "sandbox-comparison") {
      resultsSection.classList.remove("hidden");
      inputSection.classList.add("hidden");
      resultsUrl.textContent = "Sandbox Comparison";
      resultsStatus.textContent = "Page-level before/after comparison for sandbox changes.";
      document.body.classList.add("jobless");
      setDashboardVisible(true);
      const cmpTab = document.querySelector('.tab[data-tab="sandbox-comparison"]');
      if (cmpTab) { cmpTab.style.display = 'block'; cmpTab.click(); }
      loadSandboxComparison();
    } else {
      setDashboardVisible(false);
    }
    return;
  }
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

function formatInline(s) {
  return s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
          .replace(/(https?:\/\/[^\s<>"']+)/g, m => `<a href="${m}" target="_blank" rel="noopener noreferrer">${m}</a>`);
}

function renderBotBlock(lines) {
  const out = [];
  let group = [];
  const flush = () => {
    if (!group.length) return;
    const bullet = /^\s*[-*] /.test(group[0]);
    const items = group.map(l => {
      const item = bullet ? l.replace(/^\s*[-*] /, "") : l.replace(/^\d+\.\s/, "");
      return `<li>${formatInline(item)}</li>`;
    }).join("");
    out.push(`<${bullet ? "ul" : "ol"} class="chat-bullets">${items}</${bullet ? "ul" : "ol"}>`);
    group = [];
  };
  for (const line of lines) {
    if (/^\s*[-*] /.test(line) || /^\d+\.\s/.test(line)) {
      group.push(line);
    } else if (/^\s*#{1,3}\s/.test(line)) {
      flush();
      out.push(`<p class="chat-head"><strong>${formatInline(line.replace(/^\s*#{1,3}\s*/, ""))}</strong></p>`);
    } else {
      flush();
      out.push(`<p>${formatInline(line)}</p>`);
    }
  }
  flush();
  return out.join("");
}

function renderBotReply(text) {
  const raw = String(text || "").replace(/[\u202F\u00A0]/g, " ").replace(/\r\n/g, "\n");
  const esc = escapeHtml(raw);
  const blocks = esc.split(/\n{2,}/);
  return blocks.map(block => {
    const lines = block.split("\n").filter(l => l.trim() !== "");
    if (lines.length > 1 && lines.every(l => /^\s*\|/.test(l))) {
      const rows = lines.map(l => l.replace(/^\s*\|\s?/, "").replace(/\s?\|\s*$/, "").split("|").map(c => c.trim().replace(/\*\*/g, "")));
      const head = rows[0];
      const body = rows.slice(1);
      const thead = `<thead><tr>${head.map(c => `<th>${c}</th>`).join("")}</tr></thead>`;
      const tbody = `<tbody>${body.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody>`;
      return `<details class="chat-collapse"><summary>Full breakdown</summary><div class="table-container"><table class="chat-table">${thead}${tbody}</table></div></details>`;
    }
    return renderBotBlock(lines);
  }).join("");
}

// --- Sandbox Approvals ---

async function loadSandboxApprovals() {
  const container = document.getElementById("sandbox-approvals-queue");
  container.innerHTML = '<div class="skeleton-shimmer-row" style="height:100px"></div>'.repeat(3);
  try {
    const res = await fetch("/api/sandbox/suggestions");
    if (!res.ok) throw new Error("Failed to fetch suggestions");
    const data = await res.json();
    renderSandboxApprovals(data.suggestions);
  } catch (err) {
    container.innerHTML = `<div class="service-error">Error loading approvals: ${escapeHtml(err.message)}</div>`;
  }
}

function computeDiffHTML(oldText, newText) {
  if (oldText === newText) return escapeHtml(newText);
  return `
    <div style="margin-bottom:8px;"><span class="diff-del" style="background:#ffcdd2;color:#b71c1c;text-decoration:line-through;padding:2px 4px;border-radius:4px;">${escapeHtml(oldText || "(empty)")}</span></div>
    <div><span class="diff-add" style="background:#c8e6c9;color:#1b5e20;padding:2px 4px;border-radius:4px;">${escapeHtml(newText || "(empty)")}</span></div>
  `;
}

function renderSandboxApprovals(suggestions) {
  const container = document.getElementById("sandbox-approvals-queue");
  container.innerHTML = "";

  if (!suggestions || suggestions.length === 0) {
    container.innerHTML = `<div class="empty-state">No pending suggestions for the sandbox.</div>`;
    return;
  }

  const groups = {};
  suggestions.forEach(s => {
    if (!groups[s.field_type]) groups[s.field_type] = [];
    groups[s.field_type].push(s);
  });

  const lowRiskFields = ["alt_text", "canonical", "footer_copyright"];

  for (const [fieldType, items] of Object.entries(groups)) {
    const groupDiv = document.createElement("div");
    groupDiv.className = "approval-group card";
    groupDiv.style.padding = "20px";
    groupDiv.style.background = "var(--bg-surface)";
    groupDiv.style.borderRadius = "8px";
    groupDiv.style.border = "1px solid var(--border)";
    groupDiv.style.marginBottom = "16px";

    const isLowRisk = lowRiskFields.includes(fieldType);
    
    let html = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; border-bottom:1px solid var(--border); padding-bottom:12px;">
        <h3 style="margin:0; font-size:16px; text-transform:capitalize;">${escapeHtml(fieldType.replace('_', ' '))}</h3>
        ${isLowRisk ? `<button class="btn-primary" onclick="batchApproveSandboxSuggestions('${escapeHtml(fieldType)}')">Batch Approve</button>` : `<span class="badge" style="background:var(--bg-elevated); color:var(--text-secondary)">Individual Approval Required</span>`}
      </div>
      <div class="approval-items">
    `;

    items.forEach(item => {
      let statusHtml = `<span class="status-pill status-unchecked">${item.status || 'pending'}</span>`;
      if (item.status === 'approved, pending apply') statusHtml = `<span class="status-pill status-ok">approved, pending apply</span>`;
      else if (item.status === 'applied') statusHtml = `<span class="status-pill status-ok">applied</span>`;
      else if (item.status === 'rejected' || item.status === 'failed') statusHtml = `<span class="status-pill status-broken">${item.status}</span>`;

      let actionsHtml = "";
      if (!item.status || item.status === 'pending') {
        actionsHtml = `
          <button class="btn-primary" onclick="approveSandboxSuggestion('${item.id}')">✓ Approve</button>
          <button class="btn-secondary" onclick="editSandboxSuggestion('${item.id}')">✎ Edit</button>
          <button class="btn-danger" style="background:var(--status-broken); color:white; border:none; border-radius:4px; padding:6px 12px; cursor:pointer;" onclick="rejectSandboxSuggestion('${item.id}')">✕ Reject</button>
        `;
      } else if (item.status === 'approved, pending apply') {
        actionsHtml = `
          <button class="btn-primary" style="background:var(--accent); border-color:var(--accent);" onclick="applySandboxSuggestion('${item.id}', this)">🚀 Apply to Sandbox</button>
          <button class="btn-danger" style="background:var(--status-broken); color:white; border:none; border-radius:4px; padding:6px 12px; cursor:pointer;" onclick="rejectSandboxSuggestion('${item.id}')">✕ Reject</button>
        `;
      } else if (item.status === 'applied') {
        actionsHtml = `
          <button class="btn-secondary" onclick="rollbackSandboxSuggestion('${item.id}', this)">↩ Rollback</button>
        `;
        if (item.preview_url || item.last_commit_hash) { // Using the preview_url from DB if we returned it, or we might need to fetch from audit logs.
           actionsHtml += `<a href="${escapeHtml(item.preview_url || '#')}" target="_blank" class="btn-secondary" style="margin-left:8px; text-decoration:none;">View Preview</a>`;
        }
      } else if (item.status === 'failed') {
        actionsHtml = `
          <button class="btn-primary" style="background:var(--accent); border-color:var(--accent);" onclick="applySandboxSuggestion('${item.id}', this)">↻ Retry Apply</button>
        `;
      }

      html += `
        <div class="approval-item" id="suggestion-${item.id}" style="padding:16px; border:1px solid var(--border); border-radius:6px; margin-bottom:12px; background:var(--bg-base);">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
            <div class="diff-view" style="font-family:var(--font-mono); font-size:13px; line-height:1.5;">
              ${computeDiffHTML(item.current_value, item.suggested_value)}
            </div>
            <div class="status-badge">
              ${statusHtml}
            </div>
          </div>
          
          <div class="context-box" style="background:var(--bg-elevated); padding:12px; border-radius:6px; font-size:13px; margin-bottom:16px;">
            <div style="margin-bottom:8px"><strong>Rationale:</strong> ${escapeHtml(item.rationale)}</div>
            <div><strong>Evidence Source:</strong> <code style="background:var(--bg-base); padding:2px 4px; border-radius:4px;">${escapeHtml(item.evidence_source)}</code></div>
          </div>
          
          <div class="actions" style="display:flex; gap:8px;">
            ${actionsHtml}
          </div>
        </div>
      `;
    });

    html += `</div>`;
    groupDiv.innerHTML = html;
    container.appendChild(groupDiv);
  }
}

async function approveSandboxSuggestion(id) {
  try {
    const res = await fetch(`/api/sandbox/suggestions/${id}/approve`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to approve");
    showToast("Suggestion approved");
    updateSuggestionStatusUI(id, "approved, pending apply", "status-ok");
  } catch (err) {
    showToast(err.message, true);
  }
}

async function rejectSandboxSuggestion(id) {
  try {
    const res = await fetch(`/api/sandbox/suggestions/${id}/reject`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to reject");
    showToast("Suggestion rejected");
    updateSuggestionStatusUI(id, "rejected", "status-broken");
  } catch (err) {
    showToast(err.message, true);
  }
}

async function editSandboxSuggestion(id) {
  const newVal = prompt("Edit the suggested value:");
  if (newVal === null) return;
  try {
    const res = await fetch(`/api/sandbox/suggestions/${id}/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ suggested_value: newVal })
    });
    if (!res.ok) throw new Error("Failed to edit");
    showToast("Suggestion edited and approved");
    loadSandboxApprovals();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function batchApproveSandboxSuggestions(fieldType) {
  try {
    const res = await fetch(`/api/sandbox/suggestions/batch_approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field_type: fieldType })
    });
    if (!res.ok) throw new Error("Failed to batch approve");
    const data = await res.json();
    showToast(`Batch approved ${data.count} items`);
    loadSandboxApprovals();
  } catch (err) {
    showToast(err.message, true);
  }
}

function updateSuggestionStatusUI(id, text, colorClass) {
  const el = document.getElementById(`suggestion-${id}`);
  if (!el) return;
  const badge = el.querySelector(".status-pill");
  if (badge) {
    badge.className = `status-pill ${colorClass}`;
    badge.textContent = text;
  }
  const actions = el.querySelector(".actions");
  if (actions) {
    // Simply reload to get updated action buttons rather than messing with DOM
    loadSandboxApprovals();
  }
}

async function applySandboxSuggestion(id, btnEl) {
  if (btnEl) btnEl.textContent = "Applying (Deploying)...";
  if (btnEl) btnEl.disabled = true;
  try {
    const res = await fetch(`/api/sandbox/suggestions/${id}/apply`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to apply");
    showToast("Suggestion applied and deployed to Sandbox!");
    loadSandboxApprovals();
  } catch (err) {
    showToast(err.message, true);
    loadSandboxApprovals();
  }
}

async function rollbackSandboxSuggestion(id, btnEl) {
  if (btnEl) btnEl.textContent = "Rolling back...";
  if (btnEl) btnEl.disabled = true;
  try {
    const res = await fetch(`/api/sandbox/suggestions/${id}/rollback`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to rollback");
    showToast("Suggestion rolled back successfully!");
    loadSandboxApprovals();
  } catch (err) {
    showToast(err.message, true);
    loadSandboxApprovals();
  }
}

async function loadSandboxComparison() {
  const loading = document.getElementById('sandbox-comparison-loading');
  const error = document.getElementById('sandbox-comparison-error');
  const content = document.getElementById('sandbox-comparison-content');
  
  loading.style.display = 'block';
  error.classList.add('hidden');
  content.classList.add('hidden');
  
  try {
    const response = await fetch('/api/sandbox/comparison');
    if (!response.ok) {
      throw new Error(`Failed to load comparison: ${response.statusText}`);
    }
    const data = await response.json();
    
    // Set images
    document.getElementById('comp-img-baseline').src = `data:image/jpeg;base64,${data.baseline_screenshot}`;
    document.getElementById('comp-img-current').src = `data:image/jpeg;base64,${data.current_screenshot}`;
    
    // Set scores
    const oldScore = data.seo_score.old;
    const newScore = data.seo_score.new;
    const delta = data.seo_score.delta;
    
    document.getElementById('comp-score-old').textContent = oldScore;
    document.getElementById('comp-score-new').textContent = newScore;
    
    const deltaEl = document.getElementById('comp-score-delta');
    if (delta > 0) {
      deltaEl.textContent = `+${delta} Points`;
      deltaEl.style.background = '#dcfce7';
      deltaEl.style.color = '#166534';
    } else if (delta < 0) {
      deltaEl.textContent = `${delta} Points`;
      deltaEl.style.background = '#fee2e2';
      deltaEl.style.color = '#991b1b';
    } else {
      deltaEl.textContent = 'No Change';
      deltaEl.style.background = '#f3f4f6';
      deltaEl.style.color = '#374151';
    }
    
    // Set fields table
    const tbody = document.getElementById('comp-fields-tbody');
    tbody.innerHTML = '';
    
    for (const f of data.field_comparison) {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid var(--border-color)';
      
      const badgeColor = f.is_changed ? '#dcfce7' : '#f3f4f6';
      const badgeTextColor = f.is_changed ? '#166534' : '#374151';
      const statusText = f.is_changed ? 'Changed' : 'Unchanged';
      
      const diffStyle = f.is_changed ? 'background:#dcfce7; padding:2px 4px; border-radius:4px;' : '';
      
      tr.innerHTML = `
        <td style="padding: 12px 16px; font-weight: 500; text-transform: capitalize;">${f.field.replace('_', ' ')}</td>
        <td style="padding: 12px 16px; color: var(--text-muted); font-size: 13px;">${escapeHtml(f.old_value || 'None')}</td>
        <td style="padding: 12px 16px; font-size: 13px;"><span style="${diffStyle}">${escapeHtml(f.new_value || 'None')}</span></td>
        <td style="padding: 12px 16px;">
          <span style="background:${badgeColor}; color:${badgeTextColor}; padding:4px 8px; border-radius:12px; font-size:12px; font-weight:500;">
            ${statusText}
          </span>
        </td>
      `;
      tbody.appendChild(tr);
    }
    
    // Set raw history
    const historyContainer = document.getElementById('comp-raw-history');
    historyContainer.innerHTML = '';
    
    if (data.raw_history.length === 0) {
      historyContainer.innerHTML = '<div style="color:var(--text-muted); font-size:13px; text-align:center; padding: 24px;">No apply history found.</div>';
    } else {
      for (const h of data.raw_history) {
        const item = document.createElement('div');
        item.style.padding = '12px';
        item.style.background = 'white';
        item.style.border = '1px solid var(--border-color)';
        item.style.borderRadius = '6px';
        
        const dateStr = h.timestamp ? new Date(h.timestamp).toLocaleString() : 'Unknown';
        
        item.innerHTML = `
          <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">${dateStr}</div>
          <div style="font-weight: 500; font-size: 14px; margin-bottom: 8px;">
            ${h.action === 'applied' ? '✅ Applied' : '↩️ Rolled Back'} <span style="text-transform: capitalize;">${h.field.replace('_', ' ')}</span>
          </div>
          <div style="font-size: 13px; margin-bottom: 4px; font-family: monospace;">
            Commit: ${h.commit_hash || 'None'}
          </div>
        `;
        historyContainer.appendChild(item);
      }
    }
    
    loading.style.display = 'none';
    content.classList.remove('hidden');
    
  } catch (err) {
    console.error(err);
    loading.style.display = 'none';
    error.textContent = err.message;
    error.classList.remove('hidden');
  }
}

// Remove the bad hook


let isSinglePageAnalysisActive = false;

document.querySelector('.tab[data-tab="sandbox-comparison"]').addEventListener('click', () => {
  if (!isSinglePageAnalysisActive) {
    loadSandboxComparison();
  }
});

async function startSinglePageAnalysis(event) {
  event.preventDefault();
  const urlInput = document.getElementById('url-input').value.trim();
  if (!urlInput) {
    showToast("Please enter a URL first", true);
    return;
  }

  const btn = document.getElementById('single-page-btn');
  const spinner = document.getElementById('single-page-spinner');
  const text = document.getElementById('single-page-text');

  btn.disabled = true;
  spinner.classList.remove('hidden');
  text.textContent = "Analyzing & Applying AI...";

  try {
    const res = await fetch('/api/sandbox/single-page', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: urlInput })
    });

    if (!res.ok) throw new Error("Failed to start analysis");

    const { job_id } = await res.json();

    // Poll for completion
    const interval = setInterval(async () => {
      try {
        const pollRes = await fetch(`/api/sandbox/single-page/${job_id}`);
        if (pollRes.ok) {
          const pollData = await pollRes.json();
          if (pollData.status === 'completed') {
            clearInterval(interval);
            btn.disabled = false;
            spinner.classList.add('hidden');
            text.textContent = "Single Page Analysis (Demo)";

            isSinglePageAnalysisActive = true;

            // Populate comparison tab
            populateComparisonTab(pollData.comparison);

            // Show results section
            document.getElementById('results-section').classList.remove('hidden');
            document.getElementById('input-section').classList.add('hidden');
            document.getElementById('results-url').textContent = "Single Page Analysis";
            document.getElementById('results-status').textContent = urlInput;
            setDashboardVisible(true);
            document.body.classList.add("jobless"); // Hide right rail for cleaner look

            // Switch to tab
            switchTab('sandbox-comparison');

            // Reset flag after switching so that subsequent manual clicks fetch normally
            setTimeout(() => {
              isSinglePageAnalysisActive = false;
            }, 500);
          } else if (pollData.status === 'failed') {
            clearInterval(interval);
            throw new Error(pollData.error || "Analysis failed");
          }
        }
      } catch (err) {
        clearInterval(interval);
        throw err;
      }
    }, 2000);

  } catch (err) {
    showToast(err.message, true);
    btn.disabled = false;
    spinner.classList.add('hidden');
    text.textContent = "Single Page Analysis (Demo)";
  }
}

function populateComparisonTab(data) {
  const loading = document.getElementById('sandbox-comparison-loading');
  const error = document.getElementById('sandbox-comparison-error');
  const content = document.getElementById('sandbox-comparison-content');

  loading.style.display = 'none';
  error.classList.add('hidden');
  content.classList.remove('hidden');

  document.getElementById('comp-img-baseline').src = `data:image/jpeg;base64,${data.visuals.baseline_b64}`;
  document.getElementById('comp-img-current').src = `data:image/jpeg;base64,${data.visuals.current_b64}`;

  document.getElementById('comp-score-old').textContent = data.seo_score.baseline;
  document.getElementById('comp-score-new').textContent = data.seo_score.current;

  const delta = data.seo_score.current - data.seo_score.baseline;
  const deltaEl = document.getElementById('comp-score-delta');
  if (delta > 0) {
    deltaEl.textContent = `+${delta} Points`;
    deltaEl.style.background = '#dcfce7';
    deltaEl.style.color = '#166534';
  } else if (delta < 0) {
    deltaEl.textContent = `${delta} Points`;
    deltaEl.style.background = '#fee2e2';
    deltaEl.style.color = '#991b1b';
  } else {
    deltaEl.textContent = 'No Change';
    deltaEl.style.background = '#f3f4f6';
    deltaEl.style.color = '#374151';
  }

  const tbody = document.getElementById('comp-fields-tbody');
  tbody.innerHTML = '';

  for (const f of data.fields) {
    const tr = document.createElement('tr');
    tr.style.borderBottom = '1px solid var(--border-color)';

    const isChanged = f.status === 'changed';
    const badgeColor = isChanged ? '#dcfce7' : '#f3f4f6';
    const badgeTextColor = isChanged ? '#166534' : '#374151';
    const statusText = isChanged ? 'Changed' : 'Unchanged';
    const diffStyle = isChanged ? 'background:#dcfce7; padding:2px 4px; border-radius:4px;' : '';

    tr.innerHTML = `
      <td style="padding: 12px 16px; font-weight: 500; text-transform: capitalize;">${f.field.replace('_', ' ')}</td>
      <td style="padding: 12px 16px; color: var(--text-muted); font-size: 13px;">${escapeHtml(f.baseline || 'None')}</td>
      <td style="padding: 12px 16px; font-size: 13px;"><span style="${diffStyle}">${escapeHtml(f.current || 'None')}</span></td>
      <td style="padding: 12px 16px;">
        <span style="background:${badgeColor}; color:${badgeTextColor}; padding:4px 8px; border-radius:12px; font-size:12px; font-weight:500;">
          ${statusText}
        </span>
      </td>
    `;
    tbody.appendChild(tr);
  }

  const historyContainer = document.getElementById('comp-raw-history');
  historyContainer.innerHTML = '';
  for (const h of data.history) {
    const item = document.createElement('div');
    item.style.padding = '12px';
    item.style.background = 'white';
    item.style.border = '1px solid var(--border-color)';
    item.style.borderRadius = '6px';

    const dateStr = h.date ? new Date(h.date).toLocaleString() : 'Unknown';

    item.innerHTML = `
      <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">${dateStr}</div>
      <div style="font-weight: 500; font-size: 14px; margin-bottom: 8px;">
        ✅ ${h.action}
      </div>
      <div style="font-size: 13px; margin-bottom: 4px; font-family: monospace;">
        Commit: ${h.commit_hash || 'None'}
      </div>
    `;
    historyContainer.appendChild(item);
  }
}

// --- AGENT SIDEBAR LOGIC ---
let activeAgentRunId = null;
let agentPollTimer = null;

function initAgentTabs() {
  const tabs = document.querySelectorAll('.chat-tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      
      document.getElementById('chat-box').classList.add('hidden');
      document.getElementById('agent-box').classList.add('hidden');
      
      const target = tab.getAttribute('data-target');
      document.getElementById(target).classList.remove('hidden');
      
      if (target === 'agent-box') {
        document.getElementById('agent-alert-dot').classList.add('hidden');
      }
    });
  });
  
  const approveBtn = document.getElementById('agent-approve-btn');
  if (approveBtn) approveBtn.addEventListener('click', async () => {
    if (!activeAgentRunId) return;
    try {
      const resp = await fetch(`${API_BASE}/agent/runs/${activeAgentRunId}/approve`, { method: "POST" });
      if (!resp.ok) throw new Error("Failed to approve");
      document.getElementById('agent-action-group').classList.add('hidden');
      pollAgentRun();
    } catch (e) {
      showToast(e.message, true);
    }
  });

  const stopBtn = document.getElementById('agent-stop-btn');
  if (stopBtn) stopBtn.addEventListener('click', async () => {
    if (!activeAgentRunId) return;
    try {
      const resp = await fetch(`${API_BASE}/agent/runs/${activeAgentRunId}/stop`, { method: "POST" });
      if (!resp.ok) throw new Error("Failed to stop");
      document.getElementById('agent-action-group').classList.add('hidden');
      pollAgentRun();
    } catch (e) {
      showToast(e.message, true);
    }
  });
}

function startAgentPoll(runId) {
  activeAgentRunId = runId;
  
  // Show sidebar if hidden, and switch to Agent tab
  const panel = document.getElementById("chat-panel");
  if (panel.classList.contains("hidden")) {
    panel.classList.remove("hidden");
    chatUserClosed = false;
  }
  document.querySelector('.chat-tab-btn[data-target="agent-box"]').click();
  
  if (agentPollTimer) clearTimeout(agentPollTimer);
  pollAgentRun();
}

async function pollAgentRun() {
  if (!activeAgentRunId) return;
  try {
    const resp = await fetch(`${API_BASE}/agent/runs/${activeAgentRunId}/log`);
    if (!resp.ok) return;
    const data = await resp.json();
    renderAgentState(data.run, data.episode);
    
    if (["queued", "running"].includes(data.run.status)) {
      agentPollTimer = setTimeout(pollAgentRun, 2000);
    }
  } catch (e) {
    console.error("Agent poll error", e);
  }
}

function renderAgentState(run, episode) {
  const badge = document.getElementById('agent-status-badge');
  badge.textContent = run.status.toUpperCase();
  
  const alertDot = document.getElementById('agent-alert-dot');
  const actionGroup = document.getElementById('agent-action-group');
  
  if (run.status === 'waiting_approval') {
    badge.style.background = 'var(--status-broken)';
    badge.style.color = 'white';
    actionGroup.classList.remove('hidden');
    const agentTab = document.querySelector('.chat-tab-btn[data-target="agent-box"]');
    if (!agentTab.classList.contains('active')) alertDot.classList.remove('hidden');
  } else {
    actionGroup.classList.add('hidden');
    if (run.status === 'running') {
      badge.style.background = 'var(--accent)';
      badge.style.color = 'white';
    } else {
      badge.style.background = 'var(--bg-elevated)';
      badge.style.color = 'var(--text-muted)';
    }
  }
  
  const msgs = document.getElementById('agent-messages');
  let html = '';
  
  if (episode && episode.steps && episode.steps.length > 0) {
    episode.steps.forEach(step => {
      let statusClass = step.ok ? 'done' : 'error';
      if (!step.result && !step.error) statusClass = 'running';
      
      let stepHtml = `<div class="agent-step ${statusClass}">
        <div class="agent-step-tool">${escapeHtml(step.tool)}</div>
        <div class="agent-step-reason">${escapeHtml(step.reasoning)}</div>`;
        
      if (step.result) {
        stepHtml += `<div class="agent-step-result">${escapeHtml(JSON.stringify(step.result, null, 2))}</div>`;
      } else if (step.error) {
        stepHtml += `<div class="agent-step-result" style="color:var(--status-broken)">${escapeHtml(step.error)}</div>`;
      }
      stepHtml += `</div>`;
      html += stepHtml;
    });
  } else {
    html = `<div class="chat-message bot" style="opacity: 0.7;">No steps executed yet.</div>`;
  }
  
  // Only update HTML if changed to prevent scrolling jump on every poll
  if (msgs.innerHTML !== html) {
    msgs.innerHTML = html;
    msgs.scrollTop = msgs.scrollHeight;
  }
}

// Call init on load
initAgentTabs();

// --- Quick Agent Audit Button ---
setTimeout(() => {
  const btn = document.getElementById("quick-run-agent");
  if (btn) {
    btn.addEventListener("click", async () => {
      if (!currentJobId) {
        showToast("Open a site first to run the agent.", true);
        return;
      }
      const jobUrl = document.getElementById("results-url")?.textContent || "https://example.com";
      try {
        btn.disabled = true;
        btn.innerHTML = `<span>Starting...</span>`;
        const resp = await fetch(`${API_BASE}/agent/runs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            goal: "Audit the site, find issues, and prepare a plan.",
            scope: "single_page",
            urls: [jobUrl],
            checkpoint_policy: "never"
          })
        });
        if (!resp.ok) throw new Error("Failed to start agent");
        const data = await resp.json();
        showToast("Agent started!");
        startAgentPoll(data.run_id);
      } catch (e) {
        showToast(e.message, true);
      } finally {
        btn.disabled = false;
        btn.innerHTML = `<span>🤖 Run Agent Audit</span>`;
      }
    });
  }
}, 1000); // delay to ensure element exists
