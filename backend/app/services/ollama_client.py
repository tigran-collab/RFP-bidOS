import json
from typing import Any

import requests

from app.config import get_settings


LOCAL_AI_UNAVAILABLE = (
    "Local AI model is not available. Start Ollama and make sure the model is installed."
)


class LocalAIUnavailableError(RuntimeError):
    pass


def is_ollama_available() -> bool:
    try:
        response = requests.get(_api_url("/api/tags"), timeout=5)
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


def list_ollama_models() -> dict:
    settings = get_settings()
    try:
        response = requests.get(_api_url("/api/tags"), timeout=5)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        return {
            "available": False,
            "base_url": settings.ollama_base_url,
            "model": settings.ollama_model,
            "models": [],
            "error": LOCAL_AI_UNAVAILABLE,
        }

    models = payload.get("models", []) if isinstance(payload, dict) else []
    return {
        "available": True,
        "base_url": settings.ollama_base_url,
        "model": settings.ollama_model,
        "models": models,
        "error": None,
    }


def generate_json(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
) -> dict:
    settings = get_settings()
    model_name = model or settings.ollama_model
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature},
    }
    try:
        response = requests.post(_api_url("/api/generate"), json=payload, timeout=120)
        response.raise_for_status()
        ollama_payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise LocalAIUnavailableError(LOCAL_AI_UNAVAILABLE) from exc

    response_text = str(ollama_payload.get("response", ""))
    parsed_json: Any | None = None
    try:
        parsed_json = json.loads(response_text)
    except ValueError:
        parsed_json = None
    return {
        "model": model_name,
        "response_text": response_text,
        "raw_response": response.text,
        "json": parsed_json,
        "ollama": ollama_payload,
    }


def _api_url(path: str) -> str:
    settings = get_settings()
    return f"{settings.ollama_base_url.rstrip('/')}{path}"
