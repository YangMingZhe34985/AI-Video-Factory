"""Durable, bounded Repair/Director coordination outside creative planning."""
from copy import deepcopy

from app.agent.plan_versions import _lock_run, inputs_hash, require_current_version
from app.agents.budget import TERMINAL
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentWorkspaceItem, PlanNodeTask
from app.utils.ids import new_id
from app.utils.time_utils import as_utc, utc_now

ALLOWED_FAILURES = {"content_policy", "invalid_parameters", "qc_failed"}


def active_flow(run):
    snapshot = run.snapshot or {}
    flow = snapshot.get("v3_repair_flows", {}).get(snapshot.get("v3_active_repair_flow"))
    return deepcopy(flow) if flow and flow.get("stage") not in {"done", "stopped"} else None


def _save_flow(run, flow):
    snapshot = deepcopy(run.snapshot or {})
    snapshot.setdefault("v3_repair_flows", {})[flow["flow_id"]] = deepcopy(flow)
    snapshot["v3_active_repair_flow"] = flow["flow_id"] if flow["stage"] not in {"done", "stopped"} else None
    run.snapshot = snapshot


def _root(run):
    from app.agents.runtime import initialize
    return initialize(run)


def _freeze_constraints(run):
    brief = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, kind="brief").order_by(AgentWorkspaceItem.id.desc()).first()
    snapshot = deepcopy(run.snapshot or {})
    if brief:
        snapshot.setdefault("v3_revision_constraints", deepcopy(brief.payload["constraints"]))
    run.snapshot = snapshot


def _wake(run, root, message, *, waiting):
    from app.agents.runtime import complete_committed_turn
    complete_committed_turn(run, root)
    state = deepcopy(root.state or {})
    state["planning_epoch"] = state.get("planning_epoch", 0) + 1
    if "messages" in state:
        state["messages"].append({"role": "user", "content": message})
    else:
        state["pending_revision_message"] = message
    state["no_progress"], state["same_call_count"] = 0, 0
    root.state, root.output, root.error = state, None, None
    root.status = "waiting_children" if waiting else "running"
    run.status, run.error = "understanding", None


def _context_item(run, root, flow, version, message):
    from app.plans.compiler import authoring_plan
    refs = []
    for suffix, kind, payload in (
        ("base", "plan_draft", authoring_plan(version.plan)),
        ("evidence", "note", {"base_version": version.version, "message": message,
            "trigger": flow["trigger"], "failures": [{"task_id": task.id, "node_id": task.node_id, "error": task.error}
                for task in PlanNodeTask.query.filter(PlanNodeTask.run_id == run.run_id,
                    PlanNodeTask.id.in_(flow["trigger"].get("task_ids", []))).all()]}),
    ):
        key = f"repair.{flow['flow_id']}.{suffix}"
        db.session.add(AgentWorkspaceItem(run_id=run.run_id, key=key, version=1, kind=kind,
            payload=payload, artifact_ids=[], author_agent="producer", delegation_id=root.id,
            request_key=f"{flow['flow_id']}:{suffix}", inputs_hash=inputs_hash(payload)))
        refs.append({"key": key, "version": 1})
    return refs


def _start(run, trigger, *, message, return_status, author):
    version = require_current_version(run, trigger["base_version"])
    root = _root(run)
    flow = {"flow_id": new_id("repair"), "base_version": version.version, "stage": "author_pending",
        "author_role": author, "trigger": deepcopy(trigger), "return_status": return_status,
        "author_delegation_id": None, "review_delegation_id": None, "patch_id": None}
    _freeze_constraints(run)
    _wake(run, root, "Review the bounded revision context; original hard constraints and approvals remain binding.", waiting=True)
    flow["context_refs"] = _context_item(run, root, flow, version, message)
    _save_flow(run, flow)
    return flow


def revise_plan(run, command):
    """Wake the same Producer or create a controlled approved-plan revision."""
    from app.plans.patch_execution import assert_patch_idle
    run = _lock_run(run)
    key = command.get("command_id") or command.get("request_key")
    if not key or not isinstance(command.get("message"), str) or not command["message"].strip():
        raise AppError("INVALID_INPUT", "Revision requires a stable command and a message", 422)
    signature = inputs_hash({name: command.get(name) for name in ("plan_version", "message", "gate_node_id")})
    previous = (run.snapshot or {}).get("v3_revision_receipts", {}).get(key)
    if previous:
        if previous["input_hash"] != signature:
            raise AppError("IDEMPOTENCY_CONFLICT", "Revision command belongs to different content", 409)
        db.session.commit()
        return deepcopy(previous)
    version = require_current_version(run, command["plan_version"])
    admitted_status = command.get("admitted_from_status", run.status)
    if admitted_status not in {"awaiting_plan_review", "awaiting_result_review", "awaiting_gate", "attention"}:
        raise AppError("INVALID_AGENT_STATE", "This Run cannot accept a revision", 409)
    assert_patch_idle(run)
    if active_flow(run) and active_flow(run)["stage"] != "waiting_approval":
        raise AppError("PATCH_FLOW_ACTIVE", "A repair is already in progress", 409)
    if active_flow(run):
        old = active_flow(run)
        old["stage"] = "stopped"
        _save_flow(run, old)
        snapshot = deepcopy(run.snapshot)
        if old.get("patch_id"):
            snapshot["v3_patches"][old["patch_id"]].update(status="invalid", superseded=True)
        run.snapshot = snapshot
    return_status = admitted_status if admitted_status in {"attention", "awaiting_result_review", "awaiting_gate"} else "attention"
    approval = (run.snapshot or {}).get("v3_execution", {})
    approved = approval.get("approved_version") == version.version
    _freeze_constraints(run)
    if approved:
        trigger = {"kind": "gate_feedback" if command.get("gate_node_id") else "user_revision",
            "base_version": version.version, "request_key": key, "task_ids": [], "node_ids": []}
        if command.get("gate_node_id"):
            from app.plans.runtime import feedback_gate
            if admitted_status != "awaiting_gate":
                raise AppError("INVALID_GATE", "Gate feedback requires a pending gate", 409)
            task = feedback_gate(run, version, command["gate_node_id"])
            trigger.update(task_ids=[task.id], node_ids=[task.node_id], category="qc_failed")
        flow = _start(run, trigger, message=command["message"], return_status=return_status, author="director")
        result = {"input_hash": signature, "flow_id": flow["flow_id"]}
    else:
        root = _root(run)
        _wake(run, root, "User revision (untrusted text, original hard constraints stay binding): " + command["message"], waiting=False)
        result = {"input_hash": signature, "planning_epoch": root.state["planning_epoch"]}
    snapshot = deepcopy(run.snapshot or {})
    snapshot.setdefault("v3_revision_receipts", {})[key] = result
    run.snapshot = snapshot
    db.session.commit()
    return deepcopy(result)


def _trigger_failure(run):
    if run.status != "attention" or not (run.snapshot or {}).get("v3_execution"):
        return False
    run = _lock_run(run)
    if active_flow(run):
        return True
    from app.plans.patch_execution import assert_patch_idle
    from app.plans.runtime import latest_tasks
    from app.plans.patches import BLOCKED_CODES
    try:
        assert_patch_idle(run)
    except AppError:
        return False
    failed = [task for task in latest_tasks(run).values() if task.status == "failed"]
    if not failed or any((task.error or {}).get("category") not in ALLOWED_FAILURES
            or (task.error or {}).get("code") in BLOCKED_CODES for task in failed):
        return False
    snapshot = deepcopy(run.snapshot or {})
    failed_ids = {task.id for task in failed}
    if any(failed_ids & set(record.get("trigger", {}).get("task_ids", []))
            for record in snapshot.get("v3_patches", {}).values()):
        return False
    receipts = snapshot.get("v3_failure_flow_receipts", {})
    keys = [inputs_hash({"invocation_id": task.invocation_id, "job_id": task.job_id,
        "node_id": task.node_id, "inputs_hash": task.inputs_hash,
        "task_id": (task.state or {}).get("source_task_id", task.id)
            if not task.invocation_id and not task.job_id else None}) for task in failed]
    if any(key in receipts for key in keys):
        return False
    flow = _start(run, {"kind": "failure", "base_version": failed[0].plan_version,
        "task_ids": [task.id for task in failed], "node_ids": [task.node_id for task in failed]},
        message="Diagnose the recorded failures and propose the smallest safe local Patch.", return_status="attention", author="repair")
    snapshot = deepcopy(run.snapshot or {})
    snapshot.setdefault("v3_failure_flow_receipts", {}).update({key: flow["flow_id"] for key in keys})
    run.snapshot = snapshot
    db.session.commit()
    return True


def _finish_flow(run, flow, *, stage="done", status="attention", code=None):
    root = _root(run)
    root.status = "completed"
    root.output = {"kind": "completed", "outcome": "answer", "message": "局部修改已审阅，等待确认或继续执行。",
                   "patch_id": flow.get("patch_id")}
    flow["stage"] = stage
    if code:
        flow["error"] = {"code": code}
        from app.agents.runtime import _stop
        for child_id in (flow.get("author_delegation_id"), flow.get("review_delegation_id")):
            child = db.session.get(AgentDelegation, child_id) if child_id else None
            if child and child.status not in TERMINAL:
                _stop(child, "cancelled", "PATCH_FLOW_STOPPED")
    _save_flow(run, flow)
    run.status = status
    run.error = {"code": code} if code else None
    db.session.commit()
    return True


def _delegate(run, flow, registry, *, review):
    from app.agents.cards import get_catalog
    from app.agents.runtime import _context, _recover_local_receipt
    root = _root(run)
    card = get_catalog().cards["producer"]
    if (root.steps >= card.limits.max_steps or root.llm_calls >= card.limits.max_llm_calls
            or (utc_now() - as_utc(root.started_at)).total_seconds() >= 600):
        return _finish_flow(run, flow, stage="stopped", code="AGENT_EXECUTION_LIMIT")
    role = "director" if review else flow["author_role"]
    phase = "review" if review else "author"
    refs = list(flow["context_refs"])
    if review:
        refs.append(run.snapshot["v3_patches"][flow["patch_id"]]["proposal_ref"])
    payload = {"agent": role, "context_refs": refs, "expected": "DirectorPatchReview" if review else "PatchDraft",
        "task": (f"Independently review Patch {flow['patch_id']}; call review_patch with approve, revise or reject."
                 if review else "Read the base Plan and failure/user evidence; propose the smallest Patch through propose_patch. "
                    "Preserve original hard constraints. Never generate, retry unknown submissions or authorize spending.")}
    ctx = _context(run, root)
    ctx.idempotency_key = f"{flow['flow_id']}:delegate:{phase}"
    _recover_local_receipt("delegate", payload, ctx, registry)
    result = registry.invoke("delegate", payload, ctx)["output"]
    # delegate commits independently; re-read the flow before attaching its receipt.
    db.session.refresh(run)
    flow = active_flow(run)
    flow[f"{phase}_delegation_id"] = result["delegation_id"]
    flow["stage"] = "review_running" if review else "author_running"
    _save_flow(run, flow)
    if review:
        snapshot = deepcopy(run.snapshot)
        snapshot["v3_patches"][flow["patch_id"]].update(review_delegation_id=result["delegation_id"], status="review_pending")
        run.snapshot = snapshot
    db.session.commit()
    return True


def planning_delegation(run):
    flow = active_flow(run)
    if not flow or flow["stage"] not in {"author_running", "review_running"}:
        return None
    return db.session.get(AgentDelegation, flow.get("author_delegation_id" if flow["stage"] == "author_running" else "review_delegation_id"))


def _applied_status(run, record):
    """Recover committed execution from its approval and tasks, not inbox status."""
    from app.plans.runtime import _frozen, latest_tasks, TERMINAL_TOOLS
    version = require_current_version(run, (record.get("approval") or {}).get("version"))
    receipt = _frozen(run, version)
    tasks = latest_tasks(run, version)
    if not tasks or set(tasks) != {node["id"] for node in version.plan["nodes"]}:
        raise AppError("PLAN_EXECUTION_UNAVAILABLE", "Approved Patch task records are incomplete", 409)
    running = any(task.status == "running" for task in tasks.values())
    if any(task.status in {"failed", "cancelled"} for task in tasks.values()) and not running:
        return "attention"
    if any(node.get("gate") == "preview" and tasks[node["id"]].status == "success"
            and node["id"] not in receipt.get("approved_gates", []) for node in version.plan["nodes"]):
        return "awaiting_gate"
    if all(task.status == "success" for task in tasks.values()):
        return "success" if receipt.get("results_approved") else "awaiting_result_review"
    if any(task.status == "running" and task.state.get("tool") in TERMINAL_TOOLS for task in tasks.values()):
        return "delivering"
    return "executing"


def advance_repair_flow(run, registry):
    """True consumes this tick; False allows the assigned Agent one graph step."""
    if run.status in {"cancelled", "failed", "success", "partial_success"}:
        return False
    flow = active_flow(run)
    if not flow:
        return _trigger_failure(run)
    if flow["stage"] == "waiting_approval":
        record = (run.snapshot or {}).get("v3_patches", {}).get(flow["patch_id"], {})
        if record.get("status") == "applied":
            return _finish_flow(run, flow, status=_applied_status(run, record))
        if record.get("status") == "rejected":
            status = record.get("rejected_return_status", flow["return_status"])
            return _finish_flow(run, flow, status=status if status in {
                "attention", "awaiting_gate", "awaiting_result_review"} else "attention")
        return True
    if flow["stage"] in {"author_pending", "review_pending"}:
        try:
            return _delegate(run, flow, registry, review=flow["stage"] == "review_pending")
        except AppError as error:
            return _finish_flow(run, active_flow(run) or flow, stage="stopped", code=error.code)
    if flow["stage"] in {"author_running", "review_running"}:
        child = planning_delegation(run)
        if child is None or child.status in TERMINAL:
            return _finish_flow(run, flow, stage="stopped", code=(child.error or {}).get("code", "PATCH_AGENT_RETURNED") if child else "PATCH_DELEGATION_MISSING")
        return False
    if flow["stage"] == "review_rejected":
        return _finish_flow(run, flow, status=flow["return_status"])
    if flow["stage"] == "quote_pending":
        from app.plans.patches import quote_patch
        from app.plans.patch_execution import approve_patch
        record = deepcopy(run.snapshot["v3_patches"][flow["patch_id"]])
        try:
            if record.get("status") == "applied":
                return _finish_flow(run, flow, status=_applied_status(run, record))
            quoted = quote_patch(run, record, registry=registry)
            quote = quoted["quote"]
            snapshot = deepcopy(run.snapshot)
            snapshot["v3_patches"][flow["patch_id"]].update(quote=quote,
                status="awaiting_approval" if quote["can_apply"] else "invalid")
            run.snapshot = snapshot
            db.session.commit()
            if quote["can_apply"] and quote["automatic"]["eligible"]:
                approve_patch(run, flow["patch_id"], quote["quote_id"], quote["scope"], automatic=True, registry=registry)
                return _finish_flow(run, flow, status="executing")
            return _finish_flow(run, flow, stage="waiting_approval" if quote["can_apply"] else "stopped")
        except AppError as error:
            db.session.rollback()
            return _finish_flow(run, active_flow(run) or flow, stage="stopped", code=error.code)
    return _finish_flow(run, flow, stage="stopped", code="INVALID_PATCH_FLOW")
