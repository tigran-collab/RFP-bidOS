"""Tests for cross-source duplicate detection in the scraper save path.

Solicitation numbers are only unique within one agency's portal, so the
solicitation-number match must be scoped to the same source: two agencies
reusing "RFP-2026-01" are two distinct opportunities.
"""

from types import SimpleNamespace

from sqlmodel import select

from app.models import Opportunity
from app.services.scraper import _create_opportunity, _find_existing_opportunity
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
