from typing import Literal

from flask import current_app
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.clarify import Answer
from app.agent.plan_spec import PlanSpec, RemixShotSpec
from app.agent.model_policy import select_video_model
from app.api import AppError
from app.skills import model_guard
from app.services.model_service import ModelService


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=2, max_length=8000)
    attachment_ids: list[str] = Field(default_factory=list)
    budget_limit: float = Field(default_factory=lambda: current_app.config["AGENT_DEFAULT_BUDGET"],
                                gt=0, allow_inf_nan=False)
    request_key: str = Field(min_length=1, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def _v2_input(cls, data):
        if isinstance(data, dict):
            deprecated = sorted(set(data) & {"goal", "mode", "shot_count", "video_model_preference", "source_artifact_id"})
            if deprecated:
                raise AppError("DEPRECATED_FIELD", "Use text and attachment_ids for new Agent runs", 422,
                               payload={"fields": deprecated})
            text = data.get("text")
            if not isinstance(text, str) or not 2 <= len(text.strip()) <= 8000:
                raise AppError("TEXT_REQUIRED", "Provide a text request of 2 to 8000 characters", 422)
        return data

    @model_validator(mode="after")
    def _attachments(self):
        if (len(self.attachment_ids) > current_app.config["AGENT_MAX_ATTACHMENTS"]
                or len(set(self.attachment_ids)) != len(self.attachment_ids)
                or any(not value or len(value) > 80 for value in self.attachment_ids)):
            raise AppError("INVALID_ATTACHMENT", "Attachment IDs must be unique and within the configured limit", 422)
        return self


class RunAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject", "deliver", "resume", "revise", "answer"]
    plan: dict | None = None
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
    minimum = current_app.config["AGENT_MIN_RUN_CREDITS"]
    if minimum > data.budget_limit:
        raise AppError("BUDGET_EXCEEDED", f"This request needs at least {minimum} estimated credits", 402)
