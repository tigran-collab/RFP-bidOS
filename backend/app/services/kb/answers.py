"""Reusable Answer Library service: approved answers for common RFP questions,
with variants, supporting claims/documents, versioning, and usage tracking."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.kb_models import (
    KbAnswerVersion,
    KbApproval,
    KbUser,
    ReusableAnswer,
    ReusableQuestion,
)
from app.kb_vocab import (
    ANSWER_STATUS_APPROVED,
    ANSWER_STATUS_ARCHIVED,
    ANSWER_STATUS_EXPIRED,
    ANSWER_STATUS_PENDING,
    ANSWER_STATUS_REJECTED,
    PERM_APPROVE_CLAIMS,
    PERM_CREATE_CLAIMS,
    PERM_EDIT_METADATA,
    PERM_REJECT_CLAIMS,
)
from app.models import utcnow_naive
from app.services.kb.audit import record_audit
from app.services.kb.permissions import has_permission, require_permission
from app.services.kb.serializers import answer_to_dict

_ANSWER_SCALARS = (
    "question_id",
    "question_title",
    "category",
    "short_answer",
    "standard_answer",
    "long_answer",
    "company_entity_id",
    "owner",
    "internal_guidance",
    "restrictions",
)
_ANSWER_LISTS = {
    "variants": "variants_json",
    "applicable_services": "applicable_services_json",
    "applicable_states": "applicable_states_json",
    "applicable_industries": "applicable_industries_json",
    "supporting_claim_ids": "supporting_claim_ids_json",
    "supporting_document_ids": "supporting_document_ids_json",
}
_ANSWER_DATES = ("effective_date", "expiration_date", "last_reviewed_at")


class AnswerNotFoundError(RuntimeError):
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


def _apply_payload(answer: ReusableAnswer, payload: dict) -> None:
    for field in _ANSWER_SCALARS:
        if field in payload:
            setattr(answer, field, payload[field])
    for key, column in _ANSWER_LISTS.items():
        if key in payload:
            value = payload[key]
            setattr(answer, column, json.dumps(value) if value else None)
    for field in _ANSWER_DATES:
        if field in payload:
            setattr(answer, field, _parse_date(payload[field]))


def _record_version(
    session: Session, answer: ReusableAnswer, actor: KbUser | None, note: str | None
) -> None:
    session.add(
        KbAnswerVersion(
            answer_id=answer.id,
            version=answer.version,
            snapshot_json=json.dumps(answer_to_dict(answer), default=str),
            change_note=note,
            changed_by=actor.id if actor else None,
            created_at=utcnow_naive(),
        )
    )


def _get_answer(session: Session, answer_id: int) -> ReusableAnswer:
    answer = session.get(ReusableAnswer, answer_id)
    if answer is None:
        raise AnswerNotFoundError(f"Answer {answer_id} not found")
    return answer


# --- reusable questions ------------------------------------------------------


def create_question(session: Session, actor: KbUser, payload: dict) -> ReusableQuestion:
    require_permission(actor, PERM_CREATE_CLAIMS)
    question = ReusableQuestion(
        title=str(payload.get("title") or "").strip(),
        variants_json=json.dumps(payload.get("variants") or []) or None,
        category=payload.get("category"),
        created_by=actor.id,
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    session.add(question)
    session.commit()
    session.refresh(question)
    record_audit(
        session, actor, "question.create", target_type="answer", target_id=question.id
    )
    return question


def list_questions(
    session: Session, *, category: str | None = None
) -> list[ReusableQuestion]:
    questions = list(session.exec(select(ReusableQuestion)).all())
    if category:
        questions = [q for q in questions if q.category == category]
    return questions


# --- reusable answers --------------------------------------------------------


def create_answer(session: Session, actor: KbUser, payload: dict) -> ReusableAnswer:
    require_permission(actor, PERM_CREATE_CLAIMS)
    now = utcnow_naive()
    answer = ReusableAnswer(
        question_title=str(payload.get("question_title") or "").strip(),
        status=payload.get("status") or "Draft",
        version=1,
        created_by=actor.id,
        owner=payload.get("owner") or actor.id,
        created_at=now,
        updated_at=now,
    )
    _apply_payload(answer, {k: v for k, v in payload.items() if k != "status"})
    if answer.status == ANSWER_STATUS_APPROVED and not has_permission(
        actor, PERM_APPROVE_CLAIMS
    ):
        answer.status = ANSWER_STATUS_PENDING
    # If created directly as Approved (by an approver), stamp the approver and
    # record the approval so an auto-usable answer carries attribution + audit.
    approved_on_create = answer.status == ANSWER_STATUS_APPROVED
    if approved_on_create:
        answer.approved_by = actor.id
        answer.approved_at = now
        answer.last_reviewed_at = now
    session.add(answer)
    session.commit()
    session.refresh(answer)
    if approved_on_create:
        session.add(
            KbApproval(
                target_type="answer",
                target_id=answer.id,
                action="approved",
                actor_id=actor.id,
                note="Approved on create",
                created_at=now,
            )
        )
    _record_version(session, answer, actor, "created")
    record_audit(
        session, actor, "answer.create", target_type="answer", target_id=answer.id,
        detail={"status": answer.status}, commit=False,
    )
    session.commit()
    session.refresh(answer)
    return answer


def update_answer(
    session: Session,
    actor: KbUser,
    answer_id: int,
    payload: dict,
    change_note: str | None = None,
) -> ReusableAnswer:
    require_permission(actor, PERM_EDIT_METADATA)
    answer = _get_answer(session, answer_id)
    _apply_payload(answer, payload)
    answer.version += 1
    answer.updated_at = utcnow_naive()
    session.add(answer)
    session.commit()
    session.refresh(answer)
    _record_version(session, answer, actor, change_note or "updated")
    record_audit(
        session, actor, "answer.update", target_type="answer", target_id=answer.id,
        detail={"fields": sorted(payload.keys())}, commit=False,
    )
    session.commit()
    session.refresh(answer)
    return answer


def _set_status(
    session: Session,
    actor: KbUser,
    answer: ReusableAnswer,
    status: str,
    action: str,
    note: str | None,
    *,
    stamp_approval: bool = False,
) -> ReusableAnswer:
    answer.status = status
    answer.version += 1
    answer.updated_at = utcnow_naive()
    if stamp_approval:
        answer.approved_by = actor.id
        answer.approved_at = utcnow_naive()
        answer.last_reviewed_at = utcnow_naive()
    session.add(answer)
    session.add(
        KbApproval(
            target_type="answer",
            target_id=answer.id,
            action=action,
            actor_id=actor.id,
            note=note,
            created_at=utcnow_naive(),
        )
    )
    session.commit()
    session.refresh(answer)
    _record_version(session, answer, actor, note or action)
    record_audit(
        session, actor, f"answer.{action}", target_type="answer", target_id=answer.id,
        detail={"status": status}, commit=False,
    )
    session.commit()
    session.refresh(answer)
    return answer


def approve_answer(
    session: Session, actor: KbUser, answer_id: int, note: str | None = None
) -> ReusableAnswer:
    require_permission(actor, PERM_APPROVE_CLAIMS)
    answer = _get_answer(session, answer_id)
    return _set_status(
        session, actor, answer, ANSWER_STATUS_APPROVED, "approved", note,
        stamp_approval=True,
    )


def reject_answer(
    session: Session, actor: KbUser, answer_id: int, note: str | None = None
) -> ReusableAnswer:
    require_permission(actor, PERM_REJECT_CLAIMS)
    answer = _get_answer(session, answer_id)
    return _set_status(session, actor, answer, ANSWER_STATUS_REJECTED, "rejected", note)


def archive_answer(
    session: Session, actor: KbUser, answer_id: int, note: str | None = None
) -> ReusableAnswer:
    require_permission(actor, PERM_EDIT_METADATA)
    answer = _get_answer(session, answer_id)
    return _set_status(session, actor, answer, ANSWER_STATUS_ARCHIVED, "archived", note)


def record_answer_usage(session: Session, answer_id: int) -> None:
    """Bump usage_count/last_used_at when an answer feeds a generated response."""
    answer = session.get(ReusableAnswer, answer_id)
    if answer is None:
        return
    answer.usage_count = (answer.usage_count or 0) + 1
    answer.last_used_at = utcnow_naive()
    session.add(answer)
    session.commit()


def list_answers(
    session: Session,
    *,
    company_entity_id: int | None = None,
    category: str | None = None,
    status: str | None = None,
) -> list[ReusableAnswer]:
    answers = list(session.exec(select(ReusableAnswer)).all())
    out = []
    for a in answers:
        if company_entity_id is not None and a.company_entity_id != company_entity_id:
            continue
        if category and a.category != category:
            continue
        if status and a.status != status:
            continue
        out.append(a)
    out.sort(key=lambda a: (a.updated_at or a.created_at or utcnow_naive()), reverse=True)
    return out


def get_answer_detail(session: Session, answer_id: int) -> dict:
    answer = _get_answer(session, answer_id)
    versions = list(
        session.exec(
            select(KbAnswerVersion).where(KbAnswerVersion.answer_id == answer_id)
        ).all()
    )
    from app.services.kb.serializers import _iso  # noqa: PLC0415

    return {
        "answer": answer_to_dict(answer),
        "versions": [
            {
                "id": v.id,
                "version": v.version,
                "change_note": v.change_note,
                "changed_by": v.changed_by,
                "created_at": _iso(v.created_at),
            }
            for v in versions
        ],
    }


def expire_due_answers(session: Session, now: datetime | None = None) -> int:
    now = now or utcnow_naive()
    answers = list(
        session.exec(
            select(ReusableAnswer).where(ReusableAnswer.status == ANSWER_STATUS_APPROVED)
        ).all()
    )
    updated = 0
    for answer in answers:
        if answer.expiration_date is not None and answer.expiration_date < now:
            answer.status = ANSWER_STATUS_EXPIRED
            answer.updated_at = now
            session.add(answer)
            updated += 1
    if updated:
        session.commit()
    return updated
