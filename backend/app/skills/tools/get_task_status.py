from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, model_validator

from app.api import AppError
from app.extensions import db
from app.models import PromptVersion, ToolInvocation
from app.services.job_service import JobService
from app.skills.permissions import CREATIVE, DIRECTOR, PRODUCTION, READ, SYSTEM
from app.skills.spec import ToolContext, ToolSpec
from app.utils.time_utils import as_utc

TERMINAL_STATUSES = {"success", "partial_success", "failed", "cancelled"}
BUSINESS_PROMPT_TYPES = {"t2v", "first_frame_image", "i2v", "i2i", "r2v_flash"}
DELIVERABLE_GROUPS = {"image", "video", "package"}


class GetTaskStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str | None = None
    invocation_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if bool(self.job_id) == bool(self.invocation_id):
            raise ValueError("Provide exactly one of job_id or invocation_id")
        return self


class NodeState(BaseModel):
    node_key: str
    status: str


class ArtifactRef(BaseModel):
    artifact_id: str
    artifact_type: str
    file_name: str | None = None
    mime_type: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    preview_url: str
    download_url: str


class TaskError(BaseModel):
    code: str | None = None
    summary: str | None = None
    hint: str | None = None


class InvocationRef(BaseModel):
    invocation_id: str
    tool_name: str
    status: str
    attempt: int


class Progress(BaseModel):
    completed: int
    total: int


class TaskStatusOutput(BaseModel):
    job_id: str
    status: str
    terminal: bool
    overdue: bool
    progress: Progress
    current_node: str | None = None
    nodes: list[NodeState]
    artifacts: list[ArtifactRef]
    prompts: dict[str, str]
    error: TaskError | None = None
    invocation: InvocationRef | None = None


def _overdue(invocation: ToolInvocation | None, terminal: bool) -> bool:
    if terminal or invocation is None:
        return False
    from app.skills import get_registry

    spec = get_registry().get(invocation.tool_name)
    if not spec.max_wait_sec:
        return False
    started = as_utc(invocation.started_at or invocation.created_at)
    elapsed = datetime.now(timezone.utc) - started
    return elapsed.total_seconds() > spec.max_wait_sec


def _root_error(detail: dict) -> dict:
    """Error of the node that actually failed, not of the nodes cascaded after it."""
    for node in reversed(detail["nodes"]):
        snapshot = ((node.get("latest_run") or {}).get("output_snapshot")) or {}
        if node["status"] == "failed" and snapshot.get("error_detail"):
            return snapshot["error_detail"]
    return detail.get("error_detail") or {}


def run(data: GetTaskStatusInput, ctx: ToolContext):
    from app.skills.registry import sync_invocation_from_job

    # Runs are executed by worker threads with their own sessions.
    db.session.expire_all()
    if data.invocation_id:
        invocation = ToolInvocation.query.filter_by(invocation_id=data.invocation_id).first()
        if invocation is None:
            raise AppError("INVOCATION_NOT_FOUND", "Tool invocation not found", 404)
        if invocation.job is None:
            raise AppError("JOB_NOT_FOUND", "This invocation has no (remaining) job", 404)
        job = invocation.job
    else:
        job = JobService.get_job(data.job_id)
        skill = (job.config or {}).get("skill") or {}
        invocation = (
            ToolInvocation.query.filter_by(invocation_id=skill["invocation_id"]).first()
            if skill.get("invocation_id")
            else None
        )

    if invocation is not None:
        sync_invocation_from_job(invocation)
        db.session.commit()

    detail = JobService.get_detail(job.job_id)
    # While the invocation is still pending/running, a terminal job status is
    # the previous run's and must not end the caller's polling loop.
    terminal = job.status in TERMINAL_STATUSES and not (
        invocation is not None and invocation.status in {"pending", "running"}
    )
    error_detail = _root_error(detail)
    prompts = {
        prompt.prompt_type: prompt.content
        for prompt in PromptVersion.query.filter_by(job_id=job.id, is_active=True)
        if prompt.prompt_type in BUSINESS_PROMPT_TYPES
    }
    return TaskStatusOutput(
        job_id=job.job_id,
        status=job.status,
        terminal=terminal,
        overdue=_overdue(invocation, terminal),
        progress=Progress(completed=detail["completed_nodes"], total=detail["total_nodes"]),
        current_node=job.current_node,
        nodes=[
            NodeState(node_key=node["node_key"], status=node["status"])
            for node in detail["nodes"]
            if node["enabled"]
        ],
        artifacts=[
            ArtifactRef(
                artifact_id=item["artifact_id"],
                artifact_type=item["artifact_type"],
                file_name=item.get("file_name"),
                mime_type=item.get("mime_type"),
                model_id=item.get("model_id"),
                prompt_version=item.get("prompt_version"),
                preview_url=f"/api/artifacts/{item['artifact_id']}/preview",
                download_url=f"/api/artifacts/{item['artifact_id']}/download",
            )
            for item in detail["artifacts"]
            if item.get("artifact_group") in DELIVERABLE_GROUPS
        ],
        prompts=prompts,
        error=(
            TaskError(
                code=error_detail.get("code"),
                summary=error_detail.get("summary") or job.error_summary,
                hint=error_detail.get("hint"),
            )
            if job.status in {"failed", "partial_success"} and (error_detail or job.error_summary)
            else None
        ),
        invocation=(
            InvocationRef(
                invocation_id=invocation.invocation_id,
                tool_name=invocation.tool_name,
                status=invocation.status,
                attempt=invocation.attempt,
            )
            if invocation is not None
            else None
        ),
    )


SPEC = ToolSpec(
    name="get_task_status",
    description=(
        "Read the state of a job started by a tool: status, per-node progress, image/video "
        "artifacts, generated prompts and a readable error. Poll this until terminal is true."
    ),
    input_model=GetTaskStatusInput,
    output_model=TaskStatusOutput,
    handler=run,
    permission=READ,
    allowed_roles=frozenset({DIRECTOR, CREATIVE, PRODUCTION, SYSTEM}),
    timeout_sec=10,
)
