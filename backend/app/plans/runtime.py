"""Deterministic DAG scheduling over the shared Job/MQ tool execution path."""
from copy import deepcopy
import math

from flask import current_app

from app.agent import plan_versions as versions
from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Job, PlanNodeTask, ToolInvocation
from app.plans import execution, policy
from app.tools.budget import BudgetGuard
from app.tools.spec import ToolContext

ACTIVE = {"executing", "awaiting_gate", "delivering"}
TERMINAL_TOOLS = {"compose_video", "probe_media", "qc_video", "package_story"}


def latest_tasks(run, version=None):
    number = version.version if hasattr(version, "version") else version
    if number is None:
        current = versions.current_version(run)
        number = current.version if current else 0
    return {task.node_id: task for task in PlanNodeTask.query.filter_by(run_id=run.run_id,
        plan_version=number).order_by(PlanNodeTask.id).all()}


def _update(run, *, status=None, **changes):
    locked = versions._lock_run(run)
    snapshot = deepcopy(locked.snapshot or {})
    snapshot.setdefault("v3_execution", {}).update(deepcopy(changes))
    locked.snapshot = snapshot
    if status:
        locked.status = status
    db.session.commit()
    return locked


def _node_costs(estimates):
    rows = estimates.get("nodes", [])
    if isinstance(rows, dict):
        return {key: float(value.get("estimated_cost", value.get("credits", 0))) if isinstance(value, dict)
                else float(value) for key, value in rows.items()}
    return {item["node_id"]: float(item.get("estimated_cost", item.get("credits", 0))) for item in rows}


def begin(run, version, repair_budget_credits=0, *, registry=None):
    from app.plans.compiler import compile_plan
    from app.tools import build_v3_registry
    registry = registry or build_v3_registry()
    if (isinstance(repair_budget_credits, bool) or not isinstance(repair_budget_credits, (float, int))
            or not math.isfinite(repair_budget_credits) or repair_budget_credits < 0):
        raise AppError("INVALID_INPUT", "Repair allowance must be a finite non-negative number", 422)
    version = versions.require_current_version(run, version.version if hasattr(version, "version") else version)
    receipt = (run.snapshot or {}).get("v3_execution", {})
    if receipt.get("approved_version") == version.version:
        if receipt.get("approval_hash") != versions.inputs_hash(version.plan):
            raise AppError("PLAN_APPROVAL_MISMATCH", "Approved Plan changed", 409)
        return run.status
    if run.status != "awaiting_plan_review":
        raise AppError("INVALID_AGENT_STATE", "Plan is not awaiting approval", 409)
    checked = compile_plan(version.plan, run, registry=registry, plan_version=version.version)
    if checked.get("issues") or not (version.check or {}).get("dry_run", {}).get("passed"):
        raise AppError("INVALID_EXECUTION_PLAN", "Plan must pass compilation and dry-run before approval", 422,
                       payload={"plan_issues": checked.get("issues", [])})
    costs = _node_costs(checked["estimates"])
    previous = _node_costs((version.check or {}).get("estimates", {}))
    if any(cost > previous.get(key, -1) + 1e-6 for key, cost in costs.items()):
        raise AppError("MODEL_PRICE_CHANGED", "Plan quote changed; review a new version", 409)
    if checked["plan"]["nodes"] != version.plan["nodes"]:
        raise AppError("PLAN_INPUT_CHANGED", "Effective Plan inputs changed since review", 409)
    total = sum(costs.values())
    run = versions._lock_run(run)
    BudgetGuard.check(run.run_id, run.request["budget_limit"], total + repair_budget_credits)
    receipt = {"approved_version": version.version, "approval_hash": versions.inputs_hash(version.plan),
        "node_costs": costs, "repair_budget_credits": float(repair_budget_credits), "repair_spent": 0.0,
        "approved_gates": [], "results_approved": False, "dag": checked["dag"],
        "output_metadata": deepcopy(checked.get("output_metadata", {})),
        "source_fingerprints": {key: execution.fingerprint(run, key) for key in checked.get("source_artifact_ids", [])}}
    snapshot = deepcopy(run.snapshot or {})
    previous_receipt = snapshot.get("v3_execution", {})
    if previous_receipt.get("approved_version"):
        snapshot.setdefault("v3_execution_history", {})[str(previous_receipt["approved_version"])] = previous_receipt
    snapshot["v3_execution"] = receipt
    run.snapshot = snapshot
    run.status, run.error = "executing", None
    for node in version.plan["nodes"]:
        estimate = next((item for item in checked["estimates"].get("nodes", []) if item["node_id"] == node["id"]), {})
        task = PlanNodeTask(run_id=run.run_id, plan_version=version.version, node_id=node["id"],
            inputs_hash=versions.inputs_hash(node), estimated_cost=costs.get(node["id"], 0),
            state={"tool": node["tool"], "resolved": False,
                   "input_video_seconds": estimate.get("input_video_seconds", 0),
                   "output_metadata": deepcopy(checked.get("output_metadata", {}).get(node["id"], {}))},
            inputs={}, output={}, artifact_ids=[])
        db.session.add(task)
    db.session.commit()
    return run.status


def _context(run, task):
    ctx = ToolContext(role="production", approved=True, budget_scope=run.run_id,
        budget_limit=run.request["budget_limit"], idempotency_key=policy.invocation_key(task))
    ctx.plan_node_task_id = task.id
    return ctx


def _frozen(run, version):
    receipt = (run.snapshot or {}).get("v3_execution", {})
    if (receipt.get("approved_version") != version.version
            or receipt.get("approval_hash") != versions.inputs_hash(version.plan)):
        raise AppError("APPROVAL_REQUIRED", "The current Plan has not been approved", 403)
    return receipt


def _fail(task, error, *, known_not_submitted=True):
    task.status = "failed"
    task.error = execution.failure(error, known_not_submitted=known_not_submitted)
    db.session.commit()


def _in_flight(job):
    from app.agent.production_engine import _execution_in_flight
    return _execution_in_flight(job)


def _recover_created(job):
    """Resume an admitted Job only when no ambiguous POST can be repeated."""
    from app.models import JobDispatch
    from app.services.job_run_service import JobRunService
    from app.services.job_run_state_service import JobRunStateService
    if JobDispatch.query.filter_by(job_id=job.id).first() or _in_flight(job):
        return
    if job.status not in {"created", "pending", "queued", "running"}:
        return
    for node in JobRunStateService.query_current_node_runs(job).all():
        if node.node_key.startswith("submit_") and node.status not in {"success", "skipped"}:
            task = ApiTask.query.filter_by(node_run_id=node.id).order_by(ApiTask.id.desc()).first()
            if not task or not task.provider_task_id:
                raise AppError("RECOVERY_REQUIRED", "Provider submission is unknown; no automatic POST retry", 409)
            node.status = "success"
            node.output_snapshot = {"api_task_id": task.api_task_id, "provider_task_id": task.provider_task_id}
    db.session.commit()
    with policy.authorized_job_dispatch(job, "run_full"):
        JobRunService.start(job.job_id, "run_full")


def _free_recover(run, task, job, info):
    from app.models import TaskOutbox
    if (info.get("recovery_action") != "recover_read" or not info.get("provider_task_id")
            or info.get("stage") not in {"poll", "download"} or task.state.get("read_recoveries", 0) >= 2):
        return False
    api = ApiTask.query.filter_by(api_task_id=info.get("api_task_id"), job_id=job.id).first()
    if api is None:
        return False
    task.state = {**task.state, "read_recoveries": task.state.get("read_recoveries", 0) + 1}
    db.session.commit()
    if api.operation_key:
        from app.queue.operations import reconcile
        last = TaskOutbox.query.filter_by(task_id=api.id).order_by(TaskOutbox.id.desc()).first()
        if not last or last.phase not in {"poll", "download"}:
            return False
        if api.queue_phase == "done" and last.phase == "download":
            api.queue_phase, api.status = "failed", "failed"
            db.session.commit()
        reconcile(api.api_task_id, retry=True, reason="Approved Plan bounded free read recovery")
    else:
        from app.services.job_run_service import JobRunService
        poll = {"first_frame_image": "poll_first_frame_image", "i2v": "poll_i2v",
                "t2v": "poll_t2v", "r2v_flash": "poll_r2v_flash"}.get(api.branch_key)
        if poll is None:
            return False
        with policy.authorized_job_dispatch(job, "run_node", poll, force=True):
            JobRunService.start(job.job_id, "run_node", node_key=poll, force=True)
    task.status, task.error = "running", None
    db.session.commit()
    return True


def _poll(run, task, registry):
    from app.agent.production_repair import classify_job_failure
    if task.state.get("tool") not in policy.PAID_TOOLS:
        version = versions.get_version(run, task.plan_version)
        node = next(item for item in version.plan["nodes"] if item["id"] == task.node_id)
        _submit(run, task, node, registry)
        return
    invocation = ToolInvocation.query.filter_by(invocation_id=task.invocation_id, budget_scope=run.run_id).first()
    job = Job.query.filter_by(job_id=task.job_id).first() if task.job_id else None
    if not job or not invocation or invocation.job_id != job.id:
        _fail(task, AppError("RECOVERY_REQUIRED", "Node receipt is incomplete", 409), known_not_submitted=False)
        return
    try:
        if not task.state.get("job_snapshot"):
            from app.models import JobDispatch, JobNodeRun
            if (ApiTask.query.filter_by(job_id=job.id).first() or JobDispatch.query.filter_by(job_id=job.id).first()
                    or JobNodeRun.query.filter_by(job_id=job.id).first()):
                raise AppError("RECOVERY_REQUIRED", "Unbound Job may have started; automatic dispatch stopped", 409)
            policy.bind_job(_context(run, task), job)
        policy.validate_job(job)
        if _in_flight(job):
            return
        _recover_created(job)
        db.session.refresh(job)
        if _in_flight(job) or job.status in {"created", "pending", "queued", "running"}:
            return
        spec = registry.get(task.state["tool"])
        if job.status in {"success", "partial_success"}:
            try:
                execution.complete(run, task, spec, execution.job_outputs(run, task, spec, job))
                return
            except AppError as error:
                api = ApiTask.query.filter_by(job_id=job.id).order_by(ApiTask.id.desc()).first()
                info = {"recovery_action": "recover_read", "provider_task_id": api.provider_task_id if api else None,
                    "api_task_id": api.api_task_id if api else None, "stage": "download"}
                if _free_recover(run, task, job, info):
                    return
                _fail(task, error)
                return
        info = classify_job_failure(job)
        if _free_recover(run, task, job, info):
            return
        task.status, task.error = "failed", info
        db.session.commit()
    except AppError as error:
        _fail(task, error, known_not_submitted=error.code != "RECOVERY_REQUIRED")


def _submit(run, task, node, registry):
    ctx = _context(run, task)
    previous = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).first()
    try:
        if previous:
            if previous.input_payload != task.inputs or previous.budget_scope != run.run_id or previous.tool_name != node["tool"]:
                raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Node receipt differs from the frozen input", 409)
            if node["tool"] not in policy.PAID_TOOLS:
                response = registry.invoke(node["tool"], task.inputs, ctx)
                task.invocation_id = response["invocation_id"]
                execution.complete(run, task, registry.get(node["tool"]), response["output"])
                return
            if previous.job is None:
                found = Job.query.filter(Job.config["skill"]["invocation_id"].as_string() == previous.invocation_id).first()
                if found:
                    previous.job = found
                    db.session.commit()
            if previous.job:
                task.invocation_id, task.job_id, task.status = previous.invocation_id, previous.job.job_id, "running"
                db.session.commit()
                _poll(run, task, registry)
                return
            if previous.status == "success":
                task.invocation_id = previous.invocation_id
                execution.complete(run, task, registry.get(node["tool"]), previous.output_payload)
                return
            raise AppError("RECOVERY_REQUIRED", "Previous node outcome cannot be submitted again", 409)
        unknown = PlanNodeTask.query.filter_by(run_id=run.run_id, status="failed").all()
        if any(item.id != task.id and (item.node_id == task.node_id or item.inputs_hash == task.inputs_hash)
                and (item.error or {}).get("submission_state") == "unknown" for item in unknown):
            raise AppError("RECOVERY_REQUIRED", "An earlier submission for this node is unresolved", 409)
        if node["tool"] in policy.PAID_TOOLS:
            from app.services.model_service import ModelService
            from app.tools.budget import estimate_model_cost
            model = ModelService.get_model(task.inputs["model_id"], require_enabled=True)
            current_cost = estimate_model_cost(model, task.inputs.get("params", {}),
                input_video_seconds=float(task.state.get("input_video_seconds", 0)))
            if current_cost > task.estimated_cost + 1e-6:
                raise AppError("MODEL_PRICE_CHANGED", "Node price increased; review a new quote", 409)
        response = registry.invoke(node["tool"], task.inputs, ctx)
        task.invocation_id = response["invocation_id"]
        job_id = (response.get("output") or {}).get("job_id")
        if job_id and node["tool"] in execution.ASYNC_OUTPUTS.keys() | {"generate_video"}:
            task.job_id, task.status = job_id, "running"
            db.session.commit()
            _poll(run, task, registry)
        else:
            execution.complete(run, task, registry.get(node["tool"]), response["output"])
    except AppError as error:
        previous = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).first()
        if previous and previous.job:
            task.invocation_id, task.job_id, task.status = previous.invocation_id, previous.job.job_id, "running"
            db.session.commit()
        else:
            _fail(task, error, known_not_submitted=node["tool"] not in policy.PAID_TOOLS
                  or previous is None or previous.status == "rejected")


def _gate_blocks(node_id, dag, gates):
    pending = list(dag["dependencies"].get(node_id, []))
    visited = set()
    while pending:
        item = pending.pop()
        if item in gates:
            return True
        if item not in visited:
            visited.add(item)
            pending.extend(dag["dependencies"].get(item, []))
    return False


def advance(run, registry=None):
    from app.tools import build_v3_registry
    registry = registry or build_v3_registry()
    if run.status not in ACTIVE:
        return run.status
    version = versions.current_version(run)
    receipt = _frozen(run, version)
    tasks, nodes = latest_tasks(run, version), {item["id"]: item for item in version.plan["nodes"]}
    for task in tasks.values():
        if task.status == "running":
            _poll(run, task, registry)
    dag = receipt["dag"]
    limit = max(1, int(current_app.config.get("AGENT_MAX_PARALLEL_SHOTS", 3)))
    for node_id in dag["order"]:
        task, node = tasks[node_id], nodes[node_id]
        if task.status != "pending" or sum(item.status == "running" for item in tasks.values()) >= limit:
            continue
        if any(tasks[dep].status != "success" for dep in dag["dependencies"].get(node_id, [])):
            continue
        gates = {key for key, value in nodes.items() if value.get("gate") == "preview"
                 and tasks[key].status == "success" and key not in receipt.get("approved_gates", [])}
        if _gate_blocks(node_id, dag, gates):
            continue
        try:
            if any(not execution.usable(run, tasks[dep]) for dep in dag["dependencies"].get(node_id, [])):
                raise AppError("PLAN_INPUT_CHANGED", "A predecessor output changed before use", 409)
            if node.get("gate") == "choice" and node_id not in receipt.get("approved_gates", []):
                from app.plans.choices import prepare
                prepare(run, version, node, task, tasks)
                continue
            if not task.state.get("resolved"):
                outputs = {key: value.output for key, value in tasks.items() if value.status == "success"}
                data, sources, digest = execution.resolve_node(run, node, version.version, outputs, registry)
                approved_sources = receipt.get("source_fingerprints", {})
                if any(key in approved_sources and record != approved_sources[key] for key, record in sources.items()):
                    raise AppError("PLAN_INPUT_CHANGED", "An approved source changed before execution", 409)
                task.inputs, task.inputs_hash = data, digest
                task.state = {**task.state, "resolved": True, "input_fingerprints": sources}
                db.session.commit()
            existing = None if task.state.get("force_execute") or node["tool"] == "select_image" else execution.reusable(run, task)
            if existing:
                execution.reuse(task, existing)
                continue
            _submit(run, task, node, registry)
        except AppError as error:
            _fail(task, error)
    if any(item.status == "failed" for item in tasks.values()) and not any(item.status == "running" for item in tasks.values()):
        return _update(run, status="attention").status
    gates = [key for key, node in nodes.items() if node.get("gate") == "preview" and tasks[key].status == "success"
             and key not in receipt.get("approved_gates", [])]
    gates.extend(key for key, node in nodes.items() if node.get("gate") == "choice" and tasks[key].status == "pending"
                 and tasks[key].state.get("choice_pending") and key not in receipt.get("approved_gates", []))
    if not gates and all(item.status == "success" for item in tasks.values()):
        return _update(run, status="awaiting_result_review").status
    status = "awaiting_gate" if gates else "delivering" if any(item.status == "running" and nodes[key]["tool"] in TERMINAL_TOOLS
        for key, item in tasks.items()) else "executing"
    return _update(run, status=status).status


def approve_gate(run, version, gate_node_id, *, selected_artifact_id=None, choice_digest=None):
    version = versions.require_current_version(run, version)
    receipt = _frozen(run, version)
    node = next((item for item in version.plan["nodes"] if item["id"] == gate_node_id), None)
    if node and node.get("gate") == "choice":
        from app.plans.choices import approve
        return approve(run, version.version, gate_node_id, selected_artifact_id, choice_digest)
    if selected_artifact_id is not None or choice_digest is not None:
        raise AppError("INVALID_CHOICE", "Preview approval does not accept a selected candidate", 422)
    task = latest_tasks(run, version).get(gate_node_id)
    if not node or node.get("gate") != "preview" or not execution.usable(run, task):
        raise AppError("INVALID_GATE", "A preview gate needs a completed valid image", 409)
    if run.status not in ACTIVE:
        raise AppError("INVALID_AGENT_STATE", "No preview gate is awaiting approval", 409)
    gates = list(dict.fromkeys([*receipt.get("approved_gates", []), gate_node_id]))
    return _update(run, status="executing", approved_gates=gates).status


def feedback_gate(run, version, gate_node_id):
    """Both completed previews and ready, still-pending choices accept feedback."""
    node = next((item for item in version.plan["nodes"] if item["id"] == gate_node_id), {})
    if node.get("gate") == "choice":
        from app.plans.choices import pending
        return pending(run, version, gate_node_id)[0]
    task = latest_tasks(run, version).get(gate_node_id)
    if (node.get("gate") != "preview" or not execution.usable(run, task)
            or gate_node_id in (run.snapshot or {}).get("v3_execution", {}).get("approved_gates", [])):
        raise AppError("INVALID_GATE", "Feedback requires an unapproved ready gate", 409)
    return task


def approve_results(run, version):
    version = versions.require_current_version(run, version)
    _frozen(run, version)
    if run.status == "success" and run.snapshot["v3_execution"].get("results_approved"):
        return "success"
    if run.status != "awaiting_result_review" or not all(execution.usable(run, item) for item in latest_tasks(run, version).values()):
        raise AppError("INVALID_AGENT_STATE", "All outputs must be available before acceptance", 409)
    return _update(run, status="success", results_approved=True).status


def cancel(run):
    for task in latest_tasks(run).values():
        if task.status in {"pending", "running"}:
            task.status = "cancelled"
            if task.job_id:
                job = Job.query.filter_by(job_id=task.job_id).first()
                if job and job.status not in {"success", "partial_success", "failed", "cancelled"}:
                    job.status = "cancelled"
    run.status = "cancelled"
    db.session.commit()
    return run.status
