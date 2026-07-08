"""Tests for the shared date helpers.

``days_until_date`` compares at DATE granularity so an item due *today* reads
as 0 (due today), never negative, regardless of the current time of day or the
machine's local timezone. This is the fix for H6 ("due today reported as past
due") and must agree with logistics_extractor.compute_deadline_risk.
"""

from datetime import UTC, datetime, timedelta, timezone

from app.utils.dates import days_until_date


def test_due_today_is_zero_even_late_in_day():
    # Due at midnight today; "now" is late afternoon UTC.
    now = datetime(2026, 7, 7, 17, 30, 0)
    due_midnight = datetime(2026, 7, 7, 0, 0, 0)
    assert days_until_date(due_midnight, now) == 0


def test_due_tomorrow_is_one():
    now = datetime(2026, 7, 7, 17, 30, 0)
    due = datetime(2026, 7, 8, 0, 0, 0)
    assert days_until_date(due, now) == 1


def test_past_due_is_negative():
    now = datetime(2026, 7, 7, 9, 0, 0)
    due = datetime(2026, 7, 5, 0, 0, 0)
    assert days_until_date(due, now) == -2


def test_aware_due_is_normalized_to_utc():
    # 2026-07-08 01:00 in UTC+2 == 2026-07-07 23:00 UTC -> still "today".
    now = datetime(2026, 7, 7, 12, 0, 0)
    aware_due = datetime(2026, 7, 8, 1, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert days_until_date(aware_due, now) == 0


def test_defaults_now_to_utc_today():
    today_midnight = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    assert days_until_date(today_midnight) == 0
