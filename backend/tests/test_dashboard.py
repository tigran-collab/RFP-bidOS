"""Tests for operations dashboard buckets."""

from datetime import UTC, datetime, timedelta

from app.models import Opportunity
from app.services.dashboard import get_operations_dashboard


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def test_upcoming_deadlines_excludes_terminal_statuses(session):
    now = _utc_now()
    active = Opportunity(
        title="Active Guard Services",
        review_status="New",
        due_date=now + timedelta(days=3),
    )
    declined = Opportunity(
        title="Declined Federal Guard Services",
        review_status="Do Not Pursue",
        due_date=now + timedelta(days=2),
    )
    archived = Opportunity(
        title="Archived Guard Services",
        review_status="Archived",
        due_date=now + timedelta(days=1),
    )
    session.add(active)
    session.add(declined)
    session.add(archived)
    session.commit()
    session.refresh(active)
    session.refresh(declined)
    session.refresh(archived)

    dashboard = get_operations_dashboard(session)
    ids = {item["id"] for item in dashboard["upcoming_deadlines"]}

    assert ids == {active.id}
    assert dashboard["counts"]["do_not_pursue"] == 1
    assert dashboard["counts"]["archived"] == 1


def test_deadline_risk_counts_exclude_terminal_statuses(session):
    # The auto-archiver stamps "Past Due" on every row it archives; the
    # dashboard's deadline counts must reflect rows needing attention, not an
    # ever-growing cumulative tally of archived history.
    active_past_due = Opportunity(
        title="Active Past Due",
        review_status="Needs Review",
        deadline_risk="Past Due",
    )
    archived_past_due = Opportunity(
        title="Archived Past Due",
        review_status="Archived",
        deadline_risk="Past Due",
    )
    declined_high = Opportunity(
        title="Declined High Risk",
        review_status="Do Not Pursue",
        deadline_risk="High",
    )
    for row in (active_past_due, archived_past_due, declined_high):
        session.add(row)
    session.commit()

    counts = get_operations_dashboard(session)["counts"]

    assert counts["deadline_past_due"] == 1
    assert counts["deadline_risk_high"] == 0
