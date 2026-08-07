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


class SmtpSettingsRequest(BaseModel):
    host: str = ""
    port: int | None = None
    user: str = ""
    password: str = ""
    from_email: str = ""
    use_tls: bool = True


async def get_smtp_settings() -> dict:
    db = get_db()
    doc = await db.app_settings.find_one({"key": "smtp"}) or {}
    return {
        "host": doc.get("host", ""),
        "port": doc.get("port", 587),
        "user": doc.get("user", ""),
        "password": doc.get("password", ""),
        "from_email": doc.get("from_email", ""),
        "use_tls": doc.get("use_tls", True),
    }


@router.get("/smtp")
async def read_smtp_settings():
    s = await get_smtp_settings()
    return {
        "host": s["host"],
        "host_set": bool(s["host"]),
        "port": s["port"],
        "user": _mask(s["user"]),
        "user_set": bool(s["user"]),
        "password_set": bool(s["password"]),
        "from_email": s["from_email"],
        "use_tls": s["use_tls"],
    }


@router.put("/smtp")
async def write_smtp_settings(req: SmtpSettingsRequest):
    db = get_db()
    update = {}
    if req.host:
        update["host"] = req.host.strip()
    if req.port:
        update["port"] = int(req.port)
    if req.user:
        update["user"] = req.user.strip()
    if req.password:
        update["password"] = req.password.strip()
    if req.from_email:
        update["from_email"] = req.from_email.strip()
    update["use_tls"] = req.use_tls
    if not update:
        return await read_smtp_settings()
    await db.app_settings.update_one({"key": "smtp"}, {"$set": {**update, "key": "smtp"}}, upsert=True)
    return await read_smtp_settings()
