"""Real local media checks, isolated from model providers."""
import subprocess
from pathlib import Path
import pytest
from app.api import AppError
from app.services.media_probe_service import MediaProbeService, MOCK_VIDEO_BYTES
from app.services.storage_service import StorageService
from app.services.video_compression_service import VideoCompressionService

FFMPEG = Path(r"C:/Users/MingZheYang/Desktop/项目开发/AI Video Factory/.venv/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe")

def media(app, *, audio=False):
    if not FFMPEG.is_file():
        pytest.skip("Local FFmpeg integration executable is not installed")
    app.config["FFMPEG_BINARY"] = str(FFMPEG)
    target = StorageService.root() / ("long_audio.mp4" if audio else "sample.mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    args = [str(FFMPEG), "-nostdin", "-hide_banner", "-y", "-f", "lavfi", "-i", "color=c=blue:s=128x96:r=10:d=1.2"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=2.4"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac"]
    args += [str(target)]
    subprocess.run(args, check=True, capture_output=True, timeout=30)
    return target

def test_real_video_full_decode_and_metadata(app):
    with app.app_context():
        result = MediaProbeService.probe(media(app), decode=True)
        assert result["duration_sec"] == pytest.approx(1.2, abs=.11)
        assert (result["width"], result["height"], result["fps"]) == (128, 96, 10)
        assert result["video"]["codec"] == "h264"
        assert result["video"]["pixel_format"] == "yuv420p"
        assert result["decoded"] and result["video_duration_verified"] and not result["mock"]
        assert result["copy_compatible_metadata"]

def test_long_audio_does_not_extend_video_duration(app):
    with app.app_context():
        source = media(app, audio=True)
        header = MediaProbeService.probe(source)
        decoded = MediaProbeService.probe(source, decode=True)
        assert header["duration_sec"] == pytest.approx(2.4, abs=.1)
        assert decoded["duration_sec"] == pytest.approx(1.2, abs=.11)
        assert decoded["audio"]["sample_rate"] == 48000
        assert decoded["audio"]["channels"] == 1
        assert decoded["has_audio"] and decoded["duration_source"] == "decoded_video"

@pytest.mark.parametrize("contents,code", [(b"", "MEDIA_EMPTY"), (b"not a video", "MEDIA_UNDECODABLE")])
def test_invalid_media_rejected(app, contents, code):
    with app.app_context():
        if FFMPEG.is_file():
            app.config["FFMPEG_BINARY"] = str(FFMPEG)
        path = StorageService.root() / "bad.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        with pytest.raises(AppError) as error:
            MediaProbeService.probe(path, decode=True)
        assert error.value.code == code

def test_missing_outside_and_unavailable_tool_are_explicit(app, tmp_path, monkeypatch):
    with app.app_context():
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"video")
        with pytest.raises(AppError, match="outside"):
            MediaProbeService.probe(outside)
        source = StorageService.root() / "source.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"video")
        monkeypatch.setattr(VideoCompressionService, "resolve_ffmpeg", lambda: (_ for _ in ()).throw(FileNotFoundError()))
        with pytest.raises(AppError) as error:
            MediaProbeService.probe(source)
        assert error.value.code == "MEDIA_TOOL_UNAVAILABLE"

def test_mock_requires_exact_sentinel_and_declared_demo_duration(app):
    with app.app_context():
        source = StorageService.root() / "mock.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(MOCK_VIDEO_BYTES)
        with pytest.raises(AppError):
            MediaProbeService.probe(source, decode=True)
        result = MediaProbeService.probe(source, decode=True, mock_duration_sec=8)
        assert result["mock"] and not result["decoded"]
        assert result["duration_sec"] == 8 and result["duration_source"] == "mock_approved_plan"
        assert not result["copy_compatible_metadata"]

def test_missing_copy_metadata_disables_stream_copy():
    result = MediaProbeService._metadata("""Input #0, mov, from 'local':
  Duration: 00:00:01.20, bitrate: 0 kb/s
  Stream #0:0: Video: h264, yuv420p, 128x96, 10 fps, 10 tbr
Stream mapping:
""")
    assert not result["copy_compatible_metadata"]
