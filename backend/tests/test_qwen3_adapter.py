"""New protocols against stub HTTP only, never paid requests."""
import base64
import io
from types import SimpleNamespace

import pytest
from flask import Flask
from PIL import Image
from pydantic import BaseModel

from app.adapters.dashscope_qwen_image import DashScopeQwenImageAdapter
from app.adapters.qwen_chat import QwenChatAdapter
from app.api import AppError
from app.services.generation_outputs import output_slots


def catalog(model_id="qwen-image-3.0", **kwargs):
    return SimpleNamespace(model_id=model_id, provider="dashscope", default_params={}, **kwargs)


@pytest.fixture
def protocol_app():
    app = Flask(__name__)
    app.config.update(MODEL_ADAPTER_MODE="real", DASHSCOPE_API_KEY="stub-only", AGENT_WORKER_ACTIVE=True)
    with app.app_context():
        yield app


def picture(tmp_path):
    path = tmp_path / "reference.png"
    Image.new("RGB", (256, 256), (40, 80, 120)).save(path)
    return path


@pytest.mark.parametrize("model_id", ["qwen-image-3.0", "qwen-image-3.0-pro"])
def test_image_protocol_and_legacy_submit_url(protocol_app, monkeypatch, model_id):
    adapter = DashScopeQwenImageAdapter(catalog(model_id))
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {"output": {"task_id": "stub-task"}}
    monkeypatch.setattr(adapter, "request_json", request)
    payload = adapter.build_payload({"prompt": "Cat", "prompt_version": "v001"},
                                    {"n": 2, "size": "1536*1024", "enable_thinking": False})
    assert payload["input"] == {"messages": [{"role": "user", "content": [{"text": "Cat"}]}]}
    assert "enable_interleave" not in payload["parameters"]
    assert adapter.submit(payload)["provider_task_id"] == "stub-task"
    assert calls[0][:2] == ("POST", "https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation")
    assert calls[0][2]["headers"] == {"Authorization": "Bearer stub-only", "Content-Type": "application/json",
                                      "X-DashScope-Async": "enable"}
    assert calls[0][2]["json"]["model"] == model_id


def test_local_images_inline_and_classic_primary_reference(protocol_app, tmp_path):
    adapter = DashScopeQwenImageAdapter(catalog())
    path = picture(tmp_path)
    url = "https://media.example.test/second.png"
    payload = adapter.build_payload({"prompt": "Keep both", "source_images": [str(path), url]}, {})
    content = payload["input"]["messages"][0]["content"]
    assert base64.b64decode(content[0]["image"].split(",", 1)[1]) == path.read_bytes()
    assert content[1:] == [{"image": url}, {"text": "Keep both"}]
    classic = adapter.build_payload({"prompt": "Suit", "source_image": str(path), "source_images": [{"path": "annotation"}]}, {})
    assert len(classic["input"]["messages"][0]["content"]) == 2


@pytest.mark.parametrize("params", [
    {"size": "1*1"}, {"size": "2049*2049"}, {"size": "8192*64"}, {"size": "nan"},
    {"n": True}, {"n": 7}, {"n": 1.2}, {"seed": -1}, {"seed": True}, {"seed": 2147483648},
    {"watermark": "false"}, {"enable_interleave": True}, {"model_id": "hidden"},
    {"prompt_extend_mode": "unknown"}, {"negative_prompt": []},
])
def test_invalid_params_rejected_locally(protocol_app, params):
    with pytest.raises(AppError) as exc:
        DashScopeQwenImageAdapter(catalog()).build_payload({"prompt": "Cat"}, params)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("references", [
    ["https://example.test/x.png"] * 4, [""], ["data:image/png;base64,bad!"], ["oss://bucket/image.png"],
])
def test_invalid_references(protocol_app, references):
    with pytest.raises(AppError):
        DashScopeQwenImageAdapter(catalog()).build_payload({"prompt": "Cat", "source_images": references}, {})


def test_image_limits_and_text_only_extension(protocol_app, tmp_path):
    adapter = DashScopeQwenImageAdapter(catalog())
    with pytest.raises(AppError):
        adapter.build_payload({"prompt": "Suit", "source_image": str(picture(tmp_path))}, {"prompt_extend_mode": "agent"})
    assert adapter.build_payload({"prompt": "Poster"}, {"prompt_extend_mode": "agent"})["parameters"]["prompt_extend_mode"] == "agent"
    path = tmp_path / "bad.png"
    path.write_bytes(b"not an image")
    for value in (str(path), "data:image/png;base64," + "a" * (adapter.MAX_IMAGE_BYTES * 4 // 3 + 256)):
        with pytest.raises(AppError):
            adapter.build_payload({"prompt": "Suit", "source_image": value}, {})


def test_poll_and_download_every_image(protocol_app, monkeypatch, tmp_path):
    adapter = DashScopeQwenImageAdapter(catalog())
    urls = [f"https://output.example.test/{i}.png" for i in range(3)]
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url))
        return {"output": {"task_status": "SUCCEEDED", "choices": [{"message": {"content": [{"image": u} for u in urls]}}]}}
    monkeypatch.setattr(adapter, "request_json", request)
    response = adapter.poll("stub-task")
    assert calls == [("GET", "https://dashscope.aliyuncs.com/api/v1/tasks/stub-task")]
    assert response["result_urls"] == urls
    task = SimpleNamespace(expected_artifact_path="images/out.png", queue_data={}, request_payload={"parameters": {"n": 3}})
    slots = output_slots(task, response, "first_frame_image")
    downloaded = []
    def download(url, path):
        downloaded.append(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stub-download")
    monkeypatch.setattr(adapter, "download_url", download)
    for relative, item in slots:
        item["expected_output_path"] = str(tmp_path / relative)
        assert len(adapter.download_outputs(item, str(tmp_path))) == 1
    assert downloaded == urls
    assert len(list((tmp_path / "images").iterdir())) == 3
    with pytest.raises(AppError):
        output_slots(task, {"result_urls": urls[:1]}, "first_frame_image")


def test_configured_legacy_base(protocol_app):
    protocol_app.config["DASHSCOPE_API_BASE_URL"] = "https://dashscope-intl.aliyuncs.com/"
    adapter = DashScopeQwenImageAdapter(catalog())
    assert adapter.create_url().startswith("https://dashscope-intl.aliyuncs.com/api/v1/")
    assert adapter.task_url("a") == "https://dashscope-intl.aliyuncs.com/api/v1/tasks/a"


def test_bailian_deepseek_uses_dashscope_and_defaults(protocol_app, monkeypatch):
    model = catalog("deepseek-v4.1-flash")
    model.default_params = {"enable_thinking": False, "temperature": 0.2}
    adapter = QwenChatAdapter(model)
    protocol_app.config["DEEPSEEK_API_KEY"] = "must-not-be-used"
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {"id": "stub-chat", "choices": [{"message": {"content": '{"answer":"ok"}'}}]}
    monkeypatch.setattr(adapter, "request_json", request)
    payload = adapter.build_payload({"messages": [{"role": "user", "content": "Return JSON"}], "expect_json": True}, {})
    assert payload["enable_thinking"] is False
    assert adapter.submit(payload)["json"] == {"answer": "ok"}
    assert calls[0][1] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert calls[0][2]["headers"]["Authorization"] == "Bearer stub-only"
    assert adapter.build_payload({"user_prompt": "Text"}, {"enable_thinking": True})["enable_thinking"] is True


def test_structured_call_model_defaults_and_no_fallback(protocol_app, monkeypatch):
    from app.agent import planning
    class Data(BaseModel):
        text: str
    class Result(BaseModel):
        answer: str
    model = catalog("deepseek-v4.1-flash", adapter_name="qwen_chat")
    model.default_params = {"enable_thinking": False}
    adapter = QwenChatAdapter(model)
    monkeypatch.setattr(planning, "resolve_agent_model", lambda role: model)
    monkeypatch.setattr(planning, "get_adapter", lambda *a, **k: adapter)
    calls = []
    def request(method, url, **kwargs):
        calls.append(kwargs["json"])
        return {"choices": [{"message": {"content": '{"answer":"ok"}'}}]}
    monkeypatch.setattr(adapter, "request_json", request)
    assert planning.structured_call("Return JSON", Data(text="Cat"), Result, {}, role="intake").answer == "ok"
    assert calls[0]["enable_thinking"] is False
    assert calls[0]["response_format"] == {"type": "json_object"}
    def fail(*args, **kwargs):
        calls.append(kwargs["json"])
        raise AppError("API_TASK_FAILED", "Stub provider error", 400)
    monkeypatch.setattr(adapter, "request_json", fail)
    with pytest.raises(AppError):
        planning.structured_call("JSON", Data(text="Cat"), Result, {}, role="intake")
    assert len(calls) == 2


@pytest.mark.parametrize("inline", [False, True])
def test_truncated_jpeg_rejected_before_paid_submit(protocol_app, tmp_path, inline):
    stream = io.BytesIO()
    Image.new("RGB", (256, 256), (40, 80, 120)).save(stream, format="JPEG")
    body = stream.getvalue()[:-100]
    path = tmp_path / "truncated.jpg"
    path.write_bytes(body)
    source = "data:image/jpeg;base64," + base64.b64encode(body).decode("ascii") if inline else str(path)
    with pytest.raises(AppError, match="Invalid Qwen reference image"):
        DashScopeQwenImageAdapter(catalog()).build_payload({"prompt": "Suit", "source_image": source}, {})
