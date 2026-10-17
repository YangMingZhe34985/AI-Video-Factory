"""The Phase A animation entry point shares the classic I2V job implementation."""
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.plan_spec import PROMPT_MAX_LENGTH
from app.skills import job_backed
from app.skills.permissions import GENERATE, PRODUCTION, SYSTEM
from app.skills.spec import ToolContext, ToolSpec
from app.skills.tools import generate_video


class AnimateShotInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_frame_artifact_id: str = Field(min_length=1)
    last_frame_artifact_id: str | None = None
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX_LENGTH)
    model_id: str | None = None
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _phase_a(self):
        if self.last_frame_artifact_id is not None:
            raise ValueError("last_frame_artifact_id is not supported in Phase A")
        return self

    def video_input(self):
        return generate_video.GenerateVideoInput(mode="i2v", **self.model_dump(exclude={"last_frame_artifact_id"}))


def run(data: AnimateShotInput, ctx: ToolContext):
    from app.agent.model_selection import validate_generation_model

    config = {}
    model = job_backed.pin_model(config, "submit_i2v", "i2v", data.model_id, data.params, ctx=ctx)
    validate_generation_model(model, "i2v", config.get("node_model_params", {}).get("submit_i2v", {}),
                              reference_count=1)
    return generate_video.run(data.video_input(), ctx)


SPEC = ToolSpec(
    name="animate_shot",
    description="Animate a first-frame image into one video clip. Billed, asynchronous; Phase A supports I2V only.",
    input_model=AnimateShotInput,
    output_model=job_backed.JobLaunchOutput,
    handler=run,
    permission=GENERATE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}),
    requires_approval=True,
    max_wait_sec=1200,
    cost_fn=lambda data, ctx: generate_video.SPEC.cost_fn(data.video_input(), ctx),
)
