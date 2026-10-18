"""Offline Wan 3 payload and async tests, with no application database."""
import os
import base64
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask
from PIL import Image

from app.adapters.dashscope_wan3 import DashScopeWan3Adapter
from app.api import AppError
from app.services.storage_service import MOCK_PNG_BYTES
from app.skills.tools.animate_shot import AnimateShotInput, validate_bridge


@pytest.fixture
def context(tmp_path):
    app = Flask(__name__)
    app.config.update(FFMPEG_BINARY=os.environ.get("FFMPEG_BINARY"), MODEL_ADAPTER_MODE="mock", DASHSCOPE_API_KEY="offline-test-key", STORAGE_ROOT=str(tmp_path),
                      DASHSCOPE_API_BASE_URL="https://dashscope.aliyuncs.com/api/v1", AGENT_ENABLE_KEYFRAME_BRIDGE=False)
    with app.app_context():
        yield app


def adapter(model_id="wan3.0-video"):
    return DashScopeWan3Adapter(SimpleNamespace(model_id=model_id, provider="dashscope", adapter_name="dashscope_wan3",
        capabilities={"modes": ["t2v", "i2v", "first_last_frame", "r2v"]}))


def picture(tmp_path, name="frame.png", size=(320, 240), mode="RGB"):
    path = tmp_path / name
    Image.new(mode, size, "white").save(path)
    return str(path)


def audio(tmp_path, name="voice.wav", seconds=2):
    path = tmp_path / name
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0" * int(8000 * seconds) * 2)
    return str(path)


@pytest.mark.parametrize("model_id", ["wan3.0-video", "wan3.0-video-prime"])
def test_text_protocol(context, model_id):
    payload = adapter(model_id).build_payload({"prompt": "猫跳舞", "prompt_version": 3, "negative_prompt": "模糊"},
        {"duration": 30, "resolution": "480P", "ratio": "21:9", "audio": False, "seed": -1, "n_outputs": 1})
    assert payload == {"model": model_id, "input": {"prompt": "猫跳舞\n\n避免出现：模糊"}, "parameters": {
        "duration": 30, "resolution": "480P", "ratio": "21:9", "audio": False, "seed": -1,
        "prompt_extend": True, "watermark": False}}


def test_first_last_and_reference_aliases(context, tmp_path):
    first, last = picture(tmp_path), picture(tmp_path, "last.jpg")
    payload = adapter().build_payload({"prompt": "猫跳舞", "first_frame_image": first, "last_frame_image": last}, {"duration": 2})
    assert payload["input"]["media"] == [{"type": "first_frame", "url": first}, {"type": "last_frame", "url": last}]
    reference = adapter().build_payload({"prompt": "参考图1", "reference_images": [first, last]}, {})
    assert [item["type"] for item in reference["input"]["media"]] == ["reference_image", "reference_image"]
    assert reference["parameters"]["duration"] == 5


def test_upload_only_after_all_validation(context, tmp_path, monkeypatch):
    value, uploads = adapter(), []
    monkeypatch.setattr(DashScopeWan3Adapter, "use_mock", property(lambda _: False))
    monkeypatch.setattr(value, "upload_local_file_get_oss_url", lambda model, path: uploads.append((model, path)) or "oss://offline/frame.png")
    path = picture(tmp_path)
    payload = value.build_payload({"prompt": "移动", "first_frame_image": path}, {})
    assert payload["input"]["media"][0]["url"] == "oss://offline/frame.png"
    assert uploads == [("wan3.0-video", path)]
    uploads.clear()
    with pytest.raises(AppError):
        value.build_payload({"prompt": "参考", "reference_images": [path, picture(tmp_path, "small.png", (1, 1))]}, {})
    assert uploads == []


@pytest.mark.parametrize("params", [{"duration": -1}, {"duration": 1}, {"duration": 31}, {"duration": 2.5},
    {"duration": True}, {"duration": "5"}, {"resolution": "4K"}, {"resolution": {}}, {"ratio": "2:1"},
    {"audio": "false"}, {"watermark": 0}, {"seed": -2}, {"seed": 2147483648}, {"n_outputs": 2},
    {"n_outputs": True}, {"size": "1280*720"}])
def test_invalid_parameters(context, params):
    with pytest.raises(AppError) as failure:
        adapter().build_payload({"prompt": "移动"}, params)
    assert failure.value.code == "INVALID_INPUT"


@pytest.mark.parametrize("inputs", [
    {"last_frame_image": "https://assets.example/last.png"},
    {"first_frame_image": "https://assets.example/first.png", "reference_images": ["https://assets.example/ref.png"]},
    {"first_frame_image": "https://assets.example/first.png", "driving_audio": "voice.wav"},
    {"media": [{"type": "first_frame", "url": "https://assets.example/1.png"}, {"type": "first_frame", "url": "https://assets.example/2.png"}]},
    {"reference_images": ["https://assets.example/frame.png"] * 11}, {"reference_images": "wrong"},
    {"media": [{"type": "file", "url": "a.md"}, {"type": "link", "url": "https://www.example.com"}]},
    {"media": [{"type": "driving_audio", "url": "a.wav"}]},
    {"media": [{"type": "reference_video", "url": "https://assets.example/video.mp4", "duration_sec": 0}]},
    {"media": [{"type": "reference_image", "url": "http://127.0.0.1/a.png"}]},
])
def test_invalid_combinations_and_spoofed_duration(context, inputs):
    with pytest.raises(AppError) as failure:
        adapter().build_payload({"prompt": "移动", **inputs}, {})
    assert failure.value.code == "INVALID_INPUT"


@pytest.mark.parametrize("url", ["https://assets.example/video.mp4", "oss://bucket/video.mp4"])
def test_remote_video_reference_explicitly_unavailable(context, url):
    with pytest.raises(AppError) as failure:
        adapter().build_payload({"prompt": "向后延长视频1", "media": [{"type": "reference_video", "url": url}]}, {"duration": 5})
    assert failure.value.code == "WAN3_MEDIA_UNSUPPORTED"


def test_local_audio_and_text_file(context, tmp_path):
    text = tmp_path / "story.md"
    text.write_text("角色在花园中相遇", encoding="utf-8")
    payload = adapter().build_payload({"prompt": "根据文件配合音频创作", "media": [
        {"type": "file", "url": str(text)}, {"type": "reference_audio", "url": audio(tmp_path)}]}, {})
    assert [item["type"] for item in payload["input"]["media"]] == ["file", "reference_audio"]
    with pytest.raises(AppError):
        adapter().build_payload({"prompt": "创作", "media": [{"type": "file", "url": str(text)}]}, {"prompt_extend": False})
    with pytest.raises(AppError):
        adapter().build_payload({"prompt": "创作", "media": [{"type": "reference_audio", "url": audio(tmp_path, "one.wav", 10)},
                                                              {"type": "reference_audio", "url": audio(tmp_path, "two.wav", 6)}]}, {})


@pytest.mark.parametrize("kind,url", [("reference_audio", "https://assets.example/audio.mp3"), ("file", "https://assets.example/story.pdf")])
def test_unverified_advanced_remote_media_unavailable(context, kind, url):
    with pytest.raises(AppError) as failure:
        adapter().build_payload({"prompt": "创作", "media": [{"type": kind, "url": url}]}, {})
    assert failure.value.code == "WAN3_MEDIA_UNSUPPORTED"


def test_link_and_inline_image(context, tmp_path):
    link = {"type": "link", "url": "https://www.example.com/article"}
    with pytest.raises(AppError) as failure:
        adapter().build_payload({"prompt": "根据网页创作", "media": [link]}, {})
    assert failure.value.code == "WAN3_MEDIA_UNSUPPORTED"
    inline = "data:image/png;base64," + base64.b64encode(Path(picture(tmp_path)).read_bytes()).decode()
    assert adapter().build_payload({"prompt": "创作", "first_frame_image": inline}, {})["input"]["media"][0]["url"] == inline


@pytest.mark.parametrize("size,mode", [((239, 240), "RGB"), ((240, 8001), "RGB"), ((240, 2000), "RGB"), ((320, 240), "RGBA")])
def test_invalid_image_dimensions_and_alpha(context, tmp_path, size, mode):
    with pytest.raises(AppError):
        adapter().build_payload({"prompt": "创作", "first_frame_image": picture(tmp_path, size=size, mode=mode)}, {})


def test_mock_sentinel_exact_and_not_real(context, tmp_path, monkeypatch):
    path = tmp_path / "mock.png"
    path.write_bytes(MOCK_PNG_BYTES)
    assert adapter().build_payload({"prompt": "创作", "first_frame_image": str(path)}, {})
    monkeypatch.setattr(DashScopeWan3Adapter, "use_mock", property(lambda _: False))
    with pytest.raises(AppError):
        adapter().build_payload({"prompt": "创作", "first_frame_image": str(path)}, {})


def test_invalid_prompt_model_and_managed_path(context, tmp_path):
    for inputs in ({"prompt": ""}, {"prompt": "x" * 20000, "negative_prompt": "x"}, {"prompt": []}):
        with pytest.raises(AppError):
            adapter().build_payload(inputs, {})
    with pytest.raises(AppError):
        adapter("wan3.0-i2v").build_payload({"prompt": "创作"}, {})
    with pytest.raises(AppError):
        adapter().build_payload({"prompt": "创作", "first_frame_image": picture(tmp_path.parent, "outside-wan3.png")}, {})


def test_legacy_async_url_and_poll_protocol(context, monkeypatch):
    value, calls = adapter(), []
    replies = iter([{"output": {"task_id": "offline-task", "task_status": "PENDING"}},
                    {"output": {"task_id": "offline-task", "task_status": "RUNNING"}},
                    {"output": {"task_id": "offline-task", "task_status": "SUCCEEDED", "video_url": "https://assets.example/result.mp4"},
                     "usage": {"input_video_duration": 0.0, "output_video_duration": 5.0, "duration": 5.0}}])
    monkeypatch.setattr(DashScopeWan3Adapter, "use_mock", property(lambda _: False))
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return next(replies)
    monkeypatch.setattr(value, "request_json", request)
    payload = value.build_payload({"prompt": "猫跳舞"}, {})
    assert value.submit(payload)["provider_task_id"] == "offline-task"
    assert value.poll("offline-task")["status"] == "running"
    result = value.poll("offline-task")
    assert result["status"] == "success" and result["result_url"].endswith("result.mp4")
    assert result["raw_response"]["usage"]["duration"] == 5.0
    assert calls[0][1] == "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
    assert calls[1][1] == calls[2][1] == "https://dashscope.aliyuncs.com/api/v1/tasks/offline-task"
    assert calls[0][2]["json"] == payload
    assert calls[0][2]["headers"]["X-DashScope-Async"] == "enable"
    assert "X-DashScope-DataInspection" not in calls[0][2]["headers"]


@pytest.mark.parametrize("vendor,expected", [("PENDING", "running"), ("FAILED", "failed"), ("UNKNOWN", "failed"), ("CANCELED", "cancelled")])
def test_poll_mapping_never_submits(context, monkeypatch, vendor, expected):
    value = adapter()
    monkeypatch.setattr(DashScopeWan3Adapter, "use_mock", property(lambda _: False))
    def request(method, url, **kwargs):
        assert method == "GET"
        return {"output": {"task_status": vendor, "code": "OfflineError"}}
    monkeypatch.setattr(value, "request_json", request)
    result = value.poll("offline-task")
    assert result["status"] == expected and result["provider_task_id"] == "offline-task"
    assert result["vendor_status"] == vendor


@pytest.mark.parametrize("model_id,adapter_name", [("wan3.0-video", "dashscope_wan3"), ("wan3.0-video-prime", "dashscope_wan3"), ("wan2.7-i2v", "dashscope_i2v")])
def test_bridge_switch_capability_adapter(context, model_id, adapter_name):
    model = adapter(model_id).model
    model.adapter_name = adapter_name
    data = AnimateShotInput(first_frame_artifact_id="first", last_frame_artifact_id="last", prompt="移动")
    with pytest.raises(AppError) as failure:
        validate_bridge(data, model)
    assert failure.value.code == "KEYFRAME_BRIDGE_UNAVAILABLE"
    context.config["AGENT_ENABLE_KEYFRAME_BRIDGE"] = True
    validate_bridge(data, model)
    model.capabilities = {"modes": ["i2v"]}
    with pytest.raises(AppError):
        validate_bridge(data, model)
    model.capabilities = {"modes": ["i2v", "first_last_frame"]}
    model.adapter_name = "mock"
    with pytest.raises(AppError):
        validate_bridge(data, model)


def test_file_and_audio_restrictions(context, tmp_path):
    for kind, name, data in (("reference_audio", "invalid.wav", b"not wav"),
                             ("reference_audio", "voice.mp3", b"mp3"),
                             ("file", "story.pdf", b"pdf")):
        path = tmp_path / name
        path.write_bytes(data)
        with pytest.raises(AppError):
            adapter().build_payload({"prompt": "创作", "media": [{"type": kind, "url": str(path)}]}, {})
    with pytest.raises(AppError):
        adapter().build_payload({"prompt": "创作", "media": [{"type": "reference_audio", "url": audio(tmp_path, seconds=0.5)}]}, {})
    path = tmp_path / "large.png"
    with path.open("wb") as output:
        output.truncate(20 * 1024 * 1024 + 1)
    with pytest.raises(AppError):
        adapter().build_payload({"prompt": "创作", "first_frame_image": str(path)}, {})


def test_custom_legacy_base_url_remains_configurable(context):
    context.config["DASHSCOPE_API_BASE_URL"] = "https://dashscope-intl.aliyuncs.com/"
    value = adapter()
    assert value.create_url() == "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
    assert value.task_url("test") == "https://dashscope-intl.aliyuncs.com/api/v1/tasks/test"


def test_missing_async_task_id_is_rejected(context, monkeypatch):
    value = adapter()
    monkeypatch.setattr(DashScopeWan3Adapter, "use_mock", property(lambda _: False))
    monkeypatch.setattr(value, "request_json", lambda *args, **kwargs: {"output": {"task_status": "PENDING"}})
    with pytest.raises(AppError) as failure:
        value.submit(value.build_payload({"prompt": "创作"}, {}))
    assert failure.value.code == "API_TASK_FAILED"


def test_mock_mode_never_requests_http(context, tmp_path, monkeypatch):
    value = adapter()
    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP must not run in Mock mode")
    monkeypatch.setattr(value, "request_json", forbidden)
    submitted = value.submit(value.build_payload({"prompt": "创作"}, {}))
    response = value.poll(submitted["provider_task_id"])
    assert response["status"] == "success"
    outputs = value.download_outputs(response, tmp_path)
    assert Path(outputs[0]).read_bytes() == b"Mock video bytes generated by MockAdapter.\n"


def test_catalog_defaults_and_explicit_overrides_match_request(context):
    value = adapter()
    value.model.default_params = {"resolution": "720P", "duration": 10, "audio": False, "prompt_extend": False}
    parameters = value.build_payload({"prompt": "创作"}, {})["parameters"]
    assert parameters["resolution"] == "720P" and parameters["duration"] == 10
    assert parameters["audio"] is parameters["prompt_extend"] is False
    override = value.build_payload({"prompt": "创作"}, {"resolution": "480P", "duration": 2})["parameters"]
    assert override["resolution"] == "480P" and override["duration"] == 2
    assert value.model.default_params["resolution"] == "720P"


@pytest.mark.parametrize("prompt", ["", "   ", "\n\t"])
def test_negative_only_prompt_is_rejected(context, prompt):
    with pytest.raises(AppError) as failure:
        adapter().build_payload({"prompt": prompt, "negative_prompt": "模糊"}, {})
    assert failure.value.code == "INVALID_INPUT"
