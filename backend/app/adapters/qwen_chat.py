import json
from typing import Any

from app.adapters.mock import MockChatAdapter
from app.api import AppError


class QwenChatAdapter(MockChatAdapter):
    """Qwen-compatible adapter shell.

    The MVP keeps behavior mocked while preserving a stable surface for adding
    DashScope chat calls in submit/poll/download_outputs later.
    """

    provider_name = "dashscope"

    def openai_base_url(self) -> str:
        if self.provider == "deepseek":
            return str(
                self.config("DEEPSEEK_OPENAI_BASE_URL", "https://api.deepseek.com/v1")
                or "https://api.deepseek.com/v1"
            ).rstrip("/")
        return str(
            self.config(
                "DASHSCOPE_OPENAI_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/")

    def api_key(self, required: bool = True) -> str:
        if self.provider == "deepseek":
            key = str(self.config("DEEPSEEK_API_KEY", "") or "")
            if required and not key:
                raise AppError(
                    "INVALID_INPUT",
                    "Missing DEEPSEEK_API_KEY for DeepSeek model adapter",
                    400,
                )
            return key
        return super().api_key(required=required)

    def build_payload(self, inputs: dict, params: dict) -> dict:
        if self.use_mock:
            return super().build_payload(inputs, params)
        self.validate_inputs(inputs, params)
        messages = inputs.get("messages")
        if not messages:
            messages = self._messages_from_inputs(inputs, params)
        schema = inputs.get("response_schema") or params.get("response_schema")
        expect_json = self._bool_option(
            inputs.get("expect_json", params.get("expect_json")),
            default=bool(schema),
        )
        payload = {
            "model": self.model_id,
            "temperature": params.get("temperature", 0.2),
            "messages": messages,
            "_expect_json": expect_json,
        }
        for key in ("enable_thinking", "top_p", "max_tokens"):
            if params.get(key) is not None:
                payload[key] = params[key]
        if schema and expect_json:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": inputs.get("schema_name") or params.get("schema_name") or "response",
                    "schema": schema,
                    "strict": True,
                },
            }
        return payload

    def submit(self, payload: dict) -> dict:
        if self.use_mock:
            return super().submit(payload)
        request_payload = dict(payload)
        expect_json = bool(request_payload.pop("_expect_json", request_payload.get("response_format")))
        completion = self._chat_completion(request_payload)
        text = self._extract_completion_text(completion)
        parsed = self._parse_json_object(text) if expect_json else None
        return {
            "provider_task_id": completion.get("id"),
            "status": "success",
            "content": text,
            "json": parsed,
            "raw_response": completion,
        }

    def poll(self, task_id: str) -> dict:
        return {"provider_task_id": task_id, "status": "success", "output_kind": "json"}

    def parse_artifacts(self, response: dict) -> list:
        return []

    def _messages_from_inputs(self, inputs: dict, params: dict) -> list[dict[str, Any]]:
        task = inputs.get("task")
        user_text = self._user_text_from_inputs(inputs)
        if task == "reverse_video_prompts":
            video_url = self._resolve_openai_media_url(inputs["source_video_path"], "video")
            return [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_url",
                            "video_url": {"url": video_url},
                            "fps": int(params.get("fps", 2)),
                        },
                        {"type": "text", "text": user_text},
                    ],
                },
            ]
        return [{"role": "user", "content": user_text}]

    @staticmethod
    def _user_text_from_inputs(inputs: dict) -> str:
        # The workflow prompt files are authored as the single instruction payload.
        # If legacy callers still pass system_prompt, send it as user text, not a system role.
        parts = [
            str(inputs.get("system_prompt") or "").strip(),
            str(inputs.get("user_prompt") or "").strip(),
        ]
        return "\n\n".join(part for part in parts if part)

    @staticmethod
    def _bool_option(value, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _resolve_openai_media_url(self, value: str, media_kind: str) -> str:
        raw = str(value).strip()
        if self.is_http_url(raw) or raw.lower().startswith("data:"):
            return raw
        if raw.lower().startswith("oss://"):
            raise AppError(
                "INVALID_INPUT",
                "OpenAI-compatible chat media input does not accept oss:// URLs",
                400,
            )
        return self.encode_local_file_as_data_url(raw, media_kind)

    def _chat_completion(self, payload: dict) -> dict:
        url = f"{self.openai_base_url()}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key()}",
            "Content-Type": "application/json",
        }
        timeout = (30, max(int(self.request_timeout), 180))
        try:
            return self.request_json("POST", url, headers=headers, json=payload, timeout=timeout)
        except AppError:
            if payload.get("response_format", {}).get("type") == "json_schema":
                fallback = dict(payload)
                fallback["response_format"] = {"type": "json_object"}
                try:
                    return self.request_json("POST", url, headers=headers, json=fallback, timeout=timeout)
                except AppError:
                    fallback.pop("response_format", None)
                    return self.request_json("POST", url, headers=headers, json=fallback, timeout=timeout)
            raise

    @staticmethod
    def _extract_completion_text(completion: dict) -> str:
        choices = completion.get("choices") or []
        if not choices:
            return ""
        content = ((choices[0] or {}).get("message") or {}).get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    parts.append(str(item["text"]))
            return "\n".join(parts).strip()
        return str(content or "").strip()

    @staticmethod
    def _parse_json_object(text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise AppError(
                    "API_TASK_FAILED",
                    "Qwen response did not contain a JSON object",
                    502,
                    payload={"content": text[:1000]},
                )
            data = json.loads(cleaned[start : end + 1])
        if not isinstance(data, dict):
            raise AppError("API_TASK_FAILED", "Qwen response JSON is not an object", 502)
        return data
