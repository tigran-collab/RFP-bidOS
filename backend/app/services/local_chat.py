import json
import logging
import traceback

from sqlmodel import Session

from app.config import get_settings
from app.services.local_chat_context import build_chat_context, context_summary
from app.services.ollama_client import (
    LOCAL_AI_UNAVAILABLE,
    OLLAMA_GENERATE_FAILED,
    OLLAMA_TIMEOUT,
    LocalAIGenerateError,
    LocalAIModelMissingError,
    LocalAITimeoutError,
    LocalAIUnavailableError,
    generate_text,
    list_ollama_models,
)

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 30000
MAX_PROMPT_CONTEXT_CHARS = 22000

ERROR_MESSAGES = {
    "ollama_unavailable": LOCAL_AI_UNAVAILABLE,
    "model_missing": "Ollama is running, but qwen3:8b is not installed. Run: ollama pull qwen3:8b",
    "context_build_failed": "Local AI is available, but app context could not be prepared. Check backend logs.",
    "prompt_too_large": "Local AI is available, but the app context is too large. Try Pursuit Queue or Deadlines mode.",
    "ollama_timeout": OLLAMA_TIMEOUT,
    "ollama_generate_failed": OLLAMA_GENERATE_FAILED,
    "unknown_chat_error": "Local AI is available, but chat failed unexpectedly. Check backend logs.",
}


def build_chat_prompt(user_message: str, context: dict | None = None) -> str:
    context_text = _format_context(context or {})
    if len(context_text) > MAX_PROMPT_CONTEXT_CHARS:
        context_text = context_text[: MAX_PROMPT_CONTEXT_CHARS - 3].rstrip() + "..."
    prompt = (
        "You are the local AI assistant inside RFP BidOS. You have read-only "
        "access to summarized app data provided in this prompt. You may analyze, "
        "rank, compare, and explain opportunities, but you cannot modify app data. "
        "Do not claim to have access to data that is not included in the context. "
        "Do not invent deadlines, values, requirements, licenses, or document facts.\n\n"
        "Behavior rules:\n"
        "- Keep answers concise. For broad app questions, use short bullet points and prioritize the most actionable items.\n"
        "- This chat is advisory and read-only. Do not create, update, delete, archive, score, scrape, download, parse, extract, submit, or modify anything.\n"
        "- Help evaluate government bid opportunities and explain bid/no-bid decisions.\n"
        "- Summarize opportunity details only when those details are provided.\n"
        "- Identify missing information and say what is missing.\n"
        "- Help with scraper, document, review, requirements, and logistics workflow questions.\n"
        "- Security services fit is high priority; target geography is CA, TX, NV, and AZ.\n"
        "- Do not recommend purely as-needed/on-call/standby/bench/task-order-only/no-guaranteed-minimum opportunities as strong pursuits unless there is guaranteed minimum, strategic value, high likelihood of use, or very low response burden.\n"
        "- Mandatory pre-bids are a risk if missed or imminent.\n"
        "- Missing deadlines, missing documents, and low logistics confidence should be flagged.\n"
        "- Do not claim to have read documents unless document context is provided below.\n"
        "- Answers are based only on available app data and local model reasoning. "
        "Verify official solicitation documents before acting.\n\n"
        f"Available app context:\n{context_text}\n\n"
        f"User message:\n{user_message.strip()}\n\n"
        "Answer:"
    )
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ChatError("prompt_too_large", ERROR_MESSAGES["prompt_too_large"])
    return prompt


class ChatError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


def send_local_chat_message(
    user_message: str,
    context: dict | None = None,
    session: Session | None = None,
) -> dict:
    status = get_chat_status()
    if not status["available"]:
        return {
            "answer": "",
            "model": status["model"],
            "available": False,
            "error": status["error"],
            "context_used": {},
            "error_category": status.get("error_category") or "ollama_unavailable",
        }

    context_request = context or {}
    context_used: dict = {}
    summary: dict = {}
    try:
        context_used = build_context(context_request, user_message=user_message, session=session)
        prompt = build_chat_prompt(user_message, context_used)
        summary = context_summary(context_used)
        _log_chat_request(user_message, context_request, context_used, prompt, status)
        answer = generate_text(prompt, model=status["model"], timeout=180, max_tokens=700)
    except ChatError as exc:
        _log_chat_error(exc.category, exc, user_message, context_request, context_used, status)
        return _chat_error_response(status, summary or context_summary(context_used), exc.category, exc.message)
    except LocalAIModelMissingError as exc:
        _log_chat_error(exc.category, exc, user_message, context_request, context_used, status)
        return _chat_error_response(status, summary, exc.category, str(exc))
    except LocalAIUnavailableError as exc:
        _log_chat_error(exc.category, exc, user_message, context_request, context_used, status)
        return _chat_error_response(status, summary, exc.category, LOCAL_AI_UNAVAILABLE)
    except LocalAITimeoutError as exc:
        _log_chat_error(exc.category, exc, user_message, context_request, context_used, status)
        fallback = _fallback_context(context_request, user_message)
        if fallback:
            retry = send_local_chat_message(user_message, fallback, session=session)
            if retry.get("available"):
                retry["context_used"]["fallback_from"] = context_request.get("mode", "auto")
                return retry
        return _chat_error_response(status, summary, exc.category, str(exc) or ERROR_MESSAGES["ollama_timeout"])
    except LocalAIGenerateError as exc:
        _log_chat_error(exc.category, exc, user_message, context_request, context_used, status)
        return _chat_error_response(status, summary, exc.category, str(exc) or ERROR_MESSAGES["ollama_generate_failed"])
    except Exception as exc:
        category = "context_build_failed" if not context_used else "unknown_chat_error"
        _log_chat_error(category, exc, user_message, context_request, context_used, status)
        return _chat_error_response(status, summary, category, ERROR_MESSAGES[category])

    return {
        "answer": answer,
        "model": status["model"],
        "available": True,
        "context_used": summary,
    }


def get_chat_status() -> dict:
    settings = get_settings()
    result = list_ollama_models()
    models = result.get("models") or []
    names = [
        model.get("name") or model.get("model")
        for model in models
        if isinstance(model, dict)
    ]
    names = [name for name in names if name]
    model_available = settings.ollama_model in names
    available = bool(result.get("available")) and model_available
    error = None
    error_category = None
    if not result.get("available"):
        error = LOCAL_AI_UNAVAILABLE
        error_category = "ollama_unavailable"
    elif not model_available:
        error = (
            f"Ollama is running, but {settings.ollama_model} is not installed. "
            f"Run: ollama pull {settings.ollama_model}"
        )
        error_category = "model_missing"
    return {
        "available": available,
        "base_url": settings.ollama_base_url,
        "model": settings.ollama_model,
        "models": models,
        "error": error,
        "error_category": error_category,
    }


def build_context(
    context_request: dict,
    user_message: str = "",
    session: Session | None = None,
) -> dict:
    if session is None:
        return {
            "mode": context_request.get("mode", "auto"),
            "read_only": True,
            "opportunity_count": 0,
            "included_requirements": False,
            "included_documents": False,
            "note": "No database session was available.",
        }
    return build_chat_context(session, user_message, context_request)


def _format_context(context: dict) -> str:
    if not context:
        return "No app context was provided."
    public_context = {key: value for key, value in context.items() if key != "requested"}
    return json.dumps(public_context, ensure_ascii=True, default=str, separators=(",", ":"))


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _chat_error_response(status: dict, summary: dict, category: str, message: str) -> dict:
    return {
        "answer": "",
        "model": status["model"],
        "available": True,
        "error": message,
        "error_category": category,
        "context_used": summary or {},
    }


def _fallback_context(context_request: dict, user_message: str) -> dict | None:
    mode = context_request.get("mode", "auto")
    if mode == "pursuit":
        # Pursuit is already the fallback target; do not retry again or we recurse.
        return None
    if mode in {"app_overview", "auto"} or "opportunit" in user_message.lower():
        return {
            **context_request,
            "mode": "pursuit",
            "limit": 10,
            "include_requirements": False,
            "include_documents": False,
        }
    return None


def _log_chat_request(
    user_message: str,
    context_request: dict,
    context_used: dict,
    prompt: str,
    status: dict,
) -> None:
    summary = context_summary(context_used)
    logger.info(
        "local_chat request message_length=%s context_mode=%s opportunity_id=%s "
        "builder=%s opportunity_count=%s requirements_count=%s document_snippets_count=%s "
        "prompt_length=%s model=%s base_url=%s",
        len(user_message or ""),
        context_request.get("mode", "auto"),
        context_request.get("opportunity_id"),
        context_used.get("mode"),
        summary.get("opportunity_count", 0),
        _count_requirements(context_used),
        _count_document_snippets(context_used),
        len(prompt),
        status.get("model"),
        status.get("base_url"),
    )


def _log_chat_error(
    category: str,
    exc: BaseException,
    user_message: str,
    context_request: dict,
    context_used: dict,
    status: dict,
) -> None:
    logger.error(
        "local_chat error category=%s message_length=%s context_mode=%s opportunity_id=%s "
        "builder=%s opportunity_count=%s model=%s base_url=%s\n%s",
        category,
        len(user_message or ""),
        context_request.get("mode", "auto"),
        context_request.get("opportunity_id"),
        context_used.get("mode"),
        context_used.get("opportunity_count", 0),
        status.get("model"),
        status.get("base_url"),
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )


def _count_requirements(context: dict) -> int:
    if isinstance(context.get("requirements"), list):
        return len(context["requirements"])
    if isinstance(context.get("opportunities"), list):
        return sum(int(opp.get("requirement_count") or 0) for opp in context["opportunities"] if isinstance(opp, dict))
    return 0


def _count_document_snippets(context: dict) -> int:
    documents = context.get("documents")
    if not isinstance(documents, list):
        return 0
    return sum(1 for document in documents if isinstance(document, dict) and document.get("snippet"))
