"""Hybrid retrieval: BM25 ranking, entity/state/scope filtering, usable-only
(approved + non-expired) enforcement, restricted exclusion."""

from datetime import timedelta

from app.models import utcnow_naive
from app.services.kb import claims
from app.services.kb.retrieval import (
    RetrievalFilters,
    retrieve_for_drafting,
    search_claims,
)
from tests.kb_factories import make_admin, make_entity


def _approved(session, admin, **kwargs):
    claim = claims.create_claim(session, admin, kwargs)
    return claims.approve_claim(session, admin, claim.id)


def test_bm25_ranks_relevant_claim_first(session):
    admin = make_admin(session)
    _approved(session, admin, title="Fire watch", canonical_text="We provide fire watch services with trained fire watch personnel.")
    _approved(session, admin, title="Recruiting", canonical_text="Our recruiting process screens candidates.")
    results = search_claims(session, "fire watch personnel", usable_only=True)
    assert results
    assert results[0].title == "Fire watch"


def test_usable_only_excludes_unapproved_and_expired(session):
    admin = make_admin(session)
    # Draft (not approved)
    claims.create_claim(session, admin, {"title": "Draft", "canonical_text": "armed guard draft"})
    # Approved but expired
    expired = claims.create_claim(
        session, admin,
        {"title": "Expired", "canonical_text": "armed guard expired",
         "expiration_date": (utcnow_naive() - timedelta(days=1)).isoformat()},
    )
    claims.approve_claim(session, admin, expired.id)
    # Approved and valid
    _approved(session, admin, title="Valid", canonical_text="armed guard valid current")

    results = search_claims(session, "armed guard", usable_only=True)
    titles = {r.title for r in results}
    assert "Valid" in titles
    assert "Draft" not in titles
    assert "Expired" not in titles


def test_state_scope_filtering(session):
    admin = make_admin(session)
    _approved(session, admin, title="CA only", canonical_text="armed guard california",
              applicable_states=["CA"])
    _approved(session, admin, title="Nationwide", canonical_text="armed guard anywhere")

    ca = {r.title for r in search_claims(session, "armed guard", filters=RetrievalFilters(state="CA"), usable_only=True)}
    tx = {r.title for r in search_claims(session, "armed guard", filters=RetrievalFilters(state="TX"), usable_only=True)}
    assert "CA only" in ca and "Nationwide" in ca
    assert "CA only" not in tx  # state-specific claim excluded outside its state
    assert "Nationwide" in tx  # scope-less claim applies everywhere


def test_entity_isolation(session):
    admin = make_admin(session)
    e1 = make_entity(session, "Entity One")
    e2 = make_entity(session, "Entity Two")
    _approved(session, admin, title="E1 claim", canonical_text="armed guard one", company_entity_id=e1.id)
    _approved(session, admin, title="E2 claim", canonical_text="armed guard two", company_entity_id=e2.id)
    _approved(session, admin, title="Agnostic", canonical_text="armed guard agnostic")

    titles = {r.title for r in search_claims(session, "armed guard", filters=RetrievalFilters(company_entity_id=e1.id), usable_only=True)}
    assert "E1 claim" in titles
    assert "Agnostic" in titles  # entity-agnostic allowed
    assert "E2 claim" not in titles  # never mix a different legal entity


def test_retrieve_for_drafting_returns_approved(session):
    admin = make_admin(session)
    _approved(session, admin, title="Training", canonical_text="We deliver 40 hours of guard training annually.")
    result = retrieve_for_drafting(session, "describe your training program")
    assert result["claims"]
    assert result["claims"][0].title == "Training"
