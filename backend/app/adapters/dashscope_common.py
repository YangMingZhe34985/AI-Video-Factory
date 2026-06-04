from pathlib import Path
from typing import Any

from app.adapters.base import BaseModelAdapter
from app.adapters.mock import MockAdapter
from app.api import AppError
from app.utils.files import ensure_dir


class DashScopeGenerationAdapter(MockAdapter):
    output_kind = "video"

    def dashscope_base_url(self) -> str:
        raw = str(
            self.config("DASHSCOPE_API_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")
            or "https://dashscope.aliyuncs.com/api/v1"
        ).rstrip("/")
        if not raw.endswith("/api/v1"):
            raw = f"{raw}/api/v1"
        return raw

    def create_url(self) -> str:
        raise NotImplementedError

    def task_url(self, task_id: str) -> str:
        return f"{self.dashscope_base_url()}/tasks/{task_id}"

    def submit(self, payload: dict) -> dict:
        if self.use_mock:
            return super().submit(payload)
        data = self.request_json(
            "POST",
            self.create_url(),
            headers={
                "Authorization": f"Bearer {self.api_key()}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
                "X-DashScope-OssResourceResolve": "enable",
            },
            json=payload,
        )
        task_id = ((data.get("output") or {}).get("task_id")) or ""
        if not task_id:
            raise AppError(
                "API_TASK_FAILED",
                "DashScope create response did not include output.task_id",
                502,
                payload={"response": data},
            )
        return {
            "provider_task_id": task_id,
            "status": "submitted",
            "request_id": data.get("request_id"),
            "raw_response": data,
        }

    def poll(self, task_id: str) -> dict:
        if self.use_mock:
            return super().poll(task_id)
        data = self.request_json(
            "GET",
            self.task_url(task_id),
            headers={"Authorization": f"Bearer {self.api_key()}"},
        )
        output = data.get("output") or {}
        vendor_status = str(output.get("task_status") or "UNKNOWN").upper()
        status = self._map_status(vendor_status)
        result_url = self._extract_image_url(data) if self.output_kind == "image" else self._extract_video_url(data)
        return {
            "provider_task_id": task_id,
            "status": status,
            "vendor_status": vendor_status,
            "output_kind": self.output_kind,
            "result_url": result_url,
            "raw_response": data,
            "error_message": data.get("message") or output.get("message") or output.get("code"),
        }

    def download_outputs(self, response: dict, output_dir: str) -> list:
        if self.use_mock:
            return super().download_outputs(response, output_dir)
        result_url = response.get("result_url")
        if not result_url:
            return []
        expected_path = response.get("expected_output_path")
        if expected_path:
            target = Path(expected_path)
        else:
            suffix = ".png" if self.output_kind == "image" else ".mp4"
            target = ensure_dir(output_dir) / f"output{suffix}"
        self.download_url(result_url, target)
        return [str(target)]

    def parse_artifacts(self, response: dict) -> list:
        result_url = response.get("result_url")
        return [{"url": result_url, "kind": self.output_kind}] if result_url else []

    def upload_local_file_get_oss_url(self, model_name: str, file_path: str | Path) -> str:
        raw = str(file_path).strip()
        if self.is_remote_resource(raw):
            return raw
        path = self.resolve_path(file_path)
        if not path.exists():
            raise AppError("INVALID_INPUT", f"Local file not found: {path}", 400)
        policy_response = self.request_json(
            "GET",
            f"{self.dashscope_base_url()}/uploads",
            headers={
                "Authorization": f"Bearer {self.api_key()}",
                "Content-Type": "application/json",
            },
            params={"action": "getPolicy", "model": model_name},
        )
        policy = policy_response.get("data") or {}
        key = f"{policy['upload_dir']}/{path.name}"
        with path.open("rb") as file:
            response = self.http_session().post(
                policy["upload_host"],
                files={
                    "OSSAccessKeyId": (None, policy["oss_access_key_id"]),
                    "Signature": (None, policy["signature"]),
                    "policy": (None, policy["policy"]),
                    "x-oss-object-acl": (None, policy["x_oss_object_acl"]),
                    "x-oss-forbid-overwrite": (None, policy["x_oss_forbid_overwrite"]),
                    "key": (None, key),
                    "success_action_status": (None, "200"),
                    "file": (path.name, file),
                },
                timeout=300,
            )
        if response.status_code >= 400:
            raise AppError(
                "API_TASK_FAILED",
                f"DashScope OSS upload failed: HTTP {response.status_code}",
                response.status_code,
                payload={"text": response.text},
            )
        bucket = policy.get("bucket") or policy.get("oss_bucket") or policy.get("bucket_name")
        if bucket:
            return f"oss://{bucket}/{key}"
        return f"oss://{key}"

    @staticmethod
    def _map_status(status: str) -> str:
        if status == "SUCCEEDED":
            return "success"
        if status == "CANCELED":
            return "cancelled"
        if status in {"FAILED", "UNKNOWN"}:
            return "failed"
        return "running"

    @staticmethod
    def _extract_video_url(task_data: dict[str, Any]) -> str | None:
        output = (task_data or {}).get("output") or {}
        for key in ("video_url", "url"):
            value = output.get(key)
            if isinstance(value, str) and value:
                return value
        video_urls = output.get("video_urls")
        if isinstance(video_urls, list):
            for url in video_urls:
                if isinstance(url, str) and url:
                    return url
        results = output.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    url = item.get("video_url") or item.get("url")
                    if isinstance(url, str) and url:
                        return url
        return None

    @staticmethod
    def _extract_image_url(task_data: dict[str, Any]) -> str | None:
        output = (task_data or {}).get("output") or {}
        choices = output.get("choices") or []
        if isinstance(choices, list):
            for choice in choices:
                message = (choice or {}).get("message") or {}
                for block in message.get("content") or []:
                    if isinstance(block, dict):
                        url = block.get("image") or block.get("url")
                        if isinstance(url, str) and url:
                            return url
        results = output.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    url = item.get("url") or item.get("image_url") or item.get("image")
                    if isinstance(url, str) and url:
                        return url
        return None
