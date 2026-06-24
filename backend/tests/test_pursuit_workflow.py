"""Tests for pursuit-workflow next-action decisions.

Regression guard: every value _decide_next_action can return must be a valid
next_action choice, or saving the opportunity afterward 422s.
"""

from app.schemas import NEXT_ACTION_CHOICES
from app.services.pursuit_workflow import _decide_next_action


def test_no_documents_returns_verify_portal():
    assert _decide_next_action({"requirements_extracted": 0}, 0, 0) == "Verify Portal"


def test_requirements_extracted_returns_review_requirements():
    assert _decide_next_action({"requirements_extracted": 5}, 2, 0) == "Review Requirements"


def test_documents_but_no_requirements_returns_manual_review():
    assert _decide_next_action({"requirements_extracted": 0}, 1, 0) == "Manual Review"


def test_all_decisions_are_valid_choices():
    cases = [
        ({"requirements_extracted": 0}, 0, 0),
        ({"requirements_extracted": 0}, 1, 0),
        ({"requirements_extracted": 3}, 1, 0),
        ({"requirements_extracted": 10}, 0, 2),
    ]
    for metrics, downloaded, pending in cases:
        decision = _decide_next_action(metrics, downloaded, pending)
        assert decision in NEXT_ACTION_CHOICES, f"invalid next_action: {decision!r}"
