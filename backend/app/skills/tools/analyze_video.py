from pydantic import BaseModel, ConfigDict, Field

from app.api import AppError
from app.skills import job_backed
from app.skills.budget import estimate_nodes_cost
from app.skills.permissions import CREATIVE, INTAKE, LLM, SYSTEM
from app.skills.spec import ToolContext, ToolSpec

NODES = ["reverse_prompts"]


class AnalyzeVideoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Only artifact references are accepted: a free-form path from an LLM
    # could point at any local file and send it to the provider.
    source_artifact_id: str = Field(min_length=1, description="Artifact id of an uploaded source video.")
    model_id: str | None = Field(default=None, description="Video-understanding model override.")
    template_id: str | None = None


def run(data: AnalyzeVideoInput, ctx: ToolContext):
    if ctx.role == INTAKE:
        from app.agent.attachments import attachment_for_owner
        from app.models import AgentRun
        owner = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
        if owner is None or data.source_artifact_id not in (owner.request or {}).get("attachment_ids", []):
            raise AppError("ATTACHMENT_NOT_FOUND", "Video is not attached to this run", 404)
        attachment_for_owner(data.source_artifact_id, owner.owner_id)
    artifact = job_backed.resolve_artifact(data.source_artifact_id)
    if artifact.artifact_type != "source_video" and not str(artifact.mime_type or "").startswith("video/"):
        raise AppError("INVALID_INPUT", f"Artifact {artifact.artifact_id} is not a video", 422)
    config = {}
    model = job_backed.pin_model(config, "reverse_prompts", "video_understanding", data.model_id)
    if ctx.role == INTAKE:
        capabilities = model.capabilities or {}
        if not capabilities.get("agent_selectable") or "video_understanding" not in capabilities.get("modes", []):
            raise AppError("MODEL_CAPABILITY_MISMATCH", "Intake requires a selectable video-understanding model", 422)
    job = job_backed.launch(
        ctx,
        NODES,
        template_id=data.template_id,
        initial_artifacts={"source_video": artifact.artifact_id},
        job_config=config,
    )
    return job_backed.launch_output(job, ["prompt:t2v"])


SPEC = ToolSpec(
    name="analyze_video",
    description=(
        "Understand a source video and produce a single dense text-to-video prompt (t2v). "
        "Asynchronous: returns a job_id; read the prompt with get_task_status."
    ),
    input_model=AnalyzeVideoInput,
    output_model=job_backed.JobLaunchOutput,
    handler=run,
    permission=LLM,
    allowed_roles=frozenset({CREATIVE, INTAKE, SYSTEM}),
    max_wait_sec=600,
    cost_fn=lambda data, ctx: estimate_nodes_cost(NODES, node_models={NODES[0]: data.model_id}, ctx=ctx),
)
