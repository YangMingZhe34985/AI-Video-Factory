from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.skills import job_backed
from app.skills.budget import estimate_nodes_cost
from app.skills.permissions import CREATIVE, LLM, SYSTEM
from app.skills.spec import ToolContext, ToolSpec

Target = Literal["first_frame_image", "i2v", "r2v_flash"]


class RewritePromptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t2v_prompt: str = Field(min_length=1, max_length=20000)
    targets: list[Target] = Field(
        default_factory=lambda: ["first_frame_image", "i2v"],
        min_length=1,
        description="first_frame_image and i2v are produced together by one rewrite.",
    )
    model_id: str | None = Field(default=None, description="Prompt-rewrite model override.")
    template_id: str | None = None

    @field_validator("targets")
    @classmethod
    def _normalize_targets(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


def _plan(data: RewritePromptInput) -> tuple[list[str], list[str]]:
    nodes, outputs = [], []
    if {"first_frame_image", "i2v"} & set(data.targets):
        nodes.append("rewrite_prompts")
        outputs += ["prompt:first_frame_image", "prompt:i2v"]
    if "r2v_flash" in data.targets:
        nodes.append("reverse_prompts4r2v")
        outputs.append("prompt:r2v_flash")
    return nodes, outputs


def run(data: RewritePromptInput, ctx: ToolContext):
    nodes, outputs = _plan(data)
    config = {}
    for node_key in nodes:
        job_backed.pin_model(config, node_key, "prompt_rewrite", data.model_id)
    job = job_backed.launch(
        ctx,
        nodes,
        template_id=data.template_id,
        initial_prompts={"t2v": data.t2v_prompt},
        job_config=config,
    )
    return job_backed.launch_output(job, outputs)


SPEC = ToolSpec(
    name="rewrite_prompt",
    description=(
        "Project a t2v prompt into model-specific prompts: a static first-frame image prompt plus "
        "a motion-only i2v prompt, and/or an identity-preserving r2v_flash prompt. Asynchronous."
    ),
    input_model=RewritePromptInput,
    output_model=job_backed.JobLaunchOutput,
    handler=run,
    permission=LLM,
    allowed_roles=frozenset({CREATIVE, SYSTEM}),
    max_wait_sec=300,
    cost_fn=lambda data: estimate_nodes_cost(_plan(data)[0]),
)
