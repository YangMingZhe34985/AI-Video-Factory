from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value
