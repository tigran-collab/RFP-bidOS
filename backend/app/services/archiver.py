"""Archive opportunities whose submission deadline has passed."""

from datetime import UTC, datetime

from sqlmodel import select

from app.models import Opportunity
from app.utils.dates import days_until_date, to_naive_utc

ARCHIVE_STATUS = "Archived"
TERMINAL_STATUSES = {"Archived", "Do Not Pursue"}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def archive_past_deadline_opportunities(
    session,
    now: datetime | None = None,
) -> dict:
    """Archive non-terminal opportunities when the due date is before today.

    Deadline math is date-granular to match dashboard/digest behavior: an
    opportunity due today remains active until the next calendar day.
    """
    checked_at = to_naive_utc(now) if now is not None else _utc_now()
    opportunities = list(
        session.exec(
            select(Opportunity)
            .where(Opportunity.due_date != None)  # noqa: E711
            .order_by(Opportunity.id)
        ).all()
    )
    archived: list[dict] = []
    skipped_terminal_count = 0

    for opportunity in opportunities:
        if opportunity.due_date is None:
            continue
        past_due = days_until_date(opportunity.due_date, checked_at) < 0
        status = opportunity.review_status or "New"
        if status in TERMINAL_STATUSES:
            # Only count terminal rows the deadline check would otherwise
            # have archived; future-dated terminal rows are not "skips".
            if past_due:
                skipped_terminal_count += 1
            continue
        if not past_due:
            continue

        previous_status = status
        due_date = to_naive_utc(opportunity.due_date).date().isoformat()
        opportunity.review_status = ARCHIVE_STATUS
        opportunity.next_action = "No Action"
        opportunity.deadline_risk = "Past Due"
        opportunity.review_notes = _archive_note(
            opportunity.review_notes,
            due_date=due_date,
            archived_on=checked_at.date().isoformat(),
            previous_status=previous_status,
        )
        opportunity.updated_at = checked_at
        session.add(opportunity)
        archived.append(
            {
                "id": opportunity.id,
                "title": opportunity.title,
                "previous_status": previous_status,
                "due_date": due_date,
            }
        )

    session.commit()
    return {
        "checked_count": len(opportunities),
        "archived_count": len(archived),
        "skipped_terminal_count": skipped_terminal_count,
        "archived": archived,
    }


def _archive_note(
    existing: str | None,
    *,
    due_date: str,
    archived_on: str,
    previous_status: str,
) -> str:
    note = (
        f"Auto-archived on {archived_on}: submission deadline "
        f"{due_date} passed while status was {previous_status}."
    )
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing}\n{note}"
