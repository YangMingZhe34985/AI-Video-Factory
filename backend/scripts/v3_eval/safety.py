"""Fail-closed, process-independent spend guards for the V10 evaluation.

Call ``configure_environment`` before importing the application, and install the
transport guards before creating an app. The audit database contains hashes and
usage only: never credentials, prompts, media, or response bodies.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

TEXT_MODEL = "deepseek-v4.1-flash"
VISION_MODEL = "qwen3.7-plus"
MAX_CALLS = 800
IMAGE_CAP = 0
API_BASE = "https://dashscope.aliyuncs.com/api/v1"
CHAT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
CHAT_URL = CHAT_BASE + "/chat/completions"
_CREDENTIAL_KEYS = frozenset({"DASHSCOPE_API_KEY", "DASHSCOPE_API_BASE_URL", "DASHSCOPE_OPENAI_BASE_URL"})


class EvaluationSafetyError(RuntimeError):
    """A prohibited, exhausted, or ambiguous evaluation request."""


def _credential_lines(path: Path, wanted: set[str]) -> dict[str, str]:
    """Decode values only for explicitly allowed provider credential keys.

    Do not use dotenv_values: it interprets the entire file, including the user's
    database configuration. No interpolation or multiline values are supported.
    """
    result: dict[str, str] = {}
    if not wanted or not path.exists():
        return result
    with path.open("rb") as handle:
        for raw in handle:
            key, separator, value = raw.lstrip().removeprefix(b"export ").partition(b"=")
            name = key.strip().decode("ascii", errors="ignore")
            if not separator or name not in wanted or name not in _CREDENTIAL_KEYS:
                continue
            text = value.decode("utf-8").strip()
            if text.startswith(("'", '"')):
                quote = text[0]
                end = text.find(quote, 1)
                tail = text[end + 1:].strip() if end >= 0 else ""
                if end < 0 or (tail and not tail.startswith("#")):
                    raise EvaluationSafetyError("Unsupported credential quoting; set the key in the process environment")
                text = text[1:end]
            else:
                text = text.split(" #", 1)[0].strip()
            if "${" in text or "\n" in text or "\r" in text:
                raise EvaluationSafetyError("Credential interpolation is disabled")
            result[name] = text
    return result


def configure_environment(root: Path, work: Path) -> dict[str, str]:
    """Disable dotenv loading and pin all external infrastructure to isolation."""
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False
    # Patching both references prevents a subsequent direct dotenv.main import.
    import dotenv.main
    dotenv.main.load_dotenv = dotenv.load_dotenv
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["FLASK_SKIP_DOTENV"] = "1"
    existing = {name: os.environ[name] for name in _CREDENTIAL_KEYS if os.environ.get(name)}
    credentials = _credential_lines(Path(root) / ".env", set(_CREDENTIAL_KEYS) - existing.keys())
    credentials.update(existing)
    api_base = credentials.get("DASHSCOPE_API_BASE_URL", API_BASE).rstrip("/")
    chat_base = credentials.get("DASHSCOPE_OPENAI_BASE_URL", CHAT_BASE).rstrip("/")
    if api_base != API_BASE or chat_base != CHAT_BASE:
        raise EvaluationSafetyError("V10 permits only the established DashScope API URLs")
    if not credentials.get("DASHSCOPE_API_KEY"):
        raise EvaluationSafetyError("DASHSCOPE_API_KEY is missing; no request was sent")
    work = Path(work).resolve()
    root = Path(root).resolve()
    if work == root or root in work.parents:
        raise EvaluationSafetyError("V10 work directory must be outside the repository")
    work.mkdir(parents=True, exist_ok=True)
    (work / "storage" / "uploads").mkdir(parents=True, exist_ok=True)
    values = {
        "DASHSCOPE_API_KEY": credentials["DASHSCOPE_API_KEY"],
        "DASHSCOPE_API_BASE_URL": API_BASE,
        "DASHSCOPE_OPENAI_BASE_URL": CHAT_BASE,
        "DASHSCOPE_BASE_URL": API_BASE,
        "QWEN_BASE_URL": CHAT_BASE,
        "DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": "",
        "DATABASE_URL": f"sqlite:///{(work / 'eval.db').as_posix()}",
        "REDIS_URL": "redis://127.0.0.1:1/0",
        "STORAGE_ROOT": str(work / "storage"),
        "UPLOAD_FOLDER": str(work / "storage" / "uploads"),
        "AGENT_CHECKPOINT_PATH": str(work / "checkpoints.sqlite"),
        "MQ_ENABLED": "false", "MODEL_ADAPTER_MODE": "real",
        "AGENT_SEARCH_PROVIDER": "mock", "EVAL_IMAGE_CAP": "0",
        "FAILURE_AGENT_ENABLED": "false", "FAILURE_AGENT_ON_ERROR": "false",
        "AGENT_PLANNER_MODEL": TEXT_MODEL, "AGENT_VISION_MODEL": VISION_MODEL,
        "AGENT_V3_DEFAULT_TEXT_MODEL": TEXT_MODEL,
        "AGENT_V3_DEFAULT_VISION_MODEL": VISION_MODEL,
        "DEFAULT_VIDEO_UNDERSTANDING_MODEL": VISION_MODEL,
        "DEFAULT_PROMPT_REWRITE_MODEL": TEXT_MODEL,
        **{f"AGENT_{role}_MODEL": TEXT_MODEL for role in (
            "PRODUCER", "RESEARCH", "CREATIVE", "DIRECTOR", "PROMPT_SMITH", "CRITIC", "REPAIR", "INTAKE")},
    }
    os.environ.update(values)
    return values


class CallMeter:
    """SQLite reservation committed before transport; survives process death."""

    def __init__(self, work: Path, *, max_calls: int = MAX_CALLS):
        if not isinstance(max_calls, int) or isinstance(max_calls, bool) or not 0 <= max_calls <= MAX_CALLS:
            raise EvaluationSafetyError("V10 call limit must be between 0 and 800")
        self.path = Path(work).resolve() / "real_call_audit.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.label = "unlabelled"
        self._patches: list[tuple[Any, str, Any]] = []
        self._transport_context = threading.local()
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS limits (id INTEGER PRIMARY KEY CHECK(id=1), max_calls INTEGER NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO limits VALUES(1, ?)", (max_calls,))
            conn.execute("UPDATE limits SET max_calls=MIN(max_calls, ?) WHERE id=1", (max_calls,))
            conn.execute("""CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL,
                model TEXT NOT NULL, kind TEXT NOT NULL, request_hash TEXT NOT NULL,
                process_id INTEGER NOT NULL, started REAL NOT NULL, ended REAL,
                status TEXT NOT NULL, http_status INTEGER, response_id TEXT,
                input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
                error_type TEXT)""")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_calls_hash ON calls(request_hash, status)")
            conn.execute("""CREATE TABLE IF NOT EXISTS blocked (
                id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL,
                kind TEXT NOT NULL, reason TEXT NOT NULL, at REAL NOT NULL)""")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def set_label(self, label: str) -> None:
        self.label = str(label)[:160]

    def _block(self, kind: str, reason: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO blocked(label,kind,reason,at) VALUES(?,?,?,?)",
                         (self.label, kind, reason, time.time()))
        raise EvaluationSafetyError(reason)

    def _reserve(self, model: str, request_hash: str) -> int:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT id FROM calls WHERE request_hash=? AND status IN ('reserved','unknown') LIMIT 1",
                (request_hash,),
            ).fetchone()
            if previous:
                raise EvaluationSafetyError(f"V10 ambiguous request already reserved as call {previous['id']}; do not resend")
            count = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
            limit = conn.execute("SELECT max_calls FROM limits WHERE id=1").fetchone()[0]
            if count >= limit:
                raise EvaluationSafetyError(f"V10 real-call cap reached ({count}/{limit})")
            cursor = conn.execute(
                "INSERT INTO calls(label,model,kind,request_hash,process_id,started,status) VALUES(?,?,?,?,?,?,?)",
                (self.label, model, "vision" if model == VISION_MODEL else "text", request_hash,
                 os.getpid(), time.time(), "reserved"),
            )
            return int(cursor.lastrowid)

    def _finish(self, call_id: int, *, response=None, error: BaseException | None = None) -> None:
        data: dict[str, Any] = {}
        if response is not None:
            try:
                parsed = response.json()
                data = parsed if isinstance(parsed, dict) else {}
            except (ValueError, TypeError):
                pass
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        def token(name):
            value = usage.get(name)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        code = int(response.status_code) if response is not None else None
        # A successful HTTP response without an identifiable completion is
        # ambiguous too; prevent silent reposts after parsing/transport failures.
        status = "unknown" if error is not None or (code is not None and code < 300 and not data.get("id")) else (
            "success" if code is not None and 200 <= code < 300 else "http_error")
        response_id = str(data["id"])[:256] if data.get("id") else None
        with self._connect() as conn:
            conn.execute("""UPDATE calls SET ended=?,status=?,http_status=?,response_id=?,
                input_tokens=?,output_tokens=?,total_tokens=?,error_type=? WHERE id=?""",
                         (time.time(), status, code, response_id, token("prompt_tokens"),
                          token("completion_tokens"), token("total_tokens"),
                          type(error).__name__ if error else None, call_id))

    def rows(self, *, label: str | None = None) -> list[dict]:
        with self._connect() as conn:
            query, params = ("SELECT * FROM calls ORDER BY id", ()) if label is None else (
                "SELECT * FROM calls WHERE label=? ORDER BY id", (label,))
            return [dict(row) for row in conn.execute(query, params)]

    def snapshot(self) -> dict:
        rows = self.rows()
        with self._connect() as conn:
            blocked = [dict(row) for row in conn.execute("SELECT * FROM blocked ORDER BY id")]
            limit = conn.execute("SELECT max_calls FROM limits WHERE id=1").fetchone()[0]
        return {
            "call_limit": limit, "real_calls": len(rows),
            "text_calls": sum(row["kind"] == "text" for row in rows),
            "vision_calls": sum(row["kind"] == "vision" for row in rows),
            "input_tokens_sum": sum(row["input_tokens"] or 0 for row in rows),
            "input_tokens_max": max((row["input_tokens"] or 0 for row in rows), default=0),
            "output_tokens_sum": sum(row["output_tokens"] or 0 for row in rows),
            "usage_missing_calls": sum(row["input_tokens"] is None for row in rows),
            "unknown_or_reserved_calls": sum(row["status"] in {"unknown", "reserved"} for row in rows),
            "real_image_calls": 0, "real_video_calls": 0,
            "blocked_media_attempts": sum(row["kind"] == "media" for row in blocked),
            "blocked_network_attempts": sum(row["kind"] == "network" for row in blocked),
        }

    def _patch(self, owner, name: str, replacement) -> None:
        self._patches.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)

    def uninstall(self) -> None:
        for owner, name, original in reversed(self._patches):
            setattr(owner, name, original)
        self._patches.clear()

    close = uninstall

    def install(self) -> "CallMeter":
        import requests
        from urllib3.connection import HTTPConnection, HTTPSConnection
        from urllib3.util.retry import Retry

        original_send = requests.Session.send
        meter = self

        def send(session, request, **kwargs):
            if request.method != "POST" or request.url != CHAT_URL:
                meter._block("network", "V10 blocked an endpoint outside the approved chat allowlist")
            try:
                payload = json.loads(request.body)
            except (ValueError, TypeError, UnicodeDecodeError):
                meter._block("network", "V10 requires a JSON chat body")
            if not isinstance(payload, dict) or payload.get("model") not in {TEXT_MODEL, VISION_MODEL}:
                meter._block("network", "V10 blocked an unapproved model")
            if payload.get("stream") or not isinstance(payload.get("messages"), list):
                meter._block("network", "V10 requires a non-streaming chat completion")
            if kwargs.get("proxies") and any(kwargs["proxies"].values()):
                meter._block("network", "V10 disallows proxy transport for provider credentials")
            if kwargs.get("verify") is False:
                meter._block("network", "V10 requires TLS certificate verification")
            # Disable retries below Session.send, where attempts would otherwise
            # bypass the reservation counter, and block Requests redirects.
            for adapter in session.adapters.values():
                adapter.max_retries = Retry(total=0, connect=0, read=0, redirect=0, status=0, other=0,
                                            raise_on_status=False)
            kwargs["allow_redirects"] = False
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            request_hash = hashlib.sha256((CHAT_URL + "\n" + canonical).encode("utf-8")).hexdigest()
            call_id = meter._reserve(payload["model"], request_hash)
            meter._transport_context.allowed = True
            try:
                response = original_send(session, request, **kwargs)
            except BaseException as error:
                meter._finish(call_id, error=error)
                raise
            finally:
                meter._transport_context.allowed = False
            meter._finish(call_id, response=response)
            return response

        self._patch(requests.Session, "send", send)
        # Direct urllib3 calls must not bypass the audited Session boundary.
        for cls in (HTTPConnection, HTTPSConnection):
            original_connect = cls.connect
            def connect(connection, _original=original_connect):
                if not getattr(meter._transport_context, "allowed", False):
                    meter._block("network", "V10 blocked unaudited urllib3 transport")
                return _original(connection)
            self._patch(cls, "connect", connect)
            original_request = cls.request
            def http_request(connection, *args, _original=original_request, **kwargs):
                if not getattr(meter._transport_context, "allowed", False):
                    meter._block("network", "V10 blocked unaudited urllib3 transport")
                return _original(connection, *args, **kwargs)
            self._patch(cls, "request", http_request)
        self._install_media_guards()
        return self

    def _install_media_guards(self) -> None:
        from app.adapters.dashscope_common import DashScopeGenerationAdapter
        from app.adapters.dashscope_image import DashScopeImageAdapter
        from app.adapters.dashscope_qwen_image import DashScopeQwenImageAdapter
        from app.adapters.dashscope_multimodal_image import DashScopeMultimodalSyncAdapter
        from app.adapters import dashscope_i2v, dashscope_r2v, dashscope_t2v, dashscope_wan3

        meter = self
        classes = (DashScopeGenerationAdapter, DashScopeImageAdapter, DashScopeQwenImageAdapter,
                   DashScopeMultimodalSyncAdapter,
                   dashscope_i2v.DashScopeI2VAdapter, dashscope_r2v.DashScopeR2VFlashAdapter,
                   dashscope_t2v.DashScopeT2VAdapter, dashscope_wan3.DashScopeWan3Adapter)
        for cls in classes:
            original = cls.submit
            def submit(adapter, payload, _original=original):
                if adapter.use_mock and os.environ.get("EVAL_MOCK_MEDIA") == "1":
                    return _original(adapter, payload)
                meter._block("media", "V10 real image/video generation is forbidden (image cap=0)")
            self._patch(cls, "submit", submit)
        if hasattr(DashScopeGenerationAdapter, "upload_local_file_get_oss_url"):
            def upload(*args, **kwargs):
                meter._block("media", "V10 media uploads to generation providers are forbidden")
            self._patch(DashScopeGenerationAdapter, "upload_local_file_get_oss_url", upload)


def install_guards(work: Path) -> CallMeter:
    """Install guards after environment isolation and before app creation."""
    configured = int(os.environ.get("EVAL_MAX_REAL_CALLS", str(MAX_CALLS)))
    return CallMeter(work, max_calls=configured).install()
