"""Bounded planning previews with one ledger entry and immutable Job permits."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
from math import isfinite

from flask import current_app
from PIL import Image
from pydantic import Field, model_validator

from app.agent.model_selection import select_for_request, validate_generation_model
from app.agent.plan_versions import _lock_run, inputs_hash
from app.agent.request_spec import StrictModel
from app.agents.workspace import require_context
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, AgentWorkspaceItem, ApiTask, Artifact, Job, JobDispatch, JobNodeRun, ToolInvocation
from app.plans.compiler import request_spec_for_run
from app.plans.execution import fingerprint
from app.services.storage_service import MOCK_PNG_BYTES, StorageService
from app.tools import job_backed
from app.tools.budget import estimate_model_cost
from app.tools.spec import ToolSpec

NODES = ["submit_first_frame_image", "poll_first_frame_image"]
SNAPSHOT_KEY = "v3_previews"
_dispatch = ContextVar("planning_preview_dispatch", default=None)


class RequestPreviewInput(StrictModel):
    purpose: str = Field(min_length=1, max_length=500)
    prompt: str = Field(min_length=1, max_length=8000)
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_references(self):
        if (len(self.reference_artifact_ids) != len(set(self.reference_artifact_ids))
                or any(not value or len(value) > 100 for value in self.reference_artifact_ids)):
            raise ValueError("Preview image references must be unique nonempty IDs")
        return self


class RequestPreviewOutput(job_backed.JobLaunchOutput):
    preview_id: str


def _identifier(ctx):
    if not ctx.idempotency_key or len(ctx.idempotency_key) > 500:
        raise AppError("INVALID_AGENT_CONTEXT", "Preview requires a stable server-owned request key", 403)
    return "preview_" + sha256(f"{ctx.budget_scope}:{ctx.idempotency_key}".encode()).hexdigest()[:32]


def _permit(run, preview_id):
    value = ((run.snapshot or {}).get(SNAPSHOT_KEY) or {}).get(preview_id)
    if not isinstance(value, dict):
        raise AppError("PREVIEW_PERMIT_REQUIRED", "A planning preview requires its original server permit", 403)
    return deepcopy(value)


def _store(run, permit):
    snapshot = deepcopy(run.snapshot or {})
    snapshot.setdefault(SNAPSHOT_KEY, {})[permit["preview_id"]] = deepcopy(permit)
    run.snapshot = snapshot


def validate_submission(data, ctx):
    run, delegation = require_context(ctx)
    preview_id = _identifier(ctx)
    ctx.plan_preview_id = preview_id
    old = ((run.snapshot or {}).get(SNAPSHOT_KEY) or {}).get(preview_id)
    if old is not None and (old.get("input") != data.model_dump(mode="json")
                           or old.get("caller_agent") != ctx.caller_agent
                           or old.get("delegation_id") != delegation.id
                           or old.get("request_key") != ctx.idempotency_key):
        raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Preview key belongs to another input or delegation", 409)
    return run, delegation


def _price_limit():
    limit = current_app.config.get("AGENT_V3_PREVIEW_MAX_CREDITS", 3)
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not isfinite(limit) or limit < 0:
        raise AppError("PREVIEW_CONFIGURATION_INVALID", "Preview price limit is invalid", 503)
    return float(limit)


def cost(data, ctx):
    run, delegation = validate_submission(data, ctx)
    run = _lock_run(run)
    if delegation.status in {"completed", "returned", "failed", "limit", "cancelled"} or run.status != "understanding":
        raise AppError("AGENT_NOT_ACTIVE", "New previews are only available during active planning", 409)
    used = ToolInvocation.query.filter_by(budget_scope=run.run_id, tool_name="request_preview").filter(
        ToolInvocation.status != "rejected").count()
    if used >= 6:
        raise AppError("PREVIEW_LIMIT_EXCEEDED", "Each Run allows at most six planning preview attempts", 422)
    previous = ((run.snapshot or {}).get(SNAPSHOT_KEY) or {}).get(ctx.plan_preview_id)
    if previous is not None:
        # A rejected local admission retains its frozen input, but still needs quota.
        ctx._plan_preview_prepared = deepcopy(previous)
        return float(previous["estimated_cost"])
    policy = request_spec_for_run(run)
    mode = "i2i" if data.reference_artifact_ids else "t2i"
    model = select_for_request(policy, mode)
    params = validate_generation_model(model, mode, {"n": 1}, reference_count=len(data.reference_artifact_ids))
    price = float(estimate_model_cost(model, params))
    if not isfinite(price) or price < 0 or price > _price_limit() + 1e-9:
        raise AppError("PREVIEW_PRICE_EXCEEDED", "The configured preview model exceeds the per-image planning limit", 422)
    sources = {value: fingerprint(run, value, "image") for value in data.reference_artifact_ids}
    ctx._plan_preview_prepared = {"preview_id": ctx.plan_preview_id, "request_key": ctx.idempotency_key,
        "input": data.model_dump(mode="json"), "mode": mode, "model_id": model.model_id,
        "params": params, "estimated_cost": price, "policy": policy, "sources": sources,
        "caller_agent": ctx.caller_agent, "delegation_id": delegation.id,
        "job_id": None, "invocation_id": None, "job_snapshot": None, "workspace_ref": None}
    return price


def run(data, ctx):
    owner, _delegation = validate_submission(data, ctx)
    owner = _lock_run(owner)
    prepared = deepcopy(getattr(ctx, "_plan_preview_prepared", None))
    if not prepared or prepared["preview_id"] != ctx.plan_preview_id or prepared["input"] != data.model_dump(mode="json"):
        raise AppError("PREVIEW_PERMIT_REQUIRED", "Preview was not admitted by the Registry", 403)
    invocation = ToolInvocation.query.filter_by(invocation_id=ctx.invocation_id,
        budget_scope=owner.run_id, tool_name="request_preview").first()
    if (invocation is None or invocation.input_payload != prepared["input"]
            or invocation.idempotency_key != ctx.idempotency_key
            or invocation.estimated_cost != prepared["estimated_cost"]):
        raise AppError("PREVIEW_PERMIT_REQUIRED", "Preview does not match a reserved tool receipt", 403)
    if invocation.job is not None or prepared.get("job_id"):
        raise AppError("RECOVERY_REQUIRED", "An accepted preview must recover its original Job", 409)
    if any(fingerprint(owner, key, "image") != value for key, value in prepared["sources"].items()):
        raise AppError("PREVIEW_INPUT_CHANGED", "Preview reference bytes changed before submission", 409)
    prepared["invocation_id"] = invocation.invocation_id
    prepared["inputs_hash"] = inputs_hash({key: prepared[key] for key in (
        "input", "mode", "model_id", "params", "estimated_cost", "policy", "sources", "caller_agent", "delegation_id")})
    _store(owner, prepared)
    db.session.commit()
    config = {"node_models": {NODES[0]: prepared["model_id"]},
              "node_model_params": {NODES[0]: prepared["params"]}, "image_generation_mode": prepared["mode"]}
    job = job_backed.launch(ctx, NODES, initial_prompts={"first_frame_image": data.prompt},
        initial_artifacts={"reference_images": data.reference_artifact_ids} if data.reference_artifact_ids else {},
        job_config=config)
    return {**job_backed.launch_output(job, ["artifact:first_frame_image"]).model_dump(mode="json"),
            "preview_id": prepared["preview_id"]}


def job_marker(ctx):
    owner = AgentRun.query.filter_by(run_id=ctx.budget_scope).one()
    permit = _permit(owner, ctx.plan_preview_id)
    if permit["invocation_id"] != ctx.invocation_id or permit["request_key"] != ctx.idempotency_key:
        raise AppError("PREVIEW_PERMIT_REQUIRED", "Preview Job requires the original tool invocation", 403)
    return {"run_id": owner.run_id, "preview_id": permit["preview_id"], "inputs_hash": permit["inputs_hash"]}


def bind_job(ctx, job):
    from app.plans.policy import _job_snapshot
    owner = _lock_run(AgentRun.query.filter_by(run_id=ctx.budget_scope).one())
    permit = _permit(owner, ctx.plan_preview_id)
    if (job.config or {}).get("agent_plan_preview") != job_marker(ctx):
        raise AppError("PREVIEW_PERMIT_REQUIRED", "Preview Job marker differs from its permit", 403)
    if permit["job_id"] not in {None, job.job_id}:
        raise AppError("PREVIEW_PERMIT_REQUIRED", "A preview permit cannot launch another Job", 409)
    snapshot = _job_snapshot(job)
    _validate_unbound_inputs(owner, permit, job, snapshot)
    if permit["job_snapshot"] is not None and permit["job_snapshot"] != snapshot:
        raise AppError("PREVIEW_INPUT_CHANGED", "Preview Job inputs are immutable", 409)
    permit.update(job_id=job.job_id, job_snapshot=snapshot)
    _store(owner, permit)
    db.session.commit()


def _validate_unbound_inputs(owner, permit, job, snapshot):
    """Validate original inputs before trusting a recovered Job's snapshot."""
    config = job.config or {}
    expected_nodes = set(NODES) | {"export_manifest"}
    if (set((job.node_overrides or {}).get("enabled_nodes", [])) != expected_nodes
            or config.get("node_models") != {NODES[0]: permit["model_id"]}
            or config.get("node_model_params") != {NODES[0]: permit["params"]}
            or config.get("image_generation_mode") != permit["mode"]
            or set(snapshot["prompts"]) != {"first_frame_image"}
            or snapshot["prompts"]["first_frame_image"]["content"] != permit["input"]["prompt"]):
        raise AppError("PREVIEW_INPUT_CHANGED", "Recovered preview Job differs from its reserved inputs", 409)
    refs = permit["input"]["reference_artifact_ids"]
    if ([item["source_artifact_id"] for item in snapshot["artifacts"]] != refs
            or any(item["type"] != "reference_image" or item["sha256"] != permit["sources"][item["source_artifact_id"]]["sha256"]
                   for item in snapshot["artifacts"])
            or any(fingerprint(owner, key, "image") != value for key, value in permit["sources"].items())):
        raise AppError("PREVIEW_INPUT_CHANGED", "Recovered preview references differ from their original bytes", 409)


def recover_invocation(invocation, ctx):
    """Recover one known preview without creating a Job or repeating a POST."""
    owner, _delegation = require_context(ctx)
    if invocation.tool_name != "request_preview" or invocation.budget_scope != owner.run_id:
        raise AppError("TOOL_FORBIDDEN", "Cannot recover another Run's preview", 403)
    owner = _lock_run(owner)
    preview_id = "preview_" + sha256(f"{owner.run_id}:{invocation.idempotency_key}".encode()).hexdigest()[:32]
    permit = _permit(owner, preview_id)
    if (permit["invocation_id"] != invocation.invocation_id or permit["request_key"] != invocation.idempotency_key
            or permit["input"] != invocation.input_payload or permit["caller_agent"] != invocation.caller_agent
            or permit["delegation_id"] != invocation.delegation_id or permit["estimated_cost"] != invocation.estimated_cost):
        raise AppError("PREVIEW_PERMIT_REQUIRED", "Preview recovery requires the original reserved receipt", 403)
    jobs = Job.query.filter(Job.config["skill"]["invocation_id"].as_string() == invocation.invocation_id).all()
    if not jobs:
        db.session.commit()
        return None
    if len(jobs) != 1 or invocation.job_id not in {None, jobs[0].id}:
        raise AppError("RECOVERY_REQUIRED", "Preview Job linkage is ambiguous", 409)
    job = jobs[0]
    marker = {"run_id": owner.run_id, "preview_id": preview_id, "inputs_hash": permit["inputs_hash"]}
    skill = (job.config or {}).get("skill") or {}
    if (job.config.get("agent_plan_preview") != marker or skill.get("tool_name") != "request_preview"
            or skill.get("budget_scope") != owner.run_id or permit["job_id"] not in {None, job.job_id}):
        raise AppError("PREVIEW_PERMIT_REQUIRED", "Recovered Job does not belong to this preview", 403)
    if invocation.job_id is None or permit["job_snapshot"] is None:
        if (ApiTask.query.filter_by(job_id=job.id).first() or JobDispatch.query.filter_by(job_id=job.id).first()
                or JobNodeRun.query.filter_by(job_id=job.id).first()):
            raise AppError("RECOVERY_REQUIRED", "Unbound preview may have started; automatic recovery stopped", 409)
        from app.plans.policy import _job_snapshot
        snapshot = _job_snapshot(job)
        _validate_unbound_inputs(owner, permit, job, snapshot)
        invocation.job = job
        permit.update(job_id=job.job_id, job_snapshot=snapshot)
        _store(owner, permit)
        db.session.commit()
    else:
        db.session.commit()
    recover_job(job, ctx)
    db.session.refresh(job)
    if job.status == "success":
        record_result(job, ctx)
    return job


def recover_job(job, ctx=None):
    from app.agent.production_engine import _execution_in_flight
    from app.agent.production_repair import classify_job_failure
    from app.services.job_run_service import JobRunService
    from app.services.job_run_state_service import JobRunStateService
    owner, permit = validate_job(job)
    if ctx is not None and ctx.budget_scope != owner.run_id:
        raise AppError("TOOL_FORBIDDEN", "Cannot recover another Run's preview", 403)
    if job.status == "success":
        record_result(job, ctx)
        return
    if owner.status in {"cancelled", "failed", "success", "partial_success"} or job.status == "cancelled" or _execution_in_flight(job):
        return
    tasks = ApiTask.query.filter_by(job_id=job.id).all()
    nodes = JobNodeRun.query.filter_by(job_id=job.id).all()
    if not tasks and not nodes and not JobDispatch.query.filter_by(job_id=job.id).first():
        # No node ever entered the provider boundary; resume only the original Job.
        with authorized_job_dispatch(job, "run_full"):
            JobRunService.start(job.job_id, "run_full")
        return
    if len(tasks) != 1 or not tasks[0].provider_task_id or tasks[0].queue_phase == "submit_unknown":
        raise AppError("RECOVERY_REQUIRED", "Preview submission is unknown; no automatic POST retry", 409)
    api = tasks[0]
    if (api.model_id != permit["model_id"] or api.branch_key != "first_frame_image"
            or api.node_run is None or api.node_run.node_key != NODES[0]
            or not JobRunStateService.run_matches_job(job, api.node_run)):
        raise AppError("PREVIEW_INPUT_CHANGED", "Preview provider receipt differs from its original model", 409)
    info = classify_job_failure(job)
    if ((api.response_payload or {}).get("status") in {"failed", "cancelled"}
            or (job.status in {"failed", "partial_success"} and info.get("recovery_action") != "recover_read")):
        return
    from app.models import TaskOutbox
    last = TaskOutbox.query.filter_by(task_id=api.id).order_by(TaskOutbox.id.desc()).first() if api.operation_key else None
    if api.operation_key and (api.queue_phase != "failed" or not last or last.phase not in {"poll", "download"}):
        return
    owner = _lock_run(owner)
    permit = _permit(owner, permit["preview_id"])
    if permit.get("read_recoveries", 0) >= 2:
        db.session.commit()
        return
    permit["read_recoveries"] = permit.get("read_recoveries", 0) + 1
    _store(owner, permit)
    # The original accepted task proves that this submit must never run again.
    for node in JobRunStateService.query_current_node_runs(job).filter_by(node_key=NODES[0]).all():
        node.status = "success"
        node.output_snapshot = {"api_task_id": api.api_task_id, "provider_task_id": api.provider_task_id}
    invocation = ToolInvocation.query.filter_by(invocation_id=permit["invocation_id"]).one()
    invocation.status, invocation.error_code, invocation.error_message, invocation.finished_at = "running", None, None, None
    db.session.commit()
    if api.operation_key:
        from app.queue.operations import reconcile
        reconcile(api.api_task_id, retry=True, reason="Planning preview bounded free read recovery")
    else:
        # The accepted submit above is frozen successful. A non-forced resume
        # skips it, retries only the read and also repairs the local manifest.
        with authorized_job_dispatch(job, "run_full"):
            JobRunService.start(job.job_id, "run_full")


def validate_job(job):
    from app.plans.policy import _job_snapshot
    marker = (job.config or {}).get("agent_plan_preview") or {}
    owner = AgentRun.query.populate_existing().filter_by(run_id=marker.get("run_id")).first()
    if owner is None or (owner.request or {}).get("schema_version") != 3:
        raise AppError("PREVIEW_PERMIT_REQUIRED", "Preview Job has no owning Run", 403)
    permit = _permit(owner, marker.get("preview_id"))
    invocation = ToolInvocation.query.filter_by(invocation_id=permit["invocation_id"],
        budget_scope=owner.run_id, tool_name="request_preview").first()
    skill = (job.config or {}).get("skill") or {}
    if (permit["job_id"] != job.job_id or permit["inputs_hash"] != marker.get("inputs_hash")
            or invocation is None or invocation.job_id != job.id or invocation.input_payload != permit["input"]
            or invocation.idempotency_key != permit["request_key"] or invocation.caller_agent != permit["caller_agent"]
            or invocation.delegation_id != permit["delegation_id"]
            or skill.get("invocation_id") != invocation.invocation_id or skill.get("tool_name") != "request_preview"
            or skill.get("budget_scope") != owner.run_id or permit["job_snapshot"] != _job_snapshot(job)):
        raise AppError("PREVIEW_INPUT_CHANGED", "Preview Job differs from its immutable permit and ledger receipt", 409)
    return owner, permit


@contextmanager
def authorized_job_dispatch(job, run_type, node_key=None, *, force=False, restart=False):
    if not ((run_type == "run_full" and node_key is None and not force and not restart)
            or (run_type == "run_node" and node_key == "poll_first_frame_image" and force and not restart)):
        raise AppError("UNSAFE_RETRY", "Preview retries may only poll the original accepted generation", 409)
    token = _dispatch.set((job.job_id, run_type, node_key, force, restart))
    try:
        yield
    finally:
        _dispatch.reset(token)


def validate_dispatch(job, run_type, node_key, force, restart):
    if not (job.config or {}).get("agent_plan_preview"):
        return
    if _dispatch.get() != (job.job_id, run_type, node_key, force, restart):
        raise AppError("UNSAFE_RETRY", "Preview Jobs require a server-owned dispatch permit", 409)
    validate_job(job)


def validate_before_submit(job, model, inputs, params, *, operation=None, adapter_name=None):
    if not job or not (job.config or {}).get("agent_plan_preview"):
        return
    owner, permit = validate_job(job)
    if owner.status in {"cancelled", "failed", "success", "partial_success"}:
        raise AppError("AGENT_NOT_ACTIVE", "The Run no longer authorizes new preview submissions", 409)
    operation = operation or NODES[0]
    effective_adapter = "dashscope_multimodal_sync" if model.model_id.startswith("wan2.7-image") else model.adapter_name
    if (operation != NODES[0] or model.model_id != permit["model_id"] or not model.enabled
            or params != permit["params"] or params.get("n") != 1
            or adapter_name not in {None, model.adapter_name, effective_adapter}
            or request_spec_for_run(owner) != permit["policy"]):
        raise AppError("PREVIEW_INPUT_CHANGED", "Preview model, parameters or user constraints changed", 409)
    validate_generation_model(model, permit["mode"], params, reference_count=len(permit["sources"]))
    for key, value in permit["sources"].items():
        if fingerprint(owner, key, "image") != value:
            raise AppError("PREVIEW_INPUT_CHANGED", "Preview reference bytes changed while queued", 409)
    original = permit["job_snapshot"]
    expected = {"prompt": permit["input"]["prompt"],
                "prompt_version": original["prompts"]["first_frame_image"]["version"]}
    if permit["mode"] == "i2i":
        paths = [item["path"] for item in original["artifacts"] if item["type"] == "reference_image"]
        if len(paths) != len(permit["sources"]):
            raise AppError("PREVIEW_INPUT_CHANGED", "Preview references are incomplete", 409)
        expected.update(source_image=paths[0], source_images=paths)
    if inputs != expected:
        raise AppError("PREVIEW_INPUT_CHANGED", "Provider input differs from the frozen planning preview", 409)
    price = float(estimate_model_cost(model, params))
    if price > permit["estimated_cost"] + 1e-9 or price > _price_limit() + 1e-9:
        raise AppError("PREVIEW_PRICE_EXCEEDED", "Preview price increased after admission", 409)


def record_result(job, ctx=None):
    """Persist a verified successful preview as an append-only workspace note."""
    if not (job.config or {}).get("agent_plan_preview") or job.status != "success":
        return None
    owner, permit = validate_job(job)
    if ctx is not None and ctx.budget_scope != owner.run_id:
        raise AppError("TOOL_FORBIDDEN", "Cannot record another Run's preview", 403)
    owner = _lock_run(owner)
    permit = _permit(owner, permit["preview_id"])
    request_key = permit["preview_id"] + ":result"
    existing = AgentWorkspaceItem.query.filter_by(run_id=owner.run_id, request_key=request_key).first()
    if existing is not None:
        result = {"key": existing.key, "version": existing.version}
        db.session.commit()
        return result
    artifacts = Artifact.query.filter_by(job_id=job.id, artifact_type="first_frame_image").order_by(Artifact.id).all()
    if len(artifacts) != 1:
        raise AppError("PREVIEW_OUTPUT_INVALID", "A preview must return exactly one image", 422)
    image = artifacts[0]
    fingerprint(owner, image.artifact_id, "image")
    path = StorageService.resolve(image.file_path)
    known_mock = (current_app.config.get("MODEL_ADAPTER_MODE") == "mock"
                  and path.stat().st_size == len(MOCK_PNG_BYTES) and path.read_bytes() == MOCK_PNG_BYTES)
    try:
        if not known_mock:
            with Image.open(path) as decoded:
                decoded.verify()
    except (OSError, ValueError, SyntaxError) as error:
        raise AppError("PREVIEW_OUTPUT_INVALID", "Preview output is not a valid image", 422) from error
    payload = {"preview_id": permit["preview_id"], "purpose": permit["input"]["purpose"],
               "artifact_ids": [image.artifact_id], "model_id": permit["model_id"],
               "estimated_cost": permit["estimated_cost"], "demo": current_app.config.get("MODEL_ADAPTER_MODE") == "mock"}
    item = AgentWorkspaceItem(run_id=owner.run_id, key=permit["preview_id"], version=1, kind="note",
        payload=payload, artifact_ids=[image.artifact_id], author_agent=permit["caller_agent"],
        delegation_id=permit["delegation_id"], request_key=request_key, inputs_hash=inputs_hash(payload))
    db.session.add(item)
    permit["workspace_ref"] = {"key": item.key, "version": 1}
    _store(owner, permit)
    db.session.commit()
    return deepcopy(permit["workspace_ref"])


SPEC = ToolSpec(name="request_preview", description="Request one low-cost planning image; maximum six attempts per Run.",
    input_model=RequestPreviewInput, output_model=RequestPreviewOutput, handler=run,
    permission="generate", allowed_roles=frozenset({"producer", "director", "prompt_smith"}),
    agent_visible=True, requires_approval=False, max_retries=0, max_wait_sec=1200, cost_fn=cost)
