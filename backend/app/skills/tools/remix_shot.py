"""Produce one approved edit using source assets and the existing DAG."""

from pydantic import Field

from app.agent.model_policy import scope_policy
from app.agent.plan_spec import RemixShotSpec, shot_cost
from app.agent.protocol import validate_shot
from app.agent.sources import source_for_run
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, Artifact, Job, PromptVersion
from app.services.artifact_service import ArtifactService
from app.services.storage_service import StorageService
from app.services.video_media_service import VideoMediaService
from app.skills import job_backed
from app.skills.permissions import GENERATE, PRODUCTION, SYSTEM
from app.skills.spec import ToolContext, ToolSpec
from app.skills.tools.produce_shot import NODES


class RemixShotInput(RemixShotSpec):
    source_artifact_id: str = Field(min_length=1, max_length=80)
    analysis_prompt_id: str = Field(min_length=1, max_length=80)
    parent_job_id: str | None = None


def _references(data, ctx):
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
    if not run:
        raise AppError("TOOL_FORBIDDEN", "Remix requires an owning Agent run", 403)
    source = source_for_run(run)
    if source.artifact_id != data.source_artifact_id:
        raise AppError("TOOL_FORBIDDEN", "Source does not belong to this run", 403)
    analysis = PromptVersion.query.filter_by(prompt_id=data.analysis_prompt_id).first()
    if not analysis or not analysis.job or (
        (analysis.job.config or {}).get("skill", {}).get("budget_scope") != run.run_id
        or (analysis.job.config or {}).get("skill", {}).get("tool_name") != "analyze_video"
        or (analysis.job.config or {}).get("initial_artifacts", {}).get("source_video") != source.artifact_id
        or analysis.prompt_type != "t2v"
    ):
        raise AppError("TOOL_FORBIDDEN", "Analysis prompt does not belong to this run", 403)
    parent = None
    if data.parent_job_id:
        parent = Job.query.filter_by(job_id=data.parent_job_id).first()
        if not parent or (parent.config or {}).get("skill", {}).get("budget_scope") != run.run_id or (
            (parent.config or {}).get("shot", {}).get("shot_id") != data.shot_id
        ):
            raise AppError("TOOL_FORBIDDEN", "Previous shot does not belong to this run and shot", 403)
    validate_shot(data, scope_policy(run.run_id), source_duration=source.meta["video"]["duration"])
    return run, source, analysis, parent


def _source_asset(data, ctx, source):
    frame = data.action != "keep"
    kind = "first_frame_image" if frame else "retained_video"
    target = StorageService.job_dir(source.job.job_id, "remix", ctx.invocation_id) / ("frame.png" if frame else "clip.mp4")
    relative = StorageService.relative_path(target)
    artifact = Artifact.query.filter_by(job_id=source.job_id, file_path=relative, artifact_type=kind).first()
    if artifact and target.is_file() and target.stat().st_size:
        return artifact
    VideoMediaService.extract(StorageService.resolve(source.file_path), target,
                              data.source_start, data.source_end, frame=frame)
    artifact = artifact or ArtifactService.register_artifact(
        source.job, relative, kind, branch_key="remix",
        metadata={"source_artifact_id": source.artifact_id, "source_start": data.source_start,
                  "source_end": data.source_end, "action": data.action})
    db.session.commit()
    return artifact


def _prompts(data, run, analysis, parent):
    text = run.request["text" if run.request.get("schema_version", 1) == 2 else "goal"]
    contents = {"source_analysis": analysis.content,
                "edit_instruction": f"{text}\n\n{data.edit_reason}"}
    if data.action == "regenerate":
        contents["i2v"] = data.i2v_prompt
        if data.first_frame_mode == "generate":
            contents["first_frame_image"] = data.first_frame_prompt
    prompts, lineage = {}, {}
    for kind, content in contents.items():
        previous = (PromptVersion.query.filter_by(job_id=parent.id, prompt_type=kind, prompt_key="default", is_active=True).first()
                    if parent and kind != "source_analysis" else None) or analysis
        lineage[kind] = previous.prompt_id
        prompts[kind] = {"content": content, "source": "agent_remix", "parent_version": previous.version,
                         "note": f"Derived from prompt {previous.prompt_id}"}
    return prompts, lineage


def run(data: RemixShotInput, ctx: ToolContext):
    agent, source, analysis, parent = _references(data, ctx)
    prompts, lineage = _prompts(data, agent, analysis, parent)
    config = {"shot": {"shot_id": data.shot_id}, "remix": {
        **data.model_dump(include={"source_artifact_id", "source_start", "source_end", "action",
                                   "first_frame_mode", "edit_reason", "analysis_prompt_id", "parent_job_id"}),
        "prompt_lineage": lineage,
    }}
    initial_artifacts = {"source_video": source.artifact_id}
    nodes = []
    if data.action == "regenerate":
        job_backed.pin_model(config, "submit_i2v", "i2v", data.video_model_id, data.video_params, ctx=ctx)
        nodes = ["submit_i2v", "poll_i2v"]
        if data.first_frame_mode == "generate":
            job_backed.pin_model(config, "submit_first_frame_image", "image", data.image_model_id, data.image_params)
            nodes = NODES
    if data.action == "keep" or data.first_frame_mode == "source":
        asset = _source_asset(data, ctx, source)
        initial_artifacts[asset.artifact_type] = asset.artifact_id
    job = job_backed.launch(ctx, nodes, initial_prompts=prompts, initial_artifacts=initial_artifacts, job_config=config)
    return job_backed.launch_output(job, ["artifact:retained_video" if data.action == "keep" else "artifact:i2v_video"])


SPEC = ToolSpec(
    name="remix_shot", description="Keep a source segment, or regenerate one approved source-based shot with prompt lineage.",
    input_model=RemixShotInput, output_model=job_backed.JobLaunchOutput, handler=run,
    permission=GENERATE, allowed_roles=frozenset({PRODUCTION, SYSTEM}), requires_approval=True,
    max_retries=0, timeout_sec=240, max_wait_sec=1800, cost_fn=shot_cost,
)
