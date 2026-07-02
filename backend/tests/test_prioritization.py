"""Tests for the deterministic (no-AI) opportunity prioritization service."""

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.models import Opportunity
from app.services.prioritization import apply_priority_to_all, compute_priority

NOW = datetime(2026, 7, 2, 12, 0, 0)


def make_opp(**overrides) -> Opportunity:
    base = dict(title="Security Guard Services")
    base.update(overrides)
    return Opportunity(**base)


def test_relevant_and_due_soon_is_high():
    opp = make_opp(
        relevance_decision="Relevant",
        relevance_score=90,
        bid_score=80.0,
        due_date=NOW + timedelta(days=2),
        review_status="Needs Review",
    )
    result = compute_priority(opp, NOW)
    assert result["tier"] == "High"
    assert result["rank"] >= 60
    assert any("Relevant" in r for r in result["reasons"])
    assert any("Due in" in r for r in result["reasons"])


def test_relevant_but_do_not_pursue_is_very_low():
    opp = make_opp(
        relevance_decision="Relevant",
        relevance_score=90,
        bid_score=90.0,
        due_date=NOW + timedelta(days=2),
        review_status="Do Not Pursue",
    )
    result = compute_priority(opp, NOW)
    assert result["rank"] <= 5
    assert result["tier"] == "Low"


def test_archived_is_very_low():
    opp = make_opp(
        relevance_decision="Relevant",
        bid_score=100.0,
        due_date=NOW + timedelta(days=1),
        review_status="Archived",
    )
    result = compute_priority(opp, NOW)
    assert result["rank"] <= 5


def test_maybe_relevant_due_in_20_days_is_medium():
    opp = make_opp(
        relevance_decision="Maybe Relevant",
        relevance_score=50,
        bid_score=40.0,
        due_date=NOW + timedelta(days=20),
        review_status="New",
    )
    result = compute_priority(opp, NOW)
    assert result["tier"] == "Medium"
    assert 30 <= result["rank"] < 60


def test_missing_due_date_does_not_crash():
    opp = make_opp(
        relevance_decision="Relevant",
        due_date=None,
        review_status="New",
    )
    result = compute_priority(opp, NOW)
    assert 0 <= result["rank"] <= 100
    assert any("No due date" in r for r in result["reasons"])


def test_past_due_lowers_urgency():
    soon = make_opp(
        relevance_decision="Relevant",
        relevance_score=80,
        bid_score=60.0,
        due_date=NOW + timedelta(days=2),
        review_status="New",
    )
    past = make_opp(
        relevance_decision="Relevant",
        relevance_score=80,
        bid_score=60.0,
        due_date=NOW - timedelta(days=5),
        review_status="New",
    )
    soon_result = compute_priority(soon, NOW)
    past_result = compute_priority(past, NOW)
    assert past_result["rank"] < soon_result["rank"]
    assert any("Past due" in r for r in past_result["reasons"])


def test_as_needed_warning_applies_penalty():
    without = make_opp(
        relevance_decision="Relevant",
        due_date=NOW + timedelta(days=10),
        as_needed_warning=False,
    )
    with_warning = make_opp(
        relevance_decision="Relevant",
        due_date=NOW + timedelta(days=10),
        as_needed_warning=True,
    )
    assert (
        compute_priority(with_warning, NOW)["rank"]
        < compute_priority(without, NOW)["rank"]
    )


def test_pursue_ranks_above_watchlist_all_else_equal():
    pursue = make_opp(
        relevance_decision="Maybe Relevant",
        due_date=NOW + timedelta(days=10),
        review_status="Pursue",
    )
    watch = make_opp(
        relevance_decision="Maybe Relevant",
        due_date=NOW + timedelta(days=10),
        review_status="Watchlist",
    )
    assert (
        compute_priority(pursue, NOW)["rank"]
        > compute_priority(watch, NOW)["rank"]
    )


def test_apply_priority_to_all_stores_ranks(session):
    high = make_opp(
        title="Hot bid",
        relevance_decision="Relevant",
        relevance_score=90,
        bid_score=85.0,
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=2),
        review_status="Pursue",
    )
    low = make_opp(
        title="Declined bid",
        relevance_decision="Relevant",
        bid_score=90.0,
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=2),
        review_status="Do Not Pursue",
    )
    session.add(high)
    session.add(low)
    session.commit()

    count = apply_priority_to_all(session)
    assert count == 2

    stored = {o.title: o for o in session.exec(select(Opportunity)).all()}
    assert stored["Hot bid"].priority_rank is not None
    assert stored["Hot bid"].priority_tier == "High"
    assert stored["Declined bid"].priority_rank <= 5
    assert stored["Hot bid"].priority_rank > stored["Declined bid"].priority_rank
