"""Tests for pursuit-workflow next-action decisions.

Regression guard: every value _decide_next_action can return must be a valid
next_action choice, or saving the opportunity afterward 422s.
"""

from app.schemas import NEXT_ACTION_CHOICES
from app.models import Opportunity
from app.services.pursuit_workflow import (
    DEFAULT_STEPS,
    STEP_LOGISTICS,
    STEP_LOGISTICS_QA,
    STEP_PORTAL_DOWNLOAD,
    _decide_next_action,
    _run_step,
)


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


def test_default_steps_include_portal_and_logistics_workflow():
    assert STEP_PORTAL_DOWNLOAD in DEFAULT_STEPS
    assert STEP_LOGISTICS in DEFAULT_STEPS
    assert STEP_LOGISTICS_QA in DEFAULT_STEPS


def test_portal_download_step_skips_without_portal_source(session):
    opportunity = Opportunity(title="Manual Security Guard Services", source="Manual")
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)
    metrics = {
        "documents_discovered": 0,
        "documents_downloaded": 0,
        "documents_parsed": 0,
        "requirements_extracted": 0,
        "ai_evaluated": False,
        "logistics_extracted": False,
        "logistics_qa_ran": False,
    }

    result = _run_step(STEP_PORTAL_DOWNLOAD, opportunity.id, session, metrics)

    assert result["status"] == "skipped"
    assert "No matching portal source" in result["summary"]
