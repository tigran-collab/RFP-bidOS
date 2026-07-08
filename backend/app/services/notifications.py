"""
Notification digest: a read-only summary of newly relevant opportunities,
upcoming deadlines, and at-risk opportunities. No network access, no mutations,
no AI. Intended for a daily heads-up via CLI or API.
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.models import Opportunity
from app.utils.dates import days_until_date, to_naive_utc

# "Do Not Pursue" is a declined bid: it should not resurface as a new
# opportunity for the next 7 days, so exclude it from the "new" bucket too.
EXCLUDED_FROM_NEW = {"Archived", "Do Not Pursue"}
EXCLUDED_FROM_DEADLINES = {"Archived", "Do Not Pursue"}
EXCLUDED_FROM_AT_RISK = {"Archived", "Do Not Pursue"}
# Relevance values that qualify as "new". None is included so manually-created
# opportunities (which never get a scraper relevance_decision) still surface.
NEW_RELEVANCE_VALUES = ("Relevant", "Maybe Relevant", None)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _status_of(opp: Opportunity) -> str:
    return opp.review_status or "New"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def build_digest(session, days: int = 7, limit: int = 50) -> dict:
    now = _utc_now()
    window = max(0, days)
    cutoff = now - timedelta(days=window)
    opportunities = list(session.exec(select(Opportunity)).all())

    # "Active" excludes declined/terminal statuses, not just Archived.
    active = [
        o
        for o in opportunities
        if _status_of(o) not in {"Archived", "Do Not Pursue"}
    ]

    # New opportunities: relevant / maybe-relevant / manually-created (NULL
    # decision) and recently created, excluding declined/archived statuses.
    new_candidates = [
        o
        for o in opportunities
        if o.relevance_decision in NEW_RELEVANCE_VALUES
        and o.created_at is not None
        and to_naive_utc(o.created_at) >= cutoff
        and _status_of(o) not in EXCLUDED_FROM_NEW
    ]
    new_candidates.sort(
        key=lambda o: to_naive_utc(o.created_at) if o.created_at else datetime.min,
        reverse=True,
    )
    new_opportunities = [
        {
            "id": o.id,
            "title": o.title,
            "agency": o.agency,
            "due_date": _iso(o.due_date),
            "created_at": _iso(o.created_at),
            "relevance_decision": o.relevance_decision,
        }
        for o in new_candidates[:limit]
    ]

    # Upcoming deadlines: future due_date within the next `days` days.
    upcoming_candidates = []
    for o in opportunities:
        if not o.due_date or _status_of(o) in EXCLUDED_FROM_DEADLINES:
            continue
        days_until = days_until_date(o.due_date, now)
        if 0 <= days_until <= window:
            upcoming_candidates.append((days_until, o))
    upcoming_candidates.sort(key=lambda pair: to_naive_utc(pair[1].due_date))
    upcoming_deadlines = [
        {
            "id": o.id,
            "title": o.title,
            "agency": o.agency,
            "due_date": _iso(o.due_date),
            "days_until": days_until,
            "deadline_risk": o.deadline_risk,
        }
        for days_until, o in upcoming_candidates[:limit]
    ]

    # At-risk: past due (due_date < now) OR deadline_risk == "High".
    at_risk_candidates = []
    for o in opportunities:
        if _status_of(o) in EXCLUDED_FROM_AT_RISK:
            continue
        days_until = days_until_date(o.due_date, now) if o.due_date else None
        # Past due at DATE granularity: due today (0) is NOT past due.
        past_due = days_until is not None and days_until < 0
        if past_due or o.deadline_risk == "High":
            at_risk_candidates.append((o.due_date, days_until, o))
    at_risk_candidates.sort(
        key=lambda triple: to_naive_utc(triple[0]) if triple[0] else datetime.max
    )
    at_risk = [
        {
            "id": o.id,
            "title": o.title,
            "agency": o.agency,
            "due_date": _iso(o.due_date),
            "days_until": days_until,
            "deadline_risk": o.deadline_risk,
        }
        for _due, days_until, o in at_risk_candidates[:limit]
    ]

    counts = {
        # Report the true number of new opportunities, not the truncated list.
        "new_opportunities": len(new_candidates),
        "upcoming_deadlines": len(upcoming_deadlines),
        "at_risk": len(at_risk),
        "active_opportunities": len(active),
    }

    return {
        "days": days,
        "new_opportunities": new_opportunities,
        "upcoming_deadlines": upcoming_deadlines,
        "at_risk": at_risk,
        "counts": counts,
    }


def _format_line(item: dict) -> str:
    due = item.get("due_date")
    due_part = "no due date"
    if due:
        due_part = f"due {due[:10]}"
        days_until = item.get("days_until")
        if days_until is not None:
            if days_until < 0:
                due_part += f" ({abs(days_until)} days ago)"
            else:
                due_part += f" (in {days_until} days)"
    agency = item.get("agency") or "-"
    return f"[{item['id']}] {item['title']} - {agency} - {due_part}"


def _render_section(title: str, items: list[dict]) -> list[str]:
    lines = [f"## {title}"]
    if not items:
        lines.append("(none)")
    else:
        lines.extend(_format_line(item) for item in items)
    return lines


def render_digest_text(digest: dict) -> str:
    counts = digest.get("counts", {})
    header = (
        f"Digest: {counts.get('new_opportunities', 0)} new, "
        f"{counts.get('upcoming_deadlines', 0)} upcoming deadline(s), "
        f"{counts.get('at_risk', 0)} at risk "
        f"({counts.get('active_opportunities', 0)} active)"
    )
    lines = [header, ""]
    lines.extend(_render_section("New Opportunities", digest.get("new_opportunities", [])))
    lines.append("")
    lines.extend(_render_section("Upcoming Deadlines", digest.get("upcoming_deadlines", [])))
    lines.append("")
    lines.extend(_render_section("At Risk", digest.get("at_risk", [])))
    return "\n".join(lines)
