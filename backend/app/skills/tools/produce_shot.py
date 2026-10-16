from app.agent.plan_spec import ShotSpec
from app.skills import job_backed
from app.skills.budget import estimate_nodes_cost
from app.skills.permissions import GENERATE, PRODUCTION, SYSTEM
from app.skills.spec import ToolContext, ToolSpec

NODES = ["submit_first_frame_image", "poll_first_frame_image", "submit_i2v", "poll_i2v"]


class ProduceShotInput(ShotSpec):
    template_id: str | None = None


def run(data: ProduceShotInput, ctx: ToolContext):
    config = {"shot": {"shot_id": data.shot_id}}
    job_backed.pin_model(config, "submit_first_frame_image", "image", data.image_model_id, data.image_params)
    job_backed.pin_model(config, "submit_i2v", "i2v", data.video_model_id, data.video_params, ctx=ctx)
    # One job for both stages: the DAG dependency submit_i2v -> poll_first_frame_image
    # hands the generated first frame to the i2v model.
    job = job_backed.launch(
        ctx,
        NODES,
        template_id=data.template_id,
        initial_prompts={"first_frame_image": data.first_frame_prompt, "i2v": data.i2v_prompt},
        job_config=config,
    )
    return job_backed.launch_output(job, ["artifact:first_frame_image", "artifact:i2v_video"])


SPEC = ToolSpec(
    name="produce_shot",
    description=(
        "Produce one shot end to end from a ShotSpec: generate the first frame, then animate it "
        "with the i2v model. Billed, asynchronous; track it with get_task_status."
    ),
    input_model=ProduceShotInput,
    output_model=job_backed.JobLaunchOutput,
    handler=run,
    permission=GENERATE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}),
    requires_approval=True,
    max_wait_sec=1800,
    cost_fn=lambda _data: estimate_nodes_cost(NODES),
)
