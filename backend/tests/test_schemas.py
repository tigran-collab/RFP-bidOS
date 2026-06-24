"""Tests for request-schema validation choices.

Regression guard for the pursuit-prep bug: "Review Requirements" must be an
accepted next_action so saving an opportunity after pursuit prep does not 422.
"""

import pytest
from pydantic import ValidationError

from app.schemas import (
    NEXT_ACTION_CHOICES,
    OpportunityReviewUpdate,
)


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
