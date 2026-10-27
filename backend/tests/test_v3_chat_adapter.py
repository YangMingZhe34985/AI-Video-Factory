"""Function-call protocol tests with stub completions and socket-free transport."""

import io
import json
from types import MethodType, SimpleNamespace

import pytest
import requests
from flask import Flask
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import NewConnectionError, ProtocolError
from urllib3.response import HTTPResponse
from urllib3.util.retry import Retry

from app.adapters.qwen_chat import QwenChatAdapter
from app.api import AppError


# Keep Requests' redirect handling available for the socket-free transport
# tests. The suite's network blocker remains active for all other sessions.
SESSION_SEND = requests.Session.send
TOOLS = [{"type": "function", "function": {
    "name": "list_models", "description": "List model capabilities",
    "parameters": {"type": "object", "properties": {"mode": {"type": "string"}}},
}}]


@pytest.fixture
def protocol_app():
    app = Flask(__name__)
    app.config.update(MODEL_ADAPTER_MODE="real", DASHSCOPE_API_KEY="stub-only",
                      DEEPSEEK_API_KEY="stub-deepseek", AGENT_WORKER_ACTIVE=False, MQ_WORKER_ACTIVE=False)
    with app.app_context():
        yield app


def make_adapter(provider="dashscope", defaults=None):
    return QwenChatAdapter(SimpleNamespace(model_id="deepseek-v4.1-flash", provider=provider,
                                           default_params=defaults or {}))


def function_call(call_id="call-1", name="list_models", arguments='{"mode":"t2i"}'):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def completion(*calls, content=None, usage=None):
    return {"id": "stub-completion", "choices": [{"message": {"content": content, "tool_calls": list(calls)}}],
            "usage": usage if usage is not None else {"prompt_tokens": 30, "completion_tokens": 12}}


def submit_stub(adapter, monkeypatch, response, **inputs):
    requests_seen = []

    def request(method, url, **kwargs):
        requests_seen.append((method, url, kwargs))
        return response

    monkeypatch.setattr(adapter, "request_json", request)
    payload = adapter.build_payload({"messages": [{"role": "user", "content": "Plan it"}],
                                     "tools": TOOLS, **inputs}, {})
    return adapter.submit(payload), requests_seen


@pytest.mark.parametrize("provider,url,key", [
    ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "stub-only"),
    ("deepseek", "https://api.deepseek.com/v1/chat/completions", "stub-deepseek"),
])
def test_tools_messages_and_choice_pass_through(protocol_app, monkeypatch, provider, url, key):
    adapter = make_adapter(provider, {"temperature": 0.4, "enable_thinking": False})
    messages = [{"role": "assistant", "content": None, "tool_calls": [function_call()]},
                {"role": "tool", "tool_call_id": "call-1", "content": '{"models":[]}'}]
    choice = {"type": "function", "function": {"name": "list_models"}}
    response, seen = submit_stub(adapter, monkeypatch, completion(function_call()),
                                 messages=messages, tool_choice=choice)
    assert len(seen) == 1
    method, actual_url, request = seen[0]
    assert (method, actual_url) == ("POST", url)
    assert request["headers"] == {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    assert request["json"]["messages"] == messages
    assert request["json"]["tools"] == TOOLS
    assert request["json"]["tool_choice"] == choice
    assert request["json"]["temperature"] == 0.4
    assert request["json"]["enable_thinking"] is False
    assert "_expect_json" not in request["json"]
    assert request["no_retry"] is True
    assert response["tool_calls"] == [{"id": "call-1", "name": "list_models", "arguments": {"mode": "t2i"}}]


def test_params_tools_and_input_precedence(protocol_app):
    adapter = make_adapter()
    payload = adapter.build_payload({"user_prompt": "Plan"}, {"tools": TOOLS, "tool_choice": "auto"})
    assert payload["tools"] == TOOLS and payload["tool_choice"] == "auto"
    payload = adapter.build_payload({"user_prompt": "Plan", "tools": [], "tool_choice": "none"},
                                    {"tools": TOOLS, "tool_choice": "auto"})
    assert payload["tools"] == [] and payload["tool_choice"] == "none"


def test_multiple_tool_calls_preserve_order_and_null_content(protocol_app, monkeypatch):
    raw = completion(function_call(), function_call("call-2", "estimate_cost", '{"nodes":[{"count":2}]}'))
    response, seen = submit_stub(make_adapter(), monkeypatch, raw, expect_json=True)
    assert response == {"provider_task_id": "stub-completion", "status": "success", "content": None,
                        "json": None, "raw_response": raw, "finish_reason": None,
                        "tool_calls": [{"id": "call-1", "name": "list_models", "arguments": {"mode": "t2i"}},
                                       {"id": "call-2", "name": "estimate_cost", "arguments": {"nodes": [{"count": 2}]}}],
                        "usage": {"prompt_tokens": 30, "completion_tokens": 12}}
    assert len(seen) == 1


@pytest.mark.parametrize("content", [None, "  Ready to review  ", [{"type": "text", "text": "Ready"}]])
def test_text_only_function_turn_and_usage(protocol_app, monkeypatch, content):
    response, _ = submit_stub(make_adapter(), monkeypatch, completion(content=content), tools=[])
    assert response["tool_calls"] == []
    assert response["content"] == (None if content is None else "Ready" if isinstance(content, list) else content.strip())
    assert response["usage"] == {"prompt_tokens": 30, "completion_tokens": 12}


@pytest.mark.parametrize("arguments", [
    "{broken", "[]", "null", "42", '"object"', "true", None, {}, "",
    '{"cost":NaN}', '{"cost":Infinity}',
])
def test_bad_arguments_return_correction_error_without_resubmit(protocol_app, monkeypatch, arguments):
    response, seen = submit_stub(make_adapter(), monkeypatch, completion(function_call(arguments=arguments)),
                                 expect_json=True)
    assert response["tool_calls"] == []
    error = response["tool_call_errors"][0]
    assert error["code"] == "INVALID_TOOL_ARGUMENTS"
    assert error["index"] == 0 and error["id"] == "call-1" and error["name"] == "list_models"
    assert error["arguments"] == arguments and error["message"]
    assert response["usage"] == {"prompt_tokens": 30, "completion_tokens": 12}
    assert len(seen) == 1


@pytest.mark.parametrize("call", [None, {}, {"id": "bad", "type": "custom", "function": {}},
                                   function_call(call_id=""), function_call(name=" ")])
def test_malformed_function_call_is_not_silently_ignored(protocol_app, monkeypatch, call):
    response, _ = submit_stub(make_adapter(), monkeypatch, completion(call))
    assert response["tool_calls"] == []
    assert response["tool_call_errors"][0]["code"] == "INVALID_TOOL_CALL"


def test_mixed_valid_invalid_and_duplicate_calls(protocol_app, monkeypatch):
    response, _ = submit_stub(make_adapter(), monkeypatch,
                              completion(function_call(), function_call("broken", arguments="[]"),
                                         function_call("call-1"), function_call("last", arguments="{}")))
    assert [call["id"] for call in response["tool_calls"]] == ["call-1", "last"]
    assert [(error["index"], error["code"]) for error in response["tool_call_errors"]] == [
        (1, "INVALID_TOOL_ARGUMENTS"), (2, "INVALID_TOOL_CALL")]


def test_non_array_calls_report_error(protocol_app, monkeypatch):
    raw = completion()
    raw["choices"][0]["message"]["tool_calls"] = {"function": "bad"}
    response, _ = submit_stub(make_adapter(), monkeypatch, raw)
    assert response["tool_calls"] == []
    assert response["tool_call_errors"][0]["code"] == "INVALID_TOOL_CALL"


@pytest.mark.parametrize("usage", [
    None, {}, "invalid", {"prompt_tokens": 30}, {"completion_tokens": 12},
    {"prompt_tokens": -1, "completion_tokens": 12},
    {"prompt_tokens": 30, "completion_tokens": -1},
    {"prompt_tokens": False, "completion_tokens": 12},
    {"prompt_tokens": 30, "completion_tokens": True},
    {"prompt_tokens": "30", "completion_tokens": 12},
    {"prompt_tokens": 30, "completion_tokens": 2.5},
    {"prompt_tokens": float("nan"), "completion_tokens": 12},
    {"prompt_tokens": 30, "completion_tokens": float("inf")},
])
def test_invalid_or_incomplete_usage_remains_unknown(protocol_app, monkeypatch, usage):
    raw = completion(content="Done")
    raw["usage"] = usage
    response, _ = submit_stub(make_adapter(), monkeypatch, raw)
    assert response["usage"] is None


def test_missing_usage_remains_unknown(protocol_app, monkeypatch):
    raw = completion(content="Done")
    raw.pop("usage")
    response, _ = submit_stub(make_adapter(), monkeypatch, raw)
    assert response["usage"] is None


def test_explicit_zero_usage_is_not_unknown(protocol_app, monkeypatch):
    response, _ = submit_stub(make_adapter(), monkeypatch,
                              completion(content="Done", usage={"prompt_tokens": 0, "completion_tokens": 0}))
    assert response["usage"] == {"prompt_tokens": 0, "completion_tokens": 0}


def test_no_tools_preserves_legacy_response(protocol_app, monkeypatch):
    adapter = make_adapter()
    raw = completion(content='  {"answer":"ok"}  ')
    monkeypatch.setattr(adapter, "_chat_completion", lambda payload: raw)
    response = adapter.submit(adapter.build_payload({"user_prompt": "JSON", "expect_json": True}, {}))
    assert response == {"provider_task_id": "stub-completion", "status": "success", "content": '{"answer":"ok"}',
                        "json": {"answer": "ok"}, "raw_response": raw}


def test_legacy_mock_behavior_is_unchanged(protocol_app):
    protocol_app.config["MODEL_ADAPTER_MODE"] = "mock"
    adapter = make_adapter()
    payload = adapter.build_payload({"user_prompt": "Hello"}, {})
    response = adapter.submit(payload)
    assert response["status"] == "submitted" and response["content"] == "Mock chat response"
    assert response["payload_echo"] == payload
    assert "tool_calls" not in response and "usage" not in response


def test_tools_do_not_retry_json_schema_fallback(protocol_app, monkeypatch):
    adapter = make_adapter()
    requests_seen = []

    def fail(*args, **kwargs):
        requests_seen.append(kwargs)
        raise AppError("API_TASK_FAILED", "Stub provider rejection", 400)

    monkeypatch.setattr(adapter, "request_json", fail)
    payload = adapter.build_payload({"messages": [{"role": "user", "content": "Plan"}], "tools": TOOLS,
                                     "response_schema": {"type": "object"}}, {})
    with pytest.raises(AppError):
        adapter.submit(payload)
    assert len(requests_seen) == 1
    assert requests_seen[0]["json"]["response_format"]["type"] == "json_schema"


def install_socket_free_transport(adapter, monkeypatch, responses):
    session = adapter.http_session()
    session.trust_env = False
    session.send = MethodType(SESSION_SEND, session)
    calls = []

    def make_request(_pool, _connection, method, url, **kwargs):
        calls.append((method, url))
        response = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(response, Exception):
            raise response
        status, headers, body = response
        return HTTPResponse(status=status, headers=headers, body=io.BytesIO(json.dumps(body).encode()),
                            preload_content=False)

    monkeypatch.setattr(HTTPConnectionPool, "_make_request", make_request)
    monkeypatch.setattr(Retry, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(adapter, "http_session", lambda: session)
    return session, calls


@pytest.mark.parametrize("response,expected_error", [
    ((503, {}, {"code": "Busy"}), AppError),
    ((429, {"Retry-After": "0"}, {"code": "RateLimit"}), AppError),
    ((307, {"Location": "https://provider.example.test/repeated"}, {}), AppError),
    (NewConnectionError(None, "Stub connection failure"), requests.exceptions.ConnectionError),
    (ProtocolError("Stub disconnected response"), requests.exceptions.ConnectionError),
])
def test_function_transport_never_retries_or_redirects(protocol_app, monkeypatch, response, expected_error):
    adapter = make_adapter()
    session, calls = install_socket_free_transport(adapter, monkeypatch, [response])
    payload = adapter.build_payload({"user_prompt": "Plan", "tools": TOOLS}, {})
    with pytest.raises(expected_error):
        adapter.submit(payload)
    assert len(calls) == 1
    assert all(transport.max_retries.total == 0 for transport in session.adapters.values())


def test_default_transport_retains_classic_retry_policy(protocol_app, monkeypatch):
    adapter = make_adapter()
    session, calls = install_socket_free_transport(adapter, monkeypatch,
                                                  [(503, {}, {"code": "Busy"}), (200, {}, {"answer": "ok"})])
    assert adapter.request_json("POST", "https://provider.example.test/chat", json={}) == {"answer": "ok"}
    assert len(calls) == 2
    assert all(transport.max_retries.total == 5 for transport in session.adapters.values())


@pytest.mark.parametrize("classic", [False, True])
def test_worker_json_fallback_only_for_classic_workflow_nodes(protocol_app, monkeypatch, classic):
    from app.plans.workflow import classic_submit
    protocol_app.config["AGENT_WORKER_ACTIVE"] = True
    adapter = make_adapter()
    requests_seen = []

    def reject_schema(*args, **kwargs):
        requests_seen.append(kwargs["json"].get("response_format", {}).get("type"))
        if kwargs["json"].get("response_format"):
            raise AppError("API_TASK_FAILED", "This response_format type is unavailable now", 400)
        return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    monkeypatch.setattr(adapter, "request_json", reject_schema)
    payload = adapter.build_payload({"user_prompt": "Rewrite", "response_schema": {"type": "object"}}, {})
    if not classic:
        with pytest.raises(AppError):
            adapter.submit(payload)
        assert requests_seen == ["json_schema"]  # Agent workers never add implicit paid calls.
    else:
        classic_submit(adapter, payload)
        assert requests_seen == ["json_schema", "json_object", None]  # Classic node semantics.
