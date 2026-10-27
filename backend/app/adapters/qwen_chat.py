import json
from contextvars import ContextVar
from typing import Any

from app.adapters.mock import MockChatAdapter
from app.api import AppError


# Classic-path workflow Jobs keep the classic JSON-mode fallback inside Agent/MQ workers (D-066).
classic_json_fallback = ContextVar("classic_json_fallback", default=False)


class QwenChatAdapter(MockChatAdapter):
    """OpenAI-compatible chat transport for DashScope and legacy DeepSeek."""

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
        params = {**(getattr(self.model, "default_params", None) or {}), **params}
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
        for key in ("tools", "tool_choice"):
            value = inputs[key] if key in inputs else params.get(key)
            if value is not None:
                payload[key] = value
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
        if "tools" in request_payload or "tool_choice" in request_payload:
            turn = self._extract_completion_turn(completion)
            parsed = None
            if expect_json and not turn["tool_calls"] and not turn.get("tool_call_errors"):
                parsed = self._parse_json_object(turn["content"] or "")
            return {
                "provider_task_id": completion.get("id"),
                "status": "success",
                "json": parsed,
                "raw_response": completion,
                **turn,
            }
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
        if "tools" in payload or "tool_choice" in payload:
            # A function turn is billed and replayed by the tool ledger. Only
            # the Agent loop may request a new turn after a completed response.
            return self.request_json("POST", url, headers=headers, json=payload, timeout=timeout, no_retry=True)
        try:
            return self.request_json("POST", url, headers=headers, json=payload, timeout=timeout)
        except AppError:
            if ((self.config("AGENT_WORKER_ACTIVE", False) or self.config("MQ_WORKER_ACTIVE", False))
                    and not classic_json_fallback.get()):
                # No implicit additional paid planning calls on schema errors.
                raise
            if payload.get("response_format", {}).get("type") == "json_schema":
                fallback = dict(payload)
                fallback["response_format"] = {"type": "json_object"}
                try:
                    return self.request_json("POST", url, headers=headers, json=fallback, timeout=timeout)
                except AppError:
                    fallback.pop("response_format", None)
                    return self.request_json("POST", url, headers=headers, json=fallback, timeout=timeout)
            raise

    @classmethod
    def _extract_completion_turn(cls, completion: dict) -> dict:
        choices = completion.get("choices") or []
        message = ((choices[0] or {}).get("message") or {}) if choices else {}
        result = {
            "content": cls._extract_completion_text(completion) if message.get("content") is not None else None,
            "tool_calls": [],
            "usage": cls._extract_usage(completion),
            "finish_reason": (choices[0] or {}).get("finish_reason") if choices else None,
        }
        calls = message.get("tool_calls")
        if result["finish_reason"] == "length":
            # Provider truncation is not a JSON-format mistake. Reject the
            # entire batch, preserving even apparently valid sibling evidence.
            items = calls if isinstance(calls, list) and calls else [None]
            result["tool_call_errors"] = [
                cls._tool_call_error(index, call, "AGENT_OUTPUT_TRUNCATED",
                                     "Provider output reached its token limit; no call from this turn may execute")
                for index, call in enumerate(items)]
            if calls is not None and not isinstance(calls, list):
                result["tool_call_errors"][0]["arguments"] = calls
            return result
        if calls is None:
            return result
        errors = []
        if not isinstance(calls, list):
            errors.append(cls._tool_call_error(0, None, "INVALID_TOOL_CALL", "tool_calls must be an array"))
            calls = []
        seen_ids = set()
        for index, call in enumerate(calls):
            function = call.get("function") if isinstance(call, dict) else None
            call_id = call.get("id") if isinstance(call, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            if (not isinstance(call, dict) or call.get("type") != "function"
                    or not isinstance(function, dict)
                    or not isinstance(call_id, str) or not call_id.strip()
                    or not isinstance(name, str) or not name.strip()):
                errors.append(cls._tool_call_error(index, call, "INVALID_TOOL_CALL",
                                                  "Each function call needs a non-empty id and function.name"))
                continue
            if call_id in seen_ids:
                errors.append(cls._tool_call_error(index, call, "INVALID_TOOL_CALL", "Duplicate tool call id"))
                continue
            seen_ids.add(call_id)
            raw_arguments = function.get("arguments")
            try:
                if not isinstance(raw_arguments, str):
                    raise ValueError("function.arguments must be a JSON object encoded as a string")
                arguments = json.loads(raw_arguments, parse_constant=cls._reject_json_constant)
                if not isinstance(arguments, dict):
                    raise ValueError("function.arguments must decode to a JSON object")
            except (ValueError, RecursionError) as error:
                errors.append(cls._tool_call_error(index, call, "INVALID_TOOL_ARGUMENTS", str(error)))
                continue
            result["tool_calls"].append({"id": call_id, "name": name, "arguments": arguments})
        if errors:
            result["tool_call_errors"] = errors
        return result

    @staticmethod
    def _reject_json_constant(value: str):
        raise ValueError(f"Invalid JSON constant: {value}")

    @staticmethod
    def _tool_call_error(index: int, call, code: str, message: str) -> dict:
        call = call if isinstance(call, dict) else {}
        function = call.get("function")
        function = function if isinstance(function, dict) else {}
        return {
            "index": index,
            "id": call.get("id") if isinstance(call.get("id"), str) else None,
            "name": function.get("name") if isinstance(function.get("name"), str) else None,
            "code": code,
            "message": message,
            "arguments": function.get("arguments"),
        }

    @staticmethod
    def _extract_usage(completion: dict) -> dict | None:
        usage = completion.get("usage")
        if not isinstance(usage, dict):
            return None
        result = {}
        for key in ("prompt_tokens", "completion_tokens"):
            value = usage.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                # Unknown usage must retain the reservation, not settle a paid
                # response as zero tokens and refund the planning budget.
                return None
            result[key] = value
        return result

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
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                start = cleaned.find("{")
                end = cleaned.rfind("}")
                if start < 0 or end <= start:
                    raise ValueError("Response does not contain a JSON object")
                data = json.loads(cleaned[start : end + 1])
            if not isinstance(data, dict):
                raise ValueError("Response JSON is not an object")
        except ValueError as error:
            # Parsing only occurs after a completed response. Callers may
            # repair its structure; transport failures never receive this flag.
            raise AppError("API_TASK_FAILED", "Qwen response did not contain a valid JSON object", 502,
                           payload={"content": text[:1000], "response_validation": True}) from error
        return data
