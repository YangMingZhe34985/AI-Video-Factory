import json
import mimetypes
from pathlib import Path

from werkzeug.utils import secure_filename

from .json_utils import to_jsonable


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def safe_filename(filename: str, fallback: str = "upload.bin") -> str:
    cleaned = secure_filename(filename or "")
    return cleaned or fallback


def write_json(path: str | Path, payload: dict) -> Path:
    target = Path(path)
    ensure_dir(target.parent)
    target.write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def guess_mime_type(path: str | Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type or "application/octet-stream"
