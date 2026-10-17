"""Helpers for tools that run through the classic workflow engine.

Every generation tool is "job-backed": it creates a classic Job that enables
only the nodes it needs, seeds the prompts/artifacts the tool received, and
starts it through JobRunService. Generation, tracking, retries, artifacts and
packaging therefore all reuse the existing DAG instead of a second code path.
"""

from collections.abc import Iterable

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.api import AppError
from app.extensions import db
from app.models import Artifact, Job, ModelRegistry, Series, Template, ToolInvocation
from app.services.artifact_service import ArtifactService
from app.services.job_run_service import JobRunService
from app.services.job_service import JobService
from app.services.model_service import ModelService
from app.services.prompt_service import PromptService
from app.services.workflow_service import WorkflowService
from app.skills import model_guard
from app.skills.spec import ToolContext

# Skill jobs live in their own template so the prompts they seed (which
# PromptSyncService copies to template level) never touch classic templates.
AGENT_SERIES_ID = "agent_studio"
AGENT_TEMPLATE_ID = "agent_workspace"


class JobLaunchOutput(BaseModel):
    job_id: str
    status: str
    expected_outputs: list[str]


def ensure_agent_template() -> Template:
    template = Template.query.filter_by(template_id=AGENT_TEMPLATE_ID).first()
    if template:
        return template
    try:
        if not Series.query.filter_by(series_id=AGENT_SERIES_ID).first():
            db.session.add(
                Series(
                    series_id=AGENT_SERIES_ID,
                    name="Agent Studio",
                    description="Jobs created by the CineCrew skill layer.",
                    is_default=False,
                )
            )
            db.session.flush()
        return PromptService.create_template(
            {
                "template_id": AGENT_TEMPLATE_ID,
                "name": "Agent Workspace",
                "series": AGENT_SERIES_ID,
                "description": "Isolated template for jobs created by agent tools.",
            }
        )
    except (IntegrityError, AppError):
        db.session.rollback()
        template = Template.query.filter_by(template_id=AGENT_TEMPLATE_ID).first()
        if not template:
            raise
        return template


def node_selection(nodes: Iterable[str]) -> dict:
    enabled = set(nodes) | {"export_manifest"}
    all_keys = {node.node_key for node in WorkflowService.list_nodes()}
    unknown = enabled - all_keys
    if unknown:
        raise AppError("NODE_NOT_FOUND", f"Unknown workflow nodes: {sorted(unknown)}", 500)
    return {
        "enabled_nodes": sorted(enabled),
        "disabled_nodes": sorted(all_keys - enabled),
    }


def pin_model(
    job_config: dict,
    node_key: str,
    capability: str,
    model_id: str | None,
    params: dict | None = None,
    ctx: ToolContext | None = None,
) -> ModelRegistry:
    """Validate the node's model and params, then pin both into job_config."""
    from app.agent.model_policy import scope_policy, select_video_model
    policy = scope_policy(ctx.budget_scope) if ctx and capability in {"t2v", "i2v", "r2v"} else None
    model = (select_video_model(policy, capability, model_id) if policy
             else model_guard.effective_model(capability, node_key, model_id))
    if policy:
        job_config["video_model_policy"] = policy
    supplied = model_guard.validate_params(model, params or {})
    defaults = ModelService.effective_params(model)
    defaults.update((WorkflowService.get_node(node_key).config or {}).get("model_params") or {})
    # Freeze the exposed effective parameters at submission, including catalog
    # duration fallback; queued jobs must not drift when model defaults change.
    validated = model_guard.validate_params(model, {
        **{key: value for key, value in defaults.items() if key in (model.parameter_schema or {})},
        **supplied,
    })
    job_config.setdefault("node_models", {})[node_key] = model.model_id
    if validated:
        job_config.setdefault("node_model_params", {})[node_key] = validated
    return model


def resolve_artifact(artifact_id: str, image_only: bool = False) -> Artifact:
    artifact = ArtifactService.get_by_artifact_id(artifact_id)
    if image_only and not str(artifact.mime_type or "").startswith("image/"):
        raise AppError(
            "INVALID_INPUT",
            f"Artifact {artifact_id} is not an image ({artifact.mime_type})",
            422,
        )
    return artifact


def is_skill_job(job: Job) -> bool:
    return bool((job.config or {}).get("skill"))


def launch(
    ctx: ToolContext,
    nodes: Iterable[str],
    *,
    template_id: str | None = None,
    initial_prompts: dict | None = None,
    initial_artifacts: dict | None = None,
    job_config: dict | None = None,
) -> Job:
    # Retrying a failed invocation re-runs its job: nodes that already
    # succeeded are skipped, so nothing paid is submitted twice.
    if ctx.previous is not None and ctx.previous.job is not None:
        job = ctx.previous.job
        from app.agent.model_policy import validate_job_policy
        validate_job_policy(job)
        JobRunService.start(job.job_id, "run_full")
        return job

    template = ensure_agent_template() if not template_id else PromptService.get_template(template_id)
    config = dict(job_config or {})
    config["skill"] = {
        "invocation_id": ctx.invocation_id,
        "tool_name": ctx.tool_name,
        "budget_scope": ctx.budget_scope,
        "caller_role": ctx.role,
    }
    job = JobService.create_job(
        {
            "template_id": template.template_id,
            "strategy": f"skill:{ctx.tool_name}",
            **node_selection(nodes),
            "initial_prompts": initial_prompts or {},
            "initial_artifacts": initial_artifacts or {},
            "job_config": config,
        }
    )
    # Persist the Job link before starting asynchronous work so a worker crash
    # cannot hide an already submitted task from its invocation ledger.
    if ctx.invocation_id:
        invocation = ToolInvocation.query.filter_by(invocation_id=ctx.invocation_id).one()
        invocation.job = job
        db.session.commit()
    JobRunService.start(job.job_id, "run_full")
    return job


def launch_output(job: Job, expected_outputs: list[str]) -> JobLaunchOutput:
    db.session.refresh(job)
    return JobLaunchOutput(job_id=job.job_id, status=job.status, expected_outputs=expected_outputs)
