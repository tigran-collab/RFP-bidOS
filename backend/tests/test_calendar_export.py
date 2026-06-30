"""Tests for the .ics calendar deadline export.

Offline: uses the in-memory `session` fixture.
"""

from datetime import datetime, timedelta, timezone

from app.models import Opportunity
from app.services.exports import _ics_date, _ics_timestamp, export_deadlines_ics


def _seed(session):
    opps = {
        "with_dates": Opportunity(
            title="Security Guard Services, Phase 1",
            agency="City of Example",
            source_url="https://example.gov/rfp",
            submission_method="Online portal",
            review_status="Pursue",
            due_date=datetime(2026, 7, 15),
            q_and_a_deadline=datetime(2026, 7, 1),
        ),
        "archived": Opportunity(
            title="Archived Security RFP",
            agency="City of Example",
            review_status="Archived",
            due_date=datetime(2026, 7, 20),
        ),
    }
    for opp in opps.values():
        session.add(opp)
    session.commit()
    for opp in opps.values():
        session.refresh(opp)
    return opps


def test_ics_structure_and_events(session):
    opps = _seed(session)
    content = export_deadlines_ics(session)

    assert content.startswith("BEGIN:VCALENDAR")
    assert "VERSION:2.0" in content
    assert "PRODID:-//RFP BidOS//Deadlines//EN" in content
    assert "CALSCALE:GREGORIAN" in content
    assert content.rstrip().endswith("END:VCALENDAR")

    # Two events for the with_dates opp (due + Q&A); archived excluded.
    assert content.count("BEGIN:VEVENT") == 2
    assert "SUMMARY:Bid Due:" in content
    assert "SUMMARY:Q&A Deadline:" in content
    assert "DTSTART;VALUE=DATE:20260715" in content
    assert "BEGIN:VALARM" in content
    assert "TRIGGER:-P2D" in content

    # CRLF line endings between properties.
    assert "\r\n" in content

    # Comma in the title is escaped per RFC 5545.
    assert "Security Guard Services\\, Phase 1" in content

    # Archived opp is excluded when no opportunity_id is passed.
    assert "Archived Security RFP" not in content
    assert f"{opps['archived'].id}-due@rfp-bidos" not in content


def test_ics_single_opportunity_filter(session):
    opps = _seed(session)
    # Filtering by id returns even an archived opp's events.
    content = export_deadlines_ics(session, opportunity_id=opps["archived"].id)
    assert content.count("BEGIN:VEVENT") == 1
    assert f"UID:{opps['archived'].id}-due@rfp-bidos" in content


# --- Fix 4: RFC 5545 line folding ------------------------------------------
def test_ics_long_title_is_folded(session):
    long_title = "Security Guard Services " + "X" * 200
    opp = Opportunity(
        title=long_title,
        review_status="Pursue",
        due_date=datetime(2026, 7, 15),
    )
    session.add(opp)
    session.commit()

    content = export_deadlines_ics(session)
    lines = content.split("\r\n")

    # No content line exceeds 75 octets.
    for line in lines:
        assert len(line.encode("utf-8")) <= 75, line
    # Folding produced at least one continuation line (begins with a space).
    assert any(line.startswith(" ") for line in lines)


# --- Fix 4: tz-aware datetimes normalized to UTC before formatting ----------
def test_ics_date_normalizes_tz_aware_to_utc_day():
    # 2026-07-16 00:30 in UTC+2 is still 2026-07-15 in UTC; the DATE value must
    # be the UTC calendar day, not the local one.
    aware = datetime(2026, 7, 16, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    assert _ics_date(aware) == "20260715"
    # Naive values pass through unchanged.
    assert _ics_date(datetime(2026, 7, 15)) == "20260715"


def test_ics_timestamp_normalizes_tz_aware_to_utc():
    aware = datetime(2026, 7, 16, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    # 00:30 +02:00 -> 22:30 UTC on 2026-07-15, with a Z suffix.
    assert _ics_timestamp(aware) == "20260715T223000Z"
