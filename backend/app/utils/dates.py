from datetime import UTC, datetime


def to_naive_utc(value: datetime) -> datetime:
    """Return a naive-UTC datetime so it can be compared against naive sentinels.

    Aware values are converted to UTC and stripped of tzinfo; already-naive
    values pass through unchanged. This prevents TypeError when mixing aware
    due_date/checked_at/updated_at values with naive datetime.max/min sentinels.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def days_until_date(due: datetime, now: datetime | None = None) -> int:
    """Whole calendar days from ``now`` to ``due`` at DATE granularity.

    Both sides are normalized to naive UTC, then reduced to their date part
    before subtracting. An item due at midnight *today* returns 0 (due today),
    not a negative number, no matter the current time of day or local timezone.
    This mirrors ``logistics_extractor.compute_deadline_risk`` so the deadline
    surfaces (notifications, dashboard, scorer, prioritization) all agree.
    """
    due_norm = to_naive_utc(due)
    if now is None:
        now_norm = datetime.now(UTC).replace(tzinfo=None)
    else:
        now_norm = to_naive_utc(now)
    return (due_norm.date() - now_norm.date()).days
