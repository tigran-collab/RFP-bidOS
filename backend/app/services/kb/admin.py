"""Admin service: knowledge-base users and company entities."""

from __future__ import annotations

from sqlmodel import Session, select

from app.kb_models import CompanyEntity, KbUser
from app.kb_vocab import (
    PERM_EDIT_METADATA,
    PERM_MANAGE_USERS,
    ROLES,
)
from app.models import utcnow_naive
from app.services.kb.audit import record_audit
from app.services.kb.permissions import require_permission


class KbAdminError(RuntimeError):
    status_code = 400


class KbAdminNotFoundError(RuntimeError):
    status_code = 404


# --- users -------------------------------------------------------------------


def create_user(session: Session, actor: KbUser, payload: dict) -> KbUser:
    require_permission(actor, PERM_MANAGE_USERS)
    role = payload.get("role") or "read_only"
    if role not in ROLES:
        raise KbAdminError(f"Unknown role '{role}'. Allowed: {', '.join(ROLES)}")
    user = KbUser(
        name=str(payload.get("name") or "").strip() or "Unnamed",
        email=payload.get("email"),
        role=role,
        active=bool(payload.get("active", True)),
        created_at=utcnow_naive(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    record_audit(
        session, actor, "user.create", target_type="user", target_id=user.id,
        detail={"role": role},
    )
    return user


def update_user(session: Session, actor: KbUser, user_id: int, payload: dict) -> KbUser:
    require_permission(actor, PERM_MANAGE_USERS)
    user = session.get(KbUser, user_id)
    if user is None:
        raise KbAdminNotFoundError(f"User {user_id} not found")
    if "role" in payload:
        if payload["role"] not in ROLES:
            raise KbAdminError(f"Unknown role '{payload['role']}'")
        user.role = payload["role"]
    for field in ("name", "email", "active"):
        if field in payload:
            setattr(user, field, payload[field])
    session.add(user)
    session.commit()
    session.refresh(user)
    record_audit(
        session, actor, "user.update", target_type="user", target_id=user.id
    )
    return user


def list_users(session: Session, *, active_only: bool = False) -> list[KbUser]:
    users = list(session.exec(select(KbUser)).all())
    if active_only:
        users = [u for u in users if u.active]
    return users


# --- company entities --------------------------------------------------------


def create_entity(session: Session, actor: KbUser, payload: dict) -> CompanyEntity:
    require_permission(actor, PERM_EDIT_METADATA)
    entity = CompanyEntity(
        name=str(payload.get("name") or "").strip() or "Unnamed Entity",
        legal_name=payload.get("legal_name"),
        dba=payload.get("dba"),
        state_of_incorporation=payload.get("state_of_incorporation"),
        description=payload.get("description"),
        active=bool(payload.get("active", True)),
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    session.add(entity)
    session.commit()
    session.refresh(entity)
    record_audit(
        session, actor, "entity.create", target_type="entity", target_id=entity.id
    )
    return entity


def update_entity(
    session: Session, actor: KbUser, entity_id: int, payload: dict
) -> CompanyEntity:
    require_permission(actor, PERM_EDIT_METADATA)
    entity = session.get(CompanyEntity, entity_id)
    if entity is None:
        raise KbAdminNotFoundError(f"Entity {entity_id} not found")
    for field in (
        "name",
        "legal_name",
        "dba",
        "state_of_incorporation",
        "description",
        "active",
    ):
        if field in payload:
            setattr(entity, field, payload[field])
    entity.updated_at = utcnow_naive()
    session.add(entity)
    session.commit()
    session.refresh(entity)
    record_audit(
        session, actor, "entity.update", target_type="entity", target_id=entity.id
    )
    return entity


def list_entities(session: Session, *, active_only: bool = False) -> list[CompanyEntity]:
    entities = list(session.exec(select(CompanyEntity)).all())
    if active_only:
        entities = [e for e in entities if e.active]
    return entities
