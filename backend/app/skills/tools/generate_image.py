from typing import Literal

from flask import current_app
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.plan_spec import PROMPT_MAX_LENGTH
from app.skills import job_backed
from app.skills.budget import estimate_nodes_cost
from app.skills.permissions import GENERATE, PRODUCTION, SYSTEM
from app.skills.spec import ToolContext, ToolSpec

NODES = ["submit_first_frame_image", "poll_first_frame_image"]


class GenerateImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["t2i", "i2i"] = "t2i"
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX_LENGTH)
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=20)
    n: int | None = Field(default=None, ge=1, le=4, strict=True, description="Omitted: preserve model default count.")
    model_id: str | None = Field(default=None, description="text_to_image model override.")
    params: dict = Field(default_factory=dict, description="Validated against the model's parameter schema.")
    template_id: str | None = None

    @model_validator(mode="after")
    def _references_match_mode(self):
        if self.mode == "i2i" and not self.reference_artifact_ids:
            raise ValueError("i2i requires reference_artifact_ids")
        if self.mode == "t2i" and self.reference_artifact_ids:
            raise ValueError("reference_artifact_ids are only valid for i2i")
        if len(self.reference_artifact_ids) != len(set(self.reference_artifact_ids)):
            raise ValueError("reference_artifact_ids must be unique")
        return self


def _params(data):
    # Legacy callers may already specify n in params. An explicit top-level n wins.
    return {**data.params, **({"n": data.n} if data.n is not None else {})}


def _model_id(data):
    return data.model_id or (current_app.config["DEFAULT_I2I_TEST_IMAGE_MODEL"] if data.mode == "i2i" else None)


def run(data: GenerateImageInput, ctx: ToolContext):
    from app.agent.model_selection import validate_generation_model

    config = {}
    model = job_backed.pin_model(config, NODES[0], "image", _model_id(data), _params(data))
    validate_generation_model(model, data.mode, config.get("node_model_params", {}).get(NODES[0], {}),
                              reference_count=len(data.reference_artifact_ids))
    references = [job_backed.resolve_artifact(ref, image_only=True, ctx=ctx).artifact_id
                  for ref in data.reference_artifact_ids]
    config["image_generation_mode"] = data.mode
    job = job_backed.launch(
        ctx,
        NODES,
        template_id=data.template_id,
        initial_prompts={"first_frame_image": data.prompt},
        initial_artifacts={"reference_images": references} if references else {},
        job_config=config,
    )
    return job_backed.launch_output(job, ["artifact:first_frame_image"])


SPEC = ToolSpec(
    name="generate_image",
    description="Generate or edit still images from a prompt and optional reference artifacts. Billed, asynchronous.",
    input_model=GenerateImageInput,
    output_model=job_backed.JobLaunchOutput,
    handler=run,
    permission=GENERATE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}),
    requires_approval=True,
    max_wait_sec=1200,
    cost_fn=lambda data, ctx: estimate_nodes_cost(NODES, node_models={NODES[0]: _model_id(data)},
                                              node_params={NODES[0]: _params(data)}, ctx=ctx),
)
