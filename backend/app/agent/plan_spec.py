"""Structured production plan exchanged between agents.

Creative produces a PlanSpec; plan validation checks it; Production turns
each shot into one produce_shot or remix_shot call.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.skills.budget import estimate_nodes_cost, planner_cost

PROMPT_MAX_LENGTH = 8000


class ShotSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    shot_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    first_frame_prompt: str = Field(
        min_length=1,
        max_length=PROMPT_MAX_LENGTH,
        description="Static description of the opening frame: subject, pose, scene, lighting.",
    )
    i2v_prompt: str = Field(
        min_length=1,
        max_length=PROMPT_MAX_LENGTH,
        description="Motion only: subject action, environment motion, camera movement.",
    )
    image_model_id: str | None = Field(default=None, description="Image model selection belongs here, never in image_params.")
    video_model_id: str | None = Field(default=None, description="Video model selection belongs here, never in video_params.")
    image_params: dict = Field(default_factory=dict, description="Image generation parameters only; no model_id.")
    video_params: dict = Field(default_factory=dict, description="Video generation parameters only; no model_id.")

    @model_validator(mode="before")
    @classmethod
    def _separate_model_selection(cls, value):
        """Repair misplaced model IDs without weakening model/parameter validation.

        LLM output, edited approvals and production tool inputs share this boundary.
        Promote the ID instead of dropping it, so model policy still checks the
        actual selection. Conflicting selections are ambiguous and must fail.
        """
        if not isinstance(value, dict):
            return value
        from app.services.model_service import ModelService

        normalized = dict(value)
        for kind in ("image", "video"):
            params_field, model_field = f"{kind}_params", f"{kind}_model_id"
            params = normalized.get(params_field)
            if not isinstance(params, dict) or "model_id" not in params:
                continue
            params = dict(params)
            misplaced = params.pop("model_id")
            if misplaced is not None:
                if not isinstance(misplaced, str) or not misplaced.strip():
                    raise ValueError(f"{params_field}.model_id must be a non-empty string or null")
                selected = normalized.get(model_field)
                if selected is not None and (
                    not isinstance(selected, str)
                    or ModelService.canonical_model_id(selected) != ModelService.canonical_model_id(misplaced)
                ):
                    raise ValueError(f"Conflicting {model_field} and {params_field}.model_id")
                if selected is None:
                    normalized[model_field] = misplaced
            normalized[params_field] = params
        return normalized


class RemixShotSpec(ShotSpec):
    action: Literal["keep", "regenerate"]
    source_start: float = Field(ge=0, allow_inf_nan=False, strict=True, description="Start of original segment to preserve or replace; source first frame is extracted here.")
    source_end: float = Field(gt=0, allow_inf_nan=False, strict=True, description="End of original segment to preserve or replace. Generated output length is independently set by video_params.duration.")
    edit_reason: str = Field(min_length=1, max_length=2000)
    first_frame_mode: Literal["source", "generate"] = "source"
    first_frame_prompt: str = Field(default="", max_length=PROMPT_MAX_LENGTH)
    i2v_prompt: str = Field(default="", max_length=PROMPT_MAX_LENGTH)

    @model_validator(mode="after")
    def _valid_edit(self):
        if self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        if self.action == "regenerate":
            if not self.i2v_prompt:
                raise ValueError("Regeneration requires an i2v_prompt")
            if self.first_frame_mode == "generate" and not self.first_frame_prompt:
                raise ValueError("Generating a first frame requires first_frame_prompt")
        return self


def shot_cost(shot: ShotSpec, ctx=None) -> float:
    if isinstance(shot, RemixShotSpec) and shot.action == "keep":
        return 0
    nodes = ["submit_i2v"]
    if not isinstance(shot, RemixShotSpec) or shot.first_frame_mode == "generate":
        nodes.append("submit_first_frame_image")
    return estimate_nodes_cost(
        nodes, node_models={"submit_i2v": shot.video_model_id, "submit_first_frame_image": shot.image_model_id},
        node_params={"submit_i2v": shot.video_params, "submit_first_frame_image": shot.image_params}, ctx=ctx,
    )


class PlanSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    mode: Literal["from_scratch", "remix"] = "from_scratch"
    style_notes: str | None = Field(default=None, max_length=PROMPT_MAX_LENGTH)
    shots: list[RemixShotSpec | ShotSpec] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _unique_shot_ids(self):
        if any(isinstance(shot, RemixShotSpec) != (self.mode == "remix") for shot in self.shots):
            raise ValueError("Shot fields must match the plan mode")
        shot_ids = [shot.shot_id for shot in self.shots]
        duplicates = sorted({shot_id for shot_id in shot_ids if shot_ids.count(shot_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate shot_id values: {duplicates}")
        return self

    @property
    def estimated_cost(self) -> float:
        analysis = estimate_nodes_cost(["reverse_prompts"]) if self.mode == "remix" else 0
        return planner_cost() * 2 + analysis + sum(shot_cost(shot) for shot in self.shots)
