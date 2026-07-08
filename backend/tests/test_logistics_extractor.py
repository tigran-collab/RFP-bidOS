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


def test_apply_logistics_preserves_operator_due_date(session):
    # An operator-corrected due date must survive extract-logistics even when
    # the document text yields a different (regex-extracted) date.
    opportunity = Opportunity(
        title="Security Guard Services RFP",
        due_date=datetime(2026, 9, 1),
        review_notes="Proposals due: 08/15/2026 at 2:00 PM",
    )
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)

    apply_logistics_to_opportunity(opportunity.id, session)

    session.refresh(opportunity)
    assert opportunity.due_date == datetime(2026, 9, 1)


def test_apply_logistics_fills_empty_due_date(session):
    # With no stored due date, the extracted one fills the empty field.
    opportunity = Opportunity(
        title="Security Guard Services RFP",
        review_notes="Proposals due: 08/15/2026 at 2:00 PM",
    )
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)

    apply_logistics_to_opportunity(opportunity.id, session)

    session.refresh(opportunity)
    assert opportunity.due_date is not None
    assert opportunity.due_date.month == 8 and opportunity.due_date.day == 15
