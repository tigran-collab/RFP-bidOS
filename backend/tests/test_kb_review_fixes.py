"""Regression tests for the adversarially-confirmed review findings.

Each test pins a specific bug that was found and fixed:
governance stamping on create-as-approved, full version restore, restricted-claim
edit gating, conflict authoritative-claim validation, dangling-conflict purge on
reprocess, and the restricted-source warning firing without an expiration date.
"""

import pytest
from sqlmodel import select

from app.kb_models import Claim, KbApproval, KbConflict
from app.kb_vocab import CLAIM_STATUS_APPROVED
from app.services.kb import answers, claims, conflicts, documents, drafting, processing
from app.services.kb.conflicts import ConflictResolutionError
from app.services.kb.permissions import KbPermissionError
from tests.kb_factories import make_admin, make_entity, make_writer


# Finding 8 — create_claim as Approved stamps approver + audit.
def test_create_claim_approved_stamps_approver(session):
    admin = make_admin(session)
    claim = claims.create_claim(
        session, admin, {"title": "T", "canonical_text": "x", "status": "Approved"}
    )
    assert claim.status == CLAIM_STATUS_APPROVED
    assert claim.approved_by == admin.id
    assert claim.approved_at is not None
    approvals = session.exec(
        select(KbApproval).where(
            KbApproval.target_type == "claim", KbApproval.target_id == claim.id
        )
    ).all()
    assert any(a.action == "approved" for a in approvals)


# Finding 9 — create_answer as Approved stamps approver + audit.
def test_create_answer_approved_stamps_approver(session):
    admin = make_admin(session)
    ans = answers.create_answer(
        session, admin, {"question_title": "Q", "standard_answer": "A", "status": "Approved"}
    )
    assert ans.approved_by == admin.id
    approvals = session.exec(
        select(KbApproval).where(
            KbApproval.target_type == "answer", KbApproval.target_id == ans.id
        )
    ).all()
    assert any(a.action == "approved" for a in approvals)


# Finding 10 — restore_claim_version reverts ALL fields, not a subset.
def test_restore_version_restores_all_fields(session):
    admin = make_admin(session)
    claim = claims.create_claim(
        session, admin,
        {"title": "T", "canonical_text": "orig", "source_page": 5, "confidence": "High",
         "source_section": "3.2", "supporting_excerpt": "verbatim"},
    )
    claims.update_claim(
        session, admin, claim.id,
        {"canonical_text": "changed", "source_page": 99, "confidence": "Low",
         "source_section": "9.9", "supporting_excerpt": "other"},
    )
    versions = claims.get_claim_detail(session, claim.id, admin)["versions"]
    first = min(versions, key=lambda v: v["version"])
    restored = claims.restore_claim_version(session, admin, claim.id, first["id"])
    assert restored.canonical_text == "orig"
    assert restored.source_page == 5
    assert restored.confidence == "High"
    assert restored.source_section == "3.2"
    assert restored.supporting_excerpt == "verbatim"


# Finding 6 — a writer without view_restricted cannot edit/read a Restricted claim.
def test_restricted_claim_edit_blocked_for_writer(session):
    admin = make_admin(session)
    writer = make_writer(session)
    claim = claims.create_claim(session, admin, {"title": "Secret", "canonical_text": "x"})
    claims.restrict_claim(session, admin, claim.id, "confidential")
    with pytest.raises(KbPermissionError):
        claims.update_claim(session, writer, claim.id, {"canonical_text": "y"})


# Finding 2 — resolve_conflict rejects an authoritative claim outside the pair.
def test_resolve_conflict_rejects_foreign_authoritative(session):
    admin = make_admin(session)
    entity = make_entity(session)
    a = claims.approve_claim(session, admin, claims.create_claim(
        session, admin, {"title": "A", "canonical_text": "We employ 450 officers.", "company_entity_id": entity.id}).id)
    b = claims.approve_claim(session, admin, claims.create_claim(
        session, admin, {"title": "B", "canonical_text": "We employ 600 officers.", "company_entity_id": entity.id}).id)
    foreign = claims.create_claim(session, admin, {"title": "F", "canonical_text": "unrelated"})
    conflicts.detect_conflicts(session, company_entity_id=entity.id)
    conflict = conflicts.list_conflicts(session)[0]
    with pytest.raises(ConflictResolutionError):
        conflicts.resolve_conflict(
            session, admin, conflict.id, resolution="Superseded", authoritative_claim_id=foreign.id
        )
    # The participant claims are untouched.
    assert session.get(Claim, a.id).status == CLAIM_STATUS_APPROVED
    assert session.get(Claim, b.id).status == CLAIM_STATUS_APPROVED


# Finding 3 — reprocessing purges conflicts referencing deleted candidate claims.
def test_reprocess_purges_dangling_conflicts(session):
    admin = make_admin(session)
    entity = make_entity(session)
    text = "The team includes 450 officers on day shift. The roster lists 600 officers overall."
    doc = documents.create_document(
        session, admin, filename="staffing.txt", content=text.encode("utf-8"),
        metadata={"company_entity_id": entity.id},
    )
    processing.process_document(session, doc.id)
    first_count = len(conflicts.list_conflicts(session))
    assert first_count >= 1
    # Bump the id counter so deleted candidate rowids are not reused (which would
    # mask the duplicate-accumulation bug the purge fix prevents).
    claims.create_claim(session, admin, {"title": "spacer", "canonical_text": "z"})
    processing.process_document(session, doc.id)
    remaining = conflicts.list_conflicts(session)
    # No accumulation, and no dangling references to deleted claims.
    assert len(remaining) == first_count
    for c in remaining:
        assert session.get(Claim, c.claim_a_id) is not None
        assert session.get(Claim, c.claim_b_id) is not None


# Finding 1 — restricted_source warning fires even when the claim has no expiration.
def test_restricted_source_warning_without_expiration(session, monkeypatch):
    admin = make_admin(session)
    claim = claims.create_claim(
        session, admin,
        {"title": "Restricted fact", "canonical_text": "We serve armed guard contracts.",
         "restrictions": "Client name confidential; do not disclose."},
    )
    claims.approve_claim(session, admin, claim.id)
    monkeypatch.setattr(drafting, "generate_text", lambda prompt, **kw: "We serve armed guard contracts [1].")
    result = drafting.generate_response(session, admin, {"question": "Describe armed guard contracts."})
    assert any(w["type"] == "restricted_source" for w in result["warnings"])
