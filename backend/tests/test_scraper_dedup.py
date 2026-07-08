"""Tests for cross-source duplicate detection in the scraper save path.

Solicitation numbers are only unique within one agency's portal, so the
solicitation-number match must be scoped to the same source: two agencies
reusing "RFP-2026-01" are two distinct opportunities.
"""

import json
from types import SimpleNamespace

from sqlmodel import select

from app.models import Opportunity
from app.services.scraper import (
    _create_opportunity,
    _find_existing_opportunity,
    _update_opportunity_if_safe,
)
from app.services.scrapers.base import ScraperResult


def _source(name: str):
    return SimpleNamespace(name=name, base_url=f"https://{name.lower()}.example.gov/bids")


def test_same_solicitation_number_across_sources_creates_two_opportunities(session):
    source_a = _source("City-A")
    candidate_a = ScraperResult(
        title="Unarmed Security Guard Services",
        solicitation_number="RFP-2026-01",
    )
    assert _find_existing_opportunity(session, candidate_a, source_a) is None
    session.add(_create_opportunity(candidate_a, source_a))
    session.commit()

    source_b = _source("City-B")
    candidate_b = ScraperResult(
        title="Armed Security Patrol Services",
        solicitation_number="RFP-2026-01",
    )
    # Same solicitation number but a different source: not a duplicate.
    assert _find_existing_opportunity(session, candidate_b, source_b) is None
    session.add(_create_opportunity(candidate_b, source_b))
    session.commit()

    rows = session.exec(select(Opportunity)).all()
    assert len(rows) == 2
    assert {row.source for row in rows} == {"City-A", "City-B"}
    assert all(row.solicitation_number == "RFP-2026-01" for row in rows)


def test_same_solicitation_number_within_one_source_is_a_duplicate(session):
    source = _source("City-A")
    candidate = ScraperResult(
        title="Unarmed Security Guard Services",
        solicitation_number="RFP-2026-01",
    )
    session.add(_create_opportunity(candidate, source))
    session.commit()

    rescraped = ScraperResult(
        title="Unarmed Security Guard Services (Amended)",
        solicitation_number="RFP-2026-01",
    )
    existing = _find_existing_opportunity(session, rescraped, source)
    assert existing is not None
    assert existing.source == "City-A"


# --- workflow#1: anchor-less rows must not collapse into one opportunity ---


def _anchorless(source, title: str) -> ScraperResult:
    """A table row with no detail link: source_url falls back to the base URL."""
    base = source.base_url
    return ScraperResult(title=title, source_url=base, detail_url=None, portal_url=base)


def test_anchorless_rows_do_not_collapse(session):
    source = _source("City-A")
    titles = [
        "Unarmed Guard Services - North",
        "Unarmed Guard Services - South",
        "Mobile Patrol Services",
    ]
    for title in titles:
        candidate = _anchorless(source, title)
        # No genuinely row-distinct URL, no solicitation number, distinct title.
        assert _find_existing_opportunity(session, candidate, source) is None
        session.add(_create_opportunity(candidate, source))
        session.commit()

    rows = session.exec(select(Opportunity)).all()
    assert len(rows) == 3
    assert {row.title for row in rows} == set(titles)


def test_anchorless_row_rescrape_is_still_deduped(session):
    source = _source("City-A")
    candidate = _anchorless(source, "Unarmed Guard Services - North")
    session.add(_create_opportunity(candidate, source))
    session.commit()

    # Re-scraping the SAME anchor-less row (same title, same source) is a dup.
    again = _anchorless(source, "Unarmed Guard Services - North")
    existing = _find_existing_opportunity(session, again, source)
    assert existing is not None
    assert session.exec(select(Opportunity)).all().__len__() == 1


# --- workflow#10: candidate.description must be persisted ---


def test_description_persisted_on_create(session):
    source = _source("City-A")
    candidate = ScraperResult(
        title="Guard Services",
        solicitation_number="RFP-1",
        description="Detailed 600-char scope of work from the detail page.",
    )
    opportunity = _create_opportunity(candidate, source)
    assert opportunity.description == "Detailed 600-char scope of work from the detail page."


def test_description_filled_on_update_when_empty(session):
    source = _source("City-A")
    opportunity = _create_opportunity(
        ScraperResult(title="Guard Services", solicitation_number="RFP-1"), source
    )
    session.add(opportunity)
    session.commit()
    assert opportunity.description is None

    enriched = ScraperResult(
        title="Guard Services",
        solicitation_number="RFP-1",
        description="Now enriched from the detail page.",
    )
    updated = _update_opportunity_if_safe(opportunity, enriched, source)
    assert updated is True
    assert opportunity.description == "Now enriched from the detail page."


# --- workflow#7: re-scrape must not overwrite a reviewed row's relevance ---


def test_reviewed_opportunity_keeps_relevance_on_rescrape(session):
    source = _source("City-A")
    opportunity = _create_opportunity(
        ScraperResult(
            title="Guard Services",
            solicitation_number="RFP-1",
            relevance_score=80,
            relevance_decision="Relevant",
        ),
        source,
    )
    # Operator triaged it.
    opportunity.review_status = "Pursue"
    session.add(opportunity)
    session.commit()

    rescrape = ScraperResult(
        title="Guard Services",
        solicitation_number="RFP-1",
        relevance_score=5,
        relevance_decision="Not Relevant",
    )
    _update_opportunity_if_safe(opportunity, rescrape, source)
    assert opportunity.relevance_score == 80
    assert opportunity.relevance_decision == "Relevant"


def test_new_opportunity_refreshes_relevance_on_rescrape(session):
    source = _source("City-A")
    opportunity = _create_opportunity(
        ScraperResult(
            title="Guard Services",
            solicitation_number="RFP-1",
            relevance_score=50,
            relevance_decision="Relevant",
        ),
        source,
    )
    session.add(opportunity)
    session.commit()
    assert opportunity.review_status == "New"

    rescrape = ScraperResult(
        title="Guard Services",
        solicitation_number="RFP-1",
        relevance_score=92,
        relevance_decision="Relevant",
    )
    _update_opportunity_if_safe(opportunity, rescrape, source)
    assert opportunity.relevance_score == 92


# --- workflow#7b: a portal-name fallback agency should yield to enrichment ---


def test_portal_fallback_agency_replaced_by_enrichment(session):
    source = _source("City-A")
    # No agency on the row -> _create stores the source-name fallback.
    opportunity = _create_opportunity(
        ScraperResult(title="Guard Services", solicitation_number="RFP-1"), source
    )
    assert opportunity.agency == "City-A"
    session.add(opportunity)
    session.commit()

    enriched = ScraperResult(
        title="Guard Services",
        solicitation_number="RFP-1",
        agency="City of Carson",
    )
    updated = _update_opportunity_if_safe(opportunity, enriched, source)
    assert updated is True
    assert opportunity.agency == "City of Carson"


def test_real_agency_not_overwritten_on_update(session):
    source = _source("City-A")
    opportunity = _create_opportunity(
        ScraperResult(
            title="Guard Services", solicitation_number="RFP-1", agency="City of Carson"
        ),
        source,
    )
    assert opportunity.agency == "City of Carson"
    session.add(opportunity)
    session.commit()

    rescrape = ScraperResult(
        title="Guard Services", solicitation_number="RFP-1", agency="Wrong Name"
    )
    _update_opportunity_if_safe(opportunity, rescrape, source)
    # Stored agency is a real value, not the fallback -> left untouched.
    assert opportunity.agency == "City of Carson"


def test_config_agency_fallback_replaced_by_enrichment(session):
    source = SimpleNamespace(
        name="Regional Portal",
        base_url="https://portal.example.gov/bids",
        config_json=json.dumps({"agency": "Configured Fallback Agency"}),
    )
    opportunity = Opportunity(
        title="Guard Services",
        source="Regional Portal",
        solicitation_number="RFP-1",
        agency="Configured Fallback Agency",
    )
    session.add(opportunity)
    session.commit()

    enriched = ScraperResult(
        title="Guard Services",
        solicitation_number="RFP-1",
        agency="City of Carson",
    )
    _update_opportunity_if_safe(opportunity, enriched, source)
    assert opportunity.agency == "City of Carson"
