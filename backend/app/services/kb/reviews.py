"""Review requests, comments, and approval/audit history for KB targets."""

from __future__ import annotations

from sqlmodel import Session, desc, select

from app.kb_models import KbApproval, KbComment, KbReviewRequest, KbUser
from app.kb_vocab import TARGET_TYPES
from app.models import utcnow_naive
from app.services.kb.audit import record_audit


class KbReviewError(RuntimeError):
    status_code = 400


def _validate_target(target_type: str) -> None:
    if target_type not in TARGET_TYPES:
        raise KbReviewError(f"Unknown target type '{target_type}'")


def create_review_request(
    session: Session,
    actor: KbUser,
    *,
    target_type: str,
    target_id: int,
    note: str | None = None,
    assigned_to: int | None = None,
) -> KbReviewRequest:
    _validate_target(target_type)
    request = KbReviewRequest(
        target_type=target_type,
        target_id=target_id,
        status="Open",
        note=note,
        requested_by=actor.id,
        assigned_to=assigned_to,
        created_at=utcnow_naive(),
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    record_audit(
        session, actor, "review.request", target_type=target_type, target_id=target_id
    )
    return request


def resolve_review_request(
    session: Session,
    actor: KbUser,
    request_id: int,
    *,
    status: str,
    resolution: str | None = None,
) -> KbReviewRequest:
    request = session.get(KbReviewRequest, request_id)
    if request is None:
        raise KbReviewError(f"Review request {request_id} not found")
    request.status = status
    request.resolution = resolution
    request.resolved_by = actor.id
    request.resolved_at = utcnow_naive()
    session.add(request)
    session.commit()
    session.refresh(request)
    record_audit(
        session, actor, "review.resolve", target_type=request.target_type,
        target_id=request.target_id, detail={"status": status},
    )
    return request


def list_review_requests(
    session: Session,
    *,
    status: str | None = "Open",
    target_type: str | None = None,
    assigned_to: int | None = None,
) -> list[KbReviewRequest]:
    requests = list(
        session.exec(
            select(KbReviewRequest).order_by(desc(KbReviewRequest.id))
        ).all()
    )
    out = []
    for r in requests:
        if status and r.status != status:
            continue
        if target_type and r.target_type != target_type:
            continue
        if assigned_to is not None and r.assigned_to != assigned_to:
            continue
        out.append(r)
    return out


def add_comment(
    session: Session,
    actor: KbUser,
    *,
    target_type: str,
    target_id: int,
    body: str,
) -> KbComment:
    _validate_target(target_type)
    comment = KbComment(
        target_type=target_type,
        target_id=target_id,
        author_id=actor.id,
        body=body,
        created_at=utcnow_naive(),
    )
    session.add(comment)
    session.commit()
    session.refresh(comment)
    record_audit(
        session, actor, "comment.add", target_type=target_type, target_id=target_id
    )
    return comment


def list_comments(
    session: Session, target_type: str, target_id: int
) -> list[KbComment]:
    return list(
        session.exec(
            select(KbComment)
            .where(
                KbComment.target_type == target_type,
                KbComment.target_id == target_id,
            )
            .order_by(KbComment.id)
        ).all()
    )


def list_approvals(
    session: Session, target_type: str, target_id: int
) -> list[KbApproval]:
    return list(
        session.exec(
            select(KbApproval)
            .where(
                KbApproval.target_type == target_type,
                KbApproval.target_id == target_id,
            )
            .order_by(KbApproval.id)
        ).all()
    )
