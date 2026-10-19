"""Capacity-aware image selection limited to v3 Plan authoring.

This module never changes the shared v2 selector, drops identity references or
changes a concrete node model. Approval and cost checks remain authoritative.
"""
import re

from app.adapters import ADAPTERS
from app.agent.model_selection import (
    _label, _normal, candidates_for_request, constraints_for_mode,
    validate_generation_model,
)
from app.agent.production_plan import select_plan_model
from app.api import AppError
from app.models import ModelRegistry
from app.services.model_service import ModelService


def _capacity(model):
    value = ((model.capabilities or {}).get("reference_images") or {}).get("max")
    return value if type(value) is int and value >= 1 else None


def _exact_user_choice(request_spec, mode):
    requested, _excluded = constraints_for_mode(request_spec, mode)
    catalog = ModelRegistry.query.all()
    for value in requested:
        if re.search(r"系列|\b(?:family|series)\b", value, re.I):
            continue
        label = _label(value)
        canonical = ModelService.canonical_model_id(label)
        if any(item.model_id == canonical or _normal(item.display_name) == _normal(label)
               for item in catalog):
            return True
    return False


def select_generation_model(request_spec, mode, model_id, params=None, *,
                            reference_count=0, run=None, slot=None, params_factory=None):
    """Return the selected model and fully validated, frozen parameters.

    Unspecified model IDs use deterministic catalog order only after the normal
    policy model demonstrably lacks reference capacity. A concrete ID must stay
    unchanged and belong to that same constrained pool. The latter also permits
    recompiling normalized plans, including model-specific parameter defaults.
    """
    def validate(model):
        if model.adapter_name not in ADAPTERS:
            raise AppError("MODEL_CAPABILITY_MISMATCH", "Model adapter is not integrated", 422)
        supplied = params_factory(model) if params_factory else params or {}
        return validate_generation_model(model, mode, supplied, reference_count=reference_count)

    selected_id = ModelService.canonical_model_id(model_id) if model_id else None
    is_v3 = run is not None and (run.request or {}).get("schema_version") == 3
    if not is_v3 or mode != "i2i" or reference_count <= 1 or _exact_user_choice(request_spec, mode):
        selected = select_plan_model(request_spec, mode, selected_id, run=run, slot=slot)
        return selected, validate(selected)

    # Disabled, excluded, unknown or unintegrated defaults are configuration
    # errors. They cannot enable model substitution or bypass user constraints.
    primary = select_plan_model(request_spec, mode, None, run=run, slot=slot)
    if primary.adapter_name not in ADAPTERS:
        raise AppError("MODEL_CAPABILITY_MISMATCH", "Model adapter is not integrated", 422)
    maximum = _capacity(primary)
    if maximum is None or reference_count <= maximum:
        selected = select_plan_model(request_spec, mode, selected_id, run=run, slot=slot)
        return selected, validate(selected)

    pool = sorted((item for item in candidates_for_request(request_spec, mode, use_default=False)
                   if item.adapter_name in ADAPTERS and _capacity(item) is not None
                   and _capacity(item) >= reference_count), key=lambda item: item.model_id)
    if selected_id:
        selected = next((item for item in pool if item.model_id == selected_id), None)
        if selected is not None:
            return selected, validate(selected)
        raise AppError("MODEL_CAPABILITY_MISMATCH",
            f"Requested {reference_count} reference images; the selected model is not an eligible multi-reference model",
            422, payload={"mode": mode, "allowed_model_ids": [item.model_id for item in pool]})

    for candidate in pool:
        try:
            return candidate, validate(candidate)
        except AppError as exc:
            if exc.code not in {"INVALID_INPUT", "MODEL_CAPABILITY_MISMATCH"}:
                raise
            # Try a different eligible model, but never alter caller parameters.
            continue
    raise AppError("MODEL_CAPABILITY_MISMATCH",
        f"Requested {reference_count} reference images; policy model {primary.model_id} supports {maximum}, "
        "and no eligible model accepts all supplied parameters",
        422, payload={"mode": mode, "allowed_model_ids": [item.model_id for item in pool]})
