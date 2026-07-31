import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import settings
from backend.db.mongo import connect_db, close_db
from backend.db.neo4j_db import connect_neo4j, close_neo4j
from backend.logging_setup import setup_logging, get_logger
from backend.routes import analysis, pages, content, links, actions, reports, chat, graph, seo_insights

logger = get_logger("rankengine")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await connect_db(settings.mongodb_uri)
    try:
        await connect_neo4j(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    except Exception as e:
        logger.warning("Neo4j not available: %s", e)
    logger.info("Application startup complete")
    yield
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

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")
