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
