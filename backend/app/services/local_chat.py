from sqlmodel import Session

from app.config import get_settings
from app.services.local_chat_context import build_chat_context, context_summary
from app.services.ollama_client import (
    LOCAL_AI_UNAVAILABLE,
    LocalAIUnavailableError,
    generate_text,
    list_ollama_models,
)

MAX_PROMPT_CONTEXT_CHARS = 20000


def build_chat_prompt(user_message: str, context: dict | None = None) -> str:
    context_text = _format_context(context or {})
    if len(context_text) > MAX_PROMPT_CONTEXT_CHARS:
        context_text = context_text[: MAX_PROMPT_CONTEXT_CHARS - 3].rstrip() + "..."
    return (
        "You are the local AI assistant inside RFP BidOS. You have read-only "
        "access to summarized app data provided in this prompt. You may analyze, "
        "rank, compare, and explain opportunities, but you cannot modify app data. "
        "Do not claim to have access to data that is not included in the context. "
        "Do not invent deadlines, values, requirements, licenses, or document facts.\n\n"
        "Behavior rules:\n"
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
        }

    context_used = build_context(context or {}, user_message=user_message, session=session)
    prompt = build_chat_prompt(user_message, context_used)
    summary = context_summary(context_used)
    try:
        answer = generate_text(prompt, model=status["model"])
    except LocalAIUnavailableError:
        return {
            "answer": "",
            "model": status["model"],
            "available": False,
            "error": LOCAL_AI_UNAVAILABLE,
            "context_used": summary,
        }

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
    if not result.get("available"):
        error = LOCAL_AI_UNAVAILABLE
    elif not model_available:
        error = (
            f"Ollama is running, but {settings.ollama_model} is not installed. "
            f"Run: ollama pull {settings.ollama_model}"
        )
    return {
        "available": available,
        "base_url": settings.ollama_base_url,
        "model": settings.ollama_model,
        "models": models,
        "error": error,
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
    lines = []
    for key, value in context.items():
        if key == "requested":
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines) if lines else "No app context was provided."


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
