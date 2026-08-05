from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from backend.db.mongo import get_db
from backend.services import gsc

router = APIRouter(prefix="/api/gsc", tags=["gsc"])

GSC_TTL_MINUTES = 60


def _domain_from_url(url: str) -> str:
    if "//" in url:
        return url.split("//")[-1].split("/")[0]
    return url


async def _cfg_or_raise() -> dict:
    cfg = await gsc.get_gsc_config()
    if not (cfg["client_id"] and cfg["client_secret"]):
        raise HTTPException(
            status_code=503,
            detail="Google Search Console is not configured. Open Settings to add the OAuth client id and secret.",
        )
    return cfg


@router.get("/auth/{job_id}")
async def auth_url(job_id: str, request: Request):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not await gsc.configured():
        return {
            "auth_url": None,
            "configured": False,
            "hint": "GSC not configured: open the Settings tab and save the Google OAuth client id and secret",
        }
    cfg = await gsc.get_gsc_config()
    redirect_uri = cfg["redirect_uri"] or gsc._redirect_uri_for(request)
    return {"auth_url": gsc._build_auth_url(job_id, cfg["client_id"], redirect_uri), "configured": True}


@router.get("/callback")
async def callback(code: str, state: str | None = None, error: str | None = None, request: Request = None):
    if error:
        raise HTTPException(status_code=400, detail=f"GSC authorization failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    try:
        cfg = await gsc.get_gsc_config()
        redirect_uri = cfg["redirect_uri"] or gsc._redirect_uri_for(request)
        result = await gsc.exchange_code(code, state, redirect_uri=redirect_uri)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {e}") from e
    return RedirectResponse(f"/#job/{state}/seo-insights?gsc=connected")


@router.get("/status/{job_id}")
async def status(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    domain = _domain_from_url(job.get("url", ""))
    return await gsc.gsc_status(domain)


@router.post("/{job_id}/fetch")
async def fetch(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    domain = _domain_from_url(job.get("url", ""))
    try:
        data = await gsc.fetch_gsc(domain)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    if data is None:
        raise HTTPException(status_code=400, detail="GSC not connected for this domain")
    from backend.routes.seo_insights import CACHE_VERSION
    from backend.services.dataforseo import merge_gsc_into_insights

    merged = await merge_gsc_into_insights(db, job_id, domain, data, CACHE_VERSION)
    return {"job_id": job_id, "domain": domain, **data, "merged": merged}


@router.delete("/{job_id}")
async def disconnect(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    domain = _domain_from_url(job.get("url", ""))
    await gsc.disconnect(domain)

    from backend.routes.seo_insights import CACHE_VERSION

    cached = await db.seo_insights_cache.find_one({"job_id": job_id})
    if cached:
        data = dict(cached.get("data") or {})
        data.pop("gsc", None)
        data.pop("gsc_error", None)
        ov = dict(data.get("overview") or {})
        ov.pop("estimated_organic_traffic", None)
        ov.pop("organic_keywords_count", None)
        if ov.get("source") == "gsc":
            ov["source"] = "local"
        data["overview"] = ov
        await db.seo_insights_cache.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_id": job_id,
                    "data": data,
                    "fetched_at": datetime.utcnow(),
                    "v": CACHE_VERSION,
                }
            },
        )
    return {"ok": True, "domain": domain, "disconnected": True}