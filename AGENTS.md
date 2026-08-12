# RankEngine — Agent Context & Session State

This file is the durable memory for AI coding sessions. READ THIS FIRST at the
start of every session and resume from "Next up". Update it at the end of
every session with what changed and what's left.

## Project
SEO analysis engine: crawl a site, classify content, analyze, recommend,
approve changes, generate dummy site + reports, chat. Python 3.14 FastAPI +
MongoDB + Redis + Chroma + Arq worker + Playwright. Repo:
`/Users/macbook/RankEngine-AI-Simple` (git, remote `https://github.com/ZuiGO/rankengine-seo.git`).

## Status (last update: clean Analyze/screens + landing "Past analyses" round + email-hardening + stop-analysis round — virtual-card cooldown variant 2026-08-12; 389/389 tests; pending commit)
- CLEAN-SCREENS ROUND (rails/landing, committed summary below):
  - `setDashboardVisible(visible)` toggles `#dashboard-grid.hidden` + `body.no-dashboard`;
    Analyze page, crawl screen and `/app` with no job are clean; results view and jobless
    Sites view show the dashboard. `body.jobless` hides `#tabs` + `#rail-nav` (jobless
    "Past Analyses" header = `#results-*` + Sites tab without the tab strip).
  - Bare-tab hash routing: `restoreFromHash()` handles `#sites` -> `openPastAnalyses()`
    (loadSites + jobless header "Past Analyses"). Landing nav + CTA "Past analyses"
    link to `/app#sites` — no real job data on the public landing.
  - Chat widget now floats **bottom-right** for all non-docked states
    (`position:fixed; bottom:24px; right:24px`; panel `margin-bottom:10px`,
    `transform-origin:bottom right`) — old `top:76px` overlapped the Analyze header
    and the landing CTA. Docked (>=1280 + job open, `body.app-wide`) restores
    `margin-top:8px` / `transform-origin:top right`.
  - Verified: clean-screens suite + 375/1024/1280/1440 viewport suite, zero console
    errors; crawled example.org end-to-end, jobs hard-deleted after.
- EMAIL-ROUND (backend + frontend):
  - `notifications.py`: `_send_sync` branches port 465 -> `smtplib.SMTP_SSL` (implicit
    TLS), else STARTTLS (default) or plain; NEW `try_send_email(to, subject, body,
    attachment) -> (sent: bool, error: str|None)` returning the REAL failure reason;
    `email_report()` returns `(bool, error)` with per-step messages (Job not found /
    Report rendering failed / PDF rendering failed).
  - `routes/reports.py` `POST /{job_id}/email`: 502 body `{"error": <real reason>}`.
  - `routes/app_settings.py`: `SmtpTestRequest{to}` + `POST /api/settings/smtp/test`
    -> `{sent, error}` (unconfigured -> "SMTP host not configured. Add it in
    Settings → Email."). Frontend Settings → Email: `#smtp-test-to` + `#smtp-test-send`
    + `#smtp-test-status` + `#smtp-test-error` (renders real reason); report-email
    handler unwraps `data.detail.error`.
  - Gmail ready: host smtp.gmail.com port 587, app password (16-char), STARTTLS;
    stored DB-first in `app_settings` key `smtp` (Settings tab), `.env` fallback.
- STOP-ANALYSIS ROUND (cooperative cancellation + purge):
  - `services/job_cancel.py` (NEW): `JobCancelled(job_id)` + `check_cancelled(job_id)`
    — reads `cancelled:true` flag OR status `cancelled` on the analysis_jobs doc;
    NEVER raises on DB/network errors (best-effort; tests pass a fake DB).
  - `services/job_cleanup.py` (NEW): `hard_delete_job(job_id)` — full cascade
    extracted from sites.py hard-delete (JOB_COLLECTIONS rows by job_id +
    target_job_id, child competitor analysis_jobs docs `$in` deleted, their rows,
    crawl_schedules history `$pull`, Chroma `job_{id}`, dummy_site/downloads dirs).
    sites.py hard-delete now calls it.
  - Checkpoints: crawler (update_progress tick, batch-loop top, after browser.close
    before mobile phase), link_checker (every 20 links), analysis pipeline start,
    `_progress()` / `_stage()` re-raise; `except JobCancelled` in the pipeline:
    marks `status=cancelled` + "Cancelled by user" + completed_at, purges via
    `hard_delete_job` (guarded), sends NO alert emails.
  - `POST /api/analysis/{job_id}/cancel`: 404 missing; 409 unless queued|running;
    sets flag + cancelled_at + "Cancelling...", `log_audit("analysis_cancelled")`.
  - Frontend: `#stop-analysis-btn` (btn-danger "Stop") + `#stop-analysis-note` on the
    progress card; `stopCurrentAnalysis()` (disables, "Stopping..."); `pollJob`
    handles `status==="cancelled"` AND `resp.status===404` (purge race) ->
    `showCancelledCard()`; card: "Analysis Cancelled", `.status-cancelled` badge,
    button flips to btn-secondary "Back to Analyze" (RE-ENABLES disabled state,
    onclick -> `#new-analysis-btn`). CSS: `.btn-danger`, `.progress-actions`,
    `.status-cancelled`.
  - Tests: `backend/tests/test_cancel.py` (16: check_cancelled x4, cancel endpoint
    x5 incl 404/409, pipeline pre-cancelled purge x1, hard_delete_job cascade incl
    child jobs x1, smtp x5: 465->SMTP_SSL, 587->starttls, error surfacing,
    unconfigured, test endpoint). FakeDb `__getitem__` + `_coll`-namespaced store.
    Full suite 373 -> 389. node --check clean.
- Live-verified (2026-08-12, Playwright 1440): SMTP test UI shows real error when
  unconfigured; mid-crawl Stop -> "Analysis Cancelled" card -> job 404 after purge ->
  no trace in /api/sites -> Back to Analyze clean screen; zero console errors except
  the EXPECTED one 404 poll tick after purge (frontend handles it; inherent to the
  delete-on-cancel design). Viewports 375/1280: no overflow, stop button visible.
- OPS: launchd server/worker restarted with new code. Docker demo re-pinned to
  8002 (`DEMO_PORT=8002 docker compose up -d --build app` from deploy/demo) — the
  demo compose default `${DEMO_PORT:-8001}` had squatted the dev server's 8001 after
  a plain `up`; keep demo on 8002 (8001 stays the launchd dev server). Demo health
  ok on 8002.
- Live sites on 8001: `cced02d1-8a39-41b9-a523-9489231d823b` (zuigo.ai),
  `6294eef9-1f42-4974-babb-170165f7736f` + `1c460760-4214-4597-8fc8-98a868a6be44`
  (fluidcontrols.com x2).
- KEYWORD RELEVANCE ROUND (committed; backend change -> server/worker restarted via launchd):
  - `keyword_engine.py`: `canonicalize()` merges near-duplicates via snowball stems
    ("Double Ferrule Fittings" == "double-ferrule-fittings" == "double ferrule fitting");
    `corpus_ngrams` ranked by count x sum-of-token-IDF (sitewide nav phrases like
    "industrial fittings" lose to product-specific ones); `_passes_intent` gate rejects
    stopword/modifier/nav boundaries, number+unit tokens (`10mm`, `40bar`; material grades
    like 316/316l survive), nav-only combos; `apply_modifiers` skips modifier-word cores
    ("india india" dies, "union manufacturer" survives); GREEDY_SLUGS extended (services/
    values/vision/mission/history/leadership/press/media/events/testimonials/support);
    multi-word cores outrank single-word ones (`_core_score` = weight x 1.8 for >=2 words).
  - `job_keywords` collection (NEW): versioned cache (`KEYWORD_CACHE_VERSION` = 4) written
    once per analysis; `get_smart_keywords(rebuild=True)` in the pipeline wave2 `keywords`
    stage (`use_llm=True` once per NEW job). All consumers (`fetch_all_insights` merge,
    `run_serp_rankings`, suggested-keywords, chat, competitors) slice the SAME ranked list;
    cache hit is ~0.0007s vs ~2.5s build and removes repeated SE Ranking spend.
  - `llm_polish`: fact-anchored (candidates must share >=2 tokens with a seed or appear
    verbatim in corpus text), one retry on unparseable output. ROOT CAUSE FIXED: Groq
    gpt-oss-120b burned the whole 512-token budget on reasoning (`finish: length`,
    `reasoning_tokens=510`) with long seed lists -> empty content; now max_tokens=2048 +
    seeds capped at 40, and base list reserves slots so LLM extras aren't truncated.
  - `keyword_extractor.py`: weighted fields (title 3x, meta 2x, URL slug 2x, body 1x) +
    2-3 gram phrase scoring with token-IDF prior; all callers keep `(job_id, top_k)` API.
  - `seo_insights.py` CACHE_VERSION 15 -> 16; sites hard-delete cascade gains `job_keywords`;
    analysis summary gains `total_smart_keywords`.
  - New `backend/tests/test_keyword_relevance.py` (19 tests: canonical merge, intent gates,
    idf-prior ranking, modifier-core gate, weighted extraction, cache build/hit/version/
    rebuild with no-SE-spend assertion, LLM fact-anchor accept/reject/corpus-verbatim);
    `test_suggestions.py::test_common_terms_ranked` updated (phrases now outrank the bare
    unigram — old test asserted unigram-only behavior). Full suite 354 -> 373.
  - Live-verified on fluidcontrols `6294eef9`: top-20 now real product phrases (male elbow,
    pipe clips, ball valves, drain valve, flow series, union cross/elbow, coupling cap,
    gauge valves) — corporate junk (services, fc values/vision/mission) gone; suggested-
    keywords returns 45 incl. 25 LLM purchase terms ("globe isolation valve price",
    "compact non return valve manufacturer india"); insights refresh (v16) = 22 keywords,
    12 site-derived prepended, source "se-ranking+site"; Playwright SEO Insights tab zero
    console errors.
- TINY FIX (committed with this round): crawl screen leaked the previous audit's stats — `showProgress()`
  never reset `#cs-pages` ("pages crawled" kept the old job's count until the first poll
  tick). Now resets to "0" and also empties the rail Live-activity feed (old crawl events
  cleared, then the new "Analysis queued" entry pushes). Verified: node --check clean;
  Playwright end-to-end (2 real crawls submit+complete, second submit shows reset, jobs
  hard-deleted, zero console errors) + injected-stale-state check (cs-pages 261 + 2 feed
  items -> showProgress() -> "0" + empty feed). Frontend-only, no server restart needed.
- Bigger chatbot + fresh Docker demo (`353b72b`, pushed; no backend logic change
  except crawler.py no-sandbox):
  - Chatbot: floating panel 390 -> 520px wide, chat-box 420 -> 560px tall (also
    fixed a leftover `.chat-panel .chat-box { height:400px }` override that had
    silently capped it), toggle 13px/24px @15px font, messages/input 15px,
    chat-table 12.5px. Docked (>=1280): right rail `minmax(264,288)` ->
    `minmax(304,348)px`, panel `min(540px, calc(100vh-190px))`, box
    `min(480px, calc(100vh-280px))`. Note: with NO job open the right rail
    auto-places into the middle grid column (results-section display:none) and
    becomes ~780px wide — pre-existing behavior, deliberate. Playwright at
    375/1024/1280/1440/1920: zero overflow, floating 520x560 (capped by
    viewport on short windows), docked 314x528/480 box, zero console errors.
  - DOCKER DEMO (`deploy/demo/docker-compose.yml` == THE demo stack now; the
    repo-root `docker-compose.yml` is back to dev-infra only: mongodb
    community-server + redis + neo4j): services mongodb (mongo:7, NO host-
    published ports), redis, one-shot `mongo-seed` (mongo:7 image,
    `mongorestore --nsInclude='rankengine.*' --drop /seed/dump`, mounts
    `../../seed:/seed:ro`), one-shot `seed-vectors` (`python scripts/seed_demo.py`
    -> `vector_service.index_job_vectors` per completed job; idempotent wipe+
    rebuild), `app` (port `${DEMO_PORT:-8001}:8000`) and `worker`
    (`python -m arq backend.worker.WorkerSettings`) sharing the image (build
    context `../..`, Dockerfile at repo root). `env_file: .env.docker` (example
    committed; real keys gitignored via `.env.docker` + `seed/` patterns).
    Dockerfile: py3.12-slim + libmagic1/libglib/fonts-dejavu + playwright
    chromium + install-deps; crawler launches chromium with `args=["--no-sandbox"]`
    (both sites in crawler.py) so crawls work as root in containers.
  - COMPOSE GOTCHA (cost ~1h): docker compose v5 with a project-dir `.env`
    injects that `.env` into every container and it BEAT the anchor `env_file:`
    (real keys + localhost URIs leaked into containers, mongod unreachable).
    Fix: the demo compose lives in `deploy/demo/` whose project dir has NO
    `.env` — isolated from the dev `.env` entirely. Also: `mongorestore` needs
    `--nsInclude=` (not `--db`) + the dump-root arg; `docker compose run`
    path caveats on `env_file` in anchors; seed script must
    `sys.path.insert(0, repo-root)` + call `connect_db(settings.mongodb_uri)`
    (get_db returns None otherwise).
  - Seed data: `mongodump` of local rankengine DB -> `seed/dump` (165MB,
    gitignored; excludes `app_settings` + `gsc_credentials` = no secrets).
    3 jobs: zuigo.ai (24pg), fluidcontrols.com `6294eef9` (261pg, full audits)
    + a 2nd fluidcontrols `1c460760`. Config via `python -c` script expected
    key=value lines; plain `split("=")` readers can fail on trailing/odd chars
    (used regex `^KEY=(.+)$`).
  - Live-verified on port 8002 (8001 busy with launchd): health ok, sites list
    = 3, vectors 72+500+500 indexed (Gemini 429 -> hash fallback, still indexes),
    overview/insights(9)/competitors/report tabs render, live Groq chat answered
    "261 pages, grade D" with 7 clean bullets (no raw pipes/asterisks), zero
    console errors, idempotent second `up` (seed one-shots stay exited,
    `restart: "no"`, app/worker `unless-stopped`). README has a Docker demo
    section. Full reset: `cd deploy/demo && docker compose down -v && up -d --build`.
- UI round 3 (`012dd05`, pushed; backend prompt change -> server restarted via launchd):
- UI round 3 (`012dd05`, pushed; backend prompt change -> server restarted via launchd):
  - Screen fit: left rail appears >=1024px (was >=1100) and the top tab strip is
    `display:none` >=1024px (the rail's 13-button nav — active state + badges — is the
    navigator; strip clicks still work via `switchTab()` since programmatic `.click()`
    fires handlers on hidden elements). Right rail + docked chat move to >=1280px
    (was >=1360); columns narrower (`minmax(176px,206px) | 1fr | minmax(264px,288px)`);
    `.main` padding `clamp(16px,3vw,28px)`; rails `max-height: calc(100vh - 96px)`;
    floating chat panel `max-height: min(460px, calc(100vh-96px))`; docked panel
    `min(400px, calc(100vh-190px))`, chat box `min(320px, calc(100vh-280px))`. Tab strip
    `flex-wrap: wrap` below 1024 (no more invisible sideways scroll). Playwright: zero
    horizontal overflow at 375/1024/1280/1366/1440/1920; rail-nav verified to switch
    every tab with the strip hidden (pages 24 rows loaded via rail click at 1280).
  - Chat replies: `CHAT_FORMAT_RULE` constant in `chat_service.py` appended to
    SYSTEM_PROMPT + GENERAL_SYSTEM_PROMPT (verdict sentence first, <=8 dash bullets,
    numbers inline, NEVER markdown tables/pipes/**bold**; full-site chat system =
    SYSTEM_PROMPT + FULL_SITE_PROMPT so the rule reaches it). Frontend safety net:
    `renderBotReply()` (app.js) used for bot messages — escapes first (XSS-safe),
    collapses stray `|` table blocks into `<details class="chat-collapse">Full
    breakdown</details>` with `.chat-table`, `- `/`* ` runs -> `.chat-bullets` ul/ol,
    `**bold**` -> strong, URLs -> links. New tests
    `backend/tests/test_chat_format.py` (5); suite 354/354; node --check clean;
    live-verified injecting the real markdown reply (2 collapsible tables, 3 bullets,
    1 strong, 1 link, zero raw pipes/asterisks, zero console errors).
- UI round 2 (frontend-only, no backend change, no server restart needed):
  - Full rails: `.main` 1120 -> 1440px; `#dashboard-grid` wraps results: 1-col <1100px,
    2-col `232px + 1fr` >=1100px, 3-col `232px + 1fr + 308px` >=1360px. Left rail
    (sticky): job context card (`renderRailJob` — health ring as conic-gradient from
    `summary.summary.score`/`metrics.score` when it's a number, else NO ring; pages /
    content items / actions lines), quick nav (`buildRailNav` mirrors all 13 tabs,
    active state + per-tab count badges via `setTabBadge` — lazy, set when each
    loader succeeds; `999+` cap; hidden when 0), per-tab explainer
    (`TAB_GUIDES` map, refreshed in the tab click handler + `switchTab`), static
    Tip of the day (rotates by day-of-month). Right rail: Live activity feed
    (`pushActivity`, severity dots ok/info/warn/err, cap 20, honest empty state —
    fed from `pollJob` progress_message ticks + failed/broken alerts on loadLogs),
    chat dock (`#chat-dock`): the SAME `#chat-widget` node is DOM-moved between the
    rail and `document.body` by `applyRailMode()` on a `(min-width:1360px)`
    matchMedia change — single instance, panel auto-opens when docked unless the
    user closed it (`chatUserClosed`), floats as before below 1360), quick links
    (Report / SEO Insights / Competitors / Quality / Schedules / Settings / New
    Analysis). `body.app-wide` toggled for docked-chat CSS.
  - Crawl screen: progress card gains phase chips (Queued → Crawling → Analyzing →
    Done; `updateCrawlPhase` from job.status + `current_stage`; done chips for
    passed stages, `.fail` on Analyzing when failed), live stats strip
    (`#crawl-stats`: pages crawled = real `pages_crawled`, pages/min = derived from
    tick deltas, elapsed = client-side timer from first tick, last URL = parsed
    from progress_message only when it contains a real URL, else "—"), and a 2-col
    `.progress-info` zone below (static "What the audit checks" checklist from the
    landing copy + 5-item static SEO FAQ accordion: partial audits, not-measured
    checks, timings, redirects, competitor block). `#progress-pages` element
    removed (n/a to pollJob/showProgress). Crawl screen verified mid-run on
    example.org (stages through site_health in ~41s; queued → analyzing → done
    transitions observed; zero console errors).
  - Per-tab polish: Overview content-type cards are clickable (jump to Content tab
    + set the type filter; only when the type is a valid filter option and job open);
    Quality tab gains Expand All / Collapse All buttons (toggle `open` on
    `#quality-content .audit-card`); SEO Insights Overview History gains a sparkline
    of the monthly `traffic_sum` series (`sparkline()` helper, inline SVG, only when
    >=2 numeric points, else honest "—"); rail nav badges wired into loadPages /
    loadContent / loadActions / loadSites / loadSchedules / loadLogs /
    loadCompetitors / loadQuality success paths.
  - Dead Chart.js CDN tag removed from index.html (was never used — zero
    `Chart`/`analytics` refs remain in frontend/).
  - Verified via Playwright (port 8001): 1440px — both rails visible, 13 rail nav
    entries, job card + ring, badges populated/updating (pages 261, content 807,
    actions 999+, sites 4), chat docked inside right rail (bounding-box check,
    panel fills slot), tab explainer + rail active state for all 13 tabs, quality
    expand/collapse (15 cards), theme toggle flips body bg (245,247,251 ↔
    11,18,32), no horizontal overflow; 375px — rails hidden, chat floats, crawl
    dashboard (4 stats, 2 info zones) no overflow; reduced-motion landing renders;
    zero console errors everywhere (checked 3 viewports). Layout geometry checked
    programmatically (this model cannot view screenshots). Test jobs
    (example.com/org/net) hard-deleted after verification; Sites list back to
    zuigo.ai + fluidcontrols.com × 2.
  - Deferred (in "Next up"): keyboard shortcuts; deeper per-tab widgets (ratio
    rings, run-now on schedules, status-chip filters on Pages/Links) — skipped to
    stay frontend-only + honest with data shapes that exist today.
- REAL BUG FIXED (found mid-run): `crawler.py::fetch_page_text` referenced undefined
  `REQUEST_TIMEOUT` (NameError) — every plain-fetch fallback crashed, so ALL
  competitor crawls died with "Competitor crawl returned no pages" and the first
  batch (5x) errored out. Fixed: `REQUEST_TIMEOUT = 15` module constant.
- Timed-out giant crawls now produce HONEST partial reports instead of dead
  errors: `audit_competitors` outer wait was the same 1200s as the crawl cap, so
  the whole audit died (and deleted the ephemeral job) right when a big crawl hit
  its cap. Now `competitor_audit_headroom_seconds = 2400` (config) extends the
  outer budget to crawl-cap + analysis headroom; the inner crawl cap still
  interrupts at 1200s and `_analyze_one` proceeds with the crawled slice
  (`status: partial`, pages_analyzed, "[crawl] timed out ... partial data").
- Re-ran competitor analyses on `6294eef9` (fluidcontrols.com) after clearing all
  rows: swagelok.com completed (400 pages), parker.com blocked (robots 403),
  tu-lok.com partial (163 pages, crawl cap), divineengg.in completed (68),
  stauff.com completed (400). `/report` returns all 5; SEO Insights tracked
  competitors = exactly these 5 (CACHE_VERSION 14 -> 15). Playwright: 5 cards,
  zero console errors.
- Ops note: after a worker kickstart arq may re-queue interrupted tasks — flush
  `arq:*` redis keys before re-enqueueing to avoid duplicate concurrent audits.
- (Earlier: truthfulness round committed `d9690ce`; report/links round `fe8c9a5`.)
- Links tab redirects made honest: "Ends in redirect (301/302)" (true 3xx bucket,
  was 0 for live job) split from "Followed redirects" (links that redirected then
  resolved, was 152 — previously shown under a "301/302" label). All Links table
  gains a "Redirected to" column showing `final_url` when `redirect_count>0`
  (tooltip = full chain).
- Unchecked links explained: `/api/links/{job}/all` returns `unchecked_count`;
  frontend always renders an amber note (count + "recovered from crawl, not yet
  verified — run Check Links") whenever >0, regardless of which 200-row page is
  shown (was: note only when the current page happened to contain one).
- SEO Insights keyword cleanup: `keyword_engine.MODIFIERS` drops merchant-tone
  terms (price/oem/for sale/wholesale/exporter), variants capped at 3 per stem
  (`MAX_MODIFIERS_PER_PHRASE`), `overview` added to GREEDY_SLUGS + TITLE_STOP;
  CACHE_VERSION 11 -> 13. Live: site terms are now union/union manufacturer/union
  supplier/union manufacturer india + railway family; no "for sale" junk.
- SEO Insights competitors: SE Ranking rows sorted by `domain_relevance` desc;
  tracked/organic entries with zero overlap render an amber "No keyword-overlap
  data — not verified as an organic competitor; check the Competitors tab" note
  instead of looking like verified matches.
- Duplicates evidence: Site Health "Duplicate Content & Canonicals" card now
  lists the actual duplicate groups (URL pairs linkified, similarity label, cap 5
  per group) via a new optional `evidence` block in auditCard.
- 349/349 tests (4 new: unchecked_count, merchant-tone drop + 3-cap, competitor
  relevance sort), node --check clean, live-verified on `6294eef9` (Playwright:
  both redirect cards, REDIRECTED TO column, amber unchecked note w/ 77, duplicate
  groups (59) evidence, no merchant keywords, no-overlap chips, zero console
  errors). (Earlier: report/links round committed `fe8c9a5`.)
- Report tab: standalone Indexation block and the Image-Optimization "Occurrences"
  stat card removed (image audit keeps Unique / WebP-AVIF / Without-dimensions /
  lazy counts; chat verdict no longer cites "occurrences"). Flow Count now means
  TRUE distinct funnel pages per target (depth 2 = unique `intermediate_url`,
  depth 1 = unique `start_url`) via `$addToSet` aggregation in
  `backend/services/user_flow.py`; `detect_user_flows` re-run on live job
  `6294eef9` (12,172 flows, top targets now 101 distinct vs fake 1429 before).
- Links tab: external links are now actually visible. Root cause: old
  `link_health` rows carry no `external` field. New `scripts/backfill_link_external.py`
  inserts missing external targets as `status:"unchecked"` rows (ran for
  `6294eef9` and `1c460760`: +77 external rows each, 533->610 total; DB rows
  keep the flag, so the fallback is only for jobs never backfilled). Route
  fallback in `links.py` all_links: when zero flagged rows exist, derives the
  external set from `page_links.external_link_urls` (normalize_url) and
  re-filters; `external=true` API + filter dropdown + gray "Unchecked" badge +
  "Run Check Links" hint for stale rows. 346/346 tests, node --check clean,
  live-verified on `6294eef9` (external=true -> 77 rows, 0 console errors).
  (Earlier round: Actions dedupe with per-issue groups + batch issue_key,
  committed `94bb3fb`.)
- Round (latest): blocked competitors now yield full partial reports
- UI/backend overhaul round (full suite 342/342, node --check clean, live-verified on
  `6294eef9`):
  - Pages tab: Links column REMOVED (crawler summary still stores counts).
  - Links tab: full collapsible rows (`details`), external-link filter option,
    external badge + explainer; "Link Occurrences" card kept honest.
  - Contributors of SEO Actions: Expand All / Collapse All buttons
    (`#expand-all-actions-btn`/`#collapse-all-actions-btn`); each action card
    now a `<details>` with evidence linkified + capped at 8 items.
  - Analytics tab REMOVED entirely (nav, `#tab-analytics` block, Chart.js CDN,
    all chart helpers `renderSingleAnalytics`/`renderAnalyticsCharts`/
    `chartInstances`/`destroyCharts` etc.; zero `Chart`/`analytics` strings
    in frontend/; VALID_TABS updated).
  - Alerts tab: Audit Trail section + `audit-event-filter` REMOVED; loadLogs
    renders alerts only.
  - SEO Insights: every section is now `<details class="insights-section"
    open>` + "How to use SEO Insights" explainer at top + per-section
    explainers (keywords, SERP); image accessibility card group (unique
    images, missing-alt, alt coverage %, pages with images) with accurate
    per-image counts from image_optimization audit; `renderCompetitors`
    shows tracked competitor cards (from competitor_gap_analyses, merged via
    external_insights with filters on job_id+status+domain) with "tracked"
    badge, status badge (partial/blocked), shared_keywords chips (capped 8);
    `loadTrackedCompetitors` + `#tracked-competitors-list` removed.
  - REAL BUGS FIXED (found by new tests): `external_insights.py` competitor
    merge crashed on missing `get_db` import (silently swallowed, so tracked
    competitors never merged) and dedupe seeded from `se_names` (filtered out
    every SE Ranking lookalike; now `tracked_names` only).
  - Keywords section merged smart site-derived terms: `fetch_all_insights`
    prepends `get_smart_keywords(use_llm=False)` output (flagged
    `site_derived: True`); frontend renders "site term" chip for them.
    `routes/seo_insights.py` CACHE_VERSION 5 -> 11 (multiple bumps).
  - `keyword_engine.py::slug_phrases` noise filters: strip file extensions
    (`.pdf .mp4 ...`), skip numeric-part-number leaves (e.g. `/pn-03/` ->
    "pn"), skip single-word phrases that are just modifiers (india/price/oem),
    skip slugs ending in a generic section word, GREEDY_SLUGS extended
    (randd/rnd/uk/usa/awards/certifications/quality/team/careers/clients/
    partners/gallery/downloads/videos/manuals/tenders/csr/...). Live keywords
    now exact-match product terms ("union manufacturer india",
    "double ferrule fittings", ...) + SE Ranking volume terms.
  - Reliability pack for competitor scans (HTTP-first crawl, 400-page cap,
    20-min/competitor timeout -> `partial` status with error text, `blocked`
    on robots-403, stale-row recovery, frontend poll 60 min) shipped
    previously; live job shows parker.com `blocked`, swagelok re-crawl,
    status badges + Retry buttons.
  - New tests: `backend/tests/test_ui_overhaul_round.py` (15) — slug_phrases
    modifiers/part-numbers/extensions/generic-tail; keyword_engine smart
    merge in seo-insights route; fetch_all_insights competitors
    merge/dedupe/degradation (partial rows, blocked), keywords site terms
    prepend + no-dup; local_insights/image_optimization host patched via
    module attr (bound import) not just `backend.db.mongo.get_db`.
  - Live-verified via API + Playwright (seo-insights: 12 site-term chips +
    15 keyword cards + 9 collapsible sections; competitors: 12 cards with
    tracked badges, 93 gap cards + Retry btns, zero console errors).
- Round (latest): blocked competitors now yield full partial reports
  (committed `4bfed03` recapped below). Bot-blocked competitors (≤1 page
  crawl, e.g. parker.com) produce a FULL partial report instead of being
  skipped after the status was set:
  - `_analyze_one` runs the shared SE-Ranking+SERP block first
  (baseline + `_serp_keyword_gaps`/`_serp_features_gap`/`_backlink_gap` via
  cached target keywords from `extract_keywords_from_content`) and only then
  branches: blocked → stub crawl-gap dicts with "Crawl blocked; ... not
  measured" errors; else → full crawl chain (analyze_pages/check_links/
  compute_site_health/fetch_performance/audit_structured_data/content-gap
  dicts). `se_rich` (opportunity score + recommendations) computed in both
  paths; result status `blocked` when blocked.
  - `config.py` gains `competitor_timeout_seconds: int = 1800`; `run_one`
    uses it (30-min per-competitor cap; error message now "...(30-minute
    limit)").
  - `GET /api/competitors/{job}/report` accepts status `{"$in":
    ["completed", "blocked"]}` so the sectioned JSON report includes blocked
    competitors.
  - Frontend `renderCompetitorGaps`: blocked rows render the full report card
    with an amber "Blocked crawl — partial report" badge + note ("report
    below is SE Ranking + SERP data only") + Retry button (was: dead-end
    error card).
  - Tests `test_competitor_blocked.py` now 4 (patched fixture mocks
    `_target_baseline`/`_se_rich_gap`/`_serp_*/`_backlink_gap` +
    extract_keywords import; blocked tests assert se_rich + keyword/backlink
    gaps survive; new report-route test with `$in` FakeDb.find support).
    Full suite 327/327.
  - Live-verified on `6294eef9-1f42-4974-babb-170165f7736f`: parker.com →
    `blocked` with se_rich opp 100, backlink_gap domains, traffic/authority
    sections; Swagelok re-crawling (will hit 30-min cap legitimately);
    Playwright verified badge + Retry on the live card, zero console
    errors.
  - Committed as `4bfed03`; pushed.
- Round (earlier): competitor audits that "silently completed" ... (previous
  status below) — blocked-status fix committed `8a0fa7e` (marked `blocked`
  with errors, early return before SERP/SE spend, `$unset` stale errors on
  rerun, blocked card with Retry).
- Round (earlier): Competitor analyses were stalling in `running` status when a single large site (e.g. `swagelok.com` 1,000 pages) took over 30 mins, holding faster competitors (`parker.com`, `hydac.com`) blocked in `asyncio.gather` memory without writing their `completed` status to MongoDB.
  - Fix 1 (Incremental Persistence): `_analyze_one` and `run_one` now immediately persist each competitor's completed result to MongoDB as soon as it finishes, allowing frontend polling to surface completed competitors immediately.
  - Fix 2 (15-min Per-Competitor Timeout): Wrapped `_analyze_one` calls in `asyncio.wait_for(..., timeout=900)`. If a competitor exceeds 15 minutes, it is cleanly saved with `status: "error"` without blocking the rest of the batch.
  - Fix 3 (DB Cleanup): Cleaned up stale `running` competitor rows and ephemeral jobs from past worker restarts.
  - Tests: Full suite 307/307 passing.
- Committed last as `412d33d`; prior round pushed as `1cd70c4` (competitor
  gap report); this round pushed as `d8bf1fc`.

### SE Ranking competitor gap report (this round)
  - `competitor_audit.py::_se_rich_gap(target_domain, comp_domain,
    target_job_id)`: reads TARGET's cached `seo_insights_cache` (no extra
    SE Ranking spend) and fetches COMPETITOR live best-effort per-key
    (`domain_overview`, `domain_keywords(50)`, `ranked_keywords(50)`,
    `backlink_summary`, `domain_overview_history`, `backlink_list(50)`,
    `keyword_gap`); per-key `errors` collected. Computes `keyword_analysis`
    (shared / missing_from_target / unique_target / missing_detail
    [volume+cpc+difficulty] / shared_detail [target vs comp vol/cpc/KD] /
    top_opportunities = competitor's highest-volume keywords target misses),
    `traffic_analysis` (incl. `traffic_value_estimate` = SUM volume×CPC over
    comp `domain_keywords`), `backlink_analysis` (+ high_authority_sources
    domain_inlink_rank<20), `authority_analysis` (domain/page rank deltas).
    `_opportunity_score` (0-100: kw-opportunity 0.4 · traffic-growth 0.3 ·
    RD-delta 0.3; None when no comparable metrics) + `_build_recommendations`
    (rule-based, high/med/low sorted).
  - Wired into `_analyze_one` → stored as `se_rich` in
    `competitor_gap_analyses`; failures caught & logged (doc still writes).
  - `build_competitor_report(row)` assembles named sections
    (executive_overview, keyword, traffic, content, backlink, authority,
    serp, on_page, ux, schema, technical, insights, source_report); empty
    sections stay honest. New `GET /api/competitors/{target_job_id}/report`
    (completed only, registered BEFORE `/{target_job_id}/{competitor}` so
    route wins).
  - Frontend `renderCompetitorGaps` rewritten as a professional sectioned
    report per competitor: KPI strip (opportunity badge, pages, traffic "you
    → them", keywords, gap count), Keyword Analysis table (opportunity
    volume/CPC/difficulty + shared overlap table + SERP chips), Traffic
    table, Backlinks & Authority table (you lead / competitor ahead / tie),
    high-authority source chips + SERP-derived sources, Content + schema
    lists, SERP features, Technical/On-page/UX delta grids, Insights &
    Recommendations. Helpers: `_fmtNum`, `_fmtMoney`, `_oppBadge`, `_pairRow`,
    `_deltaCard`, `_deltaGrid`.
  - Live-verified on job `d14e24df` (fluidcontrols.com) competitor hydac.com
    re-crawl: opp 100, traffic 141→4628, traffic value 54.2k, backlinks delta
    118k, DR 46/78, 5 recs. Playwright zero console errors.
  - Tests `backend/tests/test_competitor_gap_report.py` (6 new): _se_rich_gap
    assembly with FakeDb + monkeypatched se ranking fns, per-key degradation
    (7 errors), traffic_value_estimate, opp+recs, report assembler, empty row.
- All prior rounds below (SE Ranking sole paid provider, etc.) unchanged.
  - Cannibalization fully removed (`rg -ri cannibal backend/ frontend/` = 0):
    deleted `services/cannibalization.py`; pipeline stage, summary key,
    quality route, site_health block, exec_summary entries, chat/sites
    refs, frontend stats card/report section/quality card all removed.
  - `logsEl is not defined` fixed: dead `logsEl`/`appLogs` refs removed
    (`rg -n logsEl\|appLogs` = 0); `loadLogs` catch renders into
    `alertsEl`.
  - Analytics tab handles no-study, empty history, single-analysis KPI
    cards, multi-analysis charts, keyword charts only with >=2 points.
  - Competitors: parallel batches `Semaphore(2)`, cancel resets
    running→queued, dedupe enqueue, 30-min frontend poll cap \
    (`competitorPollDeadline`), running cards surface errors.
  - Exact content counts: `content_items` unique per
    (job_id, content_type, source_url); `ensure_indexes` unique index in
    `db/mongo.py` (degrades to non-unique on duplicate); classifier
    dedupes per resolved URL, skips `data:` URIs, `<source>` only inside
    `<picture>`; image_optimization uses same URL-resolved dedupe so
    `total_images` == `content_breakdown.image`; crawler dedupes
    video_embeds by download URL + DuplicateKeyError guard.
    `scripts/dedupe_content_items.py` one-time migration for existing
    jobs (dedupes content_items + orphans content_extractions).
  - Report: raw "SEO Action Items" section + `seo_action_items`/`action_items_list`
    JSON key removed (report kept Quick Wins / Long-Term Improvements /
    Content Versions / Overview + KPI bars); `action_items` var is still
    fetched into `_report_html` for exec/recommendation rendering.
    Evidence guarantee lives in `seo_analyzer._make_action`, which returns
    `None` (skips with a warning) whenever `check.evidence` is empty, so
    every stored action has real evidence; Actions tab surfaces the
    Evidence block per action or a red "No evidence recorded" note.
  - Crawl speed: link_checker CHECK_CONCURRENCY 10→20, REQUEST_TIMEOUT
    12→7, geo_alignment parallel via Semaphore(8), PSI sample cap
    `settings.psi_page_sample` = 20 (was all pages), mobile sample cap
    `settings.mobile_sample_pages` = 20 sorted by smallest `click_depth`,
    classifier/crawler/image_opt dedupe. Live fluidcontrols.com (261 pg)
    crawl time cut substantially; reports still render identical content.
  - Email reports: SMTP config DB `app_settings` key `smtp` first (`GET/PUT
    /api/settings/smtp`, masked), `.env` fallback (`smtp_host/port/user/
    password/from/use_tls` in config.py + .env.example); `notifications.py`
    `get_smtp_config`/`send_email` (smtplib in asyncio.to_thread)/
    `email_report(job_id, to)` builds branded PDF via reports `_render_pdf`;
    `POST /api/reports/{job_id}/email`; Analyze form optional `email` field
    (success + failure alert emails); Settings tab SMTP section; Report tab
    "Email report" button. Without SMTP configured the endpoint 502s with a
    clear message (tested live).
  - Crawl-progress live view: crawler writes `current_stage`/
    `pages_crawled` into the job doc on every progress tick; progress
    card shows animated `%`, "Live" pulse dot, stage title (Crawling... /
    Running audit...), and "N pages crawled" line.
- SE Ranking is the sole paid insight provider (DataForSEO removed) — see below.
- DataForSEO removal + SE Ranking expansion round (committed, was working tree; full suite 285/285):
  - `services/dataforseo.py` and `services/competitor_gap.py` DELETED. SE Ranking
    (api.seranking.com/v1) is now the sole paid insights provider for: domain
    overview + organic traffic estimates, organic keywords, paid keywords
    (`domain/overview/db`), keyword gap (`domain/keywords/comparison` diff=1),
    competitors (`domain/competitors`), backlink overview (`backlinks/summary`),
    backlink sources (`backlinks/all` per_domain=1 ordered by domain_inlink_rank),
    referring domains (`backlinks/refdomains`), anchors (`backlinks/anchors`),
    top pages (`backlinks/indexed-pages`), page/domain authority
    (`backlinks/authority` inlink_rank/domain_inlink_rank), authority history
    (`backlinks/authority/domain/history` by_month), new/lost backlinks
    (`backlinks/history` -> new_lost_backlinks, `backlinks/history/count` ->
    new_lost_backlinks_count). Region `source` param is added for `domain/*`
    endpoints only (NOT backlinks/*). 100 credits per domain request.
  - NEW `services/external_insights.py`: `fetch_all_insights(domain, job_id)`
    orchestrator (se-ranking -> local per section; onpage = local crawl only;
    best-effort extras with `*_error` keys; GSC override block; SERP via
    serp_api with se_ranking.ranked_keywords fallback) +
    `merge_gsc_into_insights` moved verbatim from dataforseo.py.
    `routes/seo_insights.py` CACHE_VERSION 3 -> 4.
  - config.py: dropped dataforseo_login/password/cost vars; spend_tracker.py:
    dropped "dataforseo" rate. `backlinks.py::fetch_backlinks`: SE Ranking
    `backlink_list` (limit 100, source_api="se-ranking") first, SERP `link:`
    fallback.
  - Frontend: all DataForSEO strings gone (insightErrorKind titles, credits/
    disabled error blocks, sourceLabel map, Labs sample note). SEO Insights
    gains: Overview History table, Top Organic Competitors cards, Backlink
    Profile section (authority cards, referring domains, anchor texts, top
    pages, authority history, new/lost + daily counts tables). Settings text
    now describes SE Ranking as the sole provider.
  - reports.py: methodology rows now name SE Ranking + competitors/overview
    history rows; Backlinks card gains profile rows (authority, top refdomains,
    anchors, top pages, new/lost); Domain Insights gains overview history,
    competitors and authority history tables (`td.subhead` style added).
  - Tests: `test_dataforseo_resilience.py` DELETED (11); `test_se_ranking.py`
    rewritten (26 tests: retry/hints/mapping for all new endpoints +
    external_insights chain tests); `test_gsc.py` imports merge_gsc_into_insights
    from external_insights. Suite 283 -> 285.
  - README.md updated (features, services list, env table); ServiceError +
    competitors.py docstrings cleaned. `rg -ri dataforseo backend/ frontend/` = 0.
  - LIVE VERIFY PENDING (see Next up): launchd restart + refresh job 24fd33f6.
- programmatic-seo + ai-seo skill integration round (working tree; full suite 283/283):
  - Skills installed: `~/.agents/skills/programmatic-seo` (SKILL.md v2.0.0) and
    `~/.agents/skills/ai-seo` (SKILL.md v2.2.0) via
    `npx skills add coreyhaines31/marketingskills --skill <name> -a opencode -g --copy -y`
    (interactive TUI hangs; the `-a opencode -g --copy -y` flags make it non-interactive).
  - `services/programmatic_seo.py` (NEW): `url_pattern(url)` collapses the leaf
    path segment (and any numbers / ≥8-hex / >60-char segments) to `{slug}`
    (root and <2-segment paths -> None); `detect_clusters(pages)` groups 3+ pages
    sharing a pattern; `audit_programmatic_seo(job_id)` upserts
    `programmatic_seo_audits` — score + 4×25 subscores (structure/content_uniqueness/
    internal_linking/indexation), checks (cluster detected, thin <150 words,
    near-duplicates via duplicate_content.duplicate_groups, internal linking via
    orphan_pages, sitemap coverage), clusters rows (pattern/page_count/thin_pages/
    duplicate_pages/unlinked_pages/sample_urls), template_pages/total_pages/
    template_page_share/thin/duplicate/unlinked/duplicate_title/not_indexable counts.
  - `services/ai_visibility.py` extended IN PLACE (kept 4×25 subscore model; new
    signals land as checks + summary keys): `TRAINING_ONLY_AGENTS={"ccbot"}`,
    `ANSWER_BLOCK_WORDS`/`DEFINITION_BLOCK_WORDS`/`FRESHNESS_DAYS=183`;
    new probes `/pricing.md`, `/pricing.txt`, `/okf/`; page scan up to
    `MAX_SCAN_PAGES=50` with `_ai_extractability(html)` -> answer_block/
    definition_first/faq_heading/comparison_table/stat_cited/author/fresh/
    semantic_landmark keys; new summary keys (pricing_md_present, pricing_txt_present,
    okf_present, scanned_pages, answer_block_pages, definition_first_pages,
    faq_heading_pages, comparison_table_pages, stat_cited_pages, author_pages,
    fresh_pages, semantic_landmark_pages, blocked_training_agents) + 4 new checks
    (machine-readable pricing, answer blocks 0.3 ratio, author 0.3 ratio, freshness
    0.3 ratio) + CCBot-blocked info check; fixed `ai_extract`->`ai_ext` NameError.
  - Pipeline: wave2 `_stage("programmatic_seo", ...)` in analysis.py; summary dict
    gains `programmatic_seo`.
  - site_health merge: pseo metrics (template_clusters/template_pages/
    thin_template_pages/duplicate_template_pages/unlinked_template_pages/
    programmatic_seo_score) + medium/high issues; ai_visibility merge extended
    with pricing_md / author issues.
  - exec_summary: keys `programmatic_thin`, `programmatic_duplicates`,
    `programmatic_linking`, `ai_pricing_md`, `ai_eaat_signals` in EFFORT/TITLES/
    EXPLANATIONS/HOW_TO_FIX/ISSUE_KEY_FROM_MESSAGE + `_evidence_for` branches.
  - chat_service: `PROGRAMMATIC_SEO_GUIDANCE` + `AI_SEO_GUIDANCE` constants
    (vendored from the skills, marketing-skills, MIT) wired into SYSTEM_PROMPT /
    GENERAL_SYSTEM_PROMPT / FULL_SITE_PROMPT section list; `_programmatic_seo_context`
    + `_ai_seo_context` builders; aliases programmatic-seo/programmatic/templates/
    template and ai-seo/ai-visibility/ai_search/ai.
  - quality.py: `GET /{job}/programmatic-seo`. sites.py hard-delete list extended
    (programmatic_seo_audits, sitemap_audits, ai_visibility_summaries,
    local_seo_summaries, cannibalization_summaries, hreflang_audits,
    url_hygiene_audits, indexation_audits, image_optimization_audits,
    exec_summaries, serp_cache).
  - reports.py: `programmatic_html` section (score + 4 subscore bars + cluster
    table + checks) appended to `_report_html`; `ai_html` extended with blocked
    agents + machine-readable files row + scanned/author/freshness line.
  - app.js Report tab: AI-Search Visibility block adds AI files row + author
    attribution + scanned-page note + training-crawler note; new Programmatic SEO
    block (3-col stats + 4 subscore bars + clusters table w/ sample links +
    checks). `node --check` clean.
  - Tests: `backend/tests/test_programmatic_seo.py` (12 new) +
    `backend/tests/test_ai_seo_extras.py` (8 new); full suite 263 -> 283.
  - Live-verified on `24fd33f6` (fluidcontrols.com): pseo score 84, 18 clusters,
    177/261 template pages (e.g. `/products/fittings-and-connectors/
    double-ferrule-fittings/{slug}/` 53 pages); ai score 50, 8 checks, scanned 50
    pages, author/fresh/pricing/okf as expected; endpoints return doc; HTML report
    + PDF (200, ~2.7MB) include both sections. Services restarted via launchd.
  - QA NOTE: FakeDb test stores must put `job_id` inside seeded value dicts or
    `find_one({"job_id": ...})` returns None (2 tests hit this); `_fetch_plain`
    monkeypatch in tests must be an async func (ai_visibility awaits it).
- UI privacy + Analyze page round `9f8f5f2` (pushed, frontend-only): NO
  customer data may appear on the public landing (`/`) or Analyze (`/app`)
  pages — the app is unauthenticated today, so anything rendered there is
  visible to anyone. Dropped the planned "recent analyses" section
  (would have leaked real job domains); instead:
  - landing.html hero mock: `fluidcontrols.com` -> fictional `yoursite.com`
    with a `Sample report` chip (`.mock-stage`/`.mock-sample`); no real
    customer referenced anywhere in frontend (verified `rg -ni fluid`).
  - index.html `#input-section` rebuilt (SEOmator-style): privacy-safe
    example chips (example.com IANA-reserved, books.toscrape.com public
    demo), "Run free site audit" CTA, "What the audit checks" 6-card
    feature grid, 2-column 12-item checks checklist, 3-step how-it-works,
    one-line privacy note. All static text; zero `/api/sites` calls.
  - style.css: `.privacy-note`, `.analyze-section/.analyze-checks/
    .analyze-how`, `.checks-grid` (2-col -> 1-col under 600px).
  - Verified: node --check clean; Playwright landing (yoursite.com +
    Sample report, 4 count-ups) and /app (2 examples, 6 features,
    12 checks, 3 steps, privacy note, CTA; example-chip submit starts a
    job; zero console errors). Test-generated example.com job deleted.
- M6 (LAST milestone of the M1-M6 plan) `94d961f` (pushed): apply-actions flow
  replaces the dummy-site demo. 263/263 tests.
  - `POST /api/actions/{job}/apply`: builds approved changes via shared
    `_collect_changes` (refactored out of `export_patch`), pushes a GitHub PR
    when a token is configured (`notifications.create_github_pr`), otherwise
    returns an in-repo markdown guide (`build_apply_guide` — export patch,
    branch, replace before->after per approved change, push, merge). Reasons:
    `no_approved` / `no_token` / `github_pr` / `pr_failed`; `log_audit`
    `actions_applied` on PR attempts.
  - GitHub settings: `GET/PUT /api/settings/github` (masked token,
    `token_set`); Settings tab section (repo-scope PAT, repo named after
    domain e.g. `example-com`); `get_github_config()` in notifications.py
    (DB-first app_settings doc key `github`, `.env` fallback);
    `create_github_pr(domain, changes, token=None)` — explicit token param.
  - Dummy-site UI entry points REMOVED (M1d): Links tab "Dummy Parallel
    Site" section + `loadDummySite()`/call + approve-all/hard-delete text.
    Backend `/api/dummy` routes + `services/dummy_site.py` KEPT (smoke +
    test_phase4/test_patch still use them); the 3 `regenerate_after_change`
    hooks in actions.py were left in place.
  - Actions tab: "Apply via GitHub PR" button + guide card
    (`renderApplyGuide`); `escapeHtml`-safe <pre> guide.
  - Tests: `backend/tests/test_apply_changes.py` (13 new; suite 250 -> 263):
    build_apply_guide (approved-only, empty), apply endpoint all 4 branches
    (FakeDb from test_patch + monkeypatched notif.get_github_config /
    create_github_pr), github settings read/put/empty-noop (masked), DB-first
    vs env-fallback config, explicit-token PR uses Bearer ghp_explicit.
  - Live-verified on `24fd33f6`: apply -> `no_approved` (1000 pending),
    patch md/json export unchanged after refactor, Settings tab shows GitHub
    section ("Not configured yet"), Actions tab apply button + hidden guide
card render, no dummy references, Playwright zero console errors.
- M1+M2+M3 round `c8aac33`, M5 round `1062bf9` (both pushed): honest counts
  (unique images/occurrences, video_embed classification), metadata-only
  crawl (~10 min vs 16.6 for fluidcontrols 261 pages), competitor reliability
  (domain normalization, stale-key migration, status lifecycle, retry,
  caps `competitor_crawl_max_pages=1000`/`competitor_psi_sample=10`,
  mobile=False for competitors), Site Health & Audits dashboard
  (renderSiteHealth + 16 audit cards + status chips), professional Pages tab
  (search/filter/sort/pagination via `GET /api/pages/{job}/all`).
- M4 round `289434c` (pushed): SE Ranking Data API provider.
  - NEW `backend/services/se_ranking.py`: `Authorization: Token` against
    `https://api.seranking.com/v1`; key/region from MongoDB `app_settings`
    doc key `se_ranking` (Settings page) with `settings.se_ranking_api_key`
    (.env) fallback (mirrors GSC); ~0.2s request throttle + 429/5xx retry
    (honors Retry-After, 3 attempts); error hints for missing key / expired
    license / insufficient funds / rate limit; `_record_usage` -> spend
    tracker (`se_ranking` added to `SERVICE_RATES`).
  - Functions (shapes matched to existing renderers): `domain_overview`
    (`domain/overview/db` -> estimated_organic_traffic/organic_keywords_count/
    paid_keywords_count), `domain_keywords` (`domain/keywords` organic, ordered
    by volume -> keyword_data.keyword_info shape), `ranked_keywords` (same
    endpoint ordered by position -> SERP rankings shape with rank + top url),
    `backlink_summary` (`backlinks/summary` mode=domain -> backlinks/
    referring_domains/referring_ips/rank/rich detail). `source` = "se-ranking".
  - Provider chain in `dataforseo.py::fetch_all_insights`: keywords
    dataforseo -> se-ranking -> local; overview dataforseo -> labs ->
    se-ranking -> local; backlinks dataforseo -> se-ranking -> local; serp
    rankings serp -> se-ranking ranked_keywords when empty/failed. Errors
    chained with ` | ` separators (e.g. "dataforseo: ... | se_ranking: SE
    Ranking API key not configured").
  - `routes/app_settings.py`: `GET/PUT /api/settings/se-ranking` (masked
    api_key + api_key_set + region, default "us"); Settings tab in index.html
    + loadSettings/save handler in app.js; `sourceLabel` map gains
    "se-ranking"; `loadSettings` also called when a job is open (settings tab
    now loads in job context — GSC status was previously blank there too).
  - Tests: `backend/tests/test_se_ranking.py` (13 new; suite 237 -> 250/250):
    retry-then-succeed, retries-exhausted, 401->key hint, insufficient-funds
    -> credits hint, region param injected from config, field mapping for all
    3 endpoints + ranked_keywords position filtering, missing-key raises,
    chain fallback tests (keywords/backlinks/overview to se-ranking and on
    full failure to local) with FakeClient + monkeypatched local/serp helpers.
  - Live-verified on job `24fd33f6` (fluidcontrols.com): refresh shows
    `keywords_source=se-ranking` (10 real keywords: vol/cpc/difficulty
    populated), `serp_source=se-ranking` (10 rankings w/ real positions);
    overview dataforseo-labs, backlinks dataforseo (both now live again);
    Settings tab shows masked key + Configured; Playwright zero console
    errors.
- Fix round `90fd0eb` (pushed): first real crawl (fluidcontrols.com 300 pages,
  job `088570da`) surfaced stored-key mismatches between the 4 new audit docs
  and their consumers:
  - `url_hygiene_audits.top_params` is a **dict**; the PDF report did
    `top_params[:6]` -> KeyError, 500 on `/api/reports/{job}/download` and
    `/pdf`; frontend `.map` on a dict silently dropped the section. Fixed in
    reports.py / app.js / chat `_url_hygiene_context` (normalize dict|list).
  - image_optimization_audits stores `total_images`/`modern_images`/
    `lazy_images`/`missing_dimensions` (NOT total_imgs/modern/lazy/dims_missing)
    — PDF said "0 images on page" for 9424. Fixed in reports.py / app.js /
    `_image_opt_context`.
  - url hygiene stores `uppercase_paths`/`underscore_paths` (not _slugs).
  - Added 4 chat-context regression tests (suite 222/222).
  - Live checks on `088570da`: all 4 stages ok (url_hygiene/hreflang/image_opt
    ~33s, indexation ~63s on 300 pages), hreflang not applicable (monolingual,
    score null), url-hygiene 40 (99 page_id params, 17 long slugs, 1 uppercase,
    4 underscore), image 15 (9424 imgs, 0 WebP, 2932 no dims), indexation
    unmeasured (credits hint); site_health metrics nested under `metrics` all
    populated; exec summary includes `image_optimization` issue; Report tab
    Playwright: 4 sections render with real data, zero console errors; PDF
    200 ~3MB.
- seo-audit skill integration round (committed `d9126b8`, pushed):
  - Skill installed: `~/.agents/skills/seo-audit/` (SKILL.md +
    references/international-seo.md) via `skills add coreyhaines31/marketingskills
    --skill seo-audit -a opencode -g --copy`; opencode picks up `~/.agents/skills/`.
  - `services/international_seo.py` (NEW): hreflang audit — self-referencing
    pages, x-default, valid codes (ISO 639-1 + ISO 3166-1 sets, KNOWN_BAD_CODES
    en-uk/es-419/pt-braz), reciprocal pairs, canonical-in-set, locale-in-URL
    structure, lang-parameter pages; `applicable` False when monolingual
    (score None); subscores 30/15/15/25/15; merges sitemap alternate stats;
    stores `hreflang_audits`.
  - `services/url_hygiene.py` (NEW): FACET_PARAMS (page/sort/filter/...),
    param/facet/lang-param counts, top_params, uppercase/underscore/long-slug
    paths, trailing-slash consistency; subscores 40/20/20/20; `url_hygiene_audits`.
  - `services/indexation.py` (NEW): `site:{domain}` SERP check via spend-tracked
    `search_keyword`; `status` measured (adwords-indexed estimate + top indexed
    pages) or `unmeasured` with credits hint on ServiceError; `indexation_audits`.
  - `services/image_optimization.py` (NEW): WebP/AVIF via src/srcset/picture
    (ancestor walk — lxml nests <img> inside <source>, so `parent.name` fails),
    lazy loading, explicit dimensions; subscores 40/30/30; `image_optimization_audits`.
  - `services/sitemap.py`: `_fetch_sitemap_entries` captures
    `<xhtml:link rel="alternate" hreflang>` into per-entry `alternates`;
    audit_sitemap aggregation adds `sitemap_alt_entries`/`sitemap_alt_codes`/
    `sitemap_missing_self_ref` (normalized self-check)/`sitemap_invalid_alt_codes`
    (via `is_valid_hreflang_code`, imported in-loop to dodge circular imports).
  - Pipeline: analysis.py wave1 stages `hreflang`, `url_hygiene`, `indexation`,
    `image_opt` (indexation needs SERP spend; degrades gracefully). quality.py
    GET endpoints `/api/quality/{job}/hreflang|url-hygiene|indexation|image-optimization`.
  - site_health: metrics (hreflang_score/locales, url_hygiene_score/param_pages,
    indexation_status/indexed_estimate, image_opt_score) + issues (multi-locale
    no-hreflang high, hreflang errors medium, facet params medium, image weak low).
    exec_summary: keys hreflang_errors/url_param_issues/image_optimization
    (EFFORT/TITLES/EXPLANATIONS/HOW_TO_FIX + ISSUE_KEY_FROM_MESSAGE substrings
    hreflang/faceted/pagination url/image optimization).
  - Frontend Report: 4 new loadReportExtras sections (hreflang incl. N/A case,
    url-hygiene top params, indexation measured/unmeasured, image-opt stats).
    PDF: 4 new branded sections in reports.py `_report_html`.
  - Chat: `SEO_AUDIT_GUIDANCE` constant (guidance vendored from the seo-audit
    skill, marketing-skills, MIT — attributed in the constant) wired into
    SYSTEM_PROMPT, FULL_SITE_PROMPT (now mentions new sections) and
    GENERAL_SYSTEM_PROMPT; `_hreflang_context`/`_url_hygiene_context`/
    `_indexation_context`/`_image_opt_context` builders added to full-site
    context + `_context_for_section` dispatch (hreflang/url-hygiene/indexation/
    image-optimization section names).
  - Tests: `backend/tests/test_international_extras.py` (20 new; full suite
    218/218) — FakeDb/FakeCollection pattern (find sync like Motor cursor),
    hreflang helpers + full audit cases (monolingual N/A, reciprocal pair
    scores 85 without x-default, invalid/one-way detection), sitemap xhtml
    alternate capture, URL hygiene counts, image modern/lazy/dims (picture
    source detection), indexation measured + ServiceError degradation,
    chat guidance + exec_summary key mapping.
  - Live-verified on example.com job `1707d895`: all 4 stages ok in /tmp/arq.log,
    endpoints return data (hreflang not applicable, url-hygiene 100, indexation
    unmeasured w/ credits hint, image 70/0 images), `/download` HTML + PDF 200
    include the new sections; services restarted via launchd.
- Professional audit extras round (working tree, committed as one round):
  fixes "0 pages crawled" plus professional Report/Overview/PDF sections.
  - `services/crawler.py`: normal analyses now call
    `crawl_site(seed_sitemap=True, unlimited=True)` -> BFS + XML-sitemap seed of
    every listed URL (fluidcontrols.com: 238 sitemap URLs seeded, 261 crawled),
    safety cap `competitor_crawl_max_pages` (5000); politeness delay honored;
    `page.goto` None/failure now falls back to an httpx plain fetch (records
    `failed_urls_count`/`failed_urls`), "Download is starting" pages are
    skipped (not fatal), module-level `_chromium_slots` Semaphore(2) caps
    concurrent Chromium instances so a big concurrent job can't starve another;
    last-modified/status use whichever fetch won. `run_analysis_pipeline` fails
    the job with a clear `error_message` instead of silently completing with
    0 pages crawled.
  - `services/sitemap.py`: rewritten — `_fetch_sitemap_entries(xml)` -> records
    `{loc,lastmod}`, expands nested sitemap indexes recursively (each child
    fetched once, dedup set), returns `[]` for empty urlset, `None` for
    non-valid / unknown-root XML; `audit_sitemap` builds a cross-file
    unique-URL set -> new stored keys `pages_in_sitemap`, `crawled_in_sitemap`,
    `crawled_coverage` (%), `missing_lastmod`, `http_plain_urls`,
    `pages_crawled`, `uncrawled_urls_count`/`uncrawled_urls`,
    per-file `results` with `lastmod_missing` (single fetch per candidate).
  - `services/ai_visibility.py`: rewritten — section-aware `_parse_robots`
    (multi-line directives, grouped User-agent lists, crawl-delay), agent
    `status` is only `blocked` for exact `/ | /* | /?` (partial otherwise) —
    kills the fake red flag from `Disallow: /wp-admin/`; structured data counted
    ONLY from `<script type="application/ld+json">` blocks (`_ld_types`);
    per-agent `ai_agents` rows, `subscores` (sitemap/llms_txt/structured_data/
    extractable_content each 0/25), `checks` (dicts), `schema_types`,
    `robots_status`/`llms_txt_status`; sitemap subscore falls back to an inline
    robots-sitemap probe when the `sitemap_audits` doc isn't written yet
    (wave1 ordering race fix).
  - `services/local_seo.py`: rewritten — JSON-LD parsed via `_iter_schema_objects`
    (handles @graph + nested dicts/lists), `_find_key` nested key search,
    NAP from LocalBusiness/Organization with contact info, geo detected ONLY
    from real `geo.*`/GeoCoordinates/latitude schema (no more "george" /
    "biogeography" false positives), `checks`, `subscores`, new stored keys
    `local_business_on_homepage`, `nap_inconsistent` + `naps_found`,
    `pages_with_local_schema`, `phone_pages`/`email_pages`/`geo_pages`/
    `opening_hours_pages`/`reviews_pages`.
  - `services/site_health.py`: local-SEO issue message now builds from
    `checks[i].label` of failed checks (old code did `", ".join` on strings —
    crashed the report once checks became dicts).
  - Report tab + Overview cards + branded PDF (all three sections): `app.js`
    `loadOverview` adds score mini-bars + "Pages Failed to Fetch" card and
    "NAP mismatch" hint; `loadReportExtras` renders sitemap coverage %
    + per-file table + uncrawled/lastmod/http-plain notes, AI score + subscore
    bars + agents table + checks ✓/✗, local score + subscore bars + NAP +
    signals + consistency warning; `routes/reports.py` `_report_html` gains
    "Sitemap", "AI-Search Visibility" and "Local SEO Readiness" sections with
    score bars and checks (CSS: `.bar`, `.checks`).
  - Tests: `backend/tests/test_audit_extras.py` (19 new; full suite 198/198):
    sitemap urlset/index dedup/nested-expansion/invalid-xml, robots
    exact-block vs partial vs allowed + crawl-delay, ld+json-only counting,
    local JSON-LD graph/nap/nested-key/homepage/geo-regex guards.
  - Live-verified on a fresh fluidcontrols.com job (`24ebac16`): 261 pages
    crawled (was 0), sitemap coverage 65% (195/300), AI score 50 (sitemap
    subscore fixed, `blocked_ai_agents: []`), local SEO 30 (no LocalBusiness
    schema — honest), Playwright Report tab shows all 3 sections with zero
    console errors, `/api/reports/{job}/pdf` = HTTP 200 ~2.7MB.
- All prior rounds DELIVERED (external-service resilience, GSC, SaaS front
  door, competitor-audit, complete-audit, professional report template). Latest
  commits pushed.
  - Resilience round (working tree): no more red "External service unavailable"
    banners above valid fallback data; retries + blacklist + SERP cache.
    - Probes (live, ~1 credit each): `keywords_data/google/keywords_for_site`,
      `keywords_data/google_ads/search_volume`, `dataforseo_labs/google/ranked_keywords`,
      `backlinks/summary` all return 200 + data when the account has credits;
      `domain_analytics/google/overview` and `on_page/summary` are HARD 404
      (not on plan). Account is CURRENTLY in payment-required state (HTTP 402 /
      task code 40200) so live DataForSEO calls fail until credits are topped up.
    - `services/dataforseo.py`: `_post` retries 429/5xx up to 3 attempts with
      backoff honoring `Retry-After`; in-memory 404/403 endpoint blacklist
      (`_BLACKLISTED_ENDPOINTS`, hint "not enabled on this plan", skips future
      calls); task code 40200 mapped to the credits hint; `_normalize_keyword_item`
      maps flat keywords_for_site items into `keyword_data.keyword_info` shape the
      renderer expects (also passes through nested labs items);
      `domain_overview_labs(domain)` synthesizes the domain overview from
      `dataforseo_labs/google/ranked_keywords` (organic traffic = summed clicks of
      top `limit` sampled keywords, `sample_n` flag, total = `total_count`) used as
      the middle tier: overview chain is now domain_analytics → labs → local.
    - `services/serp_api.py`: `_get_with_retry` (3 attempts on 429/5xx, honors
      `Retry-After`, used by `search_keyword` + `search_keyword_full`);
      `run_serp_rankings` caches per-keyword results 24h in new mongo collection
      `serp_cache` (key `domain|keyword`) so a transient SERP 429 doesn't blank
      the section on every insights refresh (cache read only via `db is not None`,
      Motor proxies raise on bool()).
    - `app.js`: `insightErrorKind` buckets error strings (credits/404-disabled/
      rate-limited/5xx/partial); `insightWarningHtml` muted amber note with
      <details> for the raw string; `renderInsightSection` only renders the big
      red/amber banner when there is NO fallback data — otherwise it shows data +
      source note + muted warning; `renderSerp` shows rankings + muted note on
      partial failure and only a red block (or SERP-specific credits block) when
      zero rankings; URL `renderDomainOverview` adds a "sampled top N keywords
      (lower bound)" footnote for the labs-sourced overview; `sourceLabel` adds
      dataforseo-labs and gsc.
    - Tests: `backend/tests/test_dataforseo_resilience.py` (11 new; total 179):
      retry-then-succeed, retry-exhausted raises, 404 blacklists + immediate
      skip, 40200 -> credits hint, keyword normalization (flat + nested), labs
      synthesis sums, SERP 429 retry, cache-hit avoids re-call, expired cache
      refetches, no-db still searches. Full suite 179/179; `node --check` clean.
    - Live-verified (fluidcontrols.com job): keywords/overview/onpage show local
      data + muted warnings; backlinks + SERP red blocks ONLY because they have
      zero fallback data currently; Playwright zero console errors.
  - SaaS UI round: professional SaaS front door + app polish.
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
  (robust, degraded). SE Ranking is the sole paid insights provider (see Status);
  graceful local crawl fallbacks live when it's unconfigured/out of credits.
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
- Configure real Gmail SMTP in Settings → Email (app `app_settings` key `smtp`):
  host smtp.gmail.com, port 587, app password, use_tls true; then verify test-send +
  report-email end-to-end (both endpoints now surface real failure reasons).
- UI follow-ups from round 2 (deferred deliberately): keyboard shortcuts (e.g.
  tab-jump keys, Ctrl/Cmd+K to focus search on Pages); Pages/Links status-chip
  click filters (needs the API to accept a status filter or adds a param);
  Schedules per-card "Run now" + live countdown from `next_run_at`; Actions
  approved-ratio ring (needs unfiltered counts — current label has them, a render
  can reuse `summary.pending/approved/rejected`); Report sticky TOC; rail job card
  could show completed-at timestamp when summary exposes one.
- Optional competitor polish: also surface `seo_insights_cache`-based target
  keyword overlap per competitor in the report's "overlap" table when SE
  Ranking data is missing (currently shows "no data" honestly).
- M1–M6 plan COMPLETE (last milestone M6 landed `94d961f`). Follow-ups:
- PRIVACY RULE: no real customer domains/data on the public landing or
  Analyze pages (app is unauthenticated). If a login/owner-gate is ever
  added, "recent analyses" could return — until then keep those pages
  static-only. The dashboard (after opening a job) is also unauthenticated:
  anyone with a job id / sites list can view any analysis.
- Apply-flow hardening: approve at least one action on `24fd33f6` and run
  `POST /api/actions/{job}/apply` end-to-end with a real GitHub token
  (repo `example-com` must exist under the token's owner); verify PR title/
  body + `actions_applied` audit row. Consider writing the PR with actual
  file contents (contents API) instead of body-only text.
- The dummy-site backend (`/api/dummy`, `services/dummy_site.py`,
  compare_service, the 3 `regenerate_after_change` hooks in actions.py) is
  now unreachable from the UI; either delete it (update smoke + test_phase4/
  test_patch which still exercise it) or keep as an API-only demo.
- The app lives at `/app` (index.html); `/` serves the marketing landing page
  (landing.html). Deep links `/#job/<id>` redirect to `/app#job/<id>`.
- Full smoke run with the new audits (long crawl) — books.toscrape is
  monolingual/clean so hreflang will be N/A, url-hygiene high, indexation
  unmeasured (serp key not configured), image-opt to be confirmed; also a
  fresh fluidcontrols.com re-crawl to see the new sections populate with real
  data + verify Playwright Report tab for the 4 new sections.
- Chat: new audits are in full-site context; a per-section chat test
  (e.g. section=hreflang) can be verified once a multilingual job exists.
- Optional follow-ups from the skill's checklist not yet automated: hreflang
  validation via `?hl=` parameter casing rules, news/video/image sitemap
  variants (sitemap audit ignores them), crawl-budget heuristics (thin
  parameter trees), real AI-overview citation monitoring.
- NOTE: `page_id` (99 pages on fluidcontrols) is a URL param not in
  FACET_PARAMS — audit flags param_pages but not facet_pages for it; consider
  adding page_id/pid to FACET_PARAMS if a future crawl shows similar pagination
  params being missed.
- Theme toggle: header `#theme-toggle` (app) / `#theme-toggle-landing`
  (landing), persists `zui-theme` in localStorage; `[data-theme="dark"]`
  overrides the token palette in style.css.
- Brand logomark is inline SVG in both pages — no logo.png dependency
  (old `#app-logo`/`#logo-fallback` markup removed).
-   GSC: user completes one-time Google Cloud OAuth client setup (Web app + in-app
  Settings tab) then end-to-end connect test on the live job.
- LIVE VERIFY (this round, pending): launchd restart, then refresh job
  `24fd33f6` (fluidcontrols.com) — confirm `overview_source=se-ranking`,
  competitors + backlink profile + overview/authority history populated, HTML +
  PDF include the new report rows; then commit + push.
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