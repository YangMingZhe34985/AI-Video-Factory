"""Evaluation-only rendered geometry from submitted Mock media parameters."""
import re

from app.plans.aspect import ASPECTS, dimensions, ratio_for, target_size
from app.services.storage_service import StorageService


def rendered_size(payload, *, image=False):
    params = payload.get("parameters") or {}
    size = dimensions(params.get("size"))
    if size:
        if max(size) > 8192 or size[0] * size[1] > 16_777_216:
            raise RuntimeError("Mock canvas exceeds the local rendering bound")
        return size
    aspect = params.get("ratio")
    if aspect is not None and aspect not in ASPECTS | {"adaptive"}:
        raise RuntimeError("Mock media has unsupported explicit ratio")
    if aspect in {None, "adaptive"}:
        inputs = payload.get("inputs") or {}
        frame = inputs.get("first_frame_image")
        if frame:
            from PIL import Image, ImageOps
            value = str(frame)
            scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
            absolute_drive = re.match(r"^[A-Za-z]:[\\/]", value)
            # Reject network/device paths before Windows resolves them.
            if value.replace("\\", "/").startswith("//") or (scheme and not absolute_drive):
                raise RuntimeError("Mock frame must be a local managed file")
            path = StorageService.resolve(frame).resolve()
            if not path.is_relative_to(StorageService.root()) or not path.is_file():
                raise RuntimeError("Mock frame must be a local managed file")
            with Image.open(path) as source:
                aspect = ratio_for(*ImageOps.exif_transpose(source).size)
            if aspect not in ASPECTS:
                # Nonstandard approved frames remain local but are not silently
                # reshaped to 16:9. Keep their actual even geometry.
                with Image.open(path) as source:
                    width, height = ImageOps.exif_transpose(source).size
                if width % 2 or height % 2 or max(width, height) > 8192:
                    raise RuntimeError("Mock video frame needs supported even dimensions")
                return width, height
    if aspect not in ASPECTS:
        return (640, 360) if image else (320, 180)
    resolution = re.fullmatch(r"([1-9][0-9]{2,3})P", str(params.get("resolution", "720P")))
    if resolution is None:
        raise RuntimeError("Mock video has invalid nominal resolution")
    return dimensions(target_size(aspect, int(resolution[1])))
