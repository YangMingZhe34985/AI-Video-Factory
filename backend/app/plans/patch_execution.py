"""Atomic authorization of reviewed Plan patches; no tool dispatch here."""
from copy import deepcopy
import math

from app.agent import plan_versions as versions
from app.api import AppError
from app.extensions import db
from app.models import AgentPlanVersion, ApiTask, Job, PlanNodeTask, ToolInvocation
from app.plans import execution, policy, runtime
from app.tools.budget import BudgetGuard


def assert_patch_idle(run):
    """Unknown submissions and unfinished old work cannot be replaced by a patch."""
    tasks = PlanNodeTask.query.filter_by(run_id=run.run_id).all()
    for task in tasks:
        error = task.error or {}
        if error.get("category") == "submit_unknown" or error.get("submission_state") == "unknown":
            raise AppError("RECOVERY_REQUIRED", "Resolve the original submission before changing its Plan", 409)
    for task in tasks:
        receipt = ToolInvocation.query.filter_by(invocation_id=task.invocation_id, budget_scope=run.run_id).first() if task.invocation_id else None
        receipt = receipt or ToolInvocation.query.filter_by(idempotency_key=policy.invocation_key(task), budget_scope=run.run_id).first()
        if (task.state.get("tool") in policy.PAID_TOOLS and receipt is not None
                and receipt.status in {"pending", "running", "failed"} and receipt.job is None):
            raise AppError("RECOVERY_REQUIRED", "An original tool submission has no definitive outcome", 409)
        job = Job.query.filter_by(job_id=task.job_id).first() if task.job_id else receipt.job if receipt else None
        if job and ApiTask.query.filter_by(job_id=job.id, queue_phase="submit_unknown").first():
            raise AppError("RECOVERY_REQUIRED", "Resolve the original provider submission before patching", 409)
        if task.status == "running" or (job and (runtime._in_flight(job)
                or job.status in {"created", "pending", "queued", "running", "waiting"}
                or ApiTask.query.filter_by(job_id=job.id).filter(ApiTask.status.in_({"submitted", "pending", "running"})).first())):
            raise AppError("PLAN_EXECUTION_ACTIVE", "Wait for original Plan work to finish before patching", 409)


def _amount(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise AppError("INVALID_PATCH_BUDGET", "Patch credits must be finite and non-negative", 409)
    return float(value)


def repair_state(run):
    state = deepcopy((run.snapshot or {}).get("v3_repair"))
    if state is None:
        state = {"budget_limit": (run.snapshot or {}).get("v3_execution", {}).get("repair_budget_credits", 0),
                 "repair_claims": {}}
    state["budget_limit"] = _amount(state["budget_limit"])
    return state


def _reserved(state):
    return sum(_amount(item["credits"]) for item in state["repair_claims"].values() if item.get("automatic"))


def _record(run, patch_id):
    if (run.request or {}).get("schema_version") != 3:
        raise AppError("INVALID_AGENT_STATE", "Plan patches require an Agent v3 Run", 409)
    record = deepcopy((run.snapshot or {}).get("v3_patches", {}).get(patch_id))
    if not record or record.get("patch_id") != patch_id:
        raise AppError("PATCH_NOT_FOUND", "Plan patch does not belong to this Run", 404)
    return record


def _same_approval(record, quote_id, scope):
    approval = record.get("approval", {})
    if approval.get("quote_id") != quote_id or approval.get("scope") != scope:
        raise AppError("PATCH_QUOTE_CHANGED", "Patch approval differs from its saved scope or quote", 409)
    return approval


def activate_patch_locked(run, version, compiled, decisions, *, patch_id, repair_state):
    """Stage tasks and authorization under the caller's Run lock, without commit."""
    from app.plans.patches import source_digest
    snapshot = deepcopy(run.snapshot or {})
    previous = deepcopy(snapshot.get("v3_execution", {}))
    approved_sources = decisions.get("source_fingerprints", {})
    if any(execution.fingerprint(run, key) != expected for key, expected in approved_sources.items()):
        raise AppError("PATCH_QUOTE_CHANGED", "A quoted source file changed before authorization", 409)
    if previous.get("approved_version"):
        snapshot.setdefault("v3_execution_history", {})[str(previous["approved_version"])] = previous
    created = {}
    for node in version.plan["nodes"]:
        decision = decisions["nodes"][node["id"]]
        old = PlanNodeTask.query.filter_by(run_id=run.run_id, node_id=node["id"]).order_by(PlanNodeTask.attempt.desc()).first()
        task = PlanNodeTask(run_id=run.run_id, plan_version=version.version, node_id=node["id"],
            attempt=old.attempt + 1 if old else 1, status="pending", inputs_hash=versions.inputs_hash(node),
            inputs={}, output={}, artifact_ids=[], estimated_cost=_amount(decision["estimated_cost"]),
            state={"tool": node["tool"], "resolved": False, "patch_id": patch_id,
                   "force_execute": bool(decision.get("force_rerun")),
                   "input_video_seconds": decision.get("input_video_seconds", 0),
                   "output_metadata": deepcopy(decision.get("output_metadata", {}))})
        if decision["action"] != "execute":
            source = db.session.get(PlanNodeTask, decision["source_task_id"])
            if (source is None or source.run_id != run.run_id
                    or source_digest(source) != decisions["sources"][node["id"]]["source_digest"]):
                raise AppError("PATCH_QUOTE_CHANGED", "A quoted source task changed before approval", 409)
            if decision["action"] in {"reuse", "retain"}:
                if not execution.usable(run, source):
                    raise AppError("PATCH_QUOTE_CHANGED", "A retained output is no longer available", 409)
                execution.carry_forward(task, source, retained_by_only=decision["action"] == "retain")
            elif decision["action"] == "preserve_failure" and source.status == "failed":
                execution.carry_forward(task, source)
            else:
                raise AppError("INVALID_PATCH", "Patch contains an invalid execution decision", 409)
        db.session.add(task)
        created[node["id"]] = task
    # Choice bindings include actual task IDs, including newly carried tasks.
    db.session.flush()
    choice_receipts = {}
    for node in version.plan["nodes"]:
        task = created[node["id"]]
        if node.get("gate") == "choice" and task.status == "success":
            from app.plans.choices import rebind
            source = db.session.get(PlanNodeTask, decisions["nodes"][node["id"]]["source_task_id"])
            choice_receipts[node["id"]] = rebind(run, version, node, task, created, source)
    approved_gates = [key for key in previous.get("approved_gates", []) if key in created
        and created[key].status == "success" and decisions["nodes"][key]["action"] in {"reuse", "retain"}
        and (created[key].state.get("tool") != "select_image" or key in choice_receipts)]
    snapshot["v3_execution"] = {"approved_version": version.version,
        "approval_hash": versions.inputs_hash(version.plan), "patch_id": patch_id,
        "node_costs": {key: item.estimated_cost for key, item in created.items()},
        "repair_budget_credits": repair_state["budget_limit"], "repair_spent": _reserved(repair_state),
        "approved_gates": approved_gates, "results_approved": False, "dag": deepcopy(compiled["dag"]),
        "output_metadata": deepcopy(compiled.get("output_metadata", {})),
        "source_fingerprints": {key: deepcopy(approved_sources[key]) for key in compiled.get("source_artifact_ids", [])}}
    if choice_receipts:
        snapshot["v3_execution"]["choice_receipts"] = choice_receipts
    snapshot["v3_repair"] = deepcopy(repair_state)
    snapshot["plan_version"] = version.version
    run.snapshot = snapshot
    run.status, run.error = "executing", None
    db.session.flush()


def approve_patch(run, patch_id, quote_id, scope, *, automatic=False, registry=None):
    from app.plans.patches import quote_patch
    try:
        run = versions._lock_run(run)
        record = _record(run, patch_id)
        if record.get("status") == "applied":
            approval = _same_approval(record, quote_id, scope)
            version = versions.get_version(run, approval["version"])
            db.session.commit()
            return version
        if record.get("status") == "rejected":
            raise AppError("PATCH_REJECTED", "A rejected patch cannot be approved", 409)
        if record.get("superseded") or record.get("status") == "invalid":
            raise AppError("PATCH_SUPERSEDED", "A newer revision replaced this patch", 409)
        if run.status not in {"attention", "awaiting_result_review", "awaiting_gate", "understanding"}:
            raise AppError("INVALID_AGENT_STATE", "This Run is not accepting a patch approval", 409)
        assert_patch_idle(run)
        bundle = quote_patch(run, record, scope=scope, registry=registry)
        quote, decisions, compiled = bundle["quote"], bundle["decisions"], bundle["compiled"]
        if quote.get("quote_id") != quote_id or quote.get("scope") != scope:
            raise AppError("PATCH_QUOTE_CHANGED", "Patch inputs or costs changed; review the current quote", 409)
        if not quote.get("can_apply") or compiled.get("issues") or not bundle["dry_run"].get("passed"):
            raise AppError("INVALID_PATCH", "Patch must pass compilation and dry-run before approval", 422,
                           payload={"issues": quote.get("issues", [])})
        if automatic and not quote.get("automatic", {}).get("eligible"):
            raise AppError("PATCH_APPROVAL_REQUIRED", "This patch requires explicit user approval", 409)
        if not automatic and not quote.get("manual_can_apply", False):
            raise AppError("BUDGET_EXCEEDED", "Explicit patch approval must preserve the remaining repair allowance", 422)
        source = versions.require_current_version(run, decisions["base_version"])
        runtime._frozen(run, source)
        number = source.version + 1
        if decisions["target_version"] != number:
            raise AppError("PATCH_QUOTE_CHANGED", "Patch target version changed", 409)
        state = repair_state(run)
        credits = _amount(quote["estimated_credits"]["repair"])
        node_ids = list(decisions.get("auto_node_ids", []))
        if automatic:
            if not node_ids or _reserved(state) + credits > state["budget_limit"] + 1e-6:
                raise AppError("REPAIR_BUDGET_EXCEEDED", "Automatic repair allowance is exhausted", 409)
            for node_id in node_ids:
                used = sum(item.get("automatic") and node_id in item["node_ids"] for item in state["repair_claims"].values())
                if used >= 2:
                    raise AppError("REPAIR_LIMIT_EXCEEDED", "This node has used its automatic repairs", 409)
        state["repair_claims"][patch_id] = {"credits": credits, "node_ids": node_ids, "automatic": bool(automatic),
            "status": "approved", "approved_version": number}
        remaining = max(0, state["budget_limit"] - _reserved(state))
        BudgetGuard.check(run.run_id, run.request["budget_limit"], _amount(quote["estimated_credits"]["total"]) + remaining)
        check = {**deepcopy(compiled), "dry_run": deepcopy(bundle["dry_run"])}
        version = AgentPlanVersion(run_id=run.run_id, version=number, parent_version=source.version,
            author="system" if automatic else "user", plan={**deepcopy(compiled["plan"]), "plan_version": number},
            story_package={}, check=check)
        db.session.add(version)
        db.session.flush()
        activate_patch_locked(run, version, compiled, decisions, patch_id=patch_id, repair_state=state)
        record.update(status="applied", approved_version=number, auto_approved=bool(automatic), quote=deepcopy(quote),
            approval={"quote_id": quote_id, "scope": scope, "version": number, "automatic": bool(automatic),
                      "candidate_hash": decisions.get("candidate_hash")})
        snapshot = deepcopy(run.snapshot)
        snapshot.setdefault("v3_patches", {})[patch_id] = record
        run.snapshot = snapshot
        db.session.commit()
        return version
    except BaseException:
        db.session.rollback()
        raise


def reject_patch(run, patch_id, quote_id, scope, *, registry=None):
    from app.plans.patches import quote_patch
    try:
        run = versions._lock_run(run)
        record = _record(run, patch_id)
        if record.get("status") == "applied":
            raise AppError("PATCH_ALREADY_APPLIED", "An applied patch cannot be rejected", 409)
        if record.get("status") == "rejected":
            _same_approval(record, quote_id, scope)
            current = versions.current_version(run)
            snapshot = run.snapshot or {}
            flow = snapshot.get("v3_repair_flows", {}).get(snapshot.get("v3_active_repair_flow"), {})
            if (current and current.version == record.get("rejected_version") and run.status == "understanding"
                    and flow.get("patch_id") in {None, patch_id}):
                run.status = record.get("rejected_return_status", "attention")
            db.session.commit()
            return run.status
        quote = quote_patch(run, record, scope=scope, registry=registry)["quote"]
        if quote.get("quote_id") != quote_id or quote.get("scope") != scope:
            raise AppError("PATCH_QUOTE_CHANGED", "Patch quote changed before rejection", 409)
        previous = record.get("return_status")
        if previous not in {"attention", "awaiting_result_review", "awaiting_gate"}:
            tasks = runtime.latest_tasks(run)
            previous = "awaiting_result_review" if tasks and all(task.status == "success" for task in tasks.values()) else "attention"
        record.update(status="rejected", approval={"quote_id": quote_id, "scope": scope},
                      rejection={"quote_id": quote_id, "scope": scope}, rejected_return_status=previous,
                      rejected_version=record["draft"]["base_version"])
        snapshot = deepcopy(run.snapshot or {})
        snapshot.setdefault("v3_patches", {})[patch_id] = record
        run.snapshot = snapshot
        run.status = previous
        db.session.commit()
        return run.status
    except BaseException:
        db.session.rollback()
        raise
