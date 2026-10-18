"""Qwen Image 3.0 async messages protocol on the configured legacy endpoint."""
import base64
import binascii
import io
import re
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

from app.adapters.dashscope_common import DashScopeGenerationAdapter
from app.api import AppError


class DashScopeQwenImageAdapter(DashScopeGenerationAdapter):
    provider_name = "dashscope"
    task_type = "text_to_image"
    output_kind = "image"
    MAX_IMAGE_BYTES = 10 * 1024 * 1024
    PARAMETERS = frozenset({"size", "n", "prompt_extend", "prompt_extend_mode", "enable_thinking",
                            "negative_prompt", "watermark", "seed"})
    IMAGE_MIMES = {"JPEG": "image/jpeg", "PNG": "image/png", "BMP": "image/bmp", "TIFF": "image/tiff",
                   "WEBP": "image/webp", "GIF": "image/gif"}

    def create_url(self) -> str:
        return f"{self.dashscope_base_url()}/services/aigc/image-generation/generation"

    def submission_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key()}", "Content-Type": "application/json",
                "X-DashScope-Async": "enable"}

    @staticmethod
    def _references(inputs):
        images = inputs.get("source_images") or []
        if not isinstance(images, list):
            raise AppError("INVALID_INPUT", "source_images must be a list", 422)
        # Classic batch input also carries an annotated reference list. Its
        # primary file is the established actual image input in that format.
        if images and all(isinstance(value, dict) for value in images) and inputs.get("source_image"):
            images = [inputs["source_image"]]
        elif not images and inputs.get("source_image"):
            images = [inputs["source_image"]]
        if len(images) > 3 or any(not isinstance(value, str) or not value.strip() for value in images):
            raise AppError("INVALID_INPUT", "Qwen Image accepts at most three nonempty image references", 422)
        return images

    def _image_url(self, value):
        raw = value.strip()
        if self.is_http_url(raw):
            parsed = urlsplit(raw)
            if not parsed.hostname or parsed.username or parsed.password:
                raise AppError("INVALID_INPUT", "Invalid public image URL", 422)
            # The provider validates remote media; the application never fetches
            # arbitrary URLs here. Agent inputs are owned, local artifacts.
            return raw
        if raw.lower().startswith("data:"):
            if len(raw) > self.MAX_IMAGE_BYTES * 4 // 3 + 256:
                raise AppError("INVALID_INPUT", "Reference image exceeds 10 MiB", 422)
            match = re.fullmatch(r"data:(image/[a-zA-Z0-9.+-]+);base64,(.+)", raw, re.DOTALL)
            if not match:
                raise AppError("INVALID_INPUT", "Expected a base64 image data URL", 422)
            try:
                content = base64.b64decode(match.group(2), validate=True)
            except (ValueError, binascii.Error) as error:
                raise AppError("INVALID_INPUT", "Invalid image base64", 422) from error
        else:
            if raw.lower().startswith("oss://"):
                raise AppError("INVALID_INPUT", "Qwen Image 3.0 requires HTTP(S) or base64 image input", 422)
            path = self.resolve_path(raw)
            if not path.is_file() or path.stat().st_size > self.MAX_IMAGE_BYTES:
                raise AppError("INVALID_INPUT", "Reference image is missing or exceeds 10 MiB", 422)
            content = path.read_bytes()
        if not content or len(content) > self.MAX_IMAGE_BYTES:
            raise AppError("INVALID_INPUT", "Reference image must be nonempty and at most 10 MiB", 422)
        try:
            with Image.open(io.BytesIO(content)) as img:
                width, height = img.size
                mime = self.IMAGE_MIMES.get(img.format)
                if not mime or not (1 <= width <= 8000 and 1 <= height <= 8000) or max(width / height, height / width) > 10:
                    raise ValueError("Unsupported image format, dimensions or aspect ratio")
                img.verify()
            with Image.open(io.BytesIO(content)) as img:
                img.load()
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise AppError("INVALID_INPUT", "Invalid Qwen reference image", 422) from error
        return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"

    def build_payload(self, inputs: dict, params: dict) -> dict:
        parameters = {**(getattr(self.model, "default_params", None) or {}), **params}
        unknown = set(parameters) - self.PARAMETERS
        if unknown:
            raise AppError("INVALID_INPUT", f"Unsupported Qwen image parameters: {', '.join(sorted(unknown))}", 422)
        prompt = inputs.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise AppError("INVALID_INPUT", "Image generation requires a text prompt", 422)
        images = self._references(inputs)
        count = parameters.get("n", 1)
        if type(count) is not int or not 1 <= count <= 6:
            raise AppError("INVALID_INPUT", "n must be an integer between 1 and 6", 422)
        parameters["n"] = count
        for key in ("prompt_extend", "enable_thinking", "watermark"):
            if key in parameters and type(parameters[key]) is not bool:
                raise AppError("INVALID_INPUT", f"{key} must be a boolean", 422)
        mode = parameters.get("prompt_extend_mode", "direct")
        if mode not in {"direct", "agent"} or (images and mode == "agent"):
            raise AppError("INVALID_INPUT", "prompt_extend_mode=agent is only supported for text-to-image", 422)
        if "size" in parameters:
            size = parameters["size"]
            match = re.fullmatch(r"([1-9][0-9]{0,4})\*([1-9][0-9]{0,4})", size) if isinstance(size, str) else None
            if not match:
                raise AppError("INVALID_INPUT", "size must be width*height", 422)
            width, height = map(int, match.groups())
            if not 512**2 <= width * height <= 2048**2 or not 1 / 8 <= width / height <= 8:
                raise AppError("INVALID_INPUT", "size is outside the Qwen Image pixel/aspect limits", 422)
        if "seed" in parameters and (type(parameters["seed"]) is not int or not 0 <= parameters["seed"] <= 2147483647):
            raise AppError("INVALID_INPUT", "seed must be an integer in [0, 2147483647]", 422)
        if "negative_prompt" in parameters and not isinstance(parameters["negative_prompt"], str):
            raise AppError("INVALID_INPUT", "negative_prompt must be a string", 422)
        content = [{"image": self._image_url(value)} for value in images]
        content.append({"text": prompt.strip()})
        return {"model": self.model_id, "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": parameters}
