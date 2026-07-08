"""Test for the daily-run pipeline.

Offline: calls daily_run with do_scrape=False so no network is touched.
"""

from datetime import UTC, datetime, timedelta

from app.models import Opportunity
from app.services.daily_run import _score_all, daily_run


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _seed(session):
    now = _utc_now()
    opps = [
        Opportunity(
            title="Unarmed Security Guard Services for County Facilities",
            agency="County A",
            location="San Jose, CA",
            description="BSIS licensed guard card required.",
            relevance_decision="Relevant",
            review_status="New",
            created_at=now - timedelta(hours=1),
            due_date=now + timedelta(days=4),
        ),
        Opportunity(
            title="Janitorial Services",
            agency="City B",
            relevance_decision="Not Relevant",
            review_status="New",
            created_at=now - timedelta(hours=2),
        ),
        Opportunity(
            title="Past Due Patrol RFP",
            agency="City C",
            relevance_decision="Relevant",
            review_status="Pursue",
            created_at=now - timedelta(days=3),
            due_date=now - timedelta(days=1),
        ),
    ]
    for opp in opps:
        session.add(opp)
    session.commit()
    for opp in opps:
        session.refresh(opp)
    return opps


def test_daily_run_offline(session):
    opps = _seed(session)
    result = daily_run(session, do_scrape=False)

    assert result["scrape"] == {"skipped": True}
    assert result["scored"] >= len(opps)

    digest = result["digest"]
    assert "new_opportunities" in digest
    assert "upcoming_deadlines" in digest
    assert "at_risk" in digest
    assert "counts" in digest

    # Upcoming deadline bucket should include the future-due relevant opp.
    upcoming_ids = {item["id"] for item in digest["upcoming_deadlines"]}
    assert opps[0].id in upcoming_ids
    # At-risk should include the past-due opp.
    at_risk_ids = {item["id"] for item in digest["at_risk"]}
    assert opps[2].id in at_risk_ids


def test_daily_run_never_auto_declines_new_bid(session):
    """workflow#3: a sparse New bid that scores negative must not be moved to a
    terminal status by the unattended run -- it caps at 'Needs Review'."""
    sparse = Opportunity(
        title="Security Guard Services",  # security match, but no license text
        agency="Some County",
        relevance_decision="Relevant",
        review_status="New",
        created_at=_utc_now() - timedelta(hours=1),
        # no due_date, no license terms -> negative score -> "Do Not Pursue"
    )
    session.add(sparse)
    session.commit()
    session.refresh(sparse)

    # Confirm the scorer would suggest a terminal status for this row.
    from app.services.scorer import score_opportunity_text

    assert score_opportunity_text(sparse)["suggested_review_status"] == "Do Not Pursue"

    daily_run(session, do_scrape=False)
    session.refresh(sparse)
    assert sparse.review_status == "Needs Review"


def test_score_all_is_noop_when_nothing_changes(session):
    """M2: re-scoring an already-scored, unchanged opportunity must not touch
    updated_at (returns 0 changed on the second pass)."""
    opp = Opportunity(
        title="Unarmed Security Guard Services",
        relevance_decision="Relevant",
        review_status="Needs Review",
        created_at=_utc_now() - timedelta(hours=1),
        due_date=_utc_now() + timedelta(days=30),
    )
    session.add(opp)
    session.commit()
    session.refresh(opp)

    first = _score_all(session)
    assert first >= 1
    session.refresh(opp)
    stamp_after_first = opp.updated_at

    second = _score_all(session)
    assert second == 0
    session.refresh(opp)
    assert opp.updated_at == stamp_after_first  # not churned
