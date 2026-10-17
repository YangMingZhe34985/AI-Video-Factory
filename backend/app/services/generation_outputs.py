"""Stable output slots for one provider request, shared by both download paths."""
from pathlib import Path
import hashlib
import json

from app.api import AppError


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def valid_receipt(path, receipt, task_id=None):
    if not path.is_file() or not receipt.is_file():
        return False
    try:
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        return (path.stat().st_size > 0 and saved["sha256"] == digest(path)
                and (task_id is None or saved.get("api_task_id") == task_id))
    except (ValueError, KeyError, OSError):
        return False


def output_slots(task, response, artifact_type, *, mock=False):
    target = Path(task.expected_artifact_path)
    if "image" not in artifact_type:
        return [(target, dict(response))]
    params = ((task.queue_data or {}).get("params") or (task.request_payload or {}).get("parameters") or {})
    count = int(params.get("n", 1))
    urls = response.get("result_urls") or ([response["result_url"]] if response.get("result_url") else [])
    if (urls or not mock) and count > 1 and len(urls) < count:
        raise AppError("API_TASK_FAILED", f"Expected {count} images but provider returned {len(urls)}", 502)
    count = max(count, len(urls))
    slots = []
    for index in range(count):
        item = {key: value for key, value in response.items() if key != "result_urls"}
        if urls:
            item["result_url"] = urls[index]
        name = target if index == 0 else target.with_name(f"{target.stem}_{index + 1:03d}{target.suffix}")
        slots.append((name, item))
    return slots
