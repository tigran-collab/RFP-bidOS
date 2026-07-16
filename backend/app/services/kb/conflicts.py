"""Conflict detection + resolution.

Surfaces potentially contradictory claims within the same legal entity:
different employee counts, license numbers, insurance limits, years in
business, addresses, company names, etc. Conflicts land in an admin review
queue where an authoritative claim can be selected and the other superseded,
restricted, rejected, merged, or explained — with an audit trail.
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from app.kb_models import Claim, KbConflict, KbUser
from app.kb_vocab import (
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_RESTRICTED,
    PERM_RESOLVE_CONFLICTS,
)
from app.models import utcnow_naive
from app.services.kb.audit import record_audit
from app.services.kb.permissions import require_permission

# Claim statuses considered "live" for conflict comparison.
_ACTIVE_STATUSES = {CLAIM_STATUS_APPROVED, CLAIM_STATUS_PENDING, CLAIM_STATUS_RESTRICTED}

_LICENSE_RE = re.compile(
    r"\b(?:PPO|PSC|license|licen[sc]e|permit|registration)\s*(?:no\.?|number|#|:)?\s*"
    r"([A-Z]{0,3}[-\s]?\d{3,10})",
    re.I,
)
_MONEY_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d{4,})(?:\.\d{2})?")
_EMPLOYEES_RE = re.compile(r"\b([\d,]{2,})\s+(?:employees|officers|guards|personnel|staff)\b", re.I)
_YEARS_RE = re.compile(r"\b(\d{1,3})\+?\s+years?\b", re.I)
_FOUNDED_RE = re.compile(r"\b(?:founded|established|incorporated|since)\s+(?:in\s+)?(\d{4})", re.I)
_ADDRESS_RE = re.compile(
    r"\b(\d{1,6}\s+[A-Z][A-Za-z0-9.\s]+(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Suite|Ste|Way|Lane|Ln)\b)",
    re.I,
)

_SIGNAL_TYPES = {
    "employee_count": ("employee count", _EMPLOYEES_RE),
    "license_number": ("license number", _LICENSE_RE),
    "insurance_limit": ("insurance limit", _MONEY_RE),
    "years_in_business": ("years in business", _YEARS_RE),
    "founded_year": ("founded year", _FOUNDED_RE),
    "office_address": ("office address", _ADDRESS_RE),
}


class ConflictNotFoundError(RuntimeError):
    status_code = 404


class ConflictResolutionError(RuntimeError):
    status_code = 400


def _normalize(value: str) -> str:
    return re.sub(r"[\s,]+", "", str(value)).strip().upper()


def _extract_signals(claim: Claim) -> dict[str, str]:
    text = " ".join(
        p for p in [claim.canonical_text, claim.short_text, claim.long_text] if p
    )
    signals: dict[str, str] = {}
    for key, (_label, pattern) in _SIGNAL_TYPES.items():
        match = pattern.search(text)
        if match:
            signals[key] = match.group(1)
    return signals


def detect_conflicts(
    session: Session, *, company_entity_id: int | None = None
) -> int:
    """Detect conflicts among live claims. Returns count of NEW conflicts.

    When ``company_entity_id`` is None, entity-agnostic claims are compared as a
    single group and each entity's claims are compared within that entity.
    """
    claims = list(session.exec(select(Claim)).all())
    claims = [c for c in claims if (c.status or "") in _ACTIVE_STATUSES]
    if company_entity_id is not None:
        claims = [
            c
            for c in claims
            if c.company_entity_id == company_entity_id or c.company_entity_id is None
        ]

    # Group by entity (None grouped under key 0) so we never cross legal entities.
    groups: dict[int, list[Claim]] = {}
    for claim in claims:
        groups.setdefault(claim.company_entity_id or 0, []).append(claim)

    existing = list(session.exec(select(KbConflict)).all())
    existing_keys = {
        (min(c.claim_a_id or 0, c.claim_b_id or 0), max(c.claim_a_id or 0, c.claim_b_id or 0), c.field)
        for c in existing
    }

    created = 0
    now = utcnow_naive()
    for entity_id, group in groups.items():
        by_signal: dict[str, list[tuple[Claim, str]]] = {}
        for claim in group:
            for key, value in _extract_signals(claim).items():
                by_signal.setdefault(key, []).append((claim, value))
        for signal_key, entries in by_signal.items():
            label = _SIGNAL_TYPES[signal_key][0]
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    claim_a, value_a = entries[i]
                    claim_b, value_b = entries[j]
                    if _normalize(value_a) == _normalize(value_b):
                        continue
                    pair_key = (
                        min(claim_a.id, claim_b.id),
                        max(claim_a.id, claim_b.id),
                        signal_key,
                    )
                    if pair_key in existing_keys:
                        continue
                    session.add(
                        KbConflict(
                            conflict_type=signal_key,
                            company_entity_id=(entity_id or None),
                            claim_a_id=claim_a.id,
                            claim_b_id=claim_b.id,
                            field=signal_key,
                            value_a=str(value_a),
                            value_b=str(value_b),
                            detail=f"Conflicting {label}: {value_a!r} vs {value_b!r}",
                            status="Open",
                            created_at=now,
                        )
                    )
                    existing_keys.add(pair_key)
                    created += 1
    if created:
        session.commit()
    return created


def list_conflicts(
    session: Session,
    *,
    status: str | None = "Open",
    company_entity_id: int | None = None,
) -> list[KbConflict]:
    conflicts = list(session.exec(select(KbConflict)).all())
    out = []
    for c in conflicts:
        if status and c.status != status:
            continue
        if company_entity_id is not None and c.company_entity_id != company_entity_id:
            continue
        out.append(c)
    out.sort(key=lambda c: c.created_at or utcnow_naive(), reverse=True)
    return out


def resolve_conflict(
    session: Session,
    actor: KbUser,
    conflict_id: int,
    *,
    resolution: str,
    authoritative_claim_id: int | None = None,
    explanation: str | None = None,
) -> KbConflict:
    """Resolve a conflict. Depending on resolution, may supersede/restrict/reject
    the non-authoritative claim. Uses the claims service so version history and
    approvals are preserved."""
    require_permission(actor, PERM_RESOLVE_CONFLICTS)
    conflict = session.get(KbConflict, conflict_id)
    if conflict is None:
        raise ConflictNotFoundError(f"Conflict {conflict_id} not found")

    # The authoritative claim must be one of the two conflicting claims —
    # otherwise the ternary below would silently supersede/restrict/reject the
    # wrong (participant) claim in favor of an unrelated one.
    if authoritative_claim_id is not None and authoritative_claim_id not in {
        conflict.claim_a_id,
        conflict.claim_b_id,
    }:
        raise ConflictResolutionError(
            "authoritative_claim_id must be one of the conflicting claims "
            f"({conflict.claim_a_id} or {conflict.claim_b_id})."
        )

    from app.services.kb import claims as claims_service

    other_id = None
    if authoritative_claim_id is not None:
        other_id = (
            conflict.claim_b_id
            if authoritative_claim_id == conflict.claim_a_id
            else conflict.claim_a_id
        )

    if resolution == "Superseded" and other_id and authoritative_claim_id:
        claims_service.supersede_claim(
            session, actor, other_id, authoritative_claim_id,
            note=f"Superseded via conflict {conflict_id}",
        )
    elif resolution == "Restricted" and other_id:
        claims_service.restrict_claim(
            session, actor, other_id, note=f"Restricted via conflict {conflict_id}"
        )
    elif resolution == "Rejected" and other_id:
        claims_service.reject_claim(
            session, actor, other_id, note=f"Rejected via conflict {conflict_id}"
        )

    conflict.status = "Resolved"
    conflict.resolution = resolution
    conflict.authoritative_claim_id = authoritative_claim_id
    conflict.explanation = explanation
    conflict.resolved_by = actor.id
    conflict.resolved_at = utcnow_naive()
    session.add(conflict)
    session.commit()
    session.refresh(conflict)
    record_audit(
        session, actor, "conflict.resolve", target_type="conflict",
        target_id=conflict_id,
        detail={"resolution": resolution, "authoritative_claim_id": authoritative_claim_id},
    )
    return conflict


def dismiss_conflict(
    session: Session, actor: KbUser, conflict_id: int, note: str | None = None
) -> KbConflict:
    require_permission(actor, PERM_RESOLVE_CONFLICTS)
    conflict = session.get(KbConflict, conflict_id)
    if conflict is None:
        raise ConflictNotFoundError(f"Conflict {conflict_id} not found")
    conflict.status = "Dismissed"
    conflict.explanation = note
    conflict.resolved_by = actor.id
    conflict.resolved_at = utcnow_naive()
    session.add(conflict)
    session.commit()
    session.refresh(conflict)
    record_audit(
        session, actor, "conflict.dismiss", target_type="conflict", target_id=conflict_id
    )
    return conflict
