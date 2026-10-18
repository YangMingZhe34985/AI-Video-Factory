"""Wan 3 unified video protocol with bounded, explicitly supported inputs."""

import base64
import binascii
import ipaddress
import io
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

from app.adapters.dashscope_common import DashScopeGenerationAdapter
from app.api import AppError
from app.services.storage_service import MOCK_PNG_BYTES, StorageService
from app.services.wan3_media_service import Wan3MediaService


MODEL_IDS = frozenset({"wan3.0-video", "wan3.0-video-prime"})
IMAGE_TYPES = frozenset({"first_frame", "last_frame", "reference_image"})
MEDIA_LIMITS = {"first_frame": 1, "last_frame": 1, "reference_image": 10,
                "reference_video": 5, "reference_audio": 5, "file": 1, "link": 1}
PARAMETERS = frozenset({"duration", "resolution", "ratio", "audio", "prompt_extend", "watermark", "seed", "n_outputs"})
INPUTS = frozenset({"prompt", "negative_prompt", "prompt_version", "first_frame_image", "last_frame_image",
                    "reference_images", "media", "audio_input", "driving_audio"})


def _invalid(message, code="INVALID_INPUT"):
    raise AppError(code, message, 422)


def _integer(value, minimum, maximum, name):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _invalid(f"Wan 3 {name} must be an integer between {minimum} and {maximum}")
    return value


class DashScopeWan3Adapter(DashScopeGenerationAdapter):
    provider_name = "dashscope"
    task_type = "text_to_video"
    output_kind = "video"

    def create_url(self):
        return f"{self.dashscope_base_url()}/services/aigc/video-generation/video-synthesis"

    def submission_headers(self):
        return {"Authorization": f"Bearer {self.api_key()}", "Content-Type": "application/json",
                "X-DashScope-Async": "enable", "X-DashScope-OssResourceResolve": "enable"}

    def build_payload(self, inputs: dict, params: dict) -> dict:
        if self.model_id not in MODEL_IDS:
            _invalid("Unsupported Wan 3 model ID")
        if not isinstance(inputs, dict) or not isinstance(params, dict):
            _invalid("Wan 3 inputs and parameters must be objects")
        effective = {**(getattr(self.model, "default_params", None) or {}), **params}
        if set(inputs) - INPUTS or set(effective) - PARAMETERS:
            _invalid("Unsupported Wan 3 input or parameter")
        parameters = self._parameters(effective)
        prompt = inputs.get("prompt", "")
        negative = inputs.get("negative_prompt", "") or ""
        if not isinstance(prompt, str) or not isinstance(negative, str):
            _invalid("Wan 3 prompt must be text")
        prompt = prompt.strip()
        if not prompt:
            _invalid("Wan 3 requires a nonempty positive prompt")
        if negative.strip():
            # Wan 3 has no standalone negative_prompt field. Preserve classic intent.
            prompt += "\n\n避免出现：" + negative.strip()
        if not prompt or len(prompt) > 20000:
            _invalid("Wan 3 prompt must contain 1 to 20000 characters")
        media = self._media(inputs)
        if any(item["type"] in {"file", "link"} for item in media) and not parameters["prompt_extend"]:
            _invalid("Wan 3 file/link inputs require prompt_extend=true")
        # Validate all resources before any upload or billable submission.
        seconds = {"reference_video": 0.0, "reference_audio": 0.0}
        for item in media:
            duration = self._validate_resource(item)
            if item["type"] in seconds:
                seconds[item["type"]] += duration
        if seconds["reference_video"] > 15 or seconds["reference_video"] + parameters["duration"] > 30:
            _invalid("Wan 3 input video must total at most 15 seconds and input plus final output at most 30 seconds")
        if seconds["reference_audio"] > 15:
            _invalid("Wan 3 reference audio total duration exceeds 15 seconds")
        output = {"prompt": prompt}
        if media:
            output["media"] = [{"type": item["type"], "url": self._resource_url(item["url"])} for item in media]
        return {"model": self.model_id, "input": output, "parameters": parameters}

    @staticmethod
    def _parameters(params):
        values = {"duration": 5, "resolution": "1080P", "ratio": "adaptive", "audio": True,
                  "prompt_extend": True, "watermark": False, **params}
        _integer(values["duration"], 2, 30, "duration (smart duration is not supported)")
        if not isinstance(values["resolution"], str) or values["resolution"] not in {"480P", "720P", "1080P"}:
            _invalid("Unsupported Wan 3 resolution")
        if not isinstance(values["ratio"], str) or values["ratio"] not in {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}:
            _invalid("Unsupported Wan 3 aspect ratio")
        for key in ("audio", "prompt_extend", "watermark"):
            if not isinstance(values[key], bool):
                _invalid(f"Wan 3 {key} must be a boolean")
        if "seed" in values:
            _integer(values["seed"], -1, 2147483647, "seed")
        if "n_outputs" in values:
            _integer(values.pop("n_outputs"), 1, 1, "n_outputs")
        return values

    @staticmethod
    def _media(inputs):
        media = inputs.get("media", [])
        if not isinstance(media, list):
            _invalid("Wan 3 media must be an array")
        media = [dict(item) if isinstance(item, dict) else item for item in media]
        for key, kind in (("first_frame_image", "first_frame"), ("last_frame_image", "last_frame"),
                          ("audio_input", "reference_audio"), ("driving_audio", "reference_audio")):
            if inputs.get(key):
                media.append({"type": kind, "url": inputs[key]})
        references = inputs.get("reference_images", [])
        if not isinstance(references, list):
            _invalid("Wan 3 reference_images must be an array")
        media.extend({"type": "reference_image", "url": value} for value in references)
        counts = dict.fromkeys(MEDIA_LIMITS, 0)
        for item in media:
            if not isinstance(item, dict) or set(item) != {"type", "url"}:
                _invalid("Wan 3 media entries require only type and url")
            kind, value = item["type"], item["url"]
            if not isinstance(kind, str) or kind not in MEDIA_LIMITS or not isinstance(value, str) or not value.strip():
                _invalid("Unsupported Wan 3 media entry")
            item["url"] = value.strip()
            counts[kind] += 1
        if any(counts[kind] > maximum for kind, maximum in MEDIA_LIMITS.items()) or len(media) > 20:
            _invalid("Wan 3 media count exceeds supported limits")
        frames = counts["first_frame"] + counts["last_frame"]
        if (frames and frames != len(media)) or (counts["last_frame"] and not counts["first_frame"]):
            _invalid("Wan 3 first/last frames cannot be mixed with reference media; a last frame requires a first frame")
        if counts["file"] and counts["link"]:
            _invalid("Wan 3 file and link are mutually exclusive")
        return media

    @staticmethod
    def _public_url(value, *, oss=True):
        try:
            parts = urlsplit(value)
            allowed = {"http", "https", "oss"} if oss else {"http", "https"}
            if parts.scheme not in allowed or not parts.hostname or parts.username or parts.password:
                _invalid("Wan 3 media URL must be a public HTTP(S) or supported OSS URL")
            hostname = parts.hostname.lower()
            if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".localhost", ".local", ".internal")):
                _invalid("Wan 3 media URL cannot target a local host")
            try:
                address = ipaddress.ip_address(hostname)
            except ValueError:
                address = None
            if address is not None and not address.is_global:
                _invalid("Wan 3 media URL cannot target a private address")
        except ValueError:
            _invalid("Invalid Wan 3 media URL")

    def _local_file(self, value, maximum):
        try:
            path = self.resolve_path(value).resolve()
            if not path.is_relative_to(StorageService.root()) or not path.is_file():
                _invalid("Wan 3 local media must be an existing managed file")
            size = path.stat().st_size
        except (OSError, ValueError):
            _invalid("Wan 3 local media path is invalid or unavailable")
        if size <= 0 or size > maximum:
            _invalid("Wan 3 media file is empty or exceeds its size limit")
        return path

    def _validate_resource(self, item):
        kind, value = item["type"], item["url"]
        remote = self.is_remote_resource(value)
        if kind == "link":
            _invalid("Live page links are not accepted; capture an approved private TXT snapshot first", "WAN3_MEDIA_UNSUPPORTED")
        if kind in IMAGE_TYPES:
            if remote:
                self._public_url(value)
            else:
                self._validate_image(value)
            return 0.0
        if remote or value.startswith("data:"):
            _invalid("Wan 3 video/audio/file inputs require locally verified managed files", "WAN3_MEDIA_UNSUPPORTED")
        media_kind = {"reference_video": "video", "reference_audio": "audio", "file": "file"}[kind]
        metadata = Wan3MediaService.inspect(value, media_kind)
        return metadata["duration_sec"] or 0.0

    def _validate_image(self, value):
        if value.startswith("data:"):
            try:
                header, encoded = value.split(",", 1)
                if header not in {"data:image/jpeg;base64", "data:image/png;base64", "data:image/webp;base64", "data:image/bmp;base64"}:
                    _invalid("Unsupported Wan 3 inline image type")
                if len(encoded) > 28 * 1024 * 1024:
                    _invalid("Wan 3 image exceeds 20 MB")
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                _invalid("Invalid Wan 3 inline image")
        else:
            raw = self._local_file(value, 20 * 1024 * 1024).read_bytes()
        if not raw or len(raw) > 20 * 1024 * 1024:
            _invalid("Wan 3 image is empty or exceeds 20 MB")
        # Existing isolated Agent tests use this exact sentinel, never arbitrary images.
        if self.use_mock and raw == MOCK_PNG_BYTES:
            return
        try:
            with Image.open(io.BytesIO(raw)) as image:
                width, height = image.size
                if image.format not in {"JPEG", "PNG", "BMP", "WEBP"}:
                    _invalid("Unsupported Wan 3 image format")
                if not 240 <= min(width, height) <= max(width, height) <= 8000 or max(width, height) / min(width, height) > 8:
                    _invalid("Wan 3 image dimensions must be 240 to 8000 pixels with aspect ratio at most 8:1")
                if image.format == "PNG" and ("A" in image.getbands() or "transparency" in image.info):
                    _invalid("Wan 3 PNG images cannot contain an alpha channel")
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            _invalid("Wan 3 image cannot be decoded")

    def _resource_url(self, value):
        if self.use_mock or self.is_remote_resource(value) or value.startswith("data:image/"):
            return value
        return self.upload_local_file_get_oss_url(self.model_id, value)
