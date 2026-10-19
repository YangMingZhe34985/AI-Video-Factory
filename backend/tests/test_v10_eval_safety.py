"""V10 spend guard tests: no provider calls, credentials, or real database."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests

from scripts.v3_eval.safety import (
    API_BASE, CHAT_BASE, CHAT_URL, TEXT_MODEL, VISION_MODEL,
    CallMeter, EvaluationSafetyError, configure_environment,
)


def response(*, status=200, prompt=123, completion=7):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps({"id": "response-stub", "usage": {
        "prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion,
    }}).encode()
    return result


@pytest.fixture
def transport(tmp_path, monkeypatch):
    sent = []
    def fake_send(session, request, **kwargs):
        sent.append((request, kwargs, [adapter.max_retries.total for adapter in session.adapters.values()]))
        return response()
    monkeypatch.setattr(requests.Session, "send", fake_send)
    meter = CallMeter(tmp_path).install()
    yield meter, sent
    meter.close()


def request(model=TEXT_MODEL, **values):
    session = requests.Session()
    session.trust_env = False
    return session.post(CHAT_URL, json={"model": model, "messages": [{"role": "user", "content": "stub"}], **values})


def test_environment_does_not_parse_database_or_redis_values(tmp_path, monkeypatch):
    import dotenv
    import dotenv.main
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_bytes(b'DATABASE_URL=\xff${RAISE_IF_PARSED}\nREDIS_URL=\xff\nDASHSCOPE_API_KEY="stub-key"\n')
    for name in ("DASHSCOPE_API_KEY", "DASHSCOPE_API_BASE_URL", "DASHSCOPE_OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "mysql://do-not-use")
    monkeypatch.setenv("REDIS_URL", "redis://do-not-use")
    # Register restoration for both dotenv references and every changed env key.
    monkeypatch.setattr(dotenv, "load_dotenv", dotenv.load_dotenv)
    monkeypatch.setattr(dotenv.main, "load_dotenv", dotenv.main.load_dotenv)
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *a, **k: pytest.fail("must not parse entire dotenv"))
    import os
    old = dict(os.environ)
    try:
        values = configure_environment(root, tmp_path / "isolated")
        assert values["DATABASE_URL"].startswith("sqlite:///")
        assert values["REDIS_URL"] == "redis://127.0.0.1:1/0"
        assert values["DASHSCOPE_API_KEY"] == "stub-key"
        assert values["EVAL_IMAGE_CAP"] == "0"
        assert dotenv.load_dotenv(root / ".env") is False
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_ambient_credentials_win_without_opening_dotenv(tmp_path, monkeypatch):
    import dotenv
    import dotenv.main
    monkeypatch.setattr(dotenv, "load_dotenv", dotenv.load_dotenv)
    monkeypatch.setattr(dotenv.main, "load_dotenv", dotenv.main.load_dotenv)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "stub")
    monkeypatch.setenv("DASHSCOPE_API_BASE_URL", API_BASE)
    monkeypatch.setenv("DASHSCOPE_OPENAI_BASE_URL", CHAT_BASE)
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("dotenv must not be opened"))
    import os
    old = dict(os.environ)
    try:
        configure_environment(tmp_path / "repo", tmp_path / "work")
    finally:
        os.environ.clear()
        os.environ.update(old)


@pytest.mark.parametrize("model", [TEXT_MODEL, VISION_MODEL])
def test_approved_request_counted_with_usage_and_no_retry(transport, model):
    meter, sent = transport
    meter.set_label("c1-unit")
    assert request(model).status_code == 200
    assert len(sent) == 1
    assert sent[0][1]["allow_redirects"] is False
    assert set(sent[0][2]) == {0}
    assert meter.rows()[0]["label"] == "c1-unit"
    assert meter.rows()[0]["status"] == "success"
    snapshot = meter.snapshot()
    assert snapshot["real_calls"] == 1
    assert snapshot["input_tokens_sum"] == snapshot["input_tokens_max"] == 123
    assert snapshot["output_tokens_sum"] == 7
    assert snapshot["real_image_calls"] == snapshot["real_video_calls"] == 0
    assert "messages" not in meter.path.read_bytes().decode("latin1")
    assert "stub-key" not in meter.path.read_bytes().decode("latin1")


@pytest.mark.parametrize("url", [
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    "https://dashscope.aliyuncs.com/api/v1/uploads",
    CHAT_URL + "?redirect=1", "https://example.invalid/chat/completions", "http://127.0.0.1:3306/",
])
def test_unapproved_endpoints_never_reach_transport(transport, url):
    meter, sent = transport
    with pytest.raises(EvaluationSafetyError, match="endpoint"):
        requests.post(url, json={"model": TEXT_MODEL})
    assert not sent
    assert meter.snapshot()["real_calls"] == 0


@pytest.mark.parametrize("model", ["wan3.0-video", "qwen-image-3.0", "deepseek-v4-flash", "gpt-4"])
def test_unapproved_models_never_reach_transport(transport, model):
    meter, sent = transport
    with pytest.raises(EvaluationSafetyError, match="model"):
        request(model)
    assert not sent
    assert not meter.rows()


def test_stream_proxy_and_disabled_tls_are_blocked(transport):
    meter, sent = transport
    with pytest.raises(EvaluationSafetyError, match="non-streaming"):
        request(stream=True)
    payload = {"model": TEXT_MODEL, "messages": []}
    with pytest.raises(EvaluationSafetyError, match="proxy"):
        requests.post(CHAT_URL, json=payload, proxies={"https": "http://example.invalid"})
    session = requests.Session()
    session.trust_env = False
    with pytest.raises(EvaluationSafetyError, match="TLS"):
        session.post(CHAT_URL, json=payload, verify=False)
    assert not sent
    assert not meter.rows()


def test_cap_is_atomic_across_connections_and_cannot_be_raised(tmp_path):
    first = CallMeter(tmp_path, max_calls=3)
    second = CallMeter(tmp_path, max_calls=800)
    def attempt(index):
        try:
            return second._reserve(TEXT_MODEL, f"hash-{index}")
        except EvaluationSafetyError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(attempt, range(12)))
    assert sum(value is not None for value in admitted) == 3
    assert first.snapshot()["real_calls"] == first.snapshot()["call_limit"] == 3


def test_reserved_or_unknown_call_survives_recovery_without_resend(tmp_path, monkeypatch):
    attempted = []
    def fail(session, prepared, **kwargs):
        attempted.append(True)
        raise requests.Timeout("do not persist private details")
    monkeypatch.setattr(requests.Session, "send", fail)
    first = CallMeter(tmp_path).install()
    try:
        with pytest.raises(requests.Timeout):
            request()
        assert first.rows()[0]["status"] == "unknown"
    finally:
        first.close()
    recovered = CallMeter(tmp_path).install()
    try:
        with pytest.raises(EvaluationSafetyError, match="ambiguous"):
            request()
        assert len(attempted) == 1
        assert recovered.snapshot()["real_calls"] == 1
        reserved = recovered._reserve(TEXT_MODEL, "interrupted-before-send")
        assert reserved == 2
        with pytest.raises(EvaluationSafetyError, match="ambiguous"):
            CallMeter(tmp_path)._reserve(TEXT_MODEL, "interrupted-before-send")
    finally:
        recovered.close()


def test_media_adapters_and_uploads_are_blocked(transport, monkeypatch):
    from app.adapters.dashscope_multimodal_image import DashScopeMultimodalSyncAdapter
    from app.adapters.dashscope_image import DashScopeImageAdapter
    from app.adapters.dashscope_qwen_image import DashScopeQwenImageAdapter
    from app.adapters.dashscope_i2v import DashScopeI2VAdapter
    from app.adapters.dashscope_wan3 import DashScopeWan3Adapter
    meter, sent = transport
    monkeypatch.setenv("MODEL_ADAPTER_MODE", "real")
    for cls in (DashScopeMultimodalSyncAdapter, DashScopeImageAdapter, DashScopeQwenImageAdapter,
                DashScopeI2VAdapter, DashScopeWan3Adapter):
        with pytest.raises(EvaluationSafetyError, match="forbidden"):
            cls().submit({})
    with pytest.raises(EvaluationSafetyError, match="uploads"):
        DashScopeImageAdapter().upload_local_file_get_oss_url("unused", "unused")
    assert meter.snapshot()["blocked_media_attempts"] == 6
    assert not sent


def test_mock_media_bypass_has_no_provider_call(transport, monkeypatch):
    from app.adapters.dashscope_i2v import DashScopeI2VAdapter
    meter, sent = transport
    monkeypatch.setenv("MODEL_ADAPTER_MODE", "mock")
    monkeypatch.setenv("EVAL_MOCK_MEDIA", "1")
    assert DashScopeI2VAdapter().submit({})["status"] == "submitted"
    assert not sent
    assert meter.snapshot()["real_calls"] == 0


@pytest.mark.parametrize("limit", [-1, 801, True])
def test_invalid_or_higher_cap_rejected(tmp_path, limit):
    with pytest.raises(EvaluationSafetyError):
        CallMeter(tmp_path, max_calls=limit)
