"""Server-owned Plan approval and immutable generation dispatch bindings."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from flask import current_app

from app.agent import plan_versions as versions
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, Artifact, PlanNodeTask, ToolInvocation
from app.services.file_fingerprint import cached_digest
from app.services.storage_service import StorageService

_dispatch = ContextVar("plan_dispatch", default=None)
PAID_TOOLS = {"generate_image", "animate_shot", "generate_video", "transform_video", "produce_shot", "remix_shot",
              "run_workflow_template"}
PLAN_TOOLS = PAID_TOOLS | {"extract_frame", "retain_video_segment", "compose_video", "probe_media", "qc_video", "package_story", "select_image"}
POLL_NODES = {"poll_first_frame_image", "poll_i2v", "poll_t2v", "poll_r2v_flash"}


def invocation_key(task):
    return f"{task.run_id}:plan:{task.plan_version}:{task.node_id}:{task.attempt}:{task.inputs_hash[:12]}"


def task_context(ctx, *, current=True):
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
    task = PlanNodeTask.query.filter_by(id=getattr(ctx, "plan_node_task_id", None), run_id=ctx.budget_scope).first()
    if not run or (run.request or {}).get("schema_version") != 3 or task is None:
        raise AppError("APPROVAL_REQUIRED", "A Plan node requires server-owned execution context", 403)
    version = versions.get_version(run, task.plan_version)
    receipt = (run.snapshot or {}).get("v3_execution", {})
    if not current and receipt.get("approved_version") != task.plan_version:
        receipt = ((run.snapshot or {}).get("v3_execution_history") or {}).get(str(task.plan_version), {})
    if (receipt.get("approved_version") != task.plan_version
            or receipt.get("approval_hash") != versions.inputs_hash(version.plan)
            or ctx.idempotency_key != invocation_key(task) or not ctx.approved):
        raise AppError("PLAN_APPROVAL_MISMATCH", "Plan execution differs from the approved version", 409)
    if current:
        versions.require_current_version(run, task.plan_version)
    node = next((item for item in version.plan["nodes"] if item["id"] == task.node_id), None)
    if node is None or node["tool"] != (task.state or {}).get("tool"):
        raise AppError("PLAN_APPROVAL_MISMATCH", "Task is not part of the approved Plan", 409)
    return run, task, version, node


def authorize_tool(name, data, ctx):
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
    if not run or (run.request or {}).get("schema_version") != 3 or name not in PLAN_TOOLS:
        return None
    if ctx.caller_agent is not None:
        raise AppError("TOOL_FORBIDDEN", "Agent decisions cannot directly execute Plan nodes", 403)
    run, task, _version, node = task_context(ctx)
    payload = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    if (name != node["tool"] or task.inputs != payload or not (task.state or {}).get("resolved")
            or task.inputs_hash != versions.inputs_hash({"tool": name, "inputs": payload,
                "sources": task.state.get("input_fingerprints", {})})):
        raise AppError("PLAN_INPUT_CHANGED", "Node inputs differ from the frozen submission", 409)
    if name == "select_image":
        from app.plans.choices import validate_execution
        validate_execution(run, task, node, payload)
    previous = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).first()
    if previous:
        if previous.budget_scope != run.run_id or previous.tool_name != name or previous.input_payload != payload:
            raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Node invocation belongs to another input", 409)
        return task
    if run.status not in {"executing", "awaiting_gate", "delivering"} or task.status != "pending":
        raise AppError("PLAN_NOT_ACTIVE", "This Plan is not accepting new node submissions", 409)
    from app.plans.execution import fingerprint
    if any(fingerprint(run, key) != value for key, value in task.state.get("input_fingerprints", {}).items()):
        raise AppError("PLAN_INPUT_CHANGED", "Source bytes changed after node admission", 409)
    return task


def submission_cost(ctx):
    return task_context(ctx)[1].estimated_cost


def job_marker(ctx):
    run, task, version, node = task_context(ctx)
    return {"run_id": run.run_id, "plan_version": version.version, "node_id": node["id"],
            "task_id": task.id, "inputs_hash": task.inputs_hash}


def _job_snapshot(job):
    config = job.config or {}
    from app.services.prompt_service import PromptService
    prompts = {}
    if config.get("agent_workflow"):
        # Classic LLM nodes add prompt versions while running; only seeded ones are bound.
        from app.plans.workflow import initial_prompts
        prompts = initial_prompts(job)
    for kind in () if config.get("agent_workflow") else ("first_frame_image", "i2v", "t2v", "r2v_flash"):
        item = PromptService.get_active_for_template(job.template, kind, job_id=job.id)
        if item and item.job_id == job.id:
            prompts[kind] = {"content": item.content, "version": item.version}
    inputs = []
    for artifact in Artifact.query.filter_by(job_id=job.id).order_by(Artifact.id):
        if (artifact.meta or {}).get("source_artifact_id"):
            path = StorageService.resolve(artifact.file_path)
            inputs.append({"artifact_id": artifact.artifact_id, "source_artifact_id": artifact.meta["source_artifact_id"],
                           "type": artifact.artifact_type, "path": artifact.file_path, "sha256": cached_digest(path)})
    fields = ("node_models", "node_model_params", "animation_mode", "image_generation_mode", "agent_plan_inputs", "negative_prompt")
    fields += ("agent_workflow", "i2i_test") if config.get("agent_workflow") else ()
    return {"config": {key: deepcopy(config.get(key)) for key in fields},
            "nodes": deepcopy(job.node_overrides or {}), "prompts": prompts, "artifacts": inputs}


def bind_job(ctx, job):
    run, task, _version, node = task_context(ctx)
    if (job.config or {}).get("agent_plan") != job_marker(ctx):
        raise AppError("PLAN_APPROVAL_MISMATCH", "Job marker differs from its Plan task", 409)
    if task.job_id not in {None, job.job_id}:
        raise AppError("PLAN_APPROVAL_MISMATCH", "A Plan attempt cannot bind a second Job", 409)
    operation = {"generate_image": "submit_first_frame_image", "animate_shot": "submit_i2v",
                 "transform_video": "submit_r2v_flash"}.get(node["tool"])
    if node["tool"] == "generate_video":
        operation = {"t2v": "submit_t2v", "i2v": "submit_i2v", "r2v": "submit_r2v_flash"}[task.inputs["mode"]]
    expected_nodes = {"export_manifest"}
    workflow_costs = None
    if node["tool"] == "run_workflow_template":
        from app.plans import workflow
        workflow_costs = workflow.bind(task, job)
        expected_nodes |= set(workflow.enabled_nodes(task.inputs))
    elif operation:
        expected_nodes |= {operation, operation.replace("submit_", "poll_", 1)}
        if ((job.config or {}).get("node_models") != {operation: task.inputs["model_id"]}
                or (job.config or {}).get("node_model_params", {}) != {operation: task.inputs.get("params", {})}):
            raise AppError("PLAN_APPROVAL_MISMATCH", "Job model parameters differ from the approved node", 409)
    if set((job.node_overrides or {}).get("enabled_nodes", [])) != expected_nodes:
        raise AppError("PLAN_APPROVAL_MISMATCH", "Job workflow differs from the approved Plan tool", 409)
    if "negative_prompt" not in (job.config or {}):
        job.config = {**(job.config or {}), "negative_prompt": current_app.config.get("DEFAULT_NEGATIVE_PROMPT") or ""}
    snapshot = _job_snapshot(job)
    if operation and (not snapshot["prompts"] or any(item["content"] != task.inputs.get("prompt")
            for item in snapshot["prompts"].values())):
        raise AppError("PLAN_APPROVAL_MISMATCH", "Job prompt differs from its approved Plan input", 409)
    old = task.state.get("job_snapshot")
    if old is not None and old != snapshot:
        raise AppError("PLAN_APPROVAL_MISMATCH", "Job binding is immutable", 409)
    task.state = {**task.state, "job_snapshot": snapshot}
    if workflow_costs is not None and old is None:
        task.state = {**task.state, "workflow_unit_costs": workflow_costs}
    task.job_id = job.job_id
    db.session.commit()


def validate_job(job):
    marker = (job.config or {}).get("agent_plan") or {}
    task = PlanNodeTask.query.filter_by(id=marker.get("task_id"), run_id=marker.get("run_id"),
        plan_version=marker.get("plan_version"), node_id=marker.get("node_id")).first()
    if task is None or task.inputs_hash != marker.get("inputs_hash") or task.job_id != job.job_id:
        raise AppError("PLAN_APPROVAL_MISMATCH", "Job has no matching Plan task", 409)
    from app.tools.spec import ToolContext
    ctx = ToolContext(role="production", approved=True, budget_scope=task.run_id,
        idempotency_key=invocation_key(task))
    ctx.plan_node_task_id = task.id
    run, task, version, node = task_context(ctx, current=False)
    skill = (job.config or {}).get("skill") or {}
    receipt = ToolInvocation.query.filter_by(invocation_id=skill.get("invocation_id"),
        budget_scope=run.run_id, tool_name=node["tool"]).first()
    if (receipt is None or receipt.job_id != job.id or receipt.input_payload != task.inputs
            or receipt.idempotency_key != invocation_key(task) or skill.get("budget_scope") != run.run_id
            or skill.get("tool_name") != node["tool"] or task.state.get("job_snapshot") != _job_snapshot(job)):
        raise AppError("PLAN_APPROVAL_MISMATCH", "Job payload differs from its frozen receipt", 409)
    return run, task, version, node


@contextmanager
def authorized_job_dispatch(job, run_type, node_key=None, *, force=False, restart=False):
    if not ((run_type == "run_full" and node_key is None and not force and not restart)
            or (run_type == "run_node" and node_key in POLL_NODES and force and not restart)):
        raise AppError("UNSAFE_RETRY", "Plan dispatch cannot restart a paid submission", 409)
    token = _dispatch.set((job.job_id, run_type, node_key, force, restart))
    try:
        yield
    finally:
        _dispatch.reset(token)


def validate_dispatch(job, run_type, node_key, force, restart):
    if not (job.config or {}).get("agent_plan"):
        return
    if _dispatch.get() != (job.job_id, run_type, node_key, force, restart):
        raise AppError("UNSAFE_RETRY", "Plan Jobs require their original server dispatch permit", 409)
    validate_job(job)


def validate_before_submit(job, model, inputs, params, *, operation=None, adapter_name=None):
    if not job or not (job.config or {}).get("agent_plan"):
        return
    run, task, version, node = validate_job(job)
    versions.require_current_version(run, version.version)
    if run.status not in {"executing", "awaiting_gate", "delivering"}:
        raise AppError("PLAN_NOT_ACTIVE", "Plan no longer authorizes submission", 409)
    if node["tool"] == "run_workflow_template":
        from app.plans.workflow import validate_submit
        validate_submit(run, task, model, inputs, params, operation, adapter_name)
        return
    config = task.state["job_snapshot"]["config"]
    if operation is None:
        operations = list((config.get("node_models") or {}))
        operation = operations[0] if len(operations) == 1 else None
    if (operation not in (config.get("node_models") or {}) or model.model_id != config["node_models"][operation]
            or params != (config.get("node_model_params") or {}).get(operation, {})
            or params != task.inputs.get("params", {})
            or model.model_id != task.inputs.get("model_id") or not model.enabled):
        raise AppError("PLAN_APPROVAL_MISMATCH", "Submission model or parameters changed after approval", 409)
    effective_adapter = "dashscope_multimodal_sync" if model.model_id.startswith("wan2.7-image") else model.adapter_name
    if adapter_name not in {None, model.adapter_name, effective_adapter}:
        raise AppError("PLAN_APPROVAL_MISMATCH", "Submission adapter differs from approval", 409)
    from app.plans.execution import fingerprint
    if any(fingerprint(run, key) != value for key, value in task.state.get("input_fingerprints", {}).items()):
        raise AppError("PLAN_INPUT_CHANGED", "Source bytes changed while queued", 409)
    if inputs.get("prompt") != task.inputs.get("prompt"):
        raise AppError("PLAN_INPUT_CHANGED", "Submission prompt differs from approval", 409)
    expected = config.get("agent_plan_inputs")
    if expected is not None:
        if inputs != expected:
            raise AppError("PLAN_INPUT_CHANGED", "Transform media differs from approval", 409)
    else:
        references = task.state["job_snapshot"]["artifacts"]
        prompt_type = {"submit_first_frame_image": "first_frame_image", "submit_i2v": "i2v",
                       "submit_t2v": "t2v", "submit_r2v_flash": "r2v_flash"}.get(operation)
        prompt = task.state["job_snapshot"]["prompts"].get(prompt_type)
        if prompt is None:
            raise AppError("PLAN_INPUT_CHANGED", "Bound prompt receipt is missing", 409)
        expected = {"prompt": prompt["content"], "prompt_version": prompt["version"]}
        if operation != "submit_first_frame_image":
            expected["negative_prompt"] = config.get("negative_prompt") or None
        def source_path(artifact_id, kind):
            matches = [item["path"] for item in references if item["source_artifact_id"] == artifact_id and item["type"] == kind]
            if len(matches) != 1:
                raise AppError("PLAN_INPUT_CHANGED", "Bound reference receipt is missing or ambiguous", 409)
            return matches[0]
        if operation == "submit_i2v":
            expected["first_frame_image"] = source_path(task.inputs["first_frame_artifact_id"], "first_frame_image")
            if task.inputs.get("last_frame_artifact_id"):
                expected["last_frame_image"] = source_path(task.inputs["last_frame_artifact_id"], "last_frame_image")
        ids = task.inputs.get("reference_artifact_ids", [])
        if operation == "submit_r2v_flash":
            expected["reference_images"] = [source_path(key, "reference_image") for key in ids]
        elif operation == "submit_first_frame_image" and task.inputs.get("mode") == "i2i":
            expected["source_images"] = [source_path(key, "reference_image") for key in ids]
            expected["source_image"] = expected["source_images"][0]
        if inputs != expected:
            raise AppError("PLAN_INPUT_CHANGED", "Logical submission differs from approved prompt and references", 409)
    # Provider POST admission rechecks current prices. Poll/download never calls this path.
    from app.tools.budget import estimate_model_cost
    incoming = float(task.state.get("input_video_seconds", 0))
    cost = estimate_model_cost(model, params, input_video_seconds=incoming)
    if cost > task.estimated_cost + 1e-6:
        raise AppError("MODEL_PRICE_CHANGED", "Model price increased; a new approval is required", 409)
