import base64
import mimetypes
import os
from abc import ABC, abstractmethod
from pathlib import Path

import requests
from flask import current_app, has_app_context
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.api import AppError
from app.services.storage_service import StorageService
from app.utils.files import ensure_dir


class BaseModelAdapter(ABC):
    def __init__(self, model=None):
        self.model = model
        self._model_id = model.model_id if model else "mock"
        self._provider = model.provider if model else None

    def config(self, name: str, default=None):
        if has_app_context():
            return current_app.config.get(name, default)
        return os.getenv(name, default)

    @property
    def adapter_mode(self) -> str:
        return str(self.config("MODEL_ADAPTER_MODE", "auto") or "auto").lower()

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider(self) -> str | None:
        return self._provider

    def api_key(self, required: bool = True) -> str:
        key = (
            self.config("DASHSCOPE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or ""
        )
        if required and not key:
            raise AppError(
                "INVALID_INPUT",
                "Missing DASHSCOPE_API_KEY or OPENAI_API_KEY for real model adapter",
                400,
            )
        return str(key)

    @property
    def use_mock(self) -> bool:
        mode = self.adapter_mode
        if mode == "mock":
            return True
        if mode == "real":
            return False
        return not bool(self.api_key(required=False))

    @property
    def request_timeout(self) -> int:
        return int(self.config("REQUEST_TIMEOUT_SEC", 120))

    @property
    def download_timeout(self) -> int:
        return int(self.config("DOWNLOAD_TIMEOUT_SEC", 600))

    @staticmethod
    def http_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def request_json(self, method: str, url: str, **kwargs) -> dict:
        response = self.http_session().request(
            method,
            url,
            timeout=kwargs.pop("timeout", self.request_timeout),
            **kwargs,
        )
        try:
            data = response.json()
        except ValueError:
            data = {"text": response.text}
        if response.status_code >= 400:
            # Extract provider-specific error code and message from response body
            error_code = data.get("code") or (data.get("output") or {}).get("code")
            error_msg  = data.get("message") or (data.get("output") or {}).get("message")
            user_msg   = f"HTTP {response.status_code} from model provider"
            if error_code or error_msg:
                detail = " — ".join(filter(None, [error_code, error_msg]))
                user_msg = f"{user_msg} — {detail}"
            raise AppError(
                "API_TASK_FAILED",
                user_msg,
                response.status_code,
                payload={"url": url, "response": data},
            )
        return data

    def resolve_path(self, value: str | Path) -> Path:
        raw = str(value).strip()
        if raw.startswith("file://"):
            raw = raw.replace("file://", "", 1)
            if os.name == "nt" and raw.startswith("/") and len(raw) > 3 and raw[2] == ":":
                raw = raw[1:]
        path = Path(raw)
        if path.is_absolute():
            return path
        return StorageService.resolve(raw)

    @staticmethod
    def is_http_url(value: str) -> bool:
        lowered = value.lower()
        return lowered.startswith("http://") or lowered.startswith("https://")

    @staticmethod
    def is_remote_resource(value: str) -> bool:
        lowered = value.lower()
        return lowered.startswith("http://") or lowered.startswith("https://") or lowered.startswith("oss://")

    def encode_local_file_as_data_url(self, file_path: str | Path, media_kind: str | None = None) -> str:
        path = self.resolve_path(file_path)
        if not path.exists():
            raise AppError("INVALID_INPUT", f"Local media file not found: {path}", 400)
        mime_type, _ = mimetypes.guess_type(str(path))
        if media_kind and (not mime_type or not mime_type.startswith(f"{media_kind}/")):
            raise AppError(
                "INVALID_INPUT",
                f"Unsupported {media_kind} file type: {path} (mime={mime_type})",
                400,
            )
        mime_type = mime_type or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    def download_url(self, url: str, save_path: str | Path) -> Path:
        target = Path(save_path)
        ensure_dir(target.parent)
        tmp = target.with_suffix(target.suffix + ".part")
        with self.http_session().get(url, stream=True, timeout=self.download_timeout) as response:
            response.raise_for_status()
            with tmp.open("wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file.write(chunk)
        tmp.replace(target)
        return target

    def validate_inputs(self, inputs: dict, params: dict) -> None:
        return None

    @abstractmethod
    def build_payload(self, inputs: dict, params: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def submit(self, payload: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def poll(self, task_id: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def download_outputs(self, response: dict, output_dir: str) -> list:
        raise NotImplementedError

    @abstractmethod
    def parse_artifacts(self, response: dict) -> list:
        raise NotImplementedError
