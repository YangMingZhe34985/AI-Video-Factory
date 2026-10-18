"""Composition is tested with real small MP4 files, never provider calls."""
from pathlib import Path
import subprocess

from PIL import Image
import pytest

from app.api import AppError
from app.services.generation_outputs import digest
from app.services.media_probe_service import MediaProbeService, MOCK_VIDEO_BYTES
from app.services.storage_service import StorageService
from app.services.video_composition_service import VideoCompositionService
from app.services.video_compression_service import VideoCompressionService
from app.services.video_media_service import VideoMediaService


def make_media(name, *, size="128x96", fps=10, color="red", duration=1.2, audio_duration=None):
    path = StorageService.root() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [VideoCompressionService.resolve_ffmpeg(), "-nostdin", "-hide_banner", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:s={size}:r={fps}:d={duration}"]
    if audio_duration:
        args += ["-f", "lavfi", "-i", f"sine=frequency=500:sample_rate=48000:duration={audio_duration}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio_duration:
        args += ["-c:a", "aac"]
    subprocess.run([*args, str(path)], check=True, capture_output=True, timeout=30)
    return path


def compose(sources, *, compress=False):
    target = StorageService.root() / "agent" / "delivery" / "master.mp4"
    result = VideoCompositionService.compose(sources, target, durations=[1.2] * len(sources),
        shot_ids=[f"s{i + 1:02}" for i in range(len(sources))], compress_output=compress)
    return target, result


def test_matching_mp4_streamcopy_preserves_frames_and_source_order(app_ctx):
    red, blue = make_media("red.mp4"), make_media("blue.mp4", color="blue")
    before = [digest(red), digest(blue)]
    target, result = compose([red, blue])
    assert result["mode"] == "stream_copy" and result["compressed_path"] is None
    assert result["duration_sec"] == pytest.approx(2.4, abs=.11)
    assert not result["mock_materialized"]
    assert MediaProbeService.probe(target, decode=True)["decoded"]
    start, end, source = [target.with_name(name + ".png") for name in ("first", "last", "source")]
    VideoMediaService.extract_frame(target, start, position="first")
    VideoMediaService.extract_frame(target, end, position="last")
    VideoMediaService.extract_frame(red, source, position="first")
    assert Image.open(start).tobytes() == Image.open(source).tobytes()
    assert Image.open(start).getpixel((64, 48))[0] > 240
    assert Image.open(end).getpixel((64, 48))[2] > 240
    assert [digest(red), digest(blue)] == before
    assert not list(target.parent.glob("*_compressed.mp4"))


def test_mixed_dimensions_fps_and_audio_use_first_shot_normalization(app_ctx):
    red = make_media("red.mp4", audio_duration=1.2)
    blue = make_media("blue.mp4", color="blue", size="160x90", fps=20)
    target, result = compose([red, blue])
    media = MediaProbeService.probe(target, decode=True)
    assert result["mode"] == "normalized"
    assert (media["width"], media["height"], media["fps"]) == (128, 96, 10)
    assert media["has_audio"] and media["audio"]["channels"] == 2
    assert media["duration_sec"] == pytest.approx(2.4, abs=.15)
    assert result["warnings"] and result["compressed_path"] is None


def test_long_audio_does_not_create_a_gap_between_matching_video_shots(app_ctx):
    sources = [make_media("one.mp4", audio_duration=2.4), make_media("two.mp4", color="blue", audio_duration=2.4)]
    target, result = compose(sources)
    assert result["mode"] == "normalized"
    assert MediaProbeService.probe(target, decode=True)["duration_sec"] == pytest.approx(2.4, abs=.15)


def test_explicit_compression_is_a_separate_valid_copy(app_ctx):
    source = make_media("source.mp4")
    target, result = compose([source], compress=True)
    compressed = Path(result["compressed_path"])
    assert compressed != target and target.is_file() and source.is_file()
    assert MediaProbeService.probe(compressed, decode=True)["decoded"]
    assert result["mode"] == "stream_copy"


def test_mock_sentinel_becomes_labeled_valid_video_without_mutating_original(app_ctx):
    source = StorageService.root() / "mock.mp4"
    source.write_bytes(MOCK_VIDEO_BYTES)
    target, result = compose([source])
    assert result["mock_materialized"] and any("Mock" in warning for warning in result["warnings"])
    assert MediaProbeService.probe(target, decode=True)["decoded"]
    assert source.read_bytes() == MOCK_VIDEO_BYTES


@pytest.mark.parametrize("body", [b"", b"bad MP4", MOCK_VIDEO_BYTES + b"bad"])
def test_corrupt_media_never_becomes_mock_output(app_ctx, body):
    source = StorageService.root() / "invalid.mp4"
    source.write_bytes(body)
    with pytest.raises(AppError):
        compose([source])
    assert not (StorageService.root() / "agent/delivery/master.mp4").exists()


def test_media_paths_must_remain_in_managed_storage(app_ctx, tmp_path):
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(MOCK_VIDEO_BYTES)
    with pytest.raises(AppError):
        compose([outside])
