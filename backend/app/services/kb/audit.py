"""Append-only audit logging for knowledge-base actions."""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, desc, select

from app.kb_models import KbAuditLog, KbUser
from app.models import utcnow_naive


def record_audit(
    session: Session,
    actor: KbUser | int | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: dict[str, Any] | None = None,
    commit: bool = True,
) -> KbAuditLog:
    """Write an audit-log row. ``actor`` may be a KbUser, a user id, or None."""
    actor_id = actor.id if isinstance(actor, KbUser) else actor
    entry = KbAuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail_json=json.dumps(detail, default=str) if detail else None,
        created_at=utcnow_naive(),
    )
    session.add(entry)
    if commit:
        session.commit()
        session.refresh(entry)
    return entry


def list_audit(
    session: Session,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    actor_id: int | None = None,
    limit: int = 200,
) -> list[KbAuditLog]:
    statement = select(KbAuditLog)
    if target_type is not None:
        statement = statement.where(KbAuditLog.target_type == target_type)
    if target_id is not None:
        statement = statement.where(KbAuditLog.target_id == target_id)
    if actor_id is not None:
        statement = statement.where(KbAuditLog.actor_id == actor_id)
    statement = statement.order_by(desc(KbAuditLog.id)).limit(limit)
    return list(session.exec(statement).all())
