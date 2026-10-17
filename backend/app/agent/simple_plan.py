"""Simple recipe approval contract and authoritative cost validation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.attachments import attachment_for_owner
from app.agent.model_selection import candidates_for_request, select_for_request, validate_generation_model
from app.agent.request_spec import RequestSpec
from app.api import AppError
from app.services.model_service import ModelService
from app.skills.budget import BudgetGuard, estimate_model_cost


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ImageStep(StrictModel):
    mode: Literal["t2i", "i2i"]
    model_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=8000)
    reference_attachment_ids: list[str] = Field(default_factory=list)
    params: dict = Field(default_factory=dict)
    n: int = Field(default=1, ge=1, le=4, strict=True)


class VideoStep(StrictModel):
    mode: Literal["i2v"] = "i2v"
    model_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=8000)
    first_frame: Literal["user_attachment", "generated_image"]
    first_frame_attachment_id: str | None = None
    params: dict = Field(default_factory=dict)


class SimplePlan(StrictModel):
    recipe: Literal["image_edit", "image_create", "single_clip"]
    title: str = Field(min_length=1, max_length=200)
    image: ImageStep | None = None
    video: VideoStep | None = None
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    rationale: str = Field(min_length=1, max_length=1000)
    estimated_cost: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_steps(self):
        if self.recipe == "single_clip":
            if not self.video:
                raise ValueError("single_clip requires a video step")
            generated = self.video.first_frame == "generated_image"
            if generated != bool(self.image) or generated == bool(self.video.first_frame_attachment_id):
                raise ValueError("The video must have exactly one first-frame source")
            if self.image and self.image.n != 1:
                raise ValueError("A video requires exactly one generated first frame")
        elif not self.image or self.video:
            raise ValueError("Image recipes require an image step and no video step")
        if self.recipe == "image_edit" and self.image.mode != "i2i":
            raise ValueError("image_edit requires i2i generation")
        if self.image:
            ids = self.image.reference_attachment_ids
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate image reference")
            if (self.image.mode == "i2i") != bool(ids):
                raise ValueError("Only i2i requires image references")
            if "n" in self.image.params and self.image.params["n"] != self.image.n:
                raise ValueError("Image params.n conflicts with the image step's n")
        return self


def approval_request_spec(request_spec, original_plan, edited_plan):
    """Record model edits as explicit user choices, preserving hard constraints."""
    spec = RequestSpec.model_validate(request_spec).model_copy(deep=True)
    original_plan = SimplePlan.model_validate(original_plan).model_dump(mode="json")
    edited_plan = SimplePlan.model_validate(edited_plan).model_dump(mode="json")
    preferences = list(spec.constraints.model_preferences)
    for kind in ("image", "video"):
        original, edited = (original_plan or {}).get(kind), (edited_plan or {}).get(kind)
        if not original or not edited:
            continue
        chosen = ModelService.canonical_model_id(edited.get("model_id"))
        if chosen == ModelService.canonical_model_id(original.get("model_id")):
            continue
        mode = edited.get("mode")
        if mode not in {"t2i", "i2i", "i2v"} or chosen not in {
            model.model_id for model in candidates_for_request(spec, mode, use_default=False)
        }:
            raise AppError("MODEL_CAPABILITY_MISMATCH", "Edited model conflicts with the request constraints", 422)
        preferences.append(chosen)
    spec.constraints.model_preferences = list(dict.fromkeys(preferences))
    return spec.model_dump(mode="json")


def validate_simple_plan(raw, request_spec, *, owner_id, budget_scope=None, budget_limit=None):
    spec = RequestSpec.model_validate(request_spec)
    plan = SimplePlan.model_validate(raw).model_copy(deep=True)
    if plan.recipe != spec.recipe_hint:
        raise AppError("INVALID_INPUT", "Plan recipe must match the understood request", 422)
    attachments = {item.attachment_id: item for item in spec.attachments}

    def require_image(artifact_id):
        use = attachments.get(artifact_id)
        if not use or use.kind != "image" or use.role == "unused":
            raise AppError("INVALID_ATTACHMENT", "Image reference is not part of the understood request", 422)
        artifact = attachment_for_owner(artifact_id, owner_id)
        if artifact.meta["media"]["kind"] != "image":
            raise AppError("INVALID_ATTACHMENT", "Reference is not an image", 422)

    cost = 0.0
    if plan.image:
        for artifact_id in plan.image.reference_attachment_ids:
            require_image(artifact_id)
        model = select_for_request(spec, plan.image.mode, plan.image.model_id)
        plan.image.model_id = model.model_id
        effective = validate_generation_model(
            model, plan.image.mode, {**plan.image.params, "n": plan.image.n},
            reference_count=len(plan.image.reference_attachment_ids),
        )
        cost += estimate_model_cost(model, effective)
        plan.image.params = {key: value for key, value in effective.items() if key != "n"}
    if plan.video:
        if plan.video.first_frame == "user_attachment":
            require_image(plan.video.first_frame_attachment_id)
        model = select_for_request(spec, "i2v", plan.video.model_id)
        plan.video.model_id = model.model_id
        plan.video.params = validate_generation_model(model, "i2v", plan.video.params, reference_count=1)
        cost += estimate_model_cost(model, plan.video.params)
    plan.estimated_cost = cost
    if budget_scope is not None:
        BudgetGuard.check(budget_scope, budget_limit, cost)
    elif budget_limit is not None and cost > budget_limit:
        raise AppError("BUDGET_EXCEEDED", "The plan exceeds its remaining budget", 402)
    return plan.model_dump(mode="json")
