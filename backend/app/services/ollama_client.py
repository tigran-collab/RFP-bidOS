import json
from typing import Any

import requests

from app.config import get_settings


LOCAL_AI_UNAVAILABLE = (
    "Local AI model is not available. Start Ollama and make sure qwen3:8b is installed."
)
OLLAMA_TIMEOUT = (
    "Local AI is available, but the model timed out while answering. "
    "Try a narrower question or reduce context."
)
OLLAMA_GENERATE_FAILED = (
    "Local AI is available, but Ollama could not generate an answer. Check backend logs."
)


class LocalAIUnavailableError(RuntimeError):
    category = "ollama_unavailable"


class LocalAIModelMissingError(LocalAIUnavailableError):
    category = "model_missing"


class LocalAITimeoutError(RuntimeError):
    category = "ollama_timeout"


class LocalAIGenerateError(RuntimeError):
    category = "ollama_generate_failed"


def _error_message(exc: BaseException) -> str:
    return str(exc) or exc.__class__.__name__


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


def generate_text(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: int = 180,
    max_tokens: int = 700,
) -> str:
    settings = get_settings()
    model_name = model or settings.ollama_model
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": 8192,
        },
    }
    try:
        response = requests.post(_api_url("/api/generate"), json=payload, timeout=timeout)
        response.raise_for_status()
        ollama_payload = response.json()
    except requests.Timeout as exc:
        raise LocalAITimeoutError(OLLAMA_TIMEOUT) from exc
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code == 404:
            raise LocalAIModelMissingError(
                f"Ollama is running, but {model_name} is not installed. Run: ollama pull {model_name}"
            ) from exc
        raise LocalAIGenerateError(f"{OLLAMA_GENERATE_FAILED} {_error_message(exc)}") from exc
    except requests.ConnectionError as exc:
        raise LocalAIUnavailableError(LOCAL_AI_UNAVAILABLE) from exc
    except (requests.RequestException, ValueError) as exc:
        raise LocalAIGenerateError(f"{OLLAMA_GENERATE_FAILED} {_error_message(exc)}") from exc

    return str(ollama_payload.get("response", "")).strip()


def _api_url(path: str) -> str:
    settings = get_settings()
    return f"{settings.ollama_base_url.rstrip('/')}{path}"
