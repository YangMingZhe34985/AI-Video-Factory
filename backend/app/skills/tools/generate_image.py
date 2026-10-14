from pydantic import BaseModel, ConfigDict, Field

from app.agent.plan_spec import PROMPT_MAX_LENGTH
from app.skills import job_backed
from app.skills.budget import estimate_nodes_cost
from app.skills.permissions import GENERATE, PRODUCTION, SYSTEM
from app.skills.spec import ToolContext, ToolSpec

NODES = ["submit_first_frame_image", "poll_first_frame_image"]


class GenerateImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=PROMPT_MAX_LENGTH)
    model_id: str | None = Field(default=None, description="text_to_image model override.")
    params: dict = Field(default_factory=dict, description="Validated against the model's parameter schema.")
    template_id: str | None = None


def run(data: GenerateImageInput, ctx: ToolContext):
    config = {}
    job_backed.pin_model(config, "submit_first_frame_image", "image", data.model_id, data.params)
    job = job_backed.launch(
        ctx,
        NODES,
        template_id=data.template_id,
        initial_prompts={"first_frame_image": data.prompt},
        job_config=config,
    )
    return job_backed.launch_output(job, ["artifact:first_frame_image"])


SPEC = ToolSpec(
    name="generate_image",
    description="Generate one still image (typically a shot's first frame) from a prompt. Billed, asynchronous.",
    input_model=GenerateImageInput,
    output_model=job_backed.JobLaunchOutput,
    handler=run,
    permission=GENERATE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}),
    requires_approval=True,
    max_wait_sec=1200,
    cost_fn=lambda _data: estimate_nodes_cost(NODES),
)
