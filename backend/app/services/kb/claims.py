"""Claims Registry service: create, edit, approve/reject/restrict/supersede,
version history, and expiration. Only Approved, non-expired claims are eligible
for automatic use in AI responses (enforced in retrieval)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.kb_models import Claim, KbApproval, KbClaimSource, KbClaimVersion, KbUser
from app.kb_vocab import (
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_ARCHIVED,
    CLAIM_STATUS_EXPIRED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_REJECTED,
    CLAIM_STATUS_RESTRICTED,
    CLAIM_STATUS_SUPERSEDED,
    PERM_APPROVE_CLAIMS,
    PERM_CREATE_CLAIMS,
    PERM_EDIT_METADATA,
    PERM_REJECT_CLAIMS,
    PERM_VIEW_RESTRICTED,
)
from app.models import utcnow_naive
from app.services.kb.audit import record_audit
from app.services.kb.permissions import (
    KbPermissionError,
    can_view_restricted,
    require_permission,
)
from app.services.kb.serializers import claim_to_dict

_LIST_FIELDS = {
    "applicable_states": "applicable_states_json",
    "service_scope": "service_scope_json",
    "industry_scope": "industry_scope_json",
}
_SCALAR_FIELDS = (
    "title",
    "canonical_text",
    "short_text",
    "long_text",
    "category",
    "company_entity_id",
    "geographic_scope",
    "source_document_id",
    "source_page",
    "source_section",
    "supporting_excerpt",
    "owner",
    "confidence",
    "restrictions",
    "internal_notes",
    "prohibited_use_notes",
)
_DATE_FIELDS = ("effective_date", "expiration_date", "last_reviewed_at")


class ClaimNotFoundError(RuntimeError):
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


def _apply_payload(claim: Claim, payload: dict) -> None:
    for field in _SCALAR_FIELDS:
        if field in payload:
            setattr(claim, field, payload[field])
    for key, column in _LIST_FIELDS.items():
        if key in payload:
            value = payload[key]
            setattr(claim, column, json.dumps(value) if value else None)
    for field in _DATE_FIELDS:
        if field in payload:
            setattr(claim, field, _parse_date(payload[field]))


def _record_version(
    session: Session, claim: Claim, actor: KbUser | None, note: str | None
) -> None:
    version = KbClaimVersion(
        claim_id=claim.id,
        version=claim.version,
        snapshot_json=json.dumps(claim_to_dict(claim), default=str),
        change_note=note,
        changed_by=actor.id if actor else None,
        created_at=utcnow_naive(),
    )
    session.add(version)


def _get_claim(session: Session, claim_id: int) -> Claim:
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim {claim_id} not found")
    return claim


def _guard_restricted(claim: Claim, actor: KbUser) -> None:
    """Block reading/mutating a Restricted claim's content for actors without
    the view-restricted permission (prevents restricted content leaking back
    through edit/archive/submit/restore/source endpoints)."""
    if claim.status == CLAIM_STATUS_RESTRICTED and not can_view_restricted(actor):
        raise KbPermissionError(PERM_VIEW_RESTRICTED, actor.role if actor else None)


def create_claim(session: Session, actor: KbUser, payload: dict) -> Claim:
    require_permission(actor, PERM_CREATE_CLAIMS)
    now = utcnow_naive()
    claim = Claim(
        title=str(payload.get("title") or "Untitled claim").strip(),
        canonical_text=str(payload.get("canonical_text") or "").strip(),
        status=payload.get("status") or "Draft",
        version=1,
        created_by=actor.id,
        owner=payload.get("owner") or actor.id,
        created_at=now,
        updated_at=now,
    )
    _apply_payload(claim, {k: v for k, v in payload.items() if k not in {"status"}})
    # A non-admin creating a claim cannot self-approve it on creation.
    if claim.status == CLAIM_STATUS_APPROVED and not _can_approve(actor):
        claim.status = CLAIM_STATUS_PENDING
    # If created directly as Approved (by an approver), stamp the approver and
    # record the approval so an auto-usable claim carries proper attribution and
    # an audit trail — matching the approve_claim path.
    approved_on_create = claim.status == CLAIM_STATUS_APPROVED
    if approved_on_create:
        claim.approved_by = actor.id
        claim.approved_at = now
        claim.last_reviewed_at = now
    session.add(claim)
    session.commit()
    session.refresh(claim)
    if approved_on_create:
        session.add(
            KbApproval(
                target_type="claim",
                target_id=claim.id,
                action="approved",
                actor_id=actor.id,
                note="Approved on create",
                created_at=now,
            )
        )
    _record_version(session, claim, actor, "created")
    record_audit(
        session, actor, "claim.create", target_type="claim", target_id=claim.id,
        detail={"title": claim.title, "status": claim.status}, commit=False,
    )
    session.commit()
    session.refresh(claim)
    return claim


def update_claim(
    session: Session,
    actor: KbUser,
    claim_id: int,
    payload: dict,
    change_note: str | None = None,
) -> Claim:
    require_permission(actor, PERM_EDIT_METADATA)
    claim = _get_claim(session, claim_id)
    _guard_restricted(claim, actor)
    _apply_payload(claim, payload)
    claim.version += 1
    claim.updated_at = utcnow_naive()
    session.add(claim)
    session.commit()
    session.refresh(claim)
    _record_version(session, claim, actor, change_note or "updated")
    record_audit(
        session, actor, "claim.update", target_type="claim", target_id=claim.id,
        detail={"fields": sorted(payload.keys())}, commit=False,
    )
    session.commit()
    session.refresh(claim)
    return claim


def _can_approve(actor: KbUser | None) -> bool:
    from app.services.kb.permissions import has_permission

    return has_permission(actor, PERM_APPROVE_CLAIMS)


def _set_status(
    session: Session,
    actor: KbUser,
    claim: Claim,
    status: str,
    action: str,
    note: str | None,
    *,
    stamp_approval: bool = False,
) -> Claim:
    claim.status = status
    claim.version += 1
    claim.updated_at = utcnow_naive()
    if stamp_approval:
        claim.approved_by = actor.id
        claim.approved_at = utcnow_naive()
        claim.last_reviewed_at = utcnow_naive()
    session.add(claim)
    session.add(
        KbApproval(
            target_type="claim",
            target_id=claim.id,
            action=action,
            actor_id=actor.id,
            note=note,
            created_at=utcnow_naive(),
        )
    )
    session.commit()
    session.refresh(claim)
    _record_version(session, claim, actor, note or action)
    record_audit(
        session, actor, f"claim.{action}", target_type="claim", target_id=claim.id,
        detail={"status": status, "note": note}, commit=False,
    )
    session.commit()
    session.refresh(claim)
    return claim


def approve_claim(
    session: Session, actor: KbUser, claim_id: int, note: str | None = None
) -> Claim:
    require_permission(actor, PERM_APPROVE_CLAIMS)
    claim = _get_claim(session, claim_id)
    return _set_status(
        session, actor, claim, CLAIM_STATUS_APPROVED, "approved", note,
        stamp_approval=True,
    )


def reject_claim(
    session: Session, actor: KbUser, claim_id: int, note: str | None = None
) -> Claim:
    require_permission(actor, PERM_REJECT_CLAIMS)
    claim = _get_claim(session, claim_id)
    return _set_status(session, actor, claim, CLAIM_STATUS_REJECTED, "rejected", note)


def restrict_claim(
    session: Session, actor: KbUser, claim_id: int, note: str | None = None
) -> Claim:
    require_permission(actor, PERM_APPROVE_CLAIMS)
    claim = _get_claim(session, claim_id)
    return _set_status(session, actor, claim, CLAIM_STATUS_RESTRICTED, "restricted", note)


def archive_claim(
    session: Session, actor: KbUser, claim_id: int, note: str | None = None
) -> Claim:
    require_permission(actor, PERM_EDIT_METADATA)
    claim = _get_claim(session, claim_id)
    _guard_restricted(claim, actor)
    return _set_status(session, actor, claim, CLAIM_STATUS_ARCHIVED, "archived", note)


def submit_for_review(
    session: Session, actor: KbUser, claim_id: int, note: str | None = None
) -> Claim:
    require_permission(actor, PERM_CREATE_CLAIMS)
    claim = _get_claim(session, claim_id)
    _guard_restricted(claim, actor)
    return _set_status(session, actor, claim, CLAIM_STATUS_PENDING, "submitted", note)


def supersede_claim(
    session: Session,
    actor: KbUser,
    claim_id: int,
    superseded_by_id: int,
    note: str | None = None,
) -> Claim:
    """Mark ``claim_id`` as superseded by ``superseded_by_id``."""
    require_permission(actor, PERM_APPROVE_CLAIMS)
    claim = _get_claim(session, claim_id)
    _get_claim(session, superseded_by_id)  # validate target exists
    claim.superseded_by_id = superseded_by_id
    return _set_status(
        session, actor, claim, CLAIM_STATUS_SUPERSEDED, "superseded", note
    )


def add_claim_source(
    session: Session,
    actor: KbUser,
    claim_id: int,
    *,
    document_id: int | None = None,
    chunk_id: int | None = None,
    page_number: int | None = None,
    section: str | None = None,
    excerpt: str | None = None,
) -> KbClaimSource:
    require_permission(actor, PERM_EDIT_METADATA)
    _guard_restricted(_get_claim(session, claim_id), actor)
    source = KbClaimSource(
        claim_id=claim_id,
        document_id=document_id,
        chunk_id=chunk_id,
        page_number=page_number,
        section=section,
        excerpt=excerpt,
        created_at=utcnow_naive(),
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    record_audit(
        session, actor, "claim.add_source", target_type="claim", target_id=claim_id,
        detail={"document_id": document_id},
    )
    return source


def restore_claim_version(
    session: Session, actor: KbUser, claim_id: int, version_id: int
) -> Claim:
    require_permission(actor, PERM_EDIT_METADATA)
    _guard_restricted(_get_claim(session, claim_id), actor)
    version = session.get(KbClaimVersion, version_id)
    if version is None or version.claim_id != claim_id:
        raise ClaimNotFoundError(f"Version {version_id} not found for claim {claim_id}")
    snapshot = json.loads(version.snapshot_json)
    # Restore every content field _apply_payload understands (scalars, list
    # fields, and dates) so the claim actually reverts to the selected version —
    # not just a hardcoded subset. Status/approval/version are intentionally not
    # restored (the restore itself is a new versioned edit).
    restorable = list(_SCALAR_FIELDS) + list(_LIST_FIELDS.keys()) + list(_DATE_FIELDS)
    payload = {field: snapshot.get(field) for field in restorable if field in snapshot}
    return update_claim(
        session, actor, claim_id, payload, change_note=f"restored v{version.version}"
    )


def list_claims(
    session: Session,
    *,
    company_entity_id: int | None = None,
    category: str | None = None,
    status: str | None = None,
    state: str | None = None,
    service_type: str | None = None,
    industry: str | None = None,
    include_restricted: bool = True,
) -> list[Claim]:
    claims = list(session.exec(select(Claim)).all())
    out = []
    for c in claims:
        if company_entity_id is not None and c.company_entity_id != company_entity_id:
            continue
        if category and c.category != category:
            continue
        if status and c.status != status:
            continue
        if not include_restricted and c.status == CLAIM_STATUS_RESTRICTED:
            continue
        if state and (states := json.loads(c.applicable_states_json or "[]")):
            if state.upper() not in [str(s).upper() for s in states]:
                continue
        if service_type and (scope := json.loads(c.service_scope_json or "[]")):
            if service_type not in scope:
                continue
        if industry and (scope := json.loads(c.industry_scope_json or "[]")):
            if industry not in scope:
                continue
        out.append(c)
    out.sort(key=lambda c: (c.updated_at or c.created_at or utcnow_naive()), reverse=True)
    return out


def get_claim_detail(
    session: Session, claim_id: int, actor: KbUser | None = None
) -> dict:
    claim = _get_claim(session, claim_id)
    if claim.status == CLAIM_STATUS_RESTRICTED and not can_view_restricted(actor):
        # Return a redacted stub rather than the restricted content.
        return {
            "claim": {
                "id": claim.id,
                "title": claim.title,
                "status": claim.status,
                "restricted": True,
            },
            "sources": [],
            "versions": [],
            "restricted": True,
        }
    from app.services.kb.serializers import (
        claim_source_to_dict,
        claim_version_to_dict,
    )

    sources = list(
        session.exec(select(KbClaimSource).where(KbClaimSource.claim_id == claim_id)).all()
    )
    versions = list(
        session.exec(
            select(KbClaimVersion).where(KbClaimVersion.claim_id == claim_id)
        ).all()
    )
    return {
        "claim": claim_to_dict(claim),
        "sources": [claim_source_to_dict(s) for s in sources],
        "versions": [claim_version_to_dict(v) for v in versions],
        "restricted": False,
    }


def expire_due_claims(session: Session, now: datetime | None = None) -> int:
    """Move Approved claims past their expiration date to Expired. Deterministic
    maintenance (no AI); returns the number updated."""
    now = now or utcnow_naive()
    claims = list(
        session.exec(select(Claim).where(Claim.status == CLAIM_STATUS_APPROVED)).all()
    )
    updated = 0
    for claim in claims:
        if claim.expiration_date is not None and claim.expiration_date < now:
            claim.status = CLAIM_STATUS_EXPIRED
            claim.updated_at = now
            session.add(claim)
            session.add(
                KbApproval(
                    target_type="claim",
                    target_id=claim.id,
                    action="expired",
                    actor_id=None,
                    note="Auto-expired past expiration date",
                    created_at=now,
                )
            )
            updated += 1
    if updated:
        session.commit()
    return updated
