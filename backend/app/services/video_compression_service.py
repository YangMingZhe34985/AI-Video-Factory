import os
import shutil
import subprocess
import sys
from pathlib import Path

from flask import current_app

from app.services.storage_service import StorageService


class VideoCompressionService:
    @staticmethod
    def compress_for_artifact(input_path: Path) -> tuple[Path, dict]:
        source = Path(input_path)
        metadata = {
            "enabled": bool(current_app.config.get("VIDEO_COMPRESSION_ENABLED", True)),
            "status": "disabled",
            "original_file_path": StorageService.relative_path(source),
            "compressed_file_path": None,
            "original_size": source.stat().st_size if source.exists() else 0,
            "compressed_size": None,
        }
        if not metadata["enabled"]:
            return source, metadata
        if not source.exists() or not source.is_file():
            metadata.update({"status": "failed", "error": "Input video file does not exist"})
            return source, metadata
        if source.stem.endswith("_compressed"):
            metadata["status"] = "skipped_already_compressed"
            return source, metadata

        target = source.with_name(f"{source.stem}_compressed.mp4")
        metadata["compressed_file_path"] = StorageService.relative_path(target)

        try:
            ffmpeg = VideoCompressionService.resolve_ffmpeg()
            command = VideoCompressionService._command(ffmpeg, source, target)
            subprocess.run(command, check=True, capture_output=True, text=True)
            compressed_size = target.stat().st_size if target.exists() else 0
            metadata.update(
                {
                    "status": "success",
                    "compressed_size": compressed_size,
                    "ffmpeg": ffmpeg,
                    "crf": str(current_app.config.get("VIDEO_COMPRESSION_CRF", "28")),
                    "preset": str(current_app.config.get("VIDEO_COMPRESSION_PRESET", "medium")),
                    "audio_bitrate": str(
                        current_app.config.get("VIDEO_COMPRESSION_AUDIO_BITRATE", "128k")
                    ),
                }
            )
            if compressed_size <= 0:
                metadata.update({"status": "failed", "error": "Compressed output is empty"})
                VideoCompressionService._unlink_quietly(target)
                return source, metadata
            if compressed_size >= metadata["original_size"] > 0:
                metadata["status"] = "larger_than_original"
                VideoCompressionService._unlink_quietly(target)
                return source, metadata
            return target, metadata
        except Exception as exc:
            metadata.update({"status": "failed", "error": str(exc)[:1000]})
            VideoCompressionService._unlink_quietly(target)
            return source, metadata

    @staticmethod
    def resolve_ffmpeg() -> str:
        configured = str(current_app.config.get("FFMPEG_BINARY") or "").strip()
        if configured:
            candidate = Path(configured)
            if candidate.exists() or shutil.which(configured):
                return configured

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg

        candidates = []
        conda_prefix = os.environ.get("CONDA_PREFIX")
        if conda_prefix:
            candidates.append(Path(conda_prefix) / "Library" / "bin" / "ffmpeg.exe")
        candidates.append(Path(sys.prefix) / "Library" / "bin" / "ffmpeg.exe")
        candidates.append(Path(sys.base_prefix) / "Library" / "bin" / "ffmpeg.exe")
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        raise FileNotFoundError("ffmpeg executable was not found")

    @staticmethod
    def _command(ffmpeg: str, source: Path, target: Path) -> list[str]:
        return [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-c:v",
            "libx264",
            "-preset",
            str(current_app.config.get("VIDEO_COMPRESSION_PRESET", "medium")),
            "-crf",
            str(current_app.config.get("VIDEO_COMPRESSION_CRF", "28")),
            "-c:a",
            "aac",
            "-b:a",
            str(current_app.config.get("VIDEO_COMPRESSION_AUDIO_BITRATE", "128k")),
            str(target),
        ]

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
