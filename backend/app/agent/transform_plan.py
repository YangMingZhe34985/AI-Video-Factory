"""Authoritative, read-only quotes for one native video transformation."""
import hashlib
import json
from math import ceil, isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.model_selection import candidates_for_request, select_for_request, validate_generation_model
from app.agent.request_spec import RequestSpec
from app.agent.transform_media import MediaReference
from app.api import AppError
from app.services.model_service import ModelService
from app.skills.budget import BudgetGuard, estimate_model_cost

OPERATION_MODES = {"reference": "omni_reference", "edit": "video_edit", "extend": "video_extend"}


class TransformPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    recipe: Literal["video_transform"] = "video_transform"
    operation: Literal["reference", "edit", "extend"]
    title: str = Field(min_length=1, max_length=200)
    model_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=8000)
    params: dict = Field(default_factory=dict)
    media: list[MediaReference] = Field(min_length=1, max_length=20)
    source_artifact_id: str | None = None
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    rationale: str = Field(min_length=1, max_length=1000)
    manifest: list[dict] = Field(default_factory=list)
    cost_breakdown: dict = Field(default_factory=dict)
    plan_hash: str = ""
    quote_id: str = ""
    estimated_cost: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_media(self):
        ids = [item.artifact_id for item in self.media]
        if len(set(ids)) != len(ids):
            raise ValueError("Transform media IDs must be unique")
        if self.operation == "reference" and self.source_artifact_id is not None:
            raise ValueError("Reference generation has no primary video source")
        if self.operation in {"edit", "extend"} and not self.source_artifact_id:
            raise ValueError("Editing/extension requires a primary video source")
        return self


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def execution_hash(plan):
    value = plan.model_dump(mode="json") if isinstance(plan, BaseModel) else plan
    return stable_hash({key: value[key] for key in ("operation", "model_id", "prompt", "params", "media",
                                                  "source_artifact_id", "manifest")})


def approval_request_spec(request_spec, original_plan, edited_plan):
    """An explicit model edit may replace the default, never a hard preference."""
    spec = RequestSpec.model_validate(request_spec).model_copy(deep=True)
    chosen = ModelService.canonical_model_id(edited_plan.get("model_id"))
    original = ModelService.canonical_model_id((original_plan or {}).get("model_id"))
    if chosen and chosen != original:
        mode = OPERATION_MODES[spec.transform.operation]
        if chosen not in {model.model_id for model in candidates_for_request(spec, mode, use_default=False)}:
            raise AppError("MODEL_CAPABILITY_MISMATCH", "Edited model conflicts with the request constraints", 422)
        spec.constraints.model_preferences = list(dict.fromkeys([*spec.constraints.model_preferences, chosen]))
    return spec.model_dump(mode="json")


def _changed(message="Approved reference media changed"):
    return AppError("TRANSFORM_INPUT_CHANGED", message, 409)


def _verify_manifest(original, current):
    expected = {item.get("artifact_id"): item for item in original}
    for item in current:
        if item["artifact_id"] in expected and expected[item["artifact_id"]] != item:
            raise _changed()


def validate_transform_plan(raw, spec, *, run, require_quote=False, check_budget=True):
    """Recompute every billable field; never accept client duration metadata."""
    from app.agent.transform_media import assert_manifest, inspect_transform_media
    spec = RequestSpec.model_validate(spec)
    plan = TransformPlan.model_validate(raw).model_copy(deep=True)
    if spec.recipe_hint != "video_transform" or plan.operation != spec.transform.operation:
        raise AppError("INVALID_PLAN", "Transform operation must match the understood request", 422)
    if plan.source_artifact_id != spec.transform.source_attachment_id:
        raise AppError("INVALID_PLAN", "Transform source must match the understood request", 422)
    mode = OPERATION_MODES[plan.operation]
    model = select_for_request(spec, mode, plan.model_id)
    plan.model_id = model.model_id
    references = sum(item.type == "reference_image" for item in plan.media)
    plan.params = validate_generation_model(model, mode, plan.params, reference_count=references)
    if plan.params.get("n_outputs", 1) != 1:
        raise AppError("INVALID_PLAN", "Transform generation requires exactly one output", 422)
    if any(item.type == "file" for item in plan.media) and plan.params.get("prompt_extend") is not True:
        raise AppError("INVALID_PLAN", "Document references require prompt_extend=true", 422)
    used = {item.attachment_id for item in spec.attachments if item.role != "unused"}
    uploaded = set(run.request.get("attachment_ids", []))
    actual = {item.artifact_id for item in plan.media}
    if not used <= actual or (actual & uploaded) != used:
        raise AppError("INVALID_PLAN", "Media must preserve every understood attachment without adding unused inputs", 422)
    baseline = ((run.snapshot or {}).get("plan") or {}).get("manifest") or []
    approved = (((run.snapshot or {}).get("transform") or {}).get("plan") or {}).get("manifest") or []
    for frozen in (baseline, approved, plan.manifest):
        by_id = {item.get("artifact_id"): item for item in frozen}
        retained = [ref for ref in plan.media if ref.artifact_id in by_id]
        if retained:
            try:
                assert_manifest(retained, run=run, expected_manifest=[by_id[ref.artifact_id] for ref in retained])
            except AppError as error:
                raise _changed() from error
    inspected = inspect_transform_media(plan.media, run=run, operation=plan.operation,
                                        source_artifact_id=plan.source_artifact_id)
    manifest = inspected["manifest"]
    # Existing quotes cannot accept replaced bytes even after a client clears
    # their read-only manifest. Unchanged references keep the original binding.
    _verify_manifest(baseline, manifest)
    _verify_manifest(approved, manifest)
    _verify_manifest(plan.manifest, manifest)
    snapshots = [item for item in manifest if item.get("source_url")]
    if ({item["source_url"] for item in snapshots} != set(spec.transform.reference_urls)
            or actual - uploaded != {item["artifact_id"] for item in snapshots}):
        raise AppError("INVALID_PLAN", "Captured page references must match the original requested URLs", 422)
    incoming, source = inspected["input_video_seconds"], inspected["source_video_seconds"]
    output = plan.params.get("duration")
    if isinstance(output, bool) or not isinstance(output, int) or not 2 <= output <= 30:
        raise AppError("INVALID_PLAN", "Generated duration must be an integer from 2 to 30 seconds", 422)
    if (isinstance(incoming, bool) or not isinstance(incoming, (int, float)) or not isfinite(incoming)
            or incoming < 0 or incoming > 15 or incoming + output > 30):
        raise AppError("INVALID_PLAN", "Input videos plus generated output must fit within 30 seconds (input at most 15)", 422)
    if plan.operation in {"edit", "extend"} and (not isinstance(source, (int, float)) or isinstance(source, bool)
                                                 or not isfinite(source) or source <= 0):
        raise AppError("INVALID_PLAN", "A verified source video duration is required", 422)
    if plan.operation == "extend" and output <= source:
        raise AppError("INVALID_PLAN", "Extended output must be longer than its source", 422)
    additional = spec.transform.additional_duration_sec
    target = spec.target_duration_sec
    if additional is not None and target is not None and target != ceil(source + additional):
        raise AppError("TRANSFORM_DURATION_CONFLICT", "Final duration conflicts with the requested additional duration; clarify the request", 422)
    # The plan is editable: deliberate output-duration edits remain visible at
    # approval, while the original user target is retained for comparison.
    pricing = (model.capabilities or {}).get("pricing") or {}
    if pricing.get("unit") != "second" or pricing.get("billing_basis") != "input_plus_output_seconds":
        raise AppError("INVALID_PLAN", "Transform models require input-plus-output per-second pricing", 422)
    cost = estimate_model_cost(model, plan.params, input_video_seconds=incoming)
    rate = cost / (incoming + output)
    if not isfinite(rate) or rate < 0:
        raise AppError("INVALID_PLAN", "Transform pricing is invalid", 422)
    plan.manifest = manifest
    plan.cost_breakdown = {"input_video_seconds": incoming, "source_video_seconds": source,
        "output_video_seconds": output, "final_duration_seconds": output,
        "extension_seconds": max(0, output - source) if source is not None else None,
        "n_outputs": 1, "billable_seconds": incoming + output, "credits_per_second": rate,
        "estimated_cost": cost, "resolution": plan.params.get("resolution"),
        "billing_basis": "input_plus_output_seconds", "demo": True}
    plan.estimated_cost = cost
    plan.plan_hash = execution_hash(plan)
    plan.quote_id = stable_hash({"plan_hash": plan.plan_hash, "pricing": pricing,
                                 "cost_breakdown": plan.cost_breakdown})
    if require_quote and (not raw.get("quote_id") or raw.get("quote_id") != plan.quote_id
                          or raw.get("plan_hash") != plan.plan_hash or raw.get("manifest") != plan.manifest):
        raise AppError("TRANSFORM_QUOTE_EXPIRED", "Transform quote changed; refresh it before approval", 409)
    if check_budget:
        BudgetGuard.check(run.run_id, run.request["budget_limit"], cost)
    return plan.model_dump(mode="json")
