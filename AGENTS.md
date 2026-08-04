# RankEngine — Agent Context & Session State

This file is the durable memory for AI coding sessions. READ THIS FIRST at the
start of every session and resume from "Next up". Update it at the end of
every session with what changed and what's left.

## Project
SEO analysis engine: crawl a site, classify content, analyze, recommend,
approve changes, generate dummy site + reports, chat. Python 3.14 FastAPI +
MongoDB + Redis + Chroma + Arq worker + Playwright. Repo:
`/Users/macbook/RankEngine-AI-Simple` (git, remote `https://github.com/ZuiGO/rankengine-seo.git`).

## Status (last update: end of Phase 4 round)
- Phases 1-4 (original spec) DELIVERED. Latest commit `1a68cf3` pushed.
- pytest: 36/36 (`backend/tests/`), smoke: 63/63 (`scripts/smoke_test.py`).
- Server + worker run under launchd: `com.zuigo.rankengine-server`,
  `com.zuigo.rankengine-worker` (plists in `deploy/`, symlinked to
  `~/Library/LaunchAgents/`). Logs: `/tmp/rankengine.log`, `/tmp/arq.log`.
- Gemini free-tier daily quota exhausted sometimes -> hash-embedding fallback
  (robust, degraded). DataForSEO 402 out of credits (local fallbacks live).
  Groq key active. Neo4j offline (graph unwired, backend files kept).
- Hard delete (`DELETE /api/sites/{job_id}/hard`) cascades 27 collections +
  Chroma + files. Chat supports global (no job_id) mode.
- Smoke crawl takes ~5-10 min (PageSpeed API per page); wait timeout 1800s.
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

## Next up (in progress round: "memory/logs/chat + missing features")
1. Phase 0 (THIS FILE): done once AGENTS.md committed.
2. Phase 1: remove Logs tab + `GET /api/logs/app` (raw log tail); KEEP
   `/api/logs/audit` + `/api/logs/alerts` (user chose).
3. Phase 2: chat full-site mode - drop `<select id="chat-section">`, backend
   builds all-sections context, model answers any section question.
4. Phase 3: GEO/AI-crawler robots.txt check (GPTBot/PerplexityBot/ClaudeBot/
   Google-Extended); `/api/trends/{domain}` aggregated from per-domain job
   summaries + UI chart; competitor-gap (DataForSEO, graceful 402); orphan
   inbound-link suggestions (embedding cosine); content-decay via
   `last_modified` header + Slack on health drop/broken links;
   `.github/workflows/ci.yml`.
5. Phase 4: scheduled keyword re-check cadence (scheduler-triggered
   `/api/tracking/check`, persist rank history).
6. Verify: pytest + smoke, restart stack, commit + push, update this file.

## Conventions
- No comments in code unless asked. Launchd restarts after backend changes.
- Full smoke = slow crawl; prefer targeted curl checks after backend edits.
- Report counts in `/tmp/rankengine.log`; worker logs `/tmp/arq.log`.
