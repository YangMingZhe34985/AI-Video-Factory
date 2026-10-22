"""Capability-based generation choices from structured user constraints."""

import re
import unicodedata
from fractions import Fraction
from math import gcd, isfinite

from flask import current_app

from app.agent.request_spec import RequestSpec
from app.api import AppError
from app.models import ModelRegistry
from app.services.model_service import ModelService
from app.services.workflow_service import WorkflowService
from app.skills import model_guard

MODES = {
    "t2i": ("text_to_image", "submit_first_frame_image", "DEFAULT_IMAGE_MODEL"),
    "i2i": ("text_to_image", "submit_first_frame_image", "DEFAULT_I2I_TEST_IMAGE_MODEL"),
    "t2v": ("text_to_video", "submit_t2v", "DEFAULT_T2V_MODEL"),
    "i2v": ("image_to_video", "submit_i2v", "DEFAULT_I2V_MODEL"),
    "r2v": ("reference_to_video", "submit_r2v_flash", "DEFAULT_R2V_FLASH_MODEL"),
}
TRANSFORM_MODES = {"omni_reference", "video_edit", "video_extend"}
MODES.update({mode: ("reference_to_video", "submit_r2v_flash", "DEFAULT_R2V_FLASH_MODEL")
              for mode in TRANSFORM_MODES})
VIDEO_MODES = {"t2v", "i2v", "r2v"} | TRANSFORM_MODES


def _normal(value):
    return re.sub(r"[\s_-]+", "", unicodedata.normalize("NFKC", value).casefold())


def _label(value):
    return re.sub(r"(?:\s*(?:系列|(?:的)?(?:视频|图像|图片)?(?:生成)?模型|family|series|models?))+\s*$", "", value, flags=re.I).strip()


def _matches_selector(value, model):
    label = _label(value)
    if ModelService.canonical_model_id(label) == model.model_id or _normal(label) == _normal(model.display_name):
        return True
    family = ModelService.model_family(model)
    prefix, name = _normal(label), _normal(family)
    return name == prefix or (name.startswith(prefix) and prefix[-1:].isalpha())


def _selectors(value, catalog):
    """Registered model IDs or families named in a preference written as a sentence.

    Briefs keep the user's wording ("图片使用wan2.7-image模型"); matching uses the
    names inside it. The longest name wins, so wan2.7-image is not read as the
    wan2.7 family. Text without any registered name stays as-is and keeps failing visibly.
    """
    if any(_matches_selector(value, item) for item in catalog):
        return [value]
    text = unicodedata.normalize("NFKC", value).casefold()
    names = {}
    for item in catalog:
        family = ModelService.model_family(item)
        for alias, selector in ((item.model_id, item.model_id), (item.display_name, item.model_id),
                                (family, f"{family}系列")):
            parts = [re.escape(part) for part in re.split(r"[\s_-]+", unicodedata.normalize("NFKC", alias or "").casefold()) if part]
            if parts:
                # Separators are optional between name parts: "Wan 2.7 I2V", "wan2.7-i2v".
                names.setdefault(r"[\s_-]*".join(parts), (len(_normal(alias)), selector))
    found, spans = [], []
    for pattern, (_length, selector) in sorted(names.items(), key=lambda item: item[1][0], reverse=True):
        # wan2.7 must not match inside wan2.70 or xwan2.7; English words around it are fine.
        for match in re.finditer(r"(?<![0-9a-z.])" + pattern + r"(?![0-9a-z]|\.[0-9])", text):
            if not any(match.start() < right and left < match.end() for left, right in spans):
                spans.append((match.start(), match.end()))
                found.append(selector)
    return list(dict.fromkeys(found)) or [value]


def _matches(value, model, catalog=None):
    catalog = catalog if catalog is not None else ModelRegistry.query.all()
    return any(_matches_selector(selector, model) for selector in _selectors(value, catalog))


def constraints_for_mode(spec, mode):
    """A model or family constrains each generation type it actually has models for.

    A family such as wan2.7 with both image and video models therefore applies to
    images and videos; wan2.7-i2v only to video. Returned values keep the brief text.
    """
    spec = RequestSpec.model_validate(spec)
    catalog = ModelRegistry.query.order_by(ModelRegistry.model_id).all()

    def belongs(value):
        if spec.deliverable == "image":
            return mode not in VIDEO_MODES
        # The user's own scope word wins: "wan2.7系列视频模型" limits video only,
        # "图片用wan2.7" limits images only; "图生视频" counts as video.
        video_scope = "视频" in value or re.search(r"\bvideos?\b", value, re.I)
        image_scope = re.search(r"图片|图像|生图|\bimages?\b", value, re.I)
        if video_scope and not image_scope and mode not in VIDEO_MODES:
            return False
        if image_scope and not video_scope and mode in VIDEO_MODES:
            return False
        matches = []
        for selector in _selectors(value, catalog):
            exact = [item for item in catalog if ModelService.canonical_model_id(_label(selector)) == item.model_id
                     or _normal(_label(selector)) == _normal(item.display_name)]
            matches += exact or [item for item in catalog if _matches_selector(selector, item)]
        if not matches:
            # Unknown names stay on the video side, where they fail visibly.
            return mode in VIDEO_MODES
        if mode in VIDEO_MODES:
            return any(item.task_type != "text_to_image" for item in matches)
        return any(item.task_type == "text_to_image" for item in matches)

    return ([value for value in spec.constraints.model_preferences if belongs(value)],
            [value for value in spec.constraints.model_exclusions if belongs(value)])


def default_model_id(mode):
    _task, node_key, config_key = MODES[mode]
    # I2I has its own configured default; the shared image execution node's
    # t2i model override must not make that independent default unusable.
    node_model = None if mode == "i2i" else (WorkflowService.get_node(node_key).config or {}).get("model_id")
    return ModelService.canonical_model_id(node_model or current_app.config[config_key])


def candidates_for_request(spec, mode, *, use_default=True):
    requested, excluded = constraints_for_mode(spec, mode)
    task_type = MODES[mode][0]
    catalog = ModelRegistry.query.order_by(ModelRegistry.model_id).all()
    models = [item for item in catalog if item.enabled
              and ModelService.supports_task_type(item, task_type) and (item.capabilities or {}).get("agent_selectable")
              and mode in (item.capabilities or {}).get("modes", [])]
    def matches_selector(value, item):
        explicit_family = re.search(r"系列|\b(?:family|series)\b", value, re.I)
        exact = [] if explicit_family else [model.model_id for model in catalog
            if ModelService.canonical_model_id(_label(value)) == model.model_id
            or _normal(_label(value)) == _normal(model.display_name)]
        return item.model_id in exact if exact else _matches_selector(value, item)

    def matches(value, item):
        return any(matches_selector(selector, item) for selector in _selectors(value, catalog))
    for value in requested:
        models = [item for item in models if matches(value, item)]
    models = [item for item in models if not any(matches(value, item) for value in excluded)]
    if use_default and not requested:
        models = [item for item in models if item.model_id == default_model_id(mode)]
    return models


def select_for_request(spec, mode, requested=None):
    models = {item.model_id: item for item in candidates_for_request(spec, mode)}
    chosen = ModelService.canonical_model_id(requested) if requested else default_model_id(mode)
    if chosen in models:
        return models[chosen]
    if not requested and models:
        return models[sorted(models)[0]]
    raise AppError("MODEL_CAPABILITY_MISMATCH", f"没有符合当前模型要求的 {mode} 模型", 422,
                   payload={"mode": mode, "model_id": requested, "allowed_model_ids": sorted(models)})


def video_policy_for_request(spec):
    requested, excluded = constraints_for_mode(spec, "i2v")
    return {
        "source": "user" if requested or excluded else "server_default",
        "requested": requested, "excluded": excluded,
        "defaults": {mode: default_model_id(mode) for mode in sorted(VIDEO_MODES)},
        "allowed_model_ids": sorted({item.model_id for mode in VIDEO_MODES
                                     for item in candidates_for_request(spec, mode)}) if requested or excluded else [],
    }


def validate_generation_model(model, mode, params=None, reference_count=0):
    """Freeze effective parameters and validate catalog plus provider schema."""
    capabilities = model.capabilities or {}
    if (not model.enabled or not ModelService.supports_task_type(model, MODES[mode][0]) or not capabilities.get("agent_selectable")
            or mode not in capabilities.get("modes", [])):
        raise AppError("MODEL_CAPABILITY_MISMATCH", f"Model {model.model_id} cannot perform {mode}", 422)
    node_config = WorkflowService.get_node(MODES[mode][1]).config or {}
    supplied = model_guard.validate_params(model, params or {})
    effective = {key: value for key, value in ModelService.effective_params(model).items()
                 if key in (model.parameter_schema or {})}
    effective.update(node_config.get("model_params") or {})
    effective.update(supplied)
    effective = model_guard.validate_params(model, effective)
    errors = []
    if mode in VIDEO_MODES:
        duration = effective.get("duration")
        bounds = capabilities.get("duration") or {}
        if (isinstance(duration, bool) or not isinstance(duration, (int, float)) or not isfinite(duration)
                or not bounds or duration < bounds["min"] or duration > bounds["max"]):
            errors.append("duration is outside the model capability range")
        elif bounds.get("step") is not None:
            step = bounds["step"]
            if isinstance(step, bool) or not isinstance(step, (int, float)) or not isfinite(step) or step <= 0:
                errors.append("duration capability step must be a positive finite number")
            elif ((Fraction(str(duration)) - Fraction(str(bounds["min"]))) / Fraction(str(step))).denominator != 1:
                errors.append("duration does not match the model capability step")
    if "resolution" in effective and effective["resolution"] not in capabilities.get("resolutions", []):
        errors.append("resolution is not supported by the model capability catalog")
    ratio = effective.get("ratio")
    if effective.get("size") and re.fullmatch(r"\d+\*\d+", str(effective["size"])):
        width, height = map(int, effective["size"].split("*"))
        divisor = gcd(width, height)
        ratio = f"{width // divisor}:{height // divisor}" if divisor else None
    dynamic_size = effective.get("size") and (model.parameter_schema or {}).get("size", {}).get("format") == "image_size"
    if ratio and not dynamic_size and ratio not in capabilities.get("aspect_ratios", []):
        errors.append("aspect ratio is not supported by the model capability catalog")
    if mode == "i2i" and effective.get("prompt_extend_mode") == "agent":
        errors.append("agent prompt extension is not available with reference images")
    maximum = (capabilities.get("reference_images") or {}).get("max", 0)
    if reference_count > maximum or (mode in {"i2i", "i2v", "r2v"} and reference_count < 1):
        errors.append(f"reference image count is not supported (requested {reference_count}, model max {maximum})")
    if mode in {"t2i", "t2v"} and reference_count:
        errors.append("text-only generation does not accept reference images")
    if errors:
        raise AppError("MODEL_CAPABILITY_MISMATCH",
                       f"Model {model.model_id} cannot execute this step: {'; '.join(errors)}", 422,
                       payload={"errors": errors, "mode": mode})
    return effective
