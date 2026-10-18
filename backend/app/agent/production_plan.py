"""Structured story-board drafts and deterministic cost/dependency projection."""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.model_selection import candidates_for_request, constraints_for_mode, select_for_request
from app.skills.budget import estimate_model_cost


class PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class FrameSpec(PlanModel):
    method: Literal["generate", "tail_frame", "user_image"]
    image_mode: Literal["t2i", "i2i"] | None = None
    model_id: str | None = Field(default=None, max_length=120)
    prompt: str = Field(default="", max_length=8000)
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=24)


class MotionSpec(PlanModel):
    mode: Literal["i2v", "first_last_frame"] = "i2v"
    model_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(default="", max_length=8000)
    params: dict = Field(default_factory=dict)


class ShotPlan(PlanModel):
    shot_id: str = Field(pattern=r"^s[0-9]{2,3}$")
    scene_id: str = Field(min_length=1, max_length=80)
    order: int = Field(ge=1, strict=True)
    beat_ids: list[str] = Field(default_factory=list, max_length=40)
    character_ids: list[str] = Field(default_factory=list, max_length=8)
    summary: str = Field(min_length=1, max_length=300)
    framing: str = Field(min_length=1, max_length=120)
    duration_sec: float = Field(gt=0, le=600, strict=True)
    transition_in: Literal["start", "tail_frame", "independent", "keyframe_bridge", "hard_cut"]
    first_frame: FrameSpec
    end_frame: FrameSpec | None = None
    motion: MotionSpec
    depends_on: list[str] = Field(default_factory=list, max_length=30)
    rationale: str = Field(default="", max_length=300)


class Scene(PlanModel):
    scene_id: str = Field(min_length=1, max_length=80)
    location: str = Field(max_length=120)
    time_of_day: str = Field(max_length=40)
    summary: str = Field(max_length=300)


class Estimates(PlanModel):
    preview_credits: float = Field(default=0, ge=0)
    video_credits: float = Field(default=0, ge=0)
    total_credits: float = Field(default=0, ge=0)


class ProductionPlan(PlanModel):
    plan_version: int = Field(default=0, ge=0, strict=True)
    recipe: Literal["story_video"] = "story_video"
    title: str = Field(min_length=1, max_length=200)
    target_duration_sec: float = Field(gt=0, le=600, strict=True)
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:3", "3:4"] = "16:9"
    scenes: list[Scene] = Field(min_length=1, max_length=12)
    shots: list[ShotPlan] = Field(min_length=1, max_length=120)
    rationale: str = Field(default="", max_length=1500)
    estimates: Estimates = Field(default_factory=Estimates)


def normalized_plan(raw):
    """Only the server writes dependencies; invalid transitions remain editable."""
    plan = ProductionPlan.model_validate(raw).model_dump(mode="json")
    for index, shot in enumerate(plan["shots"]):
        shot["depends_on"] = [plan["shots"][index - 1]["shot_id"]] if index and shot["transition_in"] == "tail_frame" else []
        # Duration has one authoritative representation for pricing/submission.
        duration = shot["duration_sec"]
        shot["motion"]["params"]["duration"] = int(duration) if duration.is_integer() else duration
    return plan


def select_plan_model(request_spec, mode, model_id, *, run=None, slot=None):
    """Only authenticated review edits may replace an unspecified server default."""
    overrides = (run.snapshot or {}).get("story_model_overrides", {}) if run is not None else {}
    requested, _excluded = constraints_for_mode(request_spec, mode)
    if slot and overrides.get(slot) == model_id and not requested:
        candidate = next((item for item in candidates_for_request(request_spec, mode, use_default=False)
                          if item.model_id == model_id), None)
        if candidate is not None:
            return candidate
    return select_for_request(request_spec, mode, model_id)


def estimate_production_plan(plan, story, request_spec, *, run=None):
    """Price one planned attempt, not already incurred cost or possible retries."""
    preview, video = 0.0, 0.0
    for character in story.get("characters", []):
        if character["reference"]["source"] == "generate" and not character["reference"]["artifact_ids"]:
            preview += estimate_model_cost(select_for_request(request_spec, "t2i"), {"n": 1})
    for shot in plan["shots"]:
        # The video adapter remains i2v; bridge capability is checked separately.
        model = select_plan_model(request_spec, "i2v", shot["motion"]["model_id"], run=run, slot=f"{shot['shot_id']}:motion")
        video += estimate_model_cost(model, {**shot["motion"]["params"], "duration": shot["duration_sec"], "n_outputs": 1})
        for field in ("first_frame", "end_frame"):
            frame = shot.get(field)
            if frame and frame["method"] == "generate":
                model = select_plan_model(request_spec, frame["image_mode"], frame["model_id"], run=run, slot=f"{shot['shot_id']}:{field}")
                preview += estimate_model_cost(model, {"n": 1})
    return {"preview_credits": round(preview, 6), "video_credits": round(video, 6),
            "total_credits": round(preview + video, 6)}


def promptless_shot(shot):
    result = deepcopy(shot)
    for key in ("first_frame", "end_frame", "motion"):
        if result.get(key):
            result[key].pop("prompt", None)
    return result
