"""Local evaluation rendering follows approved parameters without provider HTTP."""
from pathlib import Path
from types import SimpleNamespace
import os
import sys

from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/v3_eval"))
import mock_geometry
import mock_media


@pytest.mark.parametrize("size", ["1280*720", "720*1280", "1024*1024", "1536*864"])
def test_mock_image_preserves_submitted_size(tmp_path, monkeypatch, size):
    monkeypatch.setattr(mock_media, "CONTROLLER", mock_media.MediaController(tmp_path / "events.jsonl"))
    adapter = mock_media.LocalImageAdapter(SimpleNamespace(model_id="qwen-image-3.0", provider="dashscope"))
    adapter._submitted_payload = {"parameters": {"size": size}}
    path = adapter.download_outputs({}, tmp_path)[0]
    with Image.open(path) as image:
        assert image.size == tuple(map(int, size.split("*")))
    assert mock_media.CONTROLLER.summary()["actual_real_media_http_calls"] == 0


@pytest.mark.parametrize("ratio,expected", [("16:9", (1280, 720)), ("9:16", (720, 1280)), ("1:1", (720, 720))])
def test_mock_video_passes_submitted_geometry_to_local_renderer(tmp_path, monkeypatch, ratio, expected):
    from app.services.video_composition_service import VideoCompositionService
    monkeypatch.setattr(mock_media, "CONTROLLER", mock_media.MediaController(tmp_path / "events.jsonl"))
    calls = []
    def render(target, duration, shot_id, index, *, size):
        calls.append((duration, size))
        target.write_bytes(b"local-render-stub")
    monkeypatch.setattr(VideoCompositionService, "_materialize_mock", render)
    adapter = mock_media.LocalVideoAdapter(SimpleNamespace(model_id="wan3.0-video", provider="dashscope"))
    adapter._submitted_payload = {"parameters": {"duration": 5, "resolution": "720P", "ratio": ratio}}
    adapter.download_outputs({}, tmp_path)
    assert calls == [(5, expected)]


def test_mock_i2v_inherits_actual_local_first_frame(app_ctx):
    from app.services.storage_service import StorageService
    frame = StorageService.root() / "portrait.png"
    Image.new("RGB", (720, 1280)).save(frame)
    payload = {"parameters": {"duration": 5, "resolution": "720P"}, "inputs": {"first_frame_image": str(frame)}}
    assert mock_geometry.rendered_size(payload) == (720, 1280)


def test_mock_i2v_never_fetches_a_remote_frame(app_ctx):
    with pytest.raises(RuntimeError, match="local managed"):
        mock_geometry.rendered_size({"inputs": {"first_frame_image": "https://example.invalid/frame.png"}})


@pytest.mark.parametrize("separator", sorted({"/", os.sep}))
def test_mock_i2v_resolves_job_payload_relative_to_managed_storage(app_ctx, monkeypatch, tmp_path, separator):
    from app.services.storage_service import StorageService
    relative = "jobs/job_local/outputs/first_frame_image/v1.0/first_frame.png"
    frame = StorageService.root() / relative
    frame.parent.mkdir(parents=True)
    Image.new("RGB", (720, 1280)).save(frame)
    elsewhere = tmp_path / "different-cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    payload = {"model": "wan2.7-i2v", "parameters": {"duration": 5, "resolution": "720P"},
               "inputs": {"first_frame_image": relative.replace("/", separator)}}
    assert mock_geometry.rendered_size(payload) == (720, 1280)


@pytest.mark.parametrize("frame", [
    "https://example.invalid/frame.png", "file:///C:/frame.png", "data:image/png;base64,AA==",
    "s3://bucket/frame.png", r"\\server\share\frame.png", "//server/share/frame.png",
    r"\\?\UNC\server\share\frame.png", r"\/server/share/frame.png", "C:frame.png",
])
def test_mock_i2v_rejects_network_or_drive_relative_frame_before_resolution(monkeypatch, frame):
    from app.services.storage_service import StorageService
    monkeypatch.setattr(StorageService, "resolve", lambda _path: pytest.fail("Unsafe path reached filesystem resolution"))
    with pytest.raises(RuntimeError, match="local managed"):
        mock_geometry.rendered_size({"inputs": {"first_frame_image": frame}})


@pytest.mark.parametrize("absolute", [False, True])
def test_mock_i2v_rejects_existing_file_outside_managed_storage(app_ctx, absolute):
    from app.services.storage_service import StorageService
    frame = StorageService.root().parent / "outside.png"
    Image.new("RGB", (720, 1280)).save(frame)
    value = str(frame) if absolute else "../outside.png"
    with pytest.raises(RuntimeError, match="local managed"):
        mock_geometry.rendered_size({"inputs": {"first_frame_image": value}})


def test_mock_i2v_rejects_missing_managed_file(app_ctx):
    with pytest.raises(RuntimeError, match="local managed"):
        mock_geometry.rendered_size({"inputs": {"first_frame_image": "jobs/missing/frame.png"}})
