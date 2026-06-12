from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.config import get_settings
from app.models import Document, Opportunity, Requirement
from app.services.ollama_client import (
    LOCAL_AI_UNAVAILABLE,
    LocalAIUnavailableError,
    generate_text,
    list_ollama_models,
)

MAX_REQUIREMENTS = 8
MAX_DOCUMENTS = 5
MAX_DOC_SNIPPET_CHARS = 900
MAX_TOTAL_DOC_CHARS = 2400


def build_chat_prompt(user_message: str, context: dict | None = None) -> str:
    context_text = _format_context(context or {})
    return (
        "You are the local AI assistant inside RFP BidOS. You help review "
        "government bid opportunities for a security services company. Be direct, "
        "practical, and do not invent facts.\n\n"
        "Behavior rules:\n"
        "- Help evaluate government bid opportunities and explain bid/no-bid decisions.\n"
        "- Summarize opportunity details only when those details are provided.\n"
        "- Identify missing information and say what is missing.\n"
        "- Help with scraper, document, review, requirements, and logistics workflow questions.\n"
        "- Do not invent deadlines, values, licenses, insurance, requirements, or document facts.\n"
        "- Flag as-needed, on-call, or no-guaranteed-minimum opportunities as risky by default.\n"
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

    context_used = build_context(context or {}, session=session)
    prompt = build_chat_prompt(user_message, context_used)
    try:
        answer = generate_text(prompt, model=status["model"])
    except LocalAIUnavailableError:
        return {
            "answer": "",
            "model": status["model"],
            "available": False,
            "error": LOCAL_AI_UNAVAILABLE,
            "context_used": context_used,
        }

    return {
        "answer": answer,
        "model": status["model"],
        "available": True,
        "context_used": context_used,
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


def build_context(context_request: dict, session: Session | None = None) -> dict:
    if session is None or not context_request.get("opportunity_id"):
        return {"requested": context_request, "included": []}

    opportunity_id = context_request.get("opportunity_id")
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return {
            "requested": context_request,
            "included": [],
            "error": f"Opportunity not found: {opportunity_id}",
        }

    context_used: dict[str, Any] = {
        "requested": context_request,
        "included": [],
    }

    if context_request.get("include_opportunity") or opportunity_id:
        context_used["opportunity"] = _opportunity_context(opportunity)
        context_used["included"].append("opportunity")

    if context_request.get("include_logistics"):
        context_used["logistics"] = _logistics_context(opportunity)
        context_used["included"].append("logistics")

    if context_request.get("include_requirements"):
        requirements = list(
            session.exec(
                select(Requirement)
                .where(Requirement.opportunity_id == opportunity.id)
                .limit(MAX_REQUIREMENTS)
            ).all()
        )
        context_used["requirements"] = [_requirement_context(item) for item in requirements]
        context_used["requirements_limited_to"] = MAX_REQUIREMENTS
        context_used["included"].append("requirements")

    if context_request.get("include_documents"):
        documents = list(
            session.exec(
                select(Document)
                .where(Document.opportunity_id == opportunity.id)
                .limit(MAX_DOCUMENTS)
            ).all()
        )
        snippets, total_chars = _document_contexts(documents)
        context_used["documents"] = snippets
        context_used["documents_limited_to"] = MAX_DOCUMENTS
        context_used["document_context_characters"] = total_chars
        context_used["included"].append("documents")

    return context_used


def _opportunity_context(opportunity: Opportunity) -> dict:
    fields = [
        "id",
        "title",
        "agency",
        "solicitation_number",
        "source_url",
        "portal_url",
        "location",
        "due_date",
        "q_and_a_deadline",
        "pre_bid_date",
        "pre_bid_mandatory",
        "service_type",
        "contract_type",
        "estimated_value",
        "bid_score",
        "bid_decision",
        "bid_reason",
        "ai_recommendation",
        "ai_score",
        "ai_reason",
        "ai_risk_level",
        "relevance_score",
        "relevance_decision",
        "relevance_reason",
        "as_needed_warning",
        "review_status",
        "priority",
        "next_action",
    ]
    return {field: _jsonable(getattr(opportunity, field)) for field in fields}


def _logistics_context(opportunity: Opportunity) -> dict:
    fields = [
        "due_date",
        "q_and_a_deadline",
        "pre_bid_date",
        "pre_bid_mandatory",
        "submission_method",
        "submission_portal",
        "required_forms_summary",
        "deadline_risk",
        "logistics_confidence_score",
        "logistics_notes",
    ]
    return {field: _jsonable(getattr(opportunity, field)) for field in fields}


def _requirement_context(requirement: Requirement) -> dict:
    text = requirement.requirement_text or ""
    return {
        "id": requirement.id,
        "type": requirement.requirement_type,
        "title": requirement.title,
        "mandatory": requirement.mandatory,
        "status": requirement.status,
        "risk": requirement.risk,
        "source_file": requirement.source_file,
        "source_page": requirement.source_page,
        "summary": _truncate(text, 500),
    }


def _document_contexts(documents: list[Document]) -> tuple[list[dict], int]:
    snippets = []
    total_chars = 0
    for document in documents:
        snippet = ""
        if document.extracted_text_path and total_chars < MAX_TOTAL_DOC_CHARS:
            snippet = _read_snippet(
                document.extracted_text_path,
                min(MAX_DOC_SNIPPET_CHARS, MAX_TOTAL_DOC_CHARS - total_chars),
            )
            total_chars += len(snippet)
        snippets.append(
            {
                "id": document.id,
                "filename": document.filename,
                "source_url": document.source_url,
                "parsed_status": document.parsed_status,
                "page_count": document.page_count,
                "snippet": snippet,
            }
        )
    return snippets, total_chars


def _read_snippet(path_value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    try:
        path = Path(path_value)
        if not path.exists():
            return ""
        return _truncate(path.read_text(encoding="utf-8", errors="replace"), limit)
    except OSError:
        return ""


def _format_context(context: dict) -> str:
    if not context or not context.get("included"):
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


def _jsonable(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
