from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to naive datetimes (SQLite drops tzinfo on read)."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def isoformat(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value
