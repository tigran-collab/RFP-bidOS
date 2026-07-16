"""Tests for automatic archiving after submission deadlines pass."""

from datetime import UTC, datetime, timedelta

from app.models import Opportunity
from app.services.archiver import archive_past_deadline_opportunities


NOW = datetime(2026, 7, 8, 15, 30)


def _opp(**kwargs) -> Opportunity:
    defaults = {"title": "Guard Services", "review_status": "New"}
    defaults.update(kwargs)
    return Opportunity(**defaults)


def test_archives_non_terminal_opportunities_past_submission_deadline(session):
    past = _opp(
        title="Past Due Security RFP",
        review_status="Pursue",
        due_date=NOW - timedelta(days=1),
        review_notes="Operator note.",
    )
    due_today = _opp(title="Due Today Security RFP", due_date=NOW)
    future = _opp(title="Future Security RFP", due_date=NOW + timedelta(days=1))
    declined = _opp(
        title="Declined Past Due RFP",
        review_status="Do Not Pursue",
        due_date=NOW - timedelta(days=3),
    )
    already_archived = _opp(
        title="Archived Past Due RFP",
        review_status="Archived",
        due_date=NOW - timedelta(days=4),
    )
    archived_future = _opp(
        title="Archived Future RFP",
        review_status="Archived",
        due_date=NOW + timedelta(days=5),
    )
    rows = (past, due_today, future, declined, already_archived, archived_future)
    for row in rows:
        session.add(row)
    session.commit()
    for row in rows:
        session.refresh(row)

    result = archive_past_deadline_opportunities(session, now=NOW)

    assert result["checked_count"] == 6
    assert result["archived_count"] == 1
    # Only past-due terminal rows count as skips; future-dated terminal rows
    # were never candidates in the first place.
    assert result["skipped_terminal_count"] == 2
    assert result["archived"][0]["id"] == past.id

    session.refresh(past)
    session.refresh(due_today)
    session.refresh(future)
    session.refresh(declined)
    session.refresh(already_archived)
    assert past.review_status == "Archived"
    assert past.next_action == "No Action"
    assert past.deadline_risk == "Past Due"
    assert "Operator note." in past.review_notes
    assert "submission deadline" in past.review_notes
    assert due_today.review_status == "New"
    assert future.review_status == "New"
    assert declined.review_status == "Do Not Pursue"
    assert already_archived.review_status == "Archived"


def test_archive_handles_aware_due_dates_at_date_granularity(session):
    due_yesterday_aware = _opp(
        due_date=datetime(2026, 7, 7, 23, 0, tzinfo=UTC),
    )
    due_today_aware = _opp(
        due_date=datetime(2026, 7, 8, 0, 0, tzinfo=UTC),
    )
    session.add(due_yesterday_aware)
    session.add(due_today_aware)
    session.commit()

    # Pass an aware "now" too: SQLite hands due_date back naive, so this is
    # the branch that actually exercises to_naive_utc on an aware datetime.
    archive_past_deadline_opportunities(session, now=NOW.replace(tzinfo=UTC))

    session.refresh(due_yesterday_aware)
    session.refresh(due_today_aware)
    assert due_yesterday_aware.review_status == "Archived"
    assert due_today_aware.review_status == "New"
