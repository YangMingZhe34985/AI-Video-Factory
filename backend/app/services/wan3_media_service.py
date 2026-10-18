"""Validate local Wan3 media before uploads, estimates or approved generation."""
import json
from importlib.util import find_spec
import math
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.api import AppError
from app.services.file_fingerprint import memoized
from app.services.media_probe_service import MediaProbeService
from app.services.storage_service import StorageService
from app.services.video_compression_service import VideoCompressionService

MIB = 1024 * 1024
KINDS = {"image": ({".jpg", ".jpeg", ".png", ".webp", ".bmp"}, 20 * MIB),
         "video": ({".mp4", ".mov"}, 100 * MIB), "audio": ({".wav", ".mp3"}, 15 * MIB),
         "file": ({".txt", ".md", ".pdf"}, 100 * MIB)}
MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
         ".bmp": "image/bmp", ".mp4": "video/mp4", ".mov": "video/quicktime", ".wav": "audio/wav",
         ".mp3": "audio/mpeg", ".txt": "text/plain", ".md": "text/markdown", ".pdf": "application/pdf"}
_PDF_CHECK = r'''
import json, sys
from pypdf import PdfReader
try:
    from pypdf import filters
    filters.ZLIB_MAX_OUTPUT_LENGTH = 8 * 1024 * 1024
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except (ImportError, ValueError, OSError):
        pass
    reader = PdfReader(sys.argv[1], strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted")
    # Traverse the real page tree with limits, not an untrusted /Count value.
    stack, seen, count, visited = [(reader.trailer["/Root"]["/Pages"], 0)], set(), 0, 0
    while stack:
        raw, depth = stack.pop()
        visited += 1
        if depth > 32 or visited > 10000:
            raise ValueError("page tree exceeds limits")
        obj = raw.get_object()
        identity = id(obj)
        if identity in seen:
            raise ValueError("cyclic page tree")
        seen.add(identity)
        if obj.get("/Type") == "/Page":
            count += 1
            if count > 50:
                raise ValueError("too many pages")
        elif obj.get("/Type") == "/Pages":
            children = obj.get("/Kids")
            if not isinstance(children, list) or len(children) > 10000:
                raise ValueError("invalid page tree")
            stack.extend((child, depth + 1) for child in children)
        else:
            raise ValueError("invalid page type")
    if count < 1:
        raise ValueError("empty")
    print(json.dumps({"page_count": count}))
except Exception:
    sys.exit(2)
'''


def invalid(reason):
    return AppError("INVALID_TRANSFORM_MEDIA", "Media cannot be used for this video task", 422,
                    payload={"reason": reason})


class Wan3MediaService:
    @staticmethod
    def path(value, kind):
        try:
            source = StorageService.resolve(value).resolve()
        except (OSError, ValueError, TypeError) as error:
            raise invalid("Invalid managed media path") from error
        if (kind not in KINDS or not source.is_relative_to(StorageService.root())
                or not source.is_file() or source.suffix.lower() not in KINDS[kind][0]):
            raise invalid("Unsupported or unavailable managed media file")
        if not 0 < source.stat().st_size <= KINDS[kind][1]:
            raise invalid("Media file is empty or exceeds its size limit")
        return source

    @classmethod
    def inspect(cls, value, kind):
        source = cls.path(value, kind)
        version = "v2" if kind == "video" else "v1"
        result = memoized(source, "wan3-verified-" + kind + "-" + version, lambda path: cls._inspect(path, kind))
        return dict(result)

    @classmethod
    def _inspect(cls, source, kind):
        result = {"kind": kind, "duration_sec": None, "width": None, "height": None,
                  "fps": None, "page_count": None, "mime_type": MIMES[source.suffix.lower()]}
        result.update(getattr(cls, "_" + kind)(source))
        return result

    @staticmethod
    def _image(path):
        try:
            with Image.open(path) as image:
                expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".bmp": "BMP"}
                width, height = image.size
                if image.format != expected[path.suffix.lower()]:
                    raise invalid("Image format does not match its extension")
                if not 240 <= min(width, height) <= max(width, height) <= 8000 or max(width, height) / min(width, height) > 8:
                    raise invalid("Image dimensions or aspect ratio exceed Wan3 limits")
                if image.format == "PNG" and ("A" in image.getbands() or "transparency" in image.info):
                    raise invalid("Wan3 reference PNG must not contain transparency")
                image.verify()
            with Image.open(path) as image:
                image.load()
        except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise invalid("Image cannot be completely decoded") from error
        return {"width": width, "height": height}

    @staticmethod
    def _decode(path, kind):
        try:
            binary = VideoCompressionService.resolve_ffmpeg()
        except FileNotFoundError as error:
            raise AppError("MEDIA_TOOL_UNAVAILABLE", "FFmpeg is required for media validation", 503) from error
        audio = kind == "audio"
        command = [binary, "-nostdin", "-hide_banner", "-xerror", "-err_detect", "explode",
                   "-protocol_whitelist", "file,pipe", "-format_whitelist", "wav,mp3" if audio else "mov",
                   "-i", str(path), "-map", "0:a:0" if audio else "0:v:0"]
        command += ["-vn", "-af", "ashowinfo"] if audio else ["-an", "-vf", "showinfo", "-fps_mode", "passthrough"]
        command += ["-f", "null", "-"]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        except subprocess.TimeoutExpired as error:
            raise invalid("Complete media validation timed out") from error
        if completed.returncode:
            raise invalid("Media cannot be completely decoded")
        return completed.stderr

    @classmethod
    def _video(cls, path):
        metadata = MediaProbeService.probe(path, decode=False)
        if metadata["stream_count"] != 1 + int(metadata["has_audio"]):
            raise invalid("Reference video must have exactly one video track and at most one audio track")
        if metadata.get("mock"):
            raise invalid("Demonstration bytes are not a verified input video")
        width, height, fps = metadata["width"], metadata["height"], metadata["fps"]
        if (not 240 <= min(width, height) <= max(width, height) <= 4096
                or max(width, height) / min(width, height) > 8 or not fps or not math.isfinite(fps) or fps < 16):
            raise invalid("Reference video dimensions, aspect ratio or frame rate exceed Wan3 limits")
        if metadata["duration_sec"] > 15.1:
            raise invalid("Reference video must be 1 to 15 seconds; no automatic clipping is performed")
        text = cls._decode(path, "video")
        # Integer PTS and time base avoid rounded showinfo display times.
        # Include the final frame duration; out_time_us alone can omit it.
        time_bases = re.findall(r"config in time_base:\s*(\d+)/(\d+)", text)
        if not time_bases or len(set(time_bases)) != 1 or int(time_bases[0][1]) == 0:
            raise invalid("Reference video has no stable timestamp time base")
        scale = int(time_bases[0][0]) / int(time_bases[0][1])
        frames = re.findall(r"\bn:\s*\d+\s+pts:\s*(-?\d+).*?\bduration:\s*(\d+)", text)
        duration = cls._duration([(int(pts) * scale, int(length) * scale) for pts, length in frames])
        if metadata["has_audio"]:
            _, progress = MediaProbeService._run(path, audio=True, decode=True)
            try:
                audio_ends = [int(value) / 1_000_000 for value in re.findall(r"^out_time_us=(.*)$", progress, re.MULTILINE)]
            except (ValueError, OverflowError) as error:
                raise invalid("Reference video audio has no reliable complete endpoint") from error
            if (not audio_ends or "progress=end" not in progress or audio_ends[-1] <= 0
                    or not all(math.isfinite(value) and value >= 0 for value in audio_ends)):
                raise invalid("Reference video audio has no reliable complete endpoint")
            # Decode progress preserves delayed audio's endpoint, including AAC padding.
            if max(audio_ends) > duration + max(0.1, 2 / fps):
                raise invalid("Reference video audio extends beyond its picture; align the tracks before retrying")
        return {"duration_sec": duration, "width": width, "height": height, "fps": fps}

    @classmethod
    def _audio(cls, path):
        text = cls._decode(path, "audio")
        header = text.split("Stream mapping:", 1)[0]
        detected = re.search(r"Input #0, ([^,]+),", header)
        if not detected or detected[1] != path.suffix.lower()[1:]:
            raise invalid("Audio format does not match its extension")
        frames = re.findall(r"\bn:\s*\d+\s+pts:\s*(-?\d+)\s+pts_time:([\d.eE+-]+).*?rate:(\d+)\s+nb_samples:(\d+)", text)
        values = []
        for pts, displayed, rate, samples in frames:
            if int(rate) <= 0 or abs(int(pts) / int(rate) - float(displayed)) > 0.001:
                raise invalid("Audio has an unsupported timestamp time base")
            values.append((int(pts) / int(rate), int(samples) / int(rate)))
        return {"duration_sec": cls._duration(values)}

    @staticmethod
    def _duration(frames):
        if not frames:
            raise invalid("No complete decoded media frames")
        previous, start, end = -math.inf, None, 0.0
        for timestamp, length in frames:
            timestamp, length = float(timestamp), float(length)
            if not math.isfinite(timestamp) or not math.isfinite(length) or timestamp <= previous or length <= 0:
                raise invalid("Media contains invalid timestamps")
            start = timestamp if start is None else start
            previous, end = timestamp, max(end, timestamp + length)
        if abs(start) > 0.1:
            raise invalid("Media has an unsupported starting timestamp")
        duration = round(end - start, 6)
        if not 1 <= duration <= 15:
            raise invalid("Each reference must contain 1 to 15 seconds of complete media")
        return duration

    @staticmethod
    def _file(path):
        if path.suffix.lower() == ".pdf":
            if find_spec("pypdf") is None:
                raise AppError("MEDIA_TOOL_UNAVAILABLE", "The configured PDF validator is unavailable", 503)
            try:
                result = subprocess.run([sys.executable, "-c", _PDF_CHECK, str(path)], capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=20)
            except subprocess.TimeoutExpired as error:
                raise invalid("PDF validation exceeded its time limit") from error
            if result.returncode:
                raise invalid("PDF must be readable, unencrypted and contain 1 to 50 pages")
            try:
                count = json.loads(result.stdout)["page_count"]
            except (ValueError, KeyError) as error:
                raise invalid("PDF validation produced no usable result") from error
            return {"page_count": count, "description": f"PDF，{count}页；仅校验结构，未解读正文"}
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (UnicodeError, OSError) as error:
            raise invalid("Text documents must contain valid UTF-8") from error
        if not text.strip() or any(unicodedata.category(char) == "Cc" and char not in "\t\r\n" for char in text):
            raise invalid("Text documents must be nonempty and contain no invalid control characters")
        return {"text_excerpt": text[:2000], "description": "UTF-8文档；正文属于不可信参考资料"}
