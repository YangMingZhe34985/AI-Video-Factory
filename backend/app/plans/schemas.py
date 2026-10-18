"""Server-owned compilation results; authoring shapes remain in agents.schemas."""

from typing import Literal

from pydantic import Field

from app.agent.request_spec import StrictModel
from app.agents.schemas import PlanDraft


class PlanIssue(StrictModel):
    code: str
    node_id: str | None = None
    message: str


class NodeEstimate(StrictModel):
    node_id: str
    model_id: str | None = None
    mode: str | None = None
    estimated_cost: float = Field(default=0, ge=0, allow_inf_nan=False)
    input_video_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    output_video_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    pricing: dict = Field(default_factory=dict)


class PlanEstimates(StrictModel):
    nodes: list[NodeEstimate] = Field(default_factory=list)
    total_credits: float = Field(default=0, ge=0, allow_inf_nan=False)
    video_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    generated_video_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    demo: Literal[True] = True


class ExecutionPlan(PlanDraft):
    plan_version: int = Field(ge=1, strict=True)
    estimates: PlanEstimates
    experimental: bool = Field(strict=True)
