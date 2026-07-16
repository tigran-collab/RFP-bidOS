"""Tests for request-schema validation choices.

Regression guard for the pursuit-prep bug: "Review Requirements" must be an
accepted next_action so saving an opportunity after pursuit prep does not 422.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    NEXT_ACTION_CHOICES,
    OpportunityReviewUpdate,
    SourceConfigRead,
    SourceConfigUpdate,
)


def test_source_read_accepts_all_real_portal_types():
    # Regression: GET /sources 500'd (ResponseValidationError) because
    # "Socrata Open Data" was dropped from the allowed portal_type set when the
    # authenticated-portal types were added. Every portal_type present in the DB
    # must validate through SourceConfigRead.
    for portal_type in (
        None,
        "Socrata Open Data",
        "Generic Public",
        "BidNet",
        "PlanetBids",
        "Other",
    ):
        read = SourceConfigRead(
            id=1,
            name="s",
            source_type="socrata",
            base_url="https://example.gov",
            enabled=True,
            portal_type=portal_type,
            created_at=datetime(2026, 1, 1),
        )
        assert read.portal_type == portal_type


def test_review_requirements_is_a_valid_next_action():
    # Regression: pursuit prep writes this exact value.
    assert "Review Requirements" in NEXT_ACTION_CHOICES
    update = OpportunityReviewUpdate(next_action="Review Requirements")
    assert update.next_action == "Review Requirements"


def test_next_action_none_is_allowed():
    update = OpportunityReviewUpdate(next_action=None)
    assert update.next_action is None


def test_invalid_next_action_rejected():
    with pytest.raises(ValidationError):
        OpportunityReviewUpdate(next_action="Do A Barrel Roll")


def test_invalid_review_status_rejected():
    with pytest.raises(ValidationError):
        OpportunityReviewUpdate(review_status="Maybe Later")


def test_valid_review_status_accepted():
    update = OpportunityReviewUpdate(review_status="Pursue")
    assert update.review_status == "Pursue"


def test_invalid_priority_rejected():
    with pytest.raises(ValidationError):
        OpportunityReviewUpdate(priority="Urgent")


def test_source_config_json_is_exposed_and_validated():
    read = SourceConfigRead(
        id=1,
        name="Portal",
        source_type="authenticated_browser",
        base_url="https://example.gov",
        enabled=True,
        config_json='{"list_url": "https://example.gov/bids"}',
        created_at=datetime(2026, 1, 1),
    )
    assert "list_url" in read.config_json

    update = SourceConfigUpdate(config_json='{"row_selector": "tr"}')
    assert update.config_json == '{"row_selector": "tr"}'

    with pytest.raises(ValidationError):
        SourceConfigUpdate(config_json="not json")

    with pytest.raises(ValidationError):
        SourceConfigUpdate(config_json='["not", "an", "object"]')
