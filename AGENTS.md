# RankEngine — Agent Context & Session State

This file is the durable memory for AI coding sessions. READ THIS FIRST at the
start of every session and resume from "Next up". Update it at the end of
every session with what changed and what's left.

## Project
SEO analysis engine: crawl a site, classify content, analyze, recommend,
approve changes, generate dummy site + reports, chat. Python 3.14 FastAPI +
MongoDB + Redis + Chroma + Arq worker + Playwright. Repo:
`/Users/macbook/RankEngine-AI-Simple` (git, remote `https://github.com/ZuiGO/rankengine-seo.git`).

## Status (last update: SaaS UI — landing page, dark mode, animations)
- All rounds DELIVERED. Latest commits pushed:
  - SaaS UI round (working tree): professional SaaS front door + app polish.
    - `landing.html` (NEW) served at `/` — marketing page (brand nav, animated
      hero with orbs + staggered reveals, live-analysis mock card with
      count-up metrics, 6 feature cards, 3-step how-it-works, CTA band,
      footer). `landing.js` (NEW): theme toggle, IntersectionObserver scroll
      reveal, rAF count-up, `prefers-reduced-motion` respected.
    - App moved to `/app` (main.py routes: `/` -> landing.html, `/app` ->
      index.html). Deep links `/#job/<id>/<tab>` auto-redirect to
      `/app#job/...` from a tiny inline script in landing.html.
    - `index.html`: brand lockup (inline SVG mark + gradient wordmark, no
      dependency on logo.png anymore), header theme-toggle (sun/moon icon),
      tabs grouped into 3 clusters (Audit / SEO+Report / Platform) with
      hairline `.tab-divider` separators and 14 inline SVG icons; inline
      <head> script pre-applies saved theme to avoid FOUC.
    - `app.js`: `initTheme` (persists `zui-theme` in localStorage, system
      default), `countAnimate`/`applyCounts` (one-shot per element via
      `_counting` flag — poll-safe, 900ms ease-out), `skeletonHTML`,
      `emptyState` helpers; overview stat cards now count up on open.
    - `style.css`: tokenized full palette (surfaces, chips, status badges,
      alerts, toasts, tables) + `[data-theme="dark"]` override block
      (persisted + system-aware); shimmer `.skeleton` loaders baked into
      main tab containers (overview/sites/pages/content/actions/report),
      replaced by first render (poll-safe); landing components; button
      variants (.btn-ghost/-sm/-lg); `prefers-reduced-motion` global
      kill-switch; `color-mix` avoided (explicit border tokens).
    - Verified: pytest 168/168; Playwright — landing title/6 features/4+
      count-ups, scroll reveals fire (9 .in), deep-link `/` -> `/app`
      redirect on reload, 14 tabs + 14 icons, 28 overview stat cards with
      count-up values, theme toggle flips computed bg and persists
      (light <-> dark), tab navigation OK, zero console errors.
  - `d98d845` — Professional report template + frontend UI polish.
  - `cb3a1e1` — Truthfulness audit: no fabricated deductions or counts.
  - `bd3bef7` — Rebrand to "ZuiGO Engine" (title, header, chat, mirror, notifications, user-agents, README, smoke).
  - `ad1af55` — GSC self-serve: DB-backed operator settings (no .env for users).
  - `28d063c` — GSC credential-connect round: user-connected Google
    Search Console → real organic_traffic (clicks) when the domain is a
    verified Search Console property; otherwise organic traffic stays N/A.
    - config.py: `gsc_client_id`, `gsc_client_secret`,
      `gsc_redirect_uri=http://localhost:8001/api/gsc/callback`.
    - `services/gsc.py` (httpx only): `build_auth_url(job_id)` (scope
      `webmasters.readonly`, `access_type=offline&prompt=consent`, state =
      job_id), `exchange_code` (stores `gsc_credentials` keyed by domain,
      rejects missing refresh_token), auto token refresh, `list_sites`,
      `_analytics_query` (28d, query+page dims), `_match_property`
      (sc-domain > https://www > https > http, trailing-slash tolerant),
      `fetch_gsc` (totals + top 25 queries/pages), `gsc_status`,
      `disconnect`. No GSC keys in .env yet -> `configured()` False.
    - `routes/gsc.py` prefix `/api/gsc`: `GET /auth/{job_id}` (auth_url or
      config-missing hint), `GET /callback` (exchange -> redirect
      `/#job/{job_id}/seo-insights?gsc=connected`), `GET /status/{job_id}`,
      `POST /{job_id}/fetch` (fetch + merge into cache via
      `merge_gsc_into_insights`, skips when no cache doc), `DELETE
      /{job_id}` (drop creds + strip gsc from cached insights). Router
      registered in main.py.
    - `fetch_all_insights` (dataforseo.py): best-effort GSC block —
      `insights["gsc"]` + `gsc_error`; when connected, overview
      `estimated_organic_traffic=clicks`, `organic_keywords_count=distinct
      queries`, source gsc. `merge_gsc_into_insights(db, job_id, domain,
      gsc_data, cache_version)` reusable for POST /fetch.
    - seo_insights.py `CACHE_VERSION` 2 -> 3 (forces one refetch).
    - Frontend: SEO Insights tab GSC section (index.html) — status badge,
      Connect/Refresh Data/Disconnect buttons, connect card w/ config-missing
      hint, 4 stat cards (Clicks/Impressions/CTR/Avg position), Top Queries +
      Top Pages tables; app.js `loadGsc(jobId)` (status + `?gsc=connected`
      toast via history.replaceState), `renderGscData(gsc, error)`, handlers.
    - pytest 152/152 (137 + 15 new in test_gsc.py: auth URL params,
      configured flag, property matching incl. trailing slash, token
      exchange + refresh_token guard, analytics parsing, cache-merge
      override + skip-when-no-cache, status). Live-verified:
      `/api/gsc/auth/{job}` -> configured:false hint, `/api/gsc/status/{job}`
      -> connected:false, insights payload has `gsc:null` + `gsc_error:null`
      (graceful when not connected).
- ONE-TIME USER SETUP still required: Google Cloud Console -> enable
      Search Console API -> create OAuth client (**Web application**) -> paste
      Client ID / Client Secret into the in-app Settings tab (Settings ->
      Google Search Console; stored in Mongo `app_settings` key `gsc`, `.env`
      is only a fallback) -> add the redirect URI shown on the Settings page
      (`https://<host>/api/gsc/callback`) to the client's authorized redirects
      -> verify the analyzed domain as a Search Console property. End users
      connect per-domain on the SEO Insights tab (Connect GSC); tokens land in
      `gsc_credentials` keyed by domain.
  - GSC self-serve round (`ad1af55`): `routes/app_settings.py` GET/PUT
    `/api/settings/gsc` (masked reads; named app_settings.py to avoid
    `config.settings` shadowing); `services/gsc.py` reads `get_gsc_config()`
    (DB first, .env fallback), `configured()` is async now, auth/callback
    derive `_redirect_uri_for(request)` from request host; frontend Settings
    tab (fields + save/status/hint) in index.html + `loadSettings`/handler in
    app.js; `VALID_TABS` includes `settings`.
  - Rebrand round (`bd3bef7`): "ZuiGO Engine" user-facing strings + user-agents
    `ZuiGO-Engine/1.0` / `ZuiGO-EngineBot/1.0`; idempotent test_patch assertion.
  - Truthfulness round (`cb3a1e1`): site_health.py evaluated-only denominators
    (`pages_evaluated_*`, `mobile_friendly_evaluated`), alt-deduction only when
    images exist, thin = word_count < 200, legacy link buckets explicitly
    labeled `broken_links_legacy_bucket` ("broken or unreachable"), CWV
    per-page `cwv_source` (field/lab/mixed/partial) + summary `cwv_sources`,
    local_insights evaluated-only; `backend/tests/test_truthfulness.py` (12).
  - Professional report template (working tree, NOT committed yet): replaced
    `_report_html` in `backend/routes/reports.py` with branded builder
    (`_esc`, `_sev_badge`, `_kpi`, `_REPORT_CSS`) emitting cover w/ grade
    block, 12-KPI grid, exec summary (narrative + direction/previous score),
    severity-sorted Findings (evidence + how-to-fix), Quick Wins +
    Long-Term recommendations, Methodology table, Content/Page-type
    breakdowns, Backlinks/Domain/GSC insights, User Flows, Action Items,
    Content Versions, footer. `import html as _html_esc` at module top.
    Verified live: `/api/reports/{job}` HTML (200), `/pdf` renders 8-page A4,
    168/168 pytest.
  - Frontend polish round (working tree, NOT committed yet): rewrote
    `frontend/style.css` (all existing selectors preserved) — refined
    indigo/violet design system, gradient accent header + brand titles,
    soft shadows + hover lift on cards/buttons, tab active pill, shimmer
    progress bar, custom scrollbars, focus-visible rings, smooth tab fade.
    Verified via Playwright headless: 14 tabs, 28 overview stat cards, no
    console/JS errors (only 404 = placeholder logo.png, falls back to text).
  - `814f4af` — LLM model switched to `openai/gpt-oss-120b` (Groq; new
    `settings.groq_model`, env-overridable via `GROQ_MODEL`). Chat +
    change-applier both use it; live chat verified.
  - `81cd3a5` — honest link/content metrics round:
    - link_checker: `_check_one` retries once (GET fallback for HEAD
      timeout/error/403/405/501/5xx); status buckets now
      ok/redirect/broken/blocked/unreachable; `broken_link_count` = true
      4xx/5xx only (blocked/unreachable no longer lumped in); per-link
      `pages` (source pages) stored; summary has `unreachable` count
      (old `timeout`/`error` fields dropped).
    - crawler: summary `total_links` = UNIQUE targets
      (`unique_internal`+`unique_external` sets), new
      `total_link_occurrences`/`total_internal_occurrences`/
      `total_external_occurrences` (old occurrence counts);
      content dedup atomic (`dedup_lock`), `data:` URI items skipped
      (kills the 68x svg-placeholder duplicates).
    - routes/links.py: response gains `total_link_occurrences`
      (falls back to total_links for pre-change jobs); new
      `GET /api/links/{job_id}/all?status=&limit=&offset=` (sorted,
      status-filterable, includes source pages).
    - exec_summary: per-issue `explanation` + `how_to_fix` steps +
      `evidence` (top-5 resolver per issue_key over link_health /
      page_performance / pages / orphan_pages / sitemap_audits /
      duplicate_content), `all_issues` (full sorted list), narrative
      `overview` string; `_narrative()` + `_evidence_for()` helpers.
    - frontend: `linkify()`/`linkifyText()` helpers applied to every URL
      cell (pages, content, backlinks, link-health issues+longest,
      content versions, user flows, orphans, stale pages, sites list);
      Links tab: unique label, Link Occurrences card, Blocked/Unreachable
      cards, "Linked From" column, new All Links section with status
      filter + load-more; exec summary: overview line + `<details>`
      per issue (why/how/evidence) + collapsible all-issues list;
      report organic-traffic card no longer renders literal null.
- pytest: 137/137 (126 + 11 new in test_link_accuracy.py).
- Competitor-gap round (IN PROGRESS, free tools only — replaces broken
  DataForSEO `/api/competitors/gap`; DataForSEO endpoints 404 on plan):
  - `services/crawler.py`: `crawl_site(..., unlimited=True, seed_sitemap=True)`
    — full-site crawl: BFS queue drain + XML sitemap seed, safety ceiling
    `settings.competitor_crawl_max_pages` (5000); progress divides by
    `progress_denom` (no div-by-zero).
  - `config.py`: `competitor_crawl_max_pages=5000`,
    `competitor_psi_all_pages=True` (PSI on every crawled page).
  - `services/serp_api.py`: `search_keyword_full(keyword)` — feature extraction
    (answer_box, faq, knowledge_graph, top_stories, images, reviews, ai_overview)
    + `organic_domains`; spend-tracked.
  - `services/competitor_audit.py`: `audit_competitors(target_job_id, competitors)`
    — per competitor: ephemeral analysis_jobs doc (flagged `competitor_job`,
    excluded from Sites list) → unlimited sitemap-seeded crawl → analyze_pages /
    check_links / compute_site_health / fetch_performance(every page) /
    audit_structured_data / keyword extract → 8-gap diff vs stored target
    baseline (keyword, content, backlink, technical, schema, on-page, UX,
    SERP-features; SERP API with crawl-only fallback when key absent) →
    upsert into `competitor_gap_analyses` keyed (target_job_id, competitor) →
    ephemeral job + its collections deleted.
  - Routes `routes/competitors.py`: `POST /api/competitors/{job_id}/analyze`
    (queues `competitor_audit` worker task; `/gap` kept as alias),
    `GET /api/competitors/{job_id}` (list w/ status),
    `GET /api/competitors/{job_id}/{competitor}` (detail). Docs strip `_id`.
  - Worker: `competitor_audit` task in worker.py + `run_competitor_pipeline`
    in routes/analysis.py (marks stragglers error on failure).
  - `routes/sites.py`: hard-delete cascades `competitor_gap_analyses` +
    target-linked rows + ephemeral competitor jobs; `list_sites` excludes
    `competitor_job` docs.
  - Frontend: new Competitors tab (index.html + app.js) — analyze form,
    4s polling while queued/running, per-competitor cards (gap stat grid,
    keyword/content/backlink/schema/SERP-feature lists, technical/UX delta
    grids); old DataForSEO widget removed from SEO Insights; tab registered
    in VALID_TABS + switchTab loaders.
  - Live-checked: analyze enqueue → worker crawl running; list endpoint OK;
    sites list unaffected by ephemeral job.
- Complete-audit round (offline heuristics only; no new paid APIs):
  - `GET /api/exec/{job_id}` + `POST /api/exec/{job_id}` — impact-ranked exec
    summary: top_issues/quick_wins/long_term, per-issue effort+next_step
    (EFFORT/TITLES maps in `services/exec_summary.py`), direction
    improved/declined vs previous site_health row; computed at end of pipeline
    (`exec_summaries` collection). Actions list supports `?sort=impact`.
  - `services/sitemap.py`: robots.txt + /sitemap*.xml audit, uncrawled-URL
    count; stage `sitemap` in wave1 (`sitemap_audits` collection).
  - Crawler: per-page `click_depth` (BFS depth map), `redirect_count`
    (Playwright `request.redirected_from` walk — Response has NO `.history`),
    `https_entry`, mobile pass sets `mobile_friendly` (viewport meta).
  - Link checker: `redirect_count`/`redirect_chain` per link + summary
    `redirected_links`/`max_redirect_chain`.
  - CWV: `field_pages`/`lab_only_pages`/`field_avg` in performance summary.
  - `services/content_signals.py`: E-E-A-T (author/about/updated/publisher/schema)
    + extractable formatting (FAQ/tables/lists); consumed by seo_analyzer as
    new page checks `eaat_signals_missing`/`no_extractable_format` (only fire
    when ctx carries eaat/extractable keys).
  - `services/cannibalization.py`: keyword→page clusters from corpus+title/meta,
    `cannibalization` high-impact actions, `cannibalization_summaries`.
  - `services/ai_visibility.py`: robots AI-agent blocking, llms.txt, SD/extractable
    share → score/100 (`ai_visibility_summaries`).
  - `services/local_seo.py`: LocalBusiness/NAP/contact/address signals → score/100
    (`local_seo_summaries`).
  - site_health: new metrics + issues (sitemap, click depth, redirect chains,
    https entries, mobile, AI-blocked, local, cannibalization) and score
    deductions (https/mobile/deep + 10 for AI-blocked).
  - quality routes: `/api/quality/{job_id}/sitemap|ai-visibility|local-seo|cannibalization`.
  - Frontend: Overview exec-summary card + AI/local/cannibalization stat cards;
    Report tab sections (sitemap/AI/local/cannibalization) via loadReportExtras;
    Actions "Sort: Impact" select.
  - Smoke grew 74→80: exec summary, sitemap audit, ai visibility, local seo,
    cannibalization check, new summary keys. Smoke approves the first
    apply-able action (content_type in image/text/pdf/doc/video/audio) because
    cannibalization actions sort first but map to no HTML change.
- Server + worker run under launchd: `com.zuigo.rankengine-server`,
  `com.zuigo.rankengine-worker` (plists in `deploy/`, symlinked to
  `~/Library/LaunchAgents/`). Logs: `/tmp/rankengine.log`, `/tmp/arq.log`.
- Smoke: use bash tool timeout (no `timeout` cmd on macOS); ~15-25 min;
  full run just passed 74/74 on books.toscrape.
- Rebrand: user-facing strings are "ZuiGO Engine" (FastAPI title,
  index.html/landing.html header/title/chat greeting, chat system prompt, PR
  titles, llms.txt brand, USER_AGENT strings, test_patch assertion, smoke gchat
  question). Internal ids kept: launchd labels `com.zuigo.rankengine-*`, db name
  `rankengine`, repo path/remote, neo4j password. Logo is an inline SVG brand
  mark (no logo.png needed).
- Refresh bug FIXED: app.js persists state in URL hash `#job/<jobId>[/<tab>]`
  via `history.replaceState` (form submit, tab clicks, `openSite`, New Analysis
  clears it). `restoreFromHash()` on DOMContentLoaded/hashchange reopens the
  job (`openSite(job.id, {preserveTab: true})` so `showResults` skips its
  auto-overview click; `switchTab` re-applies the tab; unknown job ids clear
  the hash and stay on Analyze). Verified via Playwright (7/7).
- Speedup round (timing-only, smoke semantics preserved):
  - Pipeline: post-crawl stages in `routes/analysis.py` now run in waves —
    wave1 `asyncio.gather`: user_flows, extraction, insights, backlinks,
    link_health, performance, duplicate, structured, geo_readiness, sitemap,
    ai_visibility, local_seo, orphans;
    wave2 (needs extraction): action analysis, geo_alignment, cannibalization,
    vectors;
    then site_health. Each stage wrapped in `_stage()` with try/except +
    fallback and logged `Stage <name> ok job=... t=<s>` to `/tmp/arq.log`.
  - Crawler: mobile pass concurrent (`mobile_crawl_concurrency`, shared
    politeness gate); content downloads deduped per job by `source_url` +
    parallel within page (`download_concurrency`); dedupe means second-page
    duplicates skip download/analysis (content counts can drop vs pre-round).
  - Link checker: one shared `httpx.AsyncClient` (pooled) for all checks.
  - PSI concurrency `Semaphore(3)` -> `settings.psi_concurrency` (5).
  - Content extraction: PDF/doc/image parsing via `asyncio.to_thread`
    (`extract_workers`, default 4).
  - New config: `psi_concurrency=5`, `mobile_crawl_concurrency=5`,
    `download_concurrency=6`, `extract_workers=4`.
- Gemini free-tier daily quota exhausted sometimes -> hash-embedding fallback
  (robust, degraded). DataForSEO: keywords_for_site + backlinks/summary 200,
  but domain_analytics/overview, on_page/*, backlinks/referring_pages 404
  (endpoints not on plan) -> SERP fallback used; graceful local fallbacks live.
  Groq key active. Neo4j offline (graph unwired, backend files kept).
- Hard delete (`DELETE /api/sites/{job_id}/hard`) cascades 27 collections +
  Chroma + files. Chat supports global (no job_id) mode.
- Suggestions are fact-anchored: actions only created when a measured fact
  fails (issue_key/confidence/evidence/impact per action); page-level actions
  (thin content, meta, H1, noindex, no_structured_data, entity_coverage_low,
  eaat_signals_missing, no_extractable_format) generated in `analyze_pages`
  enrichment (ctx carries meta_counts/sd/corpus keywords via keyword_extractor
  + validate_structured_data + content_signals); `action_feedback`
  approval-rate learning; cross-job suppression via `content_versions.issue_key`.
- URL normalization central in `url_normalizer.py`; broken links single source
  `broken_link_count` + `total_links_scanned`; CWV `pages_checked`; keyword
  rankings `keyword_integration: configured|unconfigured` badge in trends UI.
- Part 3 features live:
  - Actions list: severity filter + `POST /api/actions/{job_id}/batch`
    (reject fast-path / approve bounded concurrency) + `GET .../patch?format=json|md`
    (machine-applicable patch incl. version before/after/diff) + Export buttons.
  - Trends: per-point `deltas` vs previous analysis; Slack "Broken links
    increased" alert (config `broken_link_alert_threshold`, default 5);
    delta columns in trends table.
  - Analytics tab: Chart.js (CDN) line charts for health/broken/pages +
    per-keyword rank history (reverse rank axis).
  - Webhooks: `notifications.send_webhook` (config `action_webhook_url`) +
    `create_github_pr` (config `github_token`, optional) on approve/reject.
  - Dummy site mirror writes `llms.txt` (LLM-citable page index).

## Run / verify commands
```bash
# restart services (needed after any backend change)
launchctl kickstart -k gui/$(id -u)/com.zuigo.rankengine-server
launchctl kickstart -k gui/$(id -u)/com.zuigo.rankengine-worker
# tests + smoke (smoke needs a long tool timeout, no `timeout` on macOS)
.venv/bin/python -m pytest backend/tests/ -q
.venv/bin/python scripts/smoke_test.py --url https://books.toscrape.com
# health
curl -s localhost:8001/api/health
# per-stage pipeline timings live in /tmp/arq.log:
#   rg 'Stage .* ok' /tmp/arq.log
```

## Next up (candidate work, NOT started)
- The app lives at `/app` (index.html); `/` serves the marketing landing page
  (landing.html). Deep links `/#job/<id>` redirect to `/app#job/<id>`.
- Theme toggle: header `#theme-toggle` (app) / `#theme-toggle-landing`
  (landing), persists `zui-theme` in localStorage; `[data-theme="dark"]`
  overrides the token palette in style.css.
- Brand logomark is inline SVG in both pages — no logo.png dependency
  (old `#app-logo`/`#logo-fallback` markup removed).
- GSC: user completes one-time Google Cloud OAuth client setup (Web app + in-app
  Settings tab) then end-to-end connect test on the live job; DataForSEO full
  re-test once account stability/fraud-pause lift confirmed ("we will do test
  later").
- Competitor-audit speed items (approved, not implemented): PSI sampling cap,
  no mobile browser pass for competitors, no asset downloads, content-hash page
  dedup, parallel competitor audits, SERP budget trim.
- Long-term rank/build history is stored; optional richer longitudinal charts
  (Chart.js already wired for trends; could add more series).
- Calibrate site-health scoring / add per-metric weight explanations.
- Re-enable Neo4j graph module or wire ranking insights from Chroma.
- Add backend validation for `crawl_schedules` duplicate domains / interval caps.
- Webhook delivery retries/dedup; patch format versioned consumers.
- Exec summary quick_wins currently uses effort+impact heuristics; could rank
  with actual approval-rate learning (`action_feedback`) per issue_key.
- Sitemap audit parses sitemapindex nesting; news/video/image sitemaps ignored.
- AI-visibility/local/cannibalization are offline heuristics; paid API upgrade
  paths (e.g. real AI-overview citation monitoring, Google Business Profile)
  remain future work.

## Conventions
- No comments in code unless asked. Launchd restarts after backend changes.
- Full smoke = slow crawl; prefer targeted curl checks after backend edits.
- Report counts in `/tmp/rankengine.log`; worker logs `/tmp/arq.log`.