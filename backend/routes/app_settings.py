from fastapi import APIRouter
from pydantic import BaseModel

from backend.db.mongo import get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


class GscSettingsRequest(BaseModel):
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:8] + "…" + "*" * 6


async def get_gsc_settings() -> dict:
    db = get_db()
    doc = await db.app_settings.find_one({"key": "gsc"})
    return {
        "client_id": (doc or {}).get("client_id", ""),
        "client_secret": (doc or {}).get("client_secret", ""),
        "redirect_uri": (doc or {}).get("redirect_uri", ""),
    }


@router.get("/gsc")
async def read_gsc_settings():
    s = await get_gsc_settings()
    return {
        "client_id": _mask(s["client_id"]),
        "client_id_set": bool(s["client_id"]),
        "client_secret_set": bool(s["client_secret"]),
        "redirect_uri": s["redirect_uri"],
    }


@router.put("/gsc")
async def write_gsc_settings(req: GscSettingsRequest):
    db = get_db()
    update = {}
    if req.client_id:
        update["client_id"] = req.client_id.strip()
    if req.client_secret:
        update["client_secret"] = req.client_secret.strip()
    if req.redirect_uri:
        update["redirect_uri"] = req.redirect_uri.strip()
    if not update:
        return await read_gsc_settings()
    await db.app_settings.update_one({"key": "gsc"}, {"$set": {**update, "key": "gsc"}}, upsert=True)
    return await read_gsc_settings()


class SeRankingSettingsRequest(BaseModel):
    api_key: str = ""
    region: str = ""


async def get_se_ranking_settings() -> dict:
    db = get_db()
    doc = await db.app_settings.find_one({"key": "se_ranking"}) or {}
    return {
        "api_key": doc.get("api_key", ""),
        "region": doc.get("region", "us"),
    }


@router.get("/se-ranking")
async def read_se_ranking_settings():
    s = await get_se_ranking_settings()
    return {
        "api_key": _mask(s["api_key"]),
        "api_key_set": bool(s["api_key"]),
        "region": s["region"],
    }


@router.put("/se-ranking")
async def write_se_ranking_settings(req: SeRankingSettingsRequest):
    db = get_db()
    update = {}
    if req.api_key:
        update["api_key"] = req.api_key.strip()
    if req.region:
        region = req.region.strip().lower()
        if region:
            update["region"] = region
    if not update:
        return await read_se_ranking_settings()
    await db.app_settings.update_one({"key": "se_ranking"}, {"$set": {**update, "key": "se_ranking"}}, upsert=True)
    return await read_se_ranking_settings()


class GithubSettingsRequest(BaseModel):
    token: str = ""


async def get_github_settings() -> dict:
    db = get_db()
    doc = await db.app_settings.find_one({"key": "github"}) or {}
    return {"token": doc.get("token", "")}


@router.get("/github")
async def read_github_settings():
    s = await get_github_settings()
    return {
        "token": _mask(s["token"]),
        "token_set": bool(s["token"]),
    }


@router.put("/github")
async def write_github_settings(req: GithubSettingsRequest):
    db = get_db()
    token = req.token.strip()
    if not token:
        return await read_github_settings()
    await db.app_settings.update_one({"key": "github"}, {"$set": {"token": token, "key": "github"}}, upsert=True)
    return await read_github_settings()
