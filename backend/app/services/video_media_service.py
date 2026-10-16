"""Local video inspection and source-segment reuse; no provider calls."""

import math
import re
import subprocess
from pathlib import Path

from app.api import AppError
from app.services.storage_service import StorageService
from app.services.video_compression_service import VideoCompressionService


class VideoMediaService:
    @staticmethod
    def _input(path: Path) -> list[str]:
        if not path.resolve().is_relative_to(StorageService.root()) or not path.is_file():
            raise AppError("INVALID_SOURCE", "Source video is missing or outside managed storage", 422)
        # Only local MP4/MOV and Matroska/WebM containers; no playlists or network protocols.
        return ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm", "-i", str(path)]

    @staticmethod
    def _run(args: list[str], timeout: int) -> str:
        try:
            binary = VideoCompressionService.resolve_ffmpeg()
        except FileNotFoundError as error:
            raise AppError("MEDIA_TOOL_UNAVAILABLE", "FFmpeg is required for source video inspection and clipping", 503) from error
        try:
            result = subprocess.run([binary, "-nostdin", "-hide_banner", "-y", *args],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise AppError("MEDIA_TIMEOUT", "Local video processing exceeded its time limit", 422) from error
        if result.returncode:
            raise AppError("INVALID_SOURCE", "Video could not be decoded or processed", 422)
        return result.stderr

    @classmethod
    def inspect(cls, path: Path) -> dict:
        output = cls._run([*cls._input(path), "-map", "0:v:0", "-frames:v", "1", "-f", "null", "-"], 60)
        duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
        # Dimensions are a comma-separated stream field, not the codec's 0x... tag.
        dimensions = re.search(r"Video:.*?,\s*(\d+)x(\d+)(?=[\s,])", output)
        if not duration or not dimensions:
            raise AppError("INVALID_SOURCE", "A finite video duration and dimensions are required", 422)
        seconds = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
        if not math.isfinite(seconds) or seconds <= 0:
            raise AppError("INVALID_SOURCE", "Source video has no usable duration", 422)
        return {"duration": seconds, "width": int(dimensions[1]), "height": int(dimensions[2])}

    @classmethod
    def extract(cls, path: Path, target: Path, start: float, end: float, *, frame: bool) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        args = ["-ss", str(start), *cls._input(path), "-map", "0:v:0"]
        if frame:
            args += ["-frames:v", "1", "-update", "1", str(target)]
        else:
            args += ["-map", "0:a:0?", "-t", str(end - start), "-c:v", "libx264", "-preset", "fast",
                     "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(target)]
        cls._run(args, 180)
        if not target.is_file() or not target.stat().st_size:
            raise AppError("INVALID_SOURCE", "Source segment produced no usable output", 422)
