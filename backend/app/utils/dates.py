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
