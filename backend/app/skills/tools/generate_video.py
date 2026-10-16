from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.plan_spec import PROMPT_MAX_LENGTH
from app.skills import job_backed
from app.skills.budget import estimate_nodes_cost
from app.skills.permissions import GENERATE, PRODUCTION, SYSTEM
from app.skills.spec import ToolContext, ToolSpec

MODES = {
    "t2v": {
        "nodes": ["submit_t2v", "poll_t2v"],
        "prompt_type": "t2v",
        "capability": "t2v",
        "output": "artifact:t2v_video",
    },
    "i2v": {
        "nodes": ["submit_i2v", "poll_i2v"],
        "prompt_type": "i2v",
        "capability": "i2v",
        "output": "artifact:i2v_video",
    },
    "r2v": {
        "nodes": ["submit_r2v_flash", "poll_r2v_flash"],
        "prompt_type": "r2v_flash",
        "capability": "r2v",
        "output": "artifact:r2v_flash_video",
    },
}


class GenerateVideoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["t2v", "i2v", "r2v"]
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX_LENGTH)
    first_frame_artifact_id: str | None = Field(default=None, description="Required for i2v.")
    reference_artifact_ids: list[str] = Field(
        default_factory=list, max_length=20, description="Required for r2v (at least one)."
    )
    model_id: str | None = None
    params: dict = Field(default_factory=dict)
    template_id: str | None = None

    @model_validator(mode="after")
    def _inputs_match_mode(self):
        if self.mode == "i2v" and not self.first_frame_artifact_id:
            raise ValueError("i2v requires first_frame_artifact_id")
        if self.mode == "r2v" and not self.reference_artifact_ids:
            raise ValueError("r2v requires at least one reference_artifact_id")
        if self.mode != "i2v" and self.first_frame_artifact_id:
            raise ValueError("first_frame_artifact_id is only valid for i2v")
        if self.mode != "r2v" and self.reference_artifact_ids:
            raise ValueError("reference_artifact_ids is only valid for r2v")
        return self


def run(data: GenerateVideoInput, ctx: ToolContext):
    mode = MODES[data.mode]
    config = {}
    job_backed.pin_model(config, mode["nodes"][0], mode["capability"], data.model_id, data.params, ctx=ctx)
    initial_artifacts = {}
    if data.first_frame_artifact_id:
        frame = job_backed.resolve_artifact(data.first_frame_artifact_id, image_only=True)
        initial_artifacts["first_frame_image"] = [frame.artifact_id]
    if data.reference_artifact_ids:
        references = [
            job_backed.resolve_artifact(artifact_id, image_only=True)
            for artifact_id in data.reference_artifact_ids
        ]
        initial_artifacts["reference_images"] = [ref.artifact_id for ref in references]
    job = job_backed.launch(
        ctx,
        mode["nodes"],
        template_id=data.template_id,
        initial_prompts={mode["prompt_type"]: data.prompt},
        initial_artifacts=initial_artifacts,
        job_config=config,
    )
    return job_backed.launch_output(job, [mode["output"]])


SPEC = ToolSpec(
    name="generate_video",
    description=(
        "Generate one video clip. mode=t2v from text, i2v from a first-frame image artifact, "
        "r2v from reference image artifacts. Billed, asynchronous."
    ),
    input_model=GenerateVideoInput,
    output_model=job_backed.JobLaunchOutput,
    handler=run,
    permission=GENERATE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}),
    requires_approval=True,
    max_wait_sec=1200,
    cost_fn=lambda data: estimate_nodes_cost(MODES[data.mode]["nodes"]),
)
