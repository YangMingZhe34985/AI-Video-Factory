"""Provider videos without a SAR tag compose to an explicit canvas (real-provider E2E F1)."""
import subprocess

import pytest

from app.plans.aspect import delivery_checks, video_geometry
from app.services.media_probe_service import MediaProbeService
from app.services.storage_service import StorageService
from app.services.video_composition_service import VideoCompositionService
from tests.test_media_probe import configure_ffmpeg


def provider_like_clip(app_ctx, name, seconds=1.0):
    """1280x720 H.264 with no SAR, like real wan2.7 outputs."""
    binary = configure_ffmpeg(app_ctx)
    target = StorageService.root() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(binary), "-nostdin", "-hide_banner", "-y", "-f", "lavfi",
                    "-i", f"testsrc=s=1280x720:r=30:d={seconds}", "-vf", "setsar=0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(target)], check=True, capture_output=True, timeout=60)
    return target


def test_missing_sar_is_square_with_evidence_and_explicit_sar_is_kept(app_ctx):
    media = MediaProbeService.probe(provider_like_clip(app_ctx, "nosar.mp4"))
    assert media["video"]["sar"] == "1:1" and media["video"]["sar_source"] == "unspecified"
    assert video_geometry(media)["aspect_ratio"] == "16:9"
    explicit = {**media, "video": {**media["video"], "sar": "4:3", "sar_source": "stream"}}
    assert video_geometry(explicit)["aspect_ratio"] == "64:27"


def test_provider_clips_without_sar_compose_and_pass_master_checks(app_ctx):
    first, second = provider_like_clip(app_ctx, "shot1.mp4"), provider_like_clip(app_ctx, "shot2.mp4")
    target = StorageService.root() / "master.mp4"
    result = VideoCompositionService.compose([str(first), str(second)], str(target), durations=[1.0, 1.0],
        shot_ids=["s1", "s2"], target_aspect_ratio="16:9", target_size="1280*720")
    assert (result["width"], result["height"]) == (1280, 720)
    master = MediaProbeService.probe(target, decode=True)
    assert all(check["passed"] for check in delivery_checks(master, "16:9", "1280*720"))
