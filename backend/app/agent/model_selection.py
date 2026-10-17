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
VIDEO_MODES = {"t2v", "i2v", "r2v"}


def _normal(value):
    return re.sub(r"[\s_-]+", "", unicodedata.normalize("NFKC", value).casefold())


def _label(value):
    return re.sub(r"\s*(?:系列|模型|family|series|model)\s*$", "", value, flags=re.I).strip()


def _matches(value, model):
    label = _label(value)
    if ModelService.canonical_model_id(label) == model.model_id or _normal(label) == _normal(model.display_name):
        return True
    family = re.split(r"[-_](?:t2v|i2v|r2v|image)(?:[-_]|$)", model.model_id, flags=re.I)[0]
    prefix, name = _normal(label), _normal(family)
    return name == prefix or (name.startswith(prefix) and prefix[-1:].isalpha())


def constraints_for_mode(spec, mode):
    """A video family constrains video generation, not its supporting images."""
    spec = RequestSpec.model_validate(spec)
    catalog = ModelRegistry.query.order_by(ModelRegistry.model_id).all()

    def belongs(value):
        if spec.deliverable == "image":
            return mode not in VIDEO_MODES
        exact = [item for item in catalog if ModelService.canonical_model_id(_label(value)) == item.model_id
                 or _normal(_label(value)) == _normal(item.display_name)]
        matches = exact or [item for item in catalog if _matches(value, item)]
        image_only = bool(matches) and all(item.task_type == "text_to_image" for item in matches)
        return image_only == (mode not in VIDEO_MODES)

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
    models = [item for item in ModelRegistry.query.filter_by(task_type=task_type, enabled=True).order_by(ModelRegistry.model_id)
              if (item.capabilities or {}).get("agent_selectable")
              and mode in (item.capabilities or {}).get("modes", [])]
    for value in requested:
        models = [item for item in models if _matches(value, item)]
    models = [item for item in models if not any(_matches(value, item) for value in excluded)]
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
    if (not model.enabled or model.task_type != MODES[mode][0] or not capabilities.get("agent_selectable")
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
    if ratio and ratio not in capabilities.get("aspect_ratios", []):
        errors.append("aspect ratio is not supported by the model capability catalog")
    maximum = (capabilities.get("reference_images") or {}).get("max", 0)
    if reference_count > maximum or (mode in {"i2i", "i2v", "r2v"} and reference_count < 1):
        errors.append("reference image count is not supported")
    if mode in {"t2i", "t2v"} and reference_count:
        errors.append("text-only generation does not accept reference images")
    if errors:
        raise AppError("MODEL_CAPABILITY_MISMATCH", f"Model {model.model_id} cannot execute this step", 422,
                       payload={"errors": errors, "mode": mode})
    return effective
