"""KB dashboard aggregation, hybrid search, audit logging, and seed idempotency."""

from app.services.kb import (
    answers,
    audit,
    claims,
    dashboard,
    search,
)
from app.services.kb.retrieval import RetrievalFilters
from app.services.kb.seed import seed_kb
from tests.kb_factories import make_admin, make_entity


def _approve_claim(session, admin, **kwargs):
    claim = claims.create_claim(session, admin, kwargs)
    return claims.approve_claim(session, admin, claim.id)


def test_dashboard_counts(session):
    admin = make_admin(session)
    entity = make_entity(session)
    _approve_claim(session, admin, title="A", canonical_text="armed guard", category="Armed Security",
                   company_entity_id=entity.id)
    claims.create_claim(session, admin, {"title": "Pending", "canonical_text": "x",
                                         "status": "Pending Review", "company_entity_id": entity.id})
    data = dashboard.get_kb_dashboard(session)
    assert data["counts"]["approved_claims"] == 1
    assert data["counts"]["pending_review"] >= 1
    # Coverage lists every category with a count.
    armed = next(c for c in data["coverage_by_category"] if c["category"] == "Armed Security")
    assert armed["approved_claims"] == 1


def test_search_all_finds_claims_and_answers(session):
    admin = make_admin(session)
    _approve_claim(session, admin, title="Training", canonical_text="We deliver guard training annually.")
    ans = answers.create_answer(session, admin, {"question_title": "Training", "standard_answer": "guard training program"})
    answers.approve_answer(session, admin, ans.id)
    results = search.search_all(session, "guard training")
    assert results["claims"]
    assert results["answers"]


def test_search_exact_phrase(session):
    admin = make_admin(session)
    _approve_claim(session, admin, title="Phrase", canonical_text="We provide fire watch coverage.")
    hit = search.search_all(session, "fire watch coverage", exact_phrase=True, kinds=("claim",))
    miss = search.search_all(session, "coverage watch fire", exact_phrase=True, kinds=("claim",))
    assert hit["claims"]
    assert not miss["claims"]


def test_audit_records_claim_actions(session):
    admin = make_admin(session)
    claim = claims.create_claim(session, admin, {"title": "T", "canonical_text": "x"})
    claims.approve_claim(session, admin, claim.id)
    rows = audit.list_audit(session, target_type="claim", target_id=claim.id)
    actions = {r.action for r in rows}
    assert "claim.create" in actions
    assert "claim.approved" in actions


def test_seed_is_idempotent(session):
    first = seed_kb(session)
    assert first["users_created"] == 5
    assert first["questions_created"] == 13
    second = seed_kb(session)
    assert second["users_created"] == 0
    assert second["questions_created"] == 0
