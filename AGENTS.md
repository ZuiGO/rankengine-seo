# RankEngine — Agent Context & Session State

This file is the durable memory for AI coding sessions. READ THIS FIRST at the
start of every session and resume from "Next up". Update it at the end of
every session with what changed and what's left.

## Project
SEO analysis engine: crawl a site, classify content, analyze, recommend,
approve changes, generate dummy site + reports, chat. Python 3.14 FastAPI +
MongoDB + Redis + Chroma + Arq worker + Playwright. Repo:
`/Users/macbook/RankEngine-AI-Simple` (git, remote `https://github.com/ZuiGO/rankengine-seo.git`).

## Status (last update: end of "memory/logs/chat + missing features" round)
- All rounds DELIVERED. Latest commit `00af36c` pushed.
- pytest: 44/44 (`backend/tests/`, incl. `test_phase5.py`), smoke: 67/67
  (`scripts/smoke_test.py`, incl. geo_readiness key, decay, trends, logs-removed).
- Server + worker run under launchd: `com.zuigo.rankengine-server`,
  `com.zuigo.rankengine-worker` (plists in `deploy/`, symlinked to
  `~/Library/LaunchAgents/`). Logs: `/tmp/rankengine.log`, `/tmp/arq.log`.
- Gemini free-tier daily quota exhausted sometimes -> hash-embedding fallback
  (robust, degraded). DataForSEO: keywords_for_site + backlinks/summary 200,
  but domain_analytics/overview, on_page/*, backlinks/referring_pages 404
  (endpoints not on plan) -> SERP fallback used; graceful local fallbacks live.
  Groq key active. Neo4j offline (graph unwired, backend files kept).
- Hard delete (`DELETE /api/sites/{job_id}/hard`) cascades 27 collections +
  Chroma + files. Chat supports global (no job_id) mode.
- Smoke crawl takes ~15-25 min (PageSpeed + mobile crawl + SERP fallbacks);
  wait timeout 1800s; run with bash timeout >= 45 min.
  books.toscrape has 0 user flows (no action-role pages) - presence check only.

## Run / verify commands
```bash
# restart services
launchctl kickstart -k gui/$(id -u)/com.zuigo.rankengine-server
launchctl kickstart -k gui/$(id -u)/com.zuigo.rankengine-worker
# tests + smoke
.venv/bin/python -m pytest backend/tests/ -q
.venv/bin/python scripts/smoke_test.py --url https://books.toscrape.com
# health
curl -s localhost:8001/api/health
```

## Next up (candidate work, NOT started)
- Long-term rank/build history is stored; optional richer longitudinal charts
  (canvas/Chart.js) beyond the current overview table.
- Notifications: currently Slack on analysis complete / health-grade drop /
  failure only. Could add broken-link-count threshold alerts.
- Calibrate site-health scoring / add per-metric weight explanations.
- Re-enable Neo4j graph module or wire ranking insights from Chroma.
- Add backend validation for `crawl_schedules` duplicate domains / interval caps.

## Conventions
- No comments in code unless asked. Launchd restarts after backend changes.
- Full smoke = slow crawl; prefer targeted curl checks after backend edits.
- Report counts in `/tmp/rankengine.log`; worker logs `/tmp/arq.log`.