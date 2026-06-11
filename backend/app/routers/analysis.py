from fastapi import APIRouter

from app.services.ollama_client import list_ollama_models

router = APIRouter(tags=["ai"])


@router.get("/ai/status")
def ai_status() -> dict:
    return list_ollama_models()
