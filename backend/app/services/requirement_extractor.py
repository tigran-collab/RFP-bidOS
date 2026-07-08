import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from sqlmodel import select

from app.config import get_settings
from app.models import Document, Opportunity, Requirement
from app.services import ollama_client
from app.services.ai_evaluator import LOCAL_AI_UNAVAILABLE


NO_PARSED_TEXT = (
    "No parsed document text is available for this opportunity. "
    "Download and parse documents before extracting requirements."
)
INVALID_JSON = "Local AI model returned invalid requirements JSON."
REQUIREMENT_TYPES = {
    "Submission Requirement",
    "Deadline",
    "License",
    "Insurance",
    "Bond",
    "Form",
    "Attachment",
    "Evaluation Criteria",
    "Scope Requirement",
    "Staffing Requirement",
    "Training Requirement",
    "Reporting Requirement",
    "Pricing Requirement",
    "Contract Term",
    "Pre-Bid Requirement",
    "Q&A Requirement",
    "Other",
}
STATUSES = {
    "Needs Review",
    "Compliant",
    "Non-Compliant",
    "Not Applicable",
    "Missing Information",
}


def build_requirement_extraction_prompt(
    opportunity: Opportunity,
    extracted_text_snippets: list[dict],
) -> str:
    fields = {
        "title": opportunity.title,
        "agency": opportunity.agency,
        "solicitation_number": opportunity.solicitation_number,
        "source": opportunity.source,
        "source_url": opportunity.source_url,
        "portal_url": opportunity.portal_url,
        "location": opportunity.location,
        "due_date": _stringify(opportunity.due_date),
        "pre_bid_date": _stringify(opportunity.pre_bid_date),
        "pre_bid_mandatory": opportunity.pre_bid_mandatory,
        "q_and_a_deadline": _stringify(opportunity.q_and_a_deadline),
        "service_type": opportunity.service_type,
        "contract_type": opportunity.contract_type,
        "estimated_value": opportunity.estimated_value,
    }
    snippet_text = "\n\n".join(
        (
            f"Document ID: {snippet.get('document_id')}\n"
            f"Filename: {snippet.get('filename')}\n"
            f"Extracted text path: {snippet.get('extracted_text_path')}\n"
            f"Text:\n{snippet.get('text')}"
        )
        for snippet in extracted_text_snippets
    )

    return f"""
You are extracting requirements from government RFP documents for a security services contractor.

Extract only requirements supported by the provided text.
Do not invent missing requirements.
If page numbers or sections are visible in the text, include them.
If page numbers are not clear, leave source_page null.
Distinguish mandatory requirements from optional/descriptive language.
Flag missing or unclear information.

Look especially for:
- proposal due date
- submission method
- portal requirements
- required forms
- required attachments
- license requirements
- insurance requirements
- bonding requirements
- pre-bid meeting details
- mandatory pre-bid status
- Q&A deadline
- addenda acknowledgment
- pricing form requirements
- staffing requirements
- training requirements
- background check requirements
- reporting requirements
- technology/reporting requirements
- contract term
- renewal options
- evaluation criteria
- minimum qualifications
- references
- financial stability requirements
- exceptions/deviations requirements
- disqualifying conditions

Return valid JSON only.

Required JSON structure:
{{
  "summary": "short summary of extracted requirements",
  "requirements": [
    {{
      "requirement_type": "Submission Requirement | Deadline | License | Insurance | Bond | Form | Attachment | Evaluation Criteria | Scope Requirement | Staffing Requirement | Training Requirement | Reporting Requirement | Pricing Requirement | Contract Term | Pre-Bid Requirement | Q&A Requirement | Other",
      "title": "short requirement title",
      "requirement_text": "exact or closely paraphrased requirement",
      "source_page": null,
      "source_section": null,
      "mandatory": true,
      "due_date": null,
      "status": "Needs Review",
      "assigned_response_section": null,
      "notes": null
    }}
  ],
  "missing_information": [],
  "risk_flags": []
}}

Opportunity metadata:
{json.dumps(fields, default=str, indent=2)}

Extracted document text:
{snippet_text}
""".strip()


def load_extracted_text_for_requirements(
    opportunity_id: int,
    session,
    max_chars: int = 25000,
) -> list[dict]:
    documents = list(
        session.exec(
            select(Document).where(Document.opportunity_id == opportunity_id)
        ).all()
    )
    snippets: list[dict] = []
    remaining = max_chars
    for document in documents:
        if remaining <= 0 or not document.extracted_text_path:
            continue
        path = Path(document.extracted_text_path)
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        snippet = text[:remaining]
        remaining -= len(snippet)
        snippets.append(
            {
                "document_id": document.id,
                "filename": document.filename,
                "extracted_text_path": document.extracted_text_path,
                "text": snippet,
            }
        )
    return snippets


def extract_requirements_with_local_ai(opportunity_id: int, session) -> dict:
    outcome = _run_local_ai_extraction(opportunity_id, session)
    if "extraction_result" not in outcome:
        return outcome
    # Idempotent: pursuit prep and the UI button both call this, so a second run
    # must not double the requirements. Delete this opportunity's prior
    # local-AI rows, then insert the fresh set in the SAME transaction (the
    # delete is only staged here; save_extracted_requirements commits both
    # together) so a failed extraction never destroys existing rows. The
    # extraction already succeeded above, so no early failure reaches this point.
    _delete_local_ai_requirements(opportunity_id, session)
    return _save_and_summarize(opportunity_id, outcome["extraction_result"], session)


def _delete_local_ai_requirements(opportunity_id: int, session) -> None:
    existing = list(
        session.exec(
            select(Requirement).where(
                Requirement.opportunity_id == opportunity_id,
                Requirement.extractor_type == "local_ollama",
            )
        ).all()
    )
    for requirement in existing:
        session.delete(requirement)


def _run_local_ai_extraction(opportunity_id: int, session) -> dict:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return {"error": "Opportunity not found"}

    snippets = load_extracted_text_for_requirements(opportunity_id, session)
    if not snippets:
        return {"error": NO_PARSED_TEXT}

    settings = get_settings()
    prompt = build_requirement_extraction_prompt(opportunity, snippets)
    try:
        response = ollama_client._post_generate(
            {
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 1024},
            },
            timeout=180,
        )
    except requests.RequestException:
        return {"error": LOCAL_AI_UNAVAILABLE}

    raw_response = response.text
    try:
        ollama_payload = response.json()
        response_text = ollama_payload.get("response", "")
        extraction_result = parse_requirements_json_response(response_text)
    except (ValueError, TypeError, json.JSONDecodeError):
        return {"error": INVALID_JSON, "raw_response": raw_response}

    return {"extraction_result": extraction_result}


def _save_and_summarize(opportunity_id: int, extraction_result: dict, session) -> dict:
    saved = save_extracted_requirements(opportunity_id, extraction_result, session)
    return {
        "summary": extraction_result["summary"],
        "requirements_count": len(saved),
        "missing_information": extraction_result["missing_information"],
        "risk_flags": extraction_result["risk_flags"],
        "requirements": saved,
    }


def save_extracted_requirements(
    opportunity_id: int,
    extraction_result: dict,
    session,
) -> list[Requirement]:
    now = _utc_now()
    saved: list[Requirement] = []
    for item in extraction_result.get("requirements", []):
        requirement = Requirement(
            opportunity_id=opportunity_id,
            document_id=None,
            requirement_type=_normalize_requirement_type(item.get("requirement_type")),
            title=str(item.get("title") or "Requirement").strip(),
            requirement_text=str(item.get("requirement_text") or "").strip(),
            source_page=_parse_int_or_none(item.get("source_page")),
            source_section=_none_or_str(item.get("source_section")),
            mandatory=bool(item.get("mandatory", True)),
            due_date=_parse_datetime_or_none(item.get("due_date")),
            status=_normalize_status(item.get("status")),
            assigned_response_section=_none_or_str(item.get("assigned_response_section")),
            notes=_none_or_str(item.get("notes")),
            created_at=now,
            updated_at=now,
            extractor_type="local_ollama",
        )
        if not requirement.requirement_text:
            continue
        session.add(requirement)
        saved.append(requirement)
    session.commit()
    for requirement in saved:
        session.refresh(requirement)
    return saved


def parse_requirements_json_response(response_text: str) -> dict:
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Requirements response was not a JSON object")
    if "requirements" not in data or not isinstance(data["requirements"], list):
        raise ValueError("Requirements response missing requirements list")
    return {
        "summary": str(data.get("summary") or "").strip(),
        "requirements": [
            item for item in data["requirements"] if isinstance(item, dict)
        ],
        "missing_information": _list_or_empty(data.get("missing_information")),
        "risk_flags": _list_or_empty(data.get("risk_flags")),
    }


def refresh_requirements_with_local_ai(opportunity_id: int, session) -> dict:
    outcome = _run_local_ai_extraction(opportunity_id, session)
    if "extraction_result" not in outcome:
        return outcome
    _delete_local_ai_requirements(opportunity_id, session)
    return _save_and_summarize(opportunity_id, outcome["extraction_result"], session)


def _normalize_requirement_type(value: Any) -> str:
    text = str(value or "Other").strip()
    return text if text in REQUIREMENT_TYPES else "Other"


def _normalize_status(value: Any) -> str:
    text = str(value or "Needs Review").strip()
    return text if text in STATUSES else "Needs Review"


def _parse_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime_or_none(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _none_or_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _list_or_empty(value: Any) -> list:
    return value if isinstance(value, list) else []


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
