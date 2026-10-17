from typing import Literal

from flask import current_app
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.clarify import Answer
from app.agent.plan_spec import PlanSpec, RemixShotSpec
from app.agent.model_policy import build_policy, select_video_model
from app.api import AppError
from app.skills import model_guard
from app.skills.budget import estimate_nodes_cost, planner_cost
from app.services.model_service import ModelService


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    goal: str = Field(min_length=1, max_length=8000)
    shot_count: int = Field(default=3, ge=1, le=20, strict=True)
    budget_limit: float = Field(default=100, gt=0, allow_inf_nan=False)
    request_key: str = Field(min_length=1, max_length=128)
    video_model_preference: str | None = Field(default=None, min_length=1, max_length=120)
    mode: Literal["from_scratch", "remix"] = "from_scratch"
    source_artifact_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def _source_matches_mode(self):
        if (self.mode == "remix") != bool(self.source_artifact_id):
            raise ValueError("Only remix runs require source_artifact_id")
        return self


class RunAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject", "deliver", "resume", "revise", "answer"]
    plan: PlanSpec | None = None
    shot: RemixShotSpec | None = None
    request_key: str | None = Field(default=None, min_length=1, max_length=128)
    card_id: str | None = Field(default=None, min_length=1, max_length=80)
    answers: list[Answer] = Field(default_factory=list, max_length=3)
    use_defaults: bool = False

    @model_validator(mode="after")
    def _revision_input(self):
        if (self.action == "answer") != (self.card_id is not None):
            raise ValueError("Only answer requires a card_id")
        if self.action != "answer" and (self.answers or self.use_defaults):
            raise ValueError("answers and use_defaults are only valid for answer")
        if (self.action == "revise") != (self.shot is not None):
            raise ValueError("Only revise requires a shot")
        if (self.action == "revise") != bool(self.request_key):
            raise ValueError("Only revise requires a request_key")
        return self


def validate_plan(raw: dict, shot_count: int, budget_limit: float, video_model_policy: dict | None = None,
                  *, mode: str = "from_scratch", source_duration: float | None = None) -> dict:
    plan = PlanSpec.model_validate(raw)
    if plan.mode != mode:
        raise AppError("INVALID_PLAN", "Plan mode must match the original request", 422)
    if len(plan.shots) != shot_count:
        raise AppError("INVALID_PLAN", "Plan shot count must match the requested shot count", 422)
    for shot in plan.shots:
        try:
            validate_shot(shot, video_model_policy, source_duration=source_duration)
        except AppError as error:
            raise AppError(error.code, error.message, error.status_code,
                           payload={**error.payload, "shot_id": shot.shot_id}) from error
    # Quote the validated, pinned models and defaults that production will use.
    estimate = plan.estimated_cost
    if estimate > budget_limit:
        raise AppError("BUDGET_EXCEEDED", f"Plan needs {estimate} estimated credits", 402)
    return plan.model_dump(mode="json")


def validate_shot(shot, video_model_policy=None, *, source_duration=None):
    if isinstance(shot, RemixShotSpec):
        if source_duration is None or shot.source_end > source_duration:
            raise AppError("INVALID_PLAN", "Source segment must lie within the uploaded video", 422)
        if shot.action == "keep":
            shot.image_model_id = shot.video_model_id = None
            shot.image_params = {}
            shot.video_params = {}
            return shot
        if shot.first_frame_mode == "source":
            shot.image_model_id = None
            shot.image_params = {}
    for capability, node, model_field, params_field in (
        ("image", "submit_first_frame_image", "image_model_id", "image_params"),
        ("i2v", "submit_i2v", "video_model_id", "video_params"),
    ):
        if capability == "image" and isinstance(shot, RemixShotSpec) and shot.first_frame_mode == "source":
            continue
        model = (select_video_model(video_model_policy, "i2v", shot.video_model_id)
                 if capability == "i2v" and video_model_policy
                 else model_guard.effective_model(capability, node, getattr(shot, model_field)))
        params = model_guard.validate_params(model, getattr(shot, params_field))
        # Freeze exposed defaults; internal adapter options (e.g. interleave) are
        # not legal tool inputs and remain owned by the existing service.
        defaults = {key: value for key, value in ModelService.effective_params(model).items()
                    if key in (model.parameter_schema or {})}
        params = {**defaults, **params}
        if capability == "image" and params.get("n", 1) != 1:
            raise AppError("INVALID_PLAN", "Each shot must generate exactly one first frame", 422)
        model_guard.validate_params(model, params)
        setattr(shot, model_field, model.model_id)
        setattr(shot, params_field, params)
    return shot


def validate_request(data: CreateRun) -> None:
    if data.budget_limit > current_app.config.get("AGENT_MAX_BUDGET", 500):
        raise AppError("INVALID_INPUT", "Budget exceeds the server limit", 422)
    minimum = 2 * planner_cost()
    if data.mode == "remix":
        minimum += estimate_nodes_cost(["reverse_prompts"])
    else:
        policy = build_policy(data.goal, data.video_model_preference)
        video = select_video_model(policy, "i2v")
        minimum += data.shot_count * estimate_nodes_cost(
            ["submit_first_frame_image", "submit_i2v"], node_models={"submit_i2v": video.model_id})
    if minimum > data.budget_limit:
        raise AppError("BUDGET_EXCEEDED", f"This request needs at least {minimum} estimated credits", 402)
