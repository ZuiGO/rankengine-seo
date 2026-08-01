import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import settings
from backend.db.mongo import connect_db, close_db, get_db
from backend.db.neo4j_db import connect_neo4j, close_neo4j
from backend.logging_setup import setup_logging, get_logger
from backend.routes import analysis, pages, content, links, actions, reports, chat, graph, seo_insights, sites, scheduler, logs, dummy, quality, tracking, spend
from backend.services.scheduler import scheduler_loop
from backend.services.dummy_site import DUMMY_ROOT
from backend.services.embeddings import embedding_source

logger = get_logger("rankengine")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
DUMMY_DIR = Path(__file__).parent.parent / DUMMY_ROOT
DOWNLOADS_DIR = Path(__file__).parent.parent / "downloads"

scheduler_task = None
STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler_task
    setup_logging()
    await connect_db(settings.mongodb_uri)
    try:
        await connect_neo4j(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    except Exception as e:
        logger.warning("Neo4j not available: %s", e)
    scheduler_task = asyncio.create_task(scheduler_loop())
    logger.info("Application startup complete")
    yield
    if scheduler_task:
        scheduler_task.cancel()
    from backend.services.queue import close_pool
    await close_pool()
    await close_db()
    await close_neo4j()
    logger.info("Application shutdown")


app = FastAPI(title="RankEngine", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %s (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


app.include_router(analysis.router)
app.include_router(pages.router)
app.include_router(content.router)
app.include_router(links.router)
app.include_router(actions.router)
app.include_router(reports.router)
app.include_router(chat.router)
app.include_router(graph.router)
app.include_router(seo_insights.router)
app.include_router(sites.router)
app.include_router(scheduler.router)
app.include_router(logs.router)
app.include_router(dummy.router)
app.include_router(quality.router)
app.include_router(tracking.router)
app.include_router(spend.router)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

os.makedirs(DUMMY_DIR, exist_ok=True)
app.mount("/dummy", StaticFiles(directory=str(DUMMY_DIR)), name="dummy")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
app.mount("/downloads", StaticFiles(directory=str(DOWNLOADS_DIR)), name="downloads")


@app.get("/api/health")
async def health():
    checks = {"status": "ok"}
    try:
        await get_db().command("ping")
        checks["mongo"] = "up"
    except Exception as e:
        checks["mongo"] = f"down: {e}"

    try:
        from backend.services.queue import get_pool
        pool = await get_pool()
        await pool.ping()
        checks["redis"] = "up"
        try:
            queue = await pool.queued_jobs()
            checks["queue_depth"] = len(queue)
        except Exception:
            checks["queue_depth"] = None
    except Exception as e:
        checks["redis"] = f"down: {e}"

    try:
        from backend.db.chroma import get_or_create_collection, delete_collection
        collection = get_or_create_collection("health_check")
        count = collection.count()
        delete_collection("health_check")
        checks["chroma"] = f"up ({count} vectors)"
    except Exception as e:
        checks["chroma"] = f"down: {e}"

    checks["embeddings"] = embedding_source()
    checks["uptime_s"] = round(time.time() - STARTED_AT)
    checks["version"] = app.version
    return checks


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")
