"""Claims Registry: creation, approval workflow, versioning, expiration."""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.kb_models import Claim, KbApproval, KbClaimVersion
from app.kb_vocab import (
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_EXPIRED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_REJECTED,
    CLAIM_STATUS_SUPERSEDED,
)
from app.models import utcnow_naive
from app.services.kb import claims
from app.services.kb.permissions import KbPermissionError
from tests.kb_factories import make_admin, make_entity, make_reader, make_writer


def test_create_claim_defaults_to_draft(session):
    writer = make_writer(session)
    claim = claims.create_claim(session, writer, {"title": "T", "canonical_text": "x"})
    assert claim.status == "Draft"
    assert claim.version == 1


def test_writer_cannot_self_approve_on_create(session):
    writer = make_writer(session)
    claim = claims.create_claim(
        session, writer, {"title": "T", "canonical_text": "x", "status": "Approved"}
    )
    # Downgraded because the writer lacks approve permission.
    assert claim.status == CLAIM_STATUS_PENDING


def test_read_only_cannot_create_claim(session):
    reader = make_reader(session)
    with pytest.raises(KbPermissionError):
        claims.create_claim(session, reader, {"title": "T", "canonical_text": "x"})


def test_approve_claim_stamps_and_versions(session):
    admin = make_admin(session)
    claim = claims.create_claim(session, admin, {"title": "T", "canonical_text": "x"})
    approved = claims.approve_claim(session, admin, claim.id, "verified")
    assert approved.status == CLAIM_STATUS_APPROVED
    assert approved.approved_by == admin.id
    assert approved.approved_at is not None
    approvals = session.exec(
        select(KbApproval).where(KbApproval.target_id == claim.id)
    ).all()
    assert any(a.action == "approved" for a in approvals)


def test_reject_claim(session):
    admin = make_admin(session)
    claim = claims.create_claim(session, admin, {"title": "T", "canonical_text": "x"})
    rejected = claims.reject_claim(session, admin, claim.id, "not accurate")
    assert rejected.status == CLAIM_STATUS_REJECTED


def test_update_records_version(session):
    admin = make_admin(session)
    claim = claims.create_claim(session, admin, {"title": "T", "canonical_text": "x"})
    claims.update_claim(session, admin, claim.id, {"canonical_text": "updated"}, "edit")
    versions = session.exec(
        select(KbClaimVersion).where(KbClaimVersion.claim_id == claim.id)
    ).all()
    assert len(versions) >= 2  # created + updated
    refreshed = session.get(Claim, claim.id)
    assert refreshed.canonical_text == "updated"
    assert refreshed.version >= 2


def test_supersede_claim(session):
    admin = make_admin(session)
    old = claims.create_claim(session, admin, {"title": "Old", "canonical_text": "x"})
    new = claims.create_claim(session, admin, {"title": "New", "canonical_text": "y"})
    superseded = claims.supersede_claim(session, admin, old.id, new.id, "replaced")
    assert superseded.status == CLAIM_STATUS_SUPERSEDED
    assert superseded.superseded_by_id == new.id


def test_expire_due_claims(session):
    admin = make_admin(session)
    claim = claims.create_claim(
        session,
        admin,
        {
            "title": "License",
            "canonical_text": "PPO 12345",
            "expiration_date": (utcnow_naive() - timedelta(days=1)).isoformat(),
        },
    )
    claims.approve_claim(session, admin, claim.id)
    count = claims.expire_due_claims(session)
    assert count == 1
    assert session.get(Claim, claim.id).status == CLAIM_STATUS_EXPIRED


def test_restore_version(session):
    admin = make_admin(session)
    claim = claims.create_claim(session, admin, {"title": "T", "canonical_text": "original"})
    claims.update_claim(session, admin, claim.id, {"canonical_text": "changed"})
    versions = session.exec(
        select(KbClaimVersion).where(KbClaimVersion.claim_id == claim.id)
    ).all()
    first = min(versions, key=lambda v: v.version)
    restored = claims.restore_claim_version(session, admin, claim.id, first.id)
    assert restored.canonical_text == "original"
