"""Generated-response management: list, detail (with citations), edit the
drafted text, review workflow, and saving a response under an existing
Opportunity (project integration)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, desc, select

from app.kb_models import GeneratedResponse, KbUser, ResponseCitation
from app.kb_vocab import PERM_DRAFT_RESPONSES, RESPONSE_REVIEW_STATUSES
from app.models import Opportunity, utcnow_naive
from app.services.kb.audit import record_audit
from app.services.kb.permissions import require_permission
from app.services.kb.serializers import citation_to_dict, response_to_dict


class ResponseNotFoundError(RuntimeError):
    status_code = 404


def _parse_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _get(session: Session, response_id: int) -> GeneratedResponse:
    response = session.get(GeneratedResponse, response_id)
    if response is None:
        raise ResponseNotFoundError(f"Response {response_id} not found")
    return response


def list_responses(
    session: Session,
    *,
    opportunity_id: int | None = None,
    review_status: str | None = None,
    company_entity_id: int | None = None,
    limit: int = 100,
) -> list[GeneratedResponse]:
    responses = list(
        session.exec(
            select(GeneratedResponse).order_by(desc(GeneratedResponse.id))
        ).all()
    )
    out = []
    for r in responses:
        if opportunity_id is not None and r.opportunity_id != opportunity_id:
            continue
        if review_status and r.review_status != review_status:
            continue
        if company_entity_id is not None and r.company_entity_id != company_entity_id:
            continue
        out.append(r)
    return out[:limit]


def get_response_detail(session: Session, response_id: int) -> dict:
    response = _get(session, response_id)
    citations = list(
        session.exec(
            select(ResponseCitation).where(ResponseCitation.response_id == response_id)
        ).all()
    )
    return {
        "response": response_to_dict(response, include_prompt=True),
        "citations": [citation_to_dict(c) for c in citations],
    }


def update_response(
    session: Session, actor: KbUser, response_id: int, payload: dict
) -> GeneratedResponse:
    """Edit the drafted text / project fields / review status."""
    require_permission(actor, PERM_DRAFT_RESPONSES)
    response = _get(session, response_id)
    for field in (
        "response_text",
        "rfp_section",
        "question_number",
        "assigned_owner",
        "agency_name",
        "solicitation_number",
    ):
        if field in payload:
            setattr(response, field, payload[field])
    if "review_status" in payload and payload["review_status"] in RESPONSE_REVIEW_STATUSES:
        response.review_status = payload["review_status"]
    if "due_date" in payload:
        response.due_date = _parse_date(payload["due_date"])
    if "opportunity_id" in payload:
        opp_id = payload["opportunity_id"]
        if opp_id is not None and session.get(Opportunity, opp_id) is None:
            raise ResponseNotFoundError(f"Opportunity {opp_id} not found")
        response.opportunity_id = opp_id
    response.updated_at = utcnow_naive()
    session.add(response)
    session.commit()
    session.refresh(response)
    record_audit(
        session, actor, "response.update", target_type="response",
        target_id=response.id, detail={"fields": sorted(payload.keys())},
    )
    return response


def save_to_project(
    session: Session,
    actor: KbUser,
    response_id: int,
    *,
    opportunity_id: int,
    rfp_section: str | None = None,
    question_number: str | None = None,
    assigned_owner: int | None = None,
    due_date: Any = None,
    review_status: str | None = None,
) -> GeneratedResponse:
    """Link a generated response to an existing Opportunity (project)."""
    require_permission(actor, PERM_DRAFT_RESPONSES)
    response = _get(session, response_id)
    if session.get(Opportunity, opportunity_id) is None:
        raise ResponseNotFoundError(f"Opportunity {opportunity_id} not found")
    response.opportunity_id = opportunity_id
    if rfp_section is not None:
        response.rfp_section = rfp_section
    if question_number is not None:
        response.question_number = question_number
    if assigned_owner is not None:
        response.assigned_owner = assigned_owner
    if due_date is not None:
        response.due_date = _parse_date(due_date)
    if review_status in RESPONSE_REVIEW_STATUSES:
        response.review_status = review_status
    response.updated_at = utcnow_naive()
    session.add(response)
    session.commit()
    session.refresh(response)
    record_audit(
        session, actor, "response.save_to_project", target_type="response",
        target_id=response.id, detail={"opportunity_id": opportunity_id},
    )
    return response


def delete_response(session: Session, actor: KbUser, response_id: int) -> None:
    require_permission(actor, PERM_DRAFT_RESPONSES)
    response = _get(session, response_id)
    for citation in session.exec(
        select(ResponseCitation).where(ResponseCitation.response_id == response_id)
    ).all():
        session.delete(citation)
    session.delete(response)
    session.commit()
    record_audit(
        session, actor, "response.delete", target_type="response", target_id=response_id
    )
