# ZuiGO Engine SEO Analysis

A simple, standalone SEO analysis tool. Enter a URL, crawl the site, classify its content, run SEO analysis, store everything in MongoDB + Neo4j, and get recommendations — with a single-page web UI.

## Features

- **Crawling** — Playwright-based BFS crawl (up to 50 pages by default, configurable)
- **Content classification** — detects images, PDFs, videos, docs, spreadsheets, presentations, audio from URLs + known domains
- **Content extraction** — PDF text/tables/images via PyMuPDF; post-crawl extraction pipeline
- **SEO analysis** — per-content-type impact scoring, identified issues, improvement suggestions, approve/reject workflow
- **Graph database** — Neo4j pages/content graph with force-directed visualization in the UI
- **Vector search + RAG chat** — n-gram hashing embeddings (numpy-only) with Groq-powered answers about the analyzed site
- **External SEO APIs** — SE Ranking (domain overview, organic/paid keywords, competitors, backlink profile) and SerpAPI (keyword rankings), cached in MongoDB
- **Reports** — JSON + downloadable HTML report including external insights
- **Logging & audit** — rotating file logs, request middleware, MongoDB audit trail

## Architecture

```
frontend/          single-page HTML/JS/CSS app (served by FastAPI)
backend/
  main.py          FastAPI app, CORS, request logging, startup wiring
  config.py        env-driven settings (.env)
  db/              Mongo + Neo4j connections
  routes/          analysis, pages, content, links, actions, reports, chat, graph, seo-insights
  services/        crawler, content_classifier, content_downloader, seo_analyzer,
                   pdf_extractor, content_extractor, graph_service, vector_service,
                   chat_service, se_ranking, serp_api, audit_service
  logging_setup.py rotating file logs (logs/app.log) + console
```

Stack: Python 3.11+ · FastAPI · Playwright · MongoDB (motor) · Neo4j · Redis · numpy · Groq

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env        # then fill in your API keys
docker compose up -d        # MongoDB, Redis, Neo4j
uvicorn backend.main:app --host 0.0.0.0 --port 8001
```

Open http://localhost:8001, enter a URL, and analyze.

## Environment Variables

See `.env.example`:

| Variable | Purpose |
|---|---|
| `MONGODB_URI` | MongoDB connection string |
| `REDIS_URL` | Redis URL |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | Neo4j graph database |
| `GROQ_API_KEY` | LLM for RAG chat |
| `SERP_API_KEY` | SerpAPI keyword ranking lookups |
| `SE_RANKING_API_KEY` | SE Ranking insights fallback (backlinks, keywords, domain overview, competitors; configure region in Settings) |
| `LOG_LEVEL` / `LOG_DIR` | Logging configuration |

## API Endpoints

- `POST /api/analysis` — start analysis `{url, max_pages}` · `GET /api/analysis/{job_id}` — status
- `GET /api/analysis/{job_id}/summary` — job summary with content breakdown
- `GET /api/pages/{job_id}` · `GET /api/content/{job_id}` · `GET /api/content/{job_id}/detail/{content_id}`
- `GET /api/content/{job_id}/extraction-stats` — PDF/image extraction stats
- `GET /api/links/{job_id}` · `GET /api/links/{job_id}/backlinks`
- `GET /api/actions/{job_id}` · `POST /api/actions/{action_id}/approve` — approve/reject action items
- `GET /api/graph/{job_id}` · `GET /api/graph/{job_id}/summary` — Neo4j graph data
- `GET /api/reports/{job_id}` · `GET /api/reports/{job_id}/download` — JSON + HTML report
- `POST /api/chat` — RAG chat `{job_id, message}`
- `GET /api/seo-insights/{job_id}` · `POST /api/seo-insights/refresh/{job_id}` · `POST /api/seo-insights/keyword-search` · `GET /api/seo-insights/{job_id}/suggested-keywords`

## Logging

- Application logs: `logs/app.log` (rotating, 5MB × 5 files)
- Console logging enabled in dev
- `audit_logs` collection in MongoDB records analysis lifecycle events and action approvals
