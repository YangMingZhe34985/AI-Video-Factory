"""Structured production plan exchanged between agents.

Creative produces a PlanSpec; plan validation checks it; Production turns
each ShotSpec into one produce_shot call. Kept deliberately small for the
from-scratch MVP; remix fields arrive with Phase 3.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROMPT_MAX_LENGTH = 8000


class ShotSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    image_model_id: str | None = None
    video_model_id: str | None = None
    image_params: dict = Field(default_factory=dict)
    video_params: dict = Field(default_factory=dict)


class PlanSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    mode: Literal["from_scratch", "remix"] = "from_scratch"
    style_notes: str | None = Field(default=None, max_length=PROMPT_MAX_LENGTH)
    shots: list[ShotSpec] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _unique_shot_ids(self):
        shot_ids = [shot.shot_id for shot in self.shots]
        duplicates = sorted({shot_id for shot_id in shot_ids if shot_ids.count(shot_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate shot_id values: {duplicates}")
        return self
