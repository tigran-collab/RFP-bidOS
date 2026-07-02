"""Tests for applying deterministic logistics extraction to an opportunity."""

from datetime import datetime

from app.models import Opportunity
from app.services.logistics_extractor import apply_logistics_to_opportunity


def test_apply_logistics_preserves_existing_values_when_extraction_finds_none(session):
    opportunity = Opportunity(
        title="RFP 26-001",
        submission_method="Electronic (PlanetBids)",
        submission_portal="PlanetBids",
        required_forms_summary="Bid Form, W-9",
        logistics_notes="Verified by hand",
        due_date=datetime(2026, 8, 1),
    )
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)

    result = apply_logistics_to_opportunity(opportunity.id, session)

    assert "error" not in result
    session.refresh(opportunity)
    assert opportunity.submission_method == "Electronic (PlanetBids)"
    assert opportunity.submission_portal == "PlanetBids"
    assert opportunity.required_forms_summary == "Bid Form, W-9"
    assert opportunity.logistics_notes == "Verified by hand"
    assert opportunity.due_date == datetime(2026, 8, 1)


def test_apply_logistics_overwrites_when_extraction_finds_values(session):
    opportunity = Opportunity(
        title="Security Guard Services",
        submission_method="Email",
        submission_portal=None,
        review_notes="Submit electronically via the Bonfire portal. Bid form required.",
    )
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)

    apply_logistics_to_opportunity(opportunity.id, session)

    session.refresh(opportunity)
    assert opportunity.submission_portal == "Bonfire"
    assert opportunity.submission_method == "Electronic (Bonfire)"
    assert opportunity.required_forms_summary == "Bid Form"
