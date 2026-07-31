from fastapi import APIRouter
from fastapi.responses import Response

from backend.db.mongo import get_db
from backend.services.dummy_site import generate_dummy_site, get_dummy_site, dummy_site_zip

router = APIRouter(prefix="/api/dummy", tags=["dummy-site"])


@router.get("/{job_id}")
async def dummy_status(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"status": "error", "message": "Job not found"}
    return await get_dummy_site(job_id)


@router.post("/{job_id}/generate")
async def generate(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"status": "error", "message": "Job not found"}
    result = await generate_dummy_site(job_id)
    result["url"] = f"/dummy/{job_id}/index.html"
    return result


@router.get("/{job_id}/download")
async def download(job_id: str):
    data = await dummy_site_zip(job_id)
    if data is None:
        return {"status": "error", "message": "Dummy site not generated yet"}
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="dummy-site-{job_id}.zip"'},
    )
