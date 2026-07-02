import json
from datetime import UTC, datetime
from typing import Any

from app.models import Opportunity
from app.services.ai_evaluator import load_extracted_text_snippets
from app.services.ollama_client import (
    LOCAL_AI_UNAVAILABLE,
    LocalAIUnavailableError,
    generate_text,
)


def build_opportunity_summary_prompt(
    opportunity: Opportunity,
    extracted_text_snippets: list[dict] | None = None,
) -> str:
    snippets = extracted_text_snippets or []
    fields = {
        "title": opportunity.title,
        "agency": opportunity.agency,
        "location": opportunity.location,
        "service_type": opportunity.service_type,
        "contract_type": opportunity.contract_type,
        "due_date": _stringify(opportunity.due_date),
        "q_and_a_deadline": _stringify(opportunity.q_and_a_deadline),
        "pre_bid_date": _stringify(opportunity.pre_bid_date),
        "submission_method": opportunity.submission_method,
        "estimated_value": opportunity.estimated_value,
        "relevance_reason": getattr(opportunity, "relevance_reason", None),
    }
    snippet_text = "\n\n".join(
        (
            f"Document: {snippet.get('filename')}\n"
            f"Text:\n{snippet.get('text')}"
        )
        for snippet in snippets
    )
    if not snippet_text:
        snippet_text = "No extracted document text is available. Summarize from opportunity fields only."

    return f"""
You are helping a security-services contractor quickly triage a government bid opportunity.

Write a TIGHT summary of 3-6 sentences in plain text (no preamble, no headings, no bullet points).
Cover:
- what the opportunity is and the scope of work
- the key dates and deadlines
- notable or mandatory requirements
- security-services fit or any red flags

Accuracy rules:
- Do not invent deadlines, licenses, values, or requirements.
- If information is missing or unclear, say so briefly.
- Base the summary only on the fields and document text provided.

Opportunity fields:
{json.dumps(fields, default=str, indent=2)}

Extracted document text snippets:
{snippet_text}
""".strip()


def summarize_opportunity(opportunity_id: int, session) -> dict:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return {"ok": False, "summary": None, "message": "Opportunity not found"}

    snippets = load_extracted_text_snippets(opportunity_id, session)
    prompt = build_opportunity_summary_prompt(opportunity, snippets)

    try:
        summary = generate_text(prompt, max_tokens=450)
    except LocalAIUnavailableError:
        return {"ok": False, "summary": None, "message": LOCAL_AI_UNAVAILABLE}
    except Exception as exc:  # noqa: BLE001 - never let AI/network errors crash
        message = str(exc) or exc.__class__.__name__
        return {"ok": False, "summary": None, "message": message}

    summary = (summary or "").strip()
    if not summary:
        return {
            "ok": False,
            "summary": None,
            "message": "Local AI model returned an empty summary.",
        }

    opportunity.ai_summary = summary
    opportunity.ai_summary_at = _utc_now()
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)
    return {"ok": True, "summary": summary, "message": "ok"}


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
