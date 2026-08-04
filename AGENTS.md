# RankEngine — Agent Context & Session State

This file is the durable memory for AI coding sessions. READ THIS FIRST at the
start of every session and resume from "Next up". Update it at the end of
every session with what changed and what's left.

## Project
SEO analysis engine: crawl a site, classify content, analyze, recommend,
approve changes, generate dummy site + reports, chat. Python 3.14 FastAPI +
MongoDB + Redis + Chroma + Arq worker + Playwright. Repo:
`/Users/macbook/RankEngine-AI-Simple` (git, remote `https://github.com/ZuiGO/rankengine-seo.git`).

## Status (last update: end of "Speedup + refresh fix + rebrand" round)
- All rounds DELIVERED. Latest commit `64685a4` pushed (speedup A–F + refresh-state G
  + rebrand H round).
- pytest: 104/104 (`backend/tests/`, incl. test_actions/test_trends/test_patch/
  test_webhooks), smoke: 74/74 (scripts/smoke_test.py).
- Server + worker run under launchd: `com.zuigo.rankengine-server`,
  `com.zuigo.rankengine-worker` (plists in `deploy/`, symlinked to
  `~/Library/LaunchAgents/`). Logs: `/tmp/rankengine.log`, `/tmp/arq.log`.
- Smoke: use bash tool timeout (no `timeout` cmd on macOS); ~15-25 min;
  full run just passed 74/74 on books.toscrape.
- Rebrand: user-facing strings are "ZuiGO.ai SEO Analysis Engine" (FastAPI
  title, index.html header/title/chat greeting, chat system prompt, PR titles,
  llms.txt brand, USER_AGENT strings, test_patch assertion, smoke gchat
  question). Internal ids kept: launchd labels `com.zuigo.rankengine-*`, db name
  `rankengine`, repo path/remote, neo4j password. Logo: header shows
  `static/logo.png` with text fallback (`#logo-fallback`) — user supplies the
  logo file later; until then the fallback renders.
- Refresh bug FIXED: app.js persists state in URL hash `#job/<jobId>[/<tab>]`
  via `history.replaceState` (form submit, tab clicks, `openSite`, New Analysis
  clears it). `restoreFromHash()` on DOMContentLoaded/hashchange reopens the
  job (`openSite(job.id, {preserveTab: true})` so `showResults` skips its
  auto-overview click; `switchTab` re-applies the tab; unknown job ids clear
  the hash and stay on Analyze). Verified via Playwright (7/7).
- Speedup round (timing-only, smoke semantics preserved):
  - Pipeline: post-crawl stages in `routes/analysis.py` now run in waves —
    wave1 `asyncio.gather`: user_flows, extraction, insights, backlinks,
    link_health, performance, duplicate, structured, geo_readiness, orphans;
    wave2 (needs extraction): action analysis, geo_alignment, vectors;
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
  (thin content, meta, H1, noindex, no_structured_data, entity_coverage_low)
  generated in `analyze_pages` enrichment (ctx carries meta_counts/sd/corpus
  keywords via keyword_extractor + validate_structured_data); `action_feedback`
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
- Long-term rank/build history is stored; optional richer longitudinal charts
  (Chart.js already wired for trends; could add more series).
- Calibrate site-health scoring / add per-metric weight explanations.
- Re-enable Neo4j graph module or wire ranking insights from Chroma.
- Add backend validation for `crawl_schedules` duplicate domains / interval caps.
- Webhook delivery retries/dedup; patch format versioned consumers.
- Receive the real logo file for `frontend/static/logo.png` (currently text
  fallback "ZuiGO.ai" shows until it exists).

## Conventions
- No comments in code unless asked. Launchd restarts after backend changes.
- Full smoke = slow crawl; prefer targeted curl checks after backend edits.
- Report counts in `/tmp/rankengine.log`; worker logs `/tmp/arq.log`.