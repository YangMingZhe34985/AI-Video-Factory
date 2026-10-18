"""Animate approved frames through the shared classic I2V Job and MQ path."""
from flask import current_app
from pydantic import BaseModel, ConfigDict, Field

from app.agent.plan_spec import PROMPT_MAX_LENGTH
from app.api import AppError
from app.skills import job_backed
from app.skills.budget import estimate_nodes_cost
from app.skills.permissions import GENERATE, PRODUCTION, SYSTEM
from app.skills.spec import ToolContext, ToolSpec


class AnimateShotInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_frame_artifact_id: str = Field(min_length=1)
    last_frame_artifact_id: str | None = Field(default=None, min_length=1)
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX_LENGTH)
    model_id: str | None = None
    params: dict = Field(default_factory=dict)


def validate_bridge(data, model):
    if not data.last_frame_artifact_id:
        return
    if (not current_app.config.get("AGENT_ENABLE_KEYFRAME_BRIDGE", False)
            or "first_last_frame" not in (model.capabilities or {}).get("modes", [])
            or model.adapter_name != "dashscope_i2v" or not model.model_id.startswith("wan2.7-i2v")):
        raise AppError("KEYFRAME_BRIDGE_UNAVAILABLE", "First/last-frame generation is not enabled for this model", 422)


def cost(data, ctx):
    # Reject unsupported bridges before reserving any paid work.
    config = {}
    model = job_backed.pin_model(config, "submit_i2v", "i2v", data.model_id, data.params, ctx=ctx)
    validate_bridge(data, model)
    return estimate_nodes_cost(["submit_i2v", "poll_i2v"], job_config=config, ctx=ctx)


def run(data: AnimateShotInput, ctx: ToolContext):
    from app.agent.model_selection import validate_generation_model

    config = {}
    model = job_backed.pin_model(config, "submit_i2v", "i2v", data.model_id, data.params, ctx=ctx)
    validate_bridge(data, model)
    validate_generation_model(model, "i2v", config.get("node_model_params", {}).get("submit_i2v", {}),
                              reference_count=2 if data.last_frame_artifact_id else 1)
    first = job_backed.resolve_artifact(data.first_frame_artifact_id, image_only=True, ctx=ctx)
    initial = {"first_frame_image": [first.artifact_id]}
    if data.last_frame_artifact_id:
        last = job_backed.resolve_artifact(data.last_frame_artifact_id, image_only=True, ctx=ctx)
        initial["last_frame_image"] = [last.artifact_id]
        config["animation_mode"] = "first_last_frame"
    job = job_backed.launch(ctx, ["submit_i2v", "poll_i2v"],
        initial_prompts={"i2v": data.prompt}, initial_artifacts=initial, job_config=config)
    return job_backed.launch_output(job, ["artifact:i2v_video"])


SPEC = ToolSpec(
    name="animate_shot", description="Animate a first frame, optionally with a capability-gated last frame. Billed per second.",
    input_model=AnimateShotInput, output_model=job_backed.JobLaunchOutput, handler=run,
    permission=GENERATE, allowed_roles=frozenset({PRODUCTION, SYSTEM}), requires_approval=True,
    max_wait_sec=1200, cost_fn=cost,
)
