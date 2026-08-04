from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.chat_service import chat_with_context, general_chat
from backend.db.mongo import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    job_id: str | None = None
    section: str | None = None
    message: str


@router.post("")
async def chat(req: ChatRequest):
    if not req.job_id:
        reply = await general_chat(req.message)
        return {"reply": reply, "section": "general"}
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": req.job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    reply = await chat_with_context(req.job_id, req.message, req.section)
    return {"reply": reply, "section": req.section or "all"}
