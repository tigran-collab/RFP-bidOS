"""Conflict detection + resolution across claims within a legal entity."""

from app.kb_models import Claim
from app.kb_vocab import CLAIM_STATUS_SUPERSEDED
from app.services.kb import claims, conflicts
from tests.kb_factories import make_admin, make_entity


def _approve(session, admin, entity, text, title="C"):
    claim = claims.create_claim(
        session, admin, {"title": title, "canonical_text": text, "company_entity_id": entity.id}
    )
    return claims.approve_claim(session, admin, claim.id)


def test_detects_conflicting_employee_counts(session):
    admin = make_admin(session)
    entity = make_entity(session)
    _approve(session, admin, entity, "We employ 450 officers.", "A")
    _approve(session, admin, entity, "We employ 600 officers.", "B")
    detected = conflicts.detect_conflicts(session, company_entity_id=entity.id)
    assert detected == 1
    assert len(conflicts.list_conflicts(session)) == 1


def test_no_conflict_for_matching_values(session):
    admin = make_admin(session)
    entity = make_entity(session)
    _approve(session, admin, entity, "We employ 450 officers.", "A")
    _approve(session, admin, entity, "Our team of 450 officers is trained.", "B")
    assert conflicts.detect_conflicts(session, company_entity_id=entity.id) == 0


def test_detection_is_idempotent(session):
    admin = make_admin(session)
    entity = make_entity(session)
    _approve(session, admin, entity, "We employ 450 officers.", "A")
    _approve(session, admin, entity, "We employ 600 officers.", "B")
    conflicts.detect_conflicts(session, company_entity_id=entity.id)
    # A second run must not duplicate the same pair/field conflict.
    conflicts.detect_conflicts(session, company_entity_id=entity.id)
    assert len(conflicts.list_conflicts(session)) == 1


def test_entities_are_isolated(session):
    admin = make_admin(session)
    e1 = make_entity(session, "One")
    e2 = make_entity(session, "Two")
    _approve(session, admin, e1, "We employ 450 officers.", "A")
    _approve(session, admin, e2, "We employ 600 officers.", "B")
    # Different legal entities are never compared against each other.
    assert conflicts.detect_conflicts(session) == 0


def test_resolve_supersedes_non_authoritative(session):
    admin = make_admin(session)
    entity = make_entity(session)
    a = _approve(session, admin, entity, "We employ 450 officers.", "A")
    b = _approve(session, admin, entity, "We employ 600 officers.", "B")
    conflicts.detect_conflicts(session, company_entity_id=entity.id)
    conflict = conflicts.list_conflicts(session)[0]
    resolved = conflicts.resolve_conflict(
        session, admin, conflict.id, resolution="Superseded", authoritative_claim_id=b.id
    )
    assert resolved.status == "Resolved"
    assert session.get(Claim, a.id).status == CLAIM_STATUS_SUPERSEDED
