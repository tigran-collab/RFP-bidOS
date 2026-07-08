"""Digest-correctness tests (workflow#12, M8, count accuracy, active count).

Offline: uses the in-memory `session` fixture from conftest.
"""

from datetime import UTC, datetime, timedelta

from app.models import Opportunity
from app.services.notifications import build_digest


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def test_manual_entry_with_null_relevance_is_new(session):
    """M8: manually-created opportunities have relevance_decision=None and must
    still appear as new."""
    now = _utc_now()
    manual = Opportunity(
        title="Manually Added Guard Contract",
        agency="City Manual",
        relevance_decision=None,
        review_status="New",
        created_at=now - timedelta(hours=1),
    )
    session.add(manual)
    session.commit()
    session.refresh(manual)

    digest = build_digest(session, days=7)
    ids = {item["id"] for item in digest["new_opportunities"]}
    assert manual.id in ids


def test_declined_bid_not_new(session):
    """workflow#12: a Do Not Pursue bid must not resurface as new."""
    now = _utc_now()
    declined = Opportunity(
        title="Declined Security RFP",
        relevance_decision="Relevant",
        review_status="Do Not Pursue",
        created_at=now - timedelta(hours=1),
    )
    session.add(declined)
    session.commit()
    session.refresh(declined)

    digest = build_digest(session, days=7)
    ids = {item["id"] for item in digest["new_opportunities"]}
    assert declined.id not in ids


def test_new_count_is_true_count_not_truncated(session):
    """Count accuracy: counts.new_opportunities reflects the real total even
    when the returned list is truncated by ``limit``."""
    now = _utc_now()
    for i in range(5):
        session.add(
            Opportunity(
                title=f"New Relevant {i}",
                relevance_decision="Relevant",
                review_status="New",
                created_at=now - timedelta(hours=1),
            )
        )
    session.commit()

    digest = build_digest(session, days=7, limit=2)
    assert len(digest["new_opportunities"]) == 2  # list truncated
    assert digest["counts"]["new_opportunities"] == 5  # count is the truth


def test_active_count_excludes_do_not_pursue(session):
    """Active count must not include declined bids."""
    now = _utc_now()
    session.add(Opportunity(title="Active One", review_status="Needs Review", created_at=now))
    session.add(Opportunity(title="Declined", review_status="Do Not Pursue", created_at=now))
    session.add(Opportunity(title="Archived", review_status="Archived", created_at=now))
    session.commit()

    digest = build_digest(session, days=7)
    assert digest["counts"]["active_opportunities"] == 1


def test_due_today_is_upcoming_not_at_risk(session):
    """H6: an item due today (midnight) is an upcoming deadline, not past due."""
    now = _utc_now()
    due_today = Opportunity(
        title="Due Today Security Services",
        relevance_decision="Relevant",
        review_status="Needs Review",
        created_at=now - timedelta(hours=1),
        due_date=now.replace(hour=0, minute=0, second=0, microsecond=0),
    )
    session.add(due_today)
    session.commit()
    session.refresh(due_today)

    digest = build_digest(session, days=7)
    upcoming_ids = {item["id"] for item in digest["upcoming_deadlines"]}
    at_risk_ids = {item["id"] for item in digest["at_risk"]}
    assert due_today.id in upcoming_ids
    assert due_today.id not in at_risk_ids
