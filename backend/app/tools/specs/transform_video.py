"""Execute only a server-approved immutable multimodal transform plan."""
from pydantic import BaseModel, ConfigDict, Field

from app.agent import transform_policy
from app.tools import job_backed
from app.tools.permissions import GENERATE, PRODUCTION, SYSTEM
from app.tools.spec import ToolSpec


class TransformVideoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_hash: str = Field(min_length=1, max_length=128)


def run(data, ctx):
    _run, plan = transform_policy.approved_plan(ctx)
    job = job_backed.launch(ctx, ["submit_r2v_flash", "poll_r2v_flash"],
        initial_prompts={"r2v_flash": plan["prompt"]},
        job_config={"node_models": {"submit_r2v_flash": plan["model_id"]},
                    "node_model_params": {"submit_r2v_flash": plan["params"]}})
    return job_backed.launch_output(job, ["artifact:r2v_flash_video"])


SPEC = ToolSpec(name="transform_video", description="Execute one approved reference/edit/extend video plan.",
    input_model=TransformVideoInput, output_model=job_backed.JobLaunchOutput, handler=run,
    permission=GENERATE, allowed_roles=frozenset({PRODUCTION, SYSTEM}), requires_approval=True,
    max_wait_sec=1200, max_retries=0,
    cost_fn=lambda _data, ctx: transform_policy.approved_plan(ctx)[1]["estimated_cost"])
