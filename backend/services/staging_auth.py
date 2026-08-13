"""Basic auth dependency for staging routes."""

from fastapi import Depends, Header, HTTPException, status

from backend.config import settings
from backend.db.mongo import get_db


async def get_staging_credentials() -> dict:
    """Get staging credentials from DB (app_settings) with .env fallback."""
    try:
        db = get_db()
        doc = await db.app_settings.find_one({"key": "staging"})
        if doc and doc.get("user") and doc.get("password"):
            return {"user": doc["user"], "password": doc["password"]}
    except Exception:
        pass
    return {
        "user": settings.staging_user,
        "password": settings.staging_password,
    }


async def require_staging_auth(
    authorization: str | None = Header(None),
) -> dict:
    """Require basic auth for staging routes."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Staging"'},
        )

    import base64
    try:
        scheme, credentials = authorization.split()
        if scheme.lower() != "basic":
            raise HTTPException(401, "Invalid auth scheme")
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid authorization header")

    creds = await get_staging_credentials()
    expected_user = creds["user"]
    expected_pass = creds["password"]

    if not expected_user or not expected_pass:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Staging auth not configured",
        )

    if username != expected_user or password != expected_pass:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="Staging"'},
        )

    return {"username": username}