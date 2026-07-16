"""Company Knowledge Base dashboard: read-only aggregation across documents,
claims, answers, conflicts, and generated responses. Supports filtering by
entity, state, service type, industry, category, approval/expiration status,
and document type."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlmodel import Session, desc, select

from app.kb_models import (
    Claim,
    GeneratedResponse,
    KbConflict,
    KbDocument,
    ReusableAnswer,
)
from app.kb_vocab import (
    ANSWER_STATUS_APPROVED,
    CLAIM_CATEGORIES,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_EXPIRED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_RESTRICTED,
    DOC_STATUS_FAILED,
    DOC_STATUS_NEEDS_REVIEW,
)
from app.models import utcnow_naive
from app.services.kb.serializers import (
    conflict_to_dict,
    document_to_dict,
    response_to_dict,
)

EXPIRING_SOON_DAYS = 30


def _loads(raw: str | None) -> list:
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return v if isinstance(v, list) else []


def _claim_matches(c: Claim, f: dict) -> bool:
    if f.get("company_entity_id") is not None and c.company_entity_id != f["company_entity_id"]:
        return False
    if f.get("category") and c.category != f["category"]:
        return False
    if f.get("approval_status") and c.status != f["approval_status"]:
        return False
    if f.get("service_type"):
        scope = _loads(c.service_scope_json)
        if scope and f["service_type"] not in scope:
            return False
    if f.get("industry"):
        scope = _loads(c.industry_scope_json)
        if scope and f["industry"] not in scope:
            return False
    if f.get("state"):
        states = [str(s).upper() for s in _loads(c.applicable_states_json)]
        if states and f["state"].upper() not in states:
            return False
    return True


def _doc_matches(d: KbDocument, f: dict) -> bool:
    if f.get("company_entity_id") is not None and d.company_entity_id != f["company_entity_id"]:
        return False
    if f.get("category") and d.category != f["category"]:
        return False
    if f.get("service_type") and d.service_type != f["service_type"]:
        return False
    if f.get("industry") and d.applicable_industry != f["industry"]:
        return False
    if f.get("state") and d.applicable_state != f["state"]:
        return False
    if f.get("document_type") and d.doc_type != f["document_type"]:
        return False
    return True


def get_kb_dashboard(session: Session, filters: dict | None = None) -> dict:
    filters = filters or {}
    now = utcnow_naive()
    soon = now + timedelta(days=EXPIRING_SOON_DAYS)

    documents = [d for d in session.exec(select(KbDocument)).all() if _doc_matches(d, filters)]
    claims = [c for c in session.exec(select(Claim)).all() if _claim_matches(c, filters)]
    answers = list(session.exec(select(ReusableAnswer)).all())
    if filters.get("company_entity_id") is not None:
        answers = [a for a in answers if a.company_entity_id == filters["company_entity_id"]]
    conflicts = list(
        session.exec(select(KbConflict).where(KbConflict.status == "Open")).all()
    )

    def expired(exp: datetime | None) -> bool:
        return exp is not None and exp < now

    def expiring_soon(exp: datetime | None) -> bool:
        return exp is not None and now <= exp <= soon

    claim_expired = sum(
        1 for c in claims if c.status == CLAIM_STATUS_EXPIRED or expired(c.expiration_date)
    )
    doc_expired = sum(1 for d in documents if expired(d.expiration_date))
    claim_soon = sum(1 for c in claims if expiring_soon(c.expiration_date))
    doc_soon = sum(1 for d in documents if expiring_soon(d.expiration_date))

    counts = {
        "source_documents": len([d for d in documents if not d.archived]),
        "approved_claims": sum(1 for c in claims if c.status == CLAIM_STATUS_APPROVED),
        "pending_review": (
            sum(1 for c in claims if c.status == CLAIM_STATUS_PENDING)
            + sum(1 for d in documents if d.processing_status == DOC_STATUS_NEEDS_REVIEW)
        ),
        "restricted_claims": sum(1 for c in claims if c.status == CLAIM_STATUS_RESTRICTED),
        "expired_items": claim_expired + doc_expired,
        "expiring_soon": claim_soon + doc_soon,
        "conflicting_claims": len(conflicts),
        "approved_answers": sum(1 for a in answers if a.status == ANSWER_STATUS_APPROVED),
        "documents_failed": sum(
            1 for d in documents if d.processing_status == DOC_STATUS_FAILED
        ),
        "total_claims": len(claims),
        "total_answers": len(answers),
    }

    # Coverage by category (approved claims per category).
    coverage = {cat: 0 for cat in CLAIM_CATEGORIES}
    for c in claims:
        if c.status == CLAIM_STATUS_APPROVED and c.category in coverage:
            coverage[c.category] += 1
    coverage_list = [
        {"category": cat, "approved_claims": n} for cat, n in coverage.items()
    ]

    recent_responses = list(
        session.exec(
            select(GeneratedResponse).order_by(desc(GeneratedResponse.id)).limit(10)
        ).all()
    )
    failed_documents = [d for d in documents if d.processing_status == DOC_STATUS_FAILED]
    expiring_items = _expiring_items(claims, documents, now, soon)

    return {
        "counts": counts,
        "coverage_by_category": coverage_list,
        "recent_responses": [response_to_dict(r) for r in recent_responses],
        "failed_documents": [document_to_dict(d, include_flags=False) for d in failed_documents],
        "open_conflicts": [conflict_to_dict(c) for c in conflicts[:15]],
        "expiring_items": expiring_items,
    }


def _expiring_items(
    claims: list[Claim], documents: list[KbDocument], now: datetime, soon: datetime
) -> list[dict]:
    items = []
    for c in claims:
        if c.expiration_date and c.expiration_date <= soon:
            items.append(
                {
                    "kind": "claim",
                    "id": c.id,
                    "title": c.title,
                    "expiration_date": c.expiration_date.isoformat(),
                    "expired": c.expiration_date < now,
                    "category": c.category,
                }
            )
    for d in documents:
        if d.expiration_date and d.expiration_date <= soon:
            items.append(
                {
                    "kind": "document",
                    "id": d.id,
                    "title": d.title,
                    "expiration_date": d.expiration_date.isoformat(),
                    "expired": d.expiration_date < now,
                    "category": d.category,
                }
            )
    items.sort(key=lambda x: x["expiration_date"])
    return items
