import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


def to_jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def dump_pretty(value) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, indent=2)
