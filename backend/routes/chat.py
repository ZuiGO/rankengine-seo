from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.chat_service import chat_with_context
from backend.db.mongo import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    job_id: str
    section: str = "content"
    message: str


@router.post("")
async def chat(req: ChatRequest):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": req.job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    reply = await chat_with_context(req.job_id, req.message)
    return {"reply": reply, "section": req.section}
