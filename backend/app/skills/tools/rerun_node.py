from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api import AppError
from app.services.job_run_service import JobRunService
from app.services.job_service import JobService
from app.services.workflow_service import WorkflowService
from app.skills import job_backed
from app.skills.budget import estimate_nodes_cost
from app.skills.permissions import GENERATE, PRODUCTION, SYSTEM
from app.skills.spec import ToolContext, ToolSpec


class RerunNodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    node_key: str = Field(min_length=1)
    mode: Literal["node", "from"] = Field(
        default="node", description="node: only this node; from: this node and everything after it."
    )
    force: bool = True


class RerunNodeOutput(BaseModel):
    job_id: str
    node_key: str
    mode: str
    status: str


def _nodes_to_run(data: RerunNodeInput) -> tuple[list[str], int]:
    job = JobService.get_job(data.job_id)
    if data.mode == "node":
        keys = [data.node_key]
    else:
        nodes = WorkflowService.list_nodes()
        start = WorkflowService.get_node(data.node_key).sequence
        keys = [
            node.node_key
            for node in nodes
            if node.sequence >= start and WorkflowService.is_node_enabled(job, node)
        ]
    sample_count = int(((job.config or {}).get("i2i_test") or {}).get("test_count") or 3)
    return keys, sample_count


def estimate_cost(data: RerunNodeInput) -> float:
    keys, sample_count = _nodes_to_run(data)
    return estimate_nodes_cost(keys, sample_count=sample_count)


def run(data: RerunNodeInput, ctx: ToolContext):
    job = JobService.get_job(data.job_id)
    if not job_backed.is_skill_job(job) and ctx.role != SYSTEM:
        raise AppError(
            "TOOL_FORBIDDEN",
            "Agents may only re-run jobs created by the skill layer",
            403,
        )
    from app.agent.model_policy import validate_job_policy
    validate_job_policy(job)
    run_type = "run_node" if data.mode == "node" else "run_from"
    result = JobRunService.start(job.job_id, run_type, node_key=data.node_key, force=data.force)
    return RerunNodeOutput(
        job_id=job.job_id,
        node_key=data.node_key,
        mode=data.mode,
        status=result.get("status") or "queued",
    )


SPEC = ToolSpec(
    name="rerun_node",
    description=(
        "Re-run one node (or a node and its successors) of a job created by a tool, e.g. to "
        "regenerate a failed shot. Billed when generation nodes are included. Identical calls "
        "are de-duplicated; pass a new idempotency_key to deliberately re-run again."
    ),
    input_model=RerunNodeInput,
    output_model=RerunNodeOutput,
    handler=run,
    permission=GENERATE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}),
    requires_approval=True,
    max_wait_sec=1800,
    cost_fn=estimate_cost,
)
