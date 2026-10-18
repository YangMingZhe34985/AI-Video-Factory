"""Local, atomic movie assembly; the approved source files are never modified."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from flask import current_app
from PIL import Image, ImageDraw

from app.api import AppError
from app.services.storage_service import StorageService
from app.services.video_media_service import VideoMediaService
from app.services.media_probe_service import MOCK_VIDEO_BYTES


class VideoCompositionService:
    @staticmethod
    def _path(value, *, exists=True):
        path = Path(value).resolve()
        if not path.is_relative_to(StorageService.root()) or (exists and (not path.is_file() or not path.stat().st_size)):
            raise AppError("INVALID_REFERENCE", "Composition requires a local managed media file", 422)
        return path

    @staticmethod
    def _run(args, timeout):
        from app.services.video_compression_service import VideoCompressionService
        try:
            binary = VideoCompressionService.resolve_ffmpeg()
            if len(subprocess.list2cmdline([binary, *args])) > 30000:
                raise AppError("DELIVERY_INCOMPLETE", "This source list exceeds the local media command limit", 422)
            return VideoMediaService._run(args, timeout)
        except OSError as error:
            raise AppError("MEDIA_TOOL_UNAVAILABLE", "Local media processing could not be started", 503) from error

    @staticmethod
    def _mock_source(path):
        return (current_app.config.get("MODEL_ADAPTER_MODE") == "mock"
                and path.stat().st_size == len(MOCK_VIDEO_BYTES) and path.read_bytes() == MOCK_VIDEO_BYTES)

    @classmethod
    def _materialize_mock(cls, target, duration, shot_id, index):
        if not 0 < duration <= 600:
            raise AppError("INVALID_INPUT", "Mock video requires the approved shot duration", 422)
        slate = target.with_suffix(".png")
        colors = [(28, 59, 91), (69, 43, 93), (29, 86, 72), (112, 64, 35)]
        image = Image.new("RGB", (320, 180), colors[index % len(colors)])
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 12, 307, 167), outline=(190, 210, 225), width=2)
        draw.text((30, 50), f"CINECREW MOCK\nSHOT {shot_id}\nLOCAL DEMO - NOT GENERATED VIDEO", fill="white", spacing=8)
        image.save(slate)
        cls._run(["-loop", "1", "-i", str(slate), "-t", str(duration), "-r", "25",
            "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-metadata", "comment=CineCrew local Mock preview; not generated video", str(target)], 180)
        return target

    @staticmethod
    def _compatible(media):
        first = media[0]
        if any(item.get("has_audio") and abs(item.get("container_duration_sec", item["duration_sec"]) - item["duration_sec"])
               > max(.1, 1 / (item.get("fps") or 25)) for item in media):
            return False
        if any(not item.get("copy_compatible_metadata") or item.get("stream_count", 0) not in {1, 2} for item in media):
            return False
        if first["video"]["codec"] not in {"h264", "hevc", "mpeg4", "av1"}:
            return False
        if first.get("audio") and first["audio"]["codec"] not in {"aac", "mp3"}:
            return False
        def signature(item):
            return {key: item.get(key) for key in ("width", "height", "fps", "video", "audio", "stream_count")}
        return all(signature(item) == signature(first) for item in media[1:])

    @classmethod
    def _normalize(cls, sources, target, media, width, height, fps, with_audio):
        args, filters, segments = [], [], []
        for index, source in enumerate(sources):
            args += VideoMediaService._input(source)
            duration = media[index]["duration_sec"]
            filters.append(f"[{index}:v:0]setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease:"
                f"force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{index}]")
            segments.append(f"[v{index}]")
            if with_audio:
                audio = f"[{index}:a:0]aresample=48000" if media[index].get("has_audio") else "anullsrc=r=48000:cl=stereo"
                filters.append(audio + f",aformat=channel_layouts=stereo,apad,atrim=duration={duration},asetpts=N/SR/TB[a{index}]")
                segments.append(f"[a{index}]")
        filters.append("".join(segments) + f"concat=n={len(sources)}:v=1:a={int(with_audio)}[v]" + ("[a]" if with_audio else ""))
        filter_file = target.with_suffix(".filters.txt")
        filter_file.write_text(";".join(filters), encoding="utf-8")
        args += ["-filter_complex_script", str(filter_file), "-map", "[v]", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps), "-fps_mode", "cfr", "-video_track_timescale", "90000"]
        if with_audio:
            args += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        else:
            args += ["-an"]
        args += ["-map_metadata", "-1", "-movflags", "+faststart", str(target)]
        cls._run(args, max(180, int(sum(item["duration_sec"] for item in media) * 6)))

    @classmethod
    def compose(cls, sources, target, *, durations, shot_ids, compress_output=False):
        """Return master metadata; compression is a separate, explicit rendition."""
        from app.services.media_probe_service import MediaProbeService
        target = cls._path(target, exists=False)
        if not sources or len(sources) != len(durations) or len(sources) != len(shot_ids):
            raise AppError("INVALID_INPUT", "Composition source order is incomplete", 422)
        sources = [cls._path(source) for source in sources]
        if target in sources or target.with_name(target.stem + "_compressed.mp4") in sources:
            raise AppError("INVALID_REFERENCE", "Composition outputs cannot overwrite source media", 422)
        target.parent.mkdir(parents=True, exist_ok=True)
        warnings, mock_materialized = [], False
        with tempfile.TemporaryDirectory(prefix="compose-", dir=target.parent) as directory:
            staging = Path(directory)
            staged, media = [], []
            for index, source in enumerate(sources):
                if cls._mock_source(source):
                    source = cls._materialize_mock(staging / f"mock_{index:03}.mp4", durations[index], shot_ids[index], index)
                    mock_materialized = True
                media.append(MediaProbeService.probe(source, decode=True))
                staged.append(source)
            mode = "stream_copy" if cls._compatible(media) else "normalized"
            if mode == "normalized":
                first = media[0]
                width, height = first["width"] + first["width"] % 2, first["height"] + first["height"] % 2
                fps = first.get("fps")
                if not fps or fps <= 0:
                    raise AppError("INVALID_SOURCE", "A valid frame rate is required for normalization", 422)
                with_audio = any(item.get("has_audio") for item in media)
                assembled = staging / "master.mp4"
                cls._normalize(staged, assembled, media, width, height, fps, with_audio)
                warnings.append("Source formats differed; normalized using high-quality H.264 CRF 18 encoding.")
            else:
                entries = []
                for index, source in enumerate(staged):
                    # Controlled relative filenames keep concat's safe mode enabled.
                    linked = staging / f"clip_{index:03}.mp4"
                    try:
                        os.link(source, linked)
                    except OSError:
                        shutil.copyfile(source, linked)
                    entries += [f"file '{linked.name}'", f"duration {media[index]['duration_sec']}"]
                concat = staging / "sources.ffconcat"
                concat.write_text("ffconcat version 1.0\n" + "\n".join(entries) + "\n", encoding="utf-8")
                assembled = staging / "master.mp4"
                cls._run(["-protocol_whitelist", "file,pipe", "-format_whitelist", "concat,mov,matroska,webm",
                    "-f", "concat", "-safe", "1", "-i", str(concat), "-map", "0:v:0", "-map", "0:a:0?",
                    "-c", "copy", "-map_metadata", "-1", "-movflags", "+faststart", str(assembled)],
                    max(180, int(sum(durations) * 2)))
            result = MediaProbeService.probe(assembled, decode=True)
            compressed_target = None
            if compress_output:
                compressed = staging / "compressed.mp4"
                cls._run([*VideoMediaService._input(assembled), "-map", "0:v:0", "-map", "0:a:0?",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "28", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(compressed)],
                    max(180, int(sum(durations) * 6)))
                MediaProbeService.probe(compressed, decode=True)
                compressed_target = target.with_name(target.stem + "_compressed.mp4")
                compressed.replace(compressed_target)
            assembled.replace(target)
        if mock_materialized:
            warnings.append("Mock demonstration: placeholder bytes were rendered as labeled local video slates.")
        return {"mode": mode, "duration_sec": result["duration_sec"], "width": result["width"],
                "height": result["height"], "fps": result["fps"], "mock_materialized": mock_materialized,
                "warnings": warnings, "compressed_path": str(compressed_target) if compressed_target else None}
