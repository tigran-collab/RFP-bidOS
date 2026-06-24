"""Tests for the rules-based bid/no-bid scorer.

The scorer reads attributes off an opportunity-like object via getattr, so a
SimpleNamespace stands in for a real Opportunity row.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.scorer import (
    apply_scored_review_status,
    score_opportunity_text,
)


def make_opp(**overrides):
    base = dict(
        title="",
        agency=None,
        source=None,
        source_url=None,
        location=None,
        service_type=None,
        contract_type=None,
        status=None,
        description=None,
        notes=None,
        relevance_decision=None,
        relevance_reason=None,
        relevance_score=None,
        keyword_matches_json=None,
        negative_matches_json=None,
        due_date=None,
        pre_bid_date=None,
        pre_bid_mandatory=False,
        as_needed_warning=False,
        estimated_value=None,
        review_status="New",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_strong_security_opportunity_scores_bid():
    opp = make_opp(
        title="Unarmed Security Guard Services for County Facilities",
        agency="Santa Clara County",
        location="San Jose, CA",
        description="BSIS licensed guard card required. Mobile patrol of multiple sites.",
        due_date=datetime.utcnow() + timedelta(days=45),
    )
    result = score_opportunity_text(opp)
    assert result["decision"] == "Bid"
    assert result["score"] >= 70
    assert "Security services match" in result["positive_factors"]


def test_non_security_opportunity_is_no_bid():
    opp = make_opp(
        title="Janitorial and Landscaping Services",
        description="Routine cleaning and grounds maintenance.",
    )
    result = score_opportunity_text(opp)
    assert result["decision"] == "No Bid"
    assert "Non-security opportunity" in result["negative_factors"]


def test_security_without_license_terms_flags_verification():
    opp = make_opp(
        title="Security Guard Services",
        location="Dallas, TX",
        description="Provide security officers for a public building.",
        due_date=datetime.utcnow() + timedelta(days=30),
    )
    result = score_opportunity_text(opp)
    assert any("BSIS" in v or "Guard Card" in v for v in result["verification_needed"])


def test_missing_due_date_penalized_and_flagged():
    opp = make_opp(
        title="Security Guard Services",
        location="Phoenix, AZ",
        description="Guard card and BSIS license required.",
        due_date=None,
    )
    result = score_opportunity_text(opp)
    assert "Due date missing" in result["negative_factors"]
    assert "Confirm proposal due date" in result["verification_needed"]


def test_as_needed_without_offset_is_penalized():
    opp = make_opp(
        title="As-Needed Security Guard Services",
        location="Las Vegas, NV",
        description="On-call security officers, BSIS guard card required. No guaranteed minimum.",
        due_date=datetime.utcnow() + timedelta(days=30),
        as_needed_warning=True,
    )
    result = score_opportunity_text(opp)
    assert any("As-needed" in f for f in result["negative_factors"])


def test_mandatory_pre_bid_missing_date_disqualifies():
    opp = make_opp(
        title="Security Guard Services",
        location="San Jose, CA",
        description="BSIS guard card required.",
        due_date=datetime.utcnow() + timedelta(days=30),
        pre_bid_mandatory=True,
        pre_bid_date=None,
    )
    result = score_opportunity_text(opp)
    assert result["decision"] == "No Bid"
    assert any("Mandatory pre-bid" in f for f in result["negative_factors"])


def test_suggested_review_status_for_negative_score():
    opp = make_opp(title="Catering Services")
    result = score_opportunity_text(opp)
    assert result["suggested_review_status"] == "Do Not Pursue"


def test_apply_scored_review_status_respects_human_decision():
    opp = make_opp(review_status="Pursue")
    apply_scored_review_status(opp, "Do Not Pursue")
    assert opp.review_status == "Pursue"  # human decision preserved


def test_apply_scored_review_status_fills_new():
    opp = make_opp(review_status="New")
    apply_scored_review_status(opp, "Needs Review")
    assert opp.review_status == "Needs Review"
