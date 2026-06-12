from fastapi import APIRouter
from sqlmodel import Session

from app.db import engine
from app.schemas import LocalChatRequest
from app.services.local_chat import get_chat_status, send_local_chat_message
from app.services.ollama_client import list_ollama_models

router = APIRouter(tags=["ai"])


@router.get("/ai/status")
def ai_status() -> dict:
    return list_ollama_models()


@router.get("/ai/chat/status")
def ai_chat_status() -> dict:
    return get_chat_status()


@router.post("/ai/chat")
def ai_chat(request: LocalChatRequest) -> dict:
    context = request.context.model_dump() if request.context else {}
    with Session(engine) as session:
        return send_local_chat_message(request.message, context=context, session=session)
