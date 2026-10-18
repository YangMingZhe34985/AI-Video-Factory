"""Offline Agent collaboration and repair side-effect recovery."""
from copy import deepcopy
from datetime import timedelta
from dataclasses import replace

import pytest

from app.agents import repair_flow, runtime
from app.agents.workspace import write_workspace
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentPlanVersion, AgentWorkspaceItem, PlanNodeTask, ToolInvocation
from app.plans import runtime as execution
from app.tools.scripted_llm import ScriptedLLM
from app.utils.time_utils import utc_now
from tests.test_v4_execution import setup, image_node
from tests.test_v3_runtime import call, done

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)


def failure(category="invalid_parameters", allowance=0):
    run, version, registry = setup()
    run.request = {**run.request, "_v3_runtime": True}
    root = AgentDelegation.query.filter_by(run_id=run.run_id, parent_id=None).one()
    root.status = "completed"
    root.output = {"kind": "completed", "outcome": "plan_submitted"}
    execution.begin(run, version, repair_budget_credits=allowance, registry=registry)
    task = execution.latest_tasks(run)["image"]
    task.status, task.error = "failed", {"category": category, "submission_state": "not_submitted"}
    run.status = "attention"
    db.session.commit()
    return run, root, task, registry


def draft(task):
    return {"base_version": task.plan_version, "reason": "Use a harmless prompt", "evidence_refs": [{"task_id": task.id}],
        "ops": [{"op": "update_inputs", "node_id": "image", "inputs": {"prompt": "A happy cat"}}]}


def assigned(run, registry):
    assert repair_flow.advance_repair_flow(run, registry)
    assert repair_flow.advance_repair_flow(run, registry)
    return repair_flow.planning_delegation(run)


def invoke(run, child, registry, name, payload, key):
    ctx = runtime._context(run, child)
    ctx.idempotency_key = key
    return registry.invoke(name, payload, ctx)["output"]


def proposed(run, child, task, registry):
    value = invoke(run, child, registry, "propose_patch", {"draft": draft(task)}, "propose")
    assert repair_flow.advance_repair_flow(run, registry)
    return value["patch_id"], repair_flow.planning_delegation(run)


@pytest.mark.parametrize("category", ["submit_unknown", "configuration", "auth", "insufficient_balance", "network"])
def test_unrepairable_failure_does_not_start_agents(app_ctx, category):
    run, root, _task, registry = failure(category)
    assert not repair_flow.advance_repair_flow(run, registry)
    assert root.status == "completed" and run.status == "attention"
    assert AgentDelegation.query.count() == 1 and ToolInvocation.query.count() == 0


def test_repair_independent_review_waits_without_producer_llm(app_ctx):
    run, root, task, registry = failure()
    child = assigned(run, registry)
    assert child.agent == "repair" and child.parent_id == root.id
    patch_id, director = proposed(run, child, task, registry)
    assert director.agent == "director" and director.id != child.id
    result = invoke(run, director, registry, "review_patch", {"patch_id": patch_id, "verdict": "approve", "reason": "Only the failed prompt changes"}, "review")
    assert result["status"] == "reviewed"
    assert repair_flow.advance_repair_flow(run, registry)
    assert run.status == "attention" and root.status == "completed"
    record = run.snapshot["v3_patches"][patch_id]
    assert record["status"] == "awaiting_approval" and record["quote"]["can_apply"]
    assert not record["quote"]["automatic"]["eligible"]
    runtime.advance(run)
    assert run.status == "attention" and ToolInvocation.query.filter_by(tool_name="agent_llm_turn").count() == 0
    assert AgentPlanVersion.query.count() == 1


def test_scripted_review_auto_applies_without_extra_producer_round(app_ctx):
    run, root, task, registry = failure(allowance=5)
    runtime.advance(run)
    runtime.advance(run)
    app_ctx.extensions["agent_v3_scripted_llm"] = ScriptedLLM({"repair": [[call("propose_patch", {"draft": draft(task)})]]})
    runtime.advance(run)
    flow = repair_flow.active_flow(run)
    assert flow["stage"] == "review_pending"
    runtime.advance(run)
    app_ctx.extensions["agent_v3_scripted_llm"] = ScriptedLLM({"director": [[call("review_patch", {
        "patch_id": flow["patch_id"], "verdict": "approve", "reason": "Local harmless correction"})]]})
    runtime.advance(run)
    runtime.advance(run)
    assert run.status == "executing", run.error
    assert AgentPlanVersion.query.count() == 2 and root.status == "completed"
    assert ToolInvocation.query.filter_by(tool_name="agent_llm_turn").count() == 2
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 0
    assert repair_flow.active_flow(run) is None


@pytest.mark.parametrize("name", ["propose_patch", "review_patch"])
def test_patch_tool_local_commit_recovers_without_duplicate_workspace(app_ctx, monkeypatch, name):
    run, _root, task, registry = failure()
    child = assigned(run, registry)
    payload = {"draft": draft(task)}
    if name == "review_patch":
        patch_id, child = proposed(run, child, task, registry)
        payload = {"patch_id": patch_id, "verdict": "approve", "reason": "Local change"}
    spec, original = registry.get(name), registry.get(name).handler
    def crash(data, ctx):
        original(data, ctx)
        raise KeyboardInterrupt("after local commit")
    monkeypatch.setitem(registry._specs, name, replace(spec, handler=crash))
    with pytest.raises(KeyboardInterrupt):
        invoke(run, child, registry, name, payload, "gap:" + name)
    count = AgentWorkspaceItem.query.filter_by(kind="patch").count()
    monkeypatch.setitem(registry._specs, name, spec)
    runtime.advance(run)
    receipt = ToolInvocation.query.filter_by(idempotency_key="gap:" + name).one()
    assert receipt.status == "success" and child.status == "completed"
    assert AgentWorkspaceItem.query.filter_by(kind="patch").count() == count


def test_delegate_commit_gap_recovers_same_child(app_ctx, monkeypatch):
    run, _root, _task, registry = failure()
    assert repair_flow.advance_repair_flow(run, registry)
    spec, original = registry.get("delegate"), registry.get("delegate").handler
    def crash(data, ctx):
        original(data, ctx)
        raise KeyboardInterrupt("after child commit")
    monkeypatch.setitem(registry._specs, "delegate", replace(spec, handler=crash))
    with pytest.raises(KeyboardInterrupt):
        repair_flow.advance_repair_flow(run, registry)
    assert AgentDelegation.query.count() == 2
    monkeypatch.setitem(registry._specs, "delegate", spec)
    assert repair_flow.advance_repair_flow(run, registry)
    assert AgentDelegation.query.count() == 2
    assert repair_flow.planning_delegation(run).agent == "repair"


def test_unassigned_director_and_finish_cannot_forge_review(app_ctx):
    run, root, task, registry = failure()
    child = assigned(run, registry)
    with pytest.raises(AppError) as error:
        invoke(run, child, registry, "finish", {"kind": "completed", "patch_ref": {"key": "x", "version": 1}, "diagnosis": "done"}, "badfinish")
    assert error.value.code == "PATCH_TOOL_REQUIRED"
    patch_id, director = proposed(run, child, task, registry)
    outsider = AgentDelegation(run_id=run.run_id, parent_id=root.id, agent="director", request_key="outsider", task="Other task", credits_limit=1)
    db.session.add(outsider)
    db.session.commit()
    with pytest.raises(AppError) as error:
        invoke(run, outsider, registry, "review_patch", {"patch_id": patch_id, "verdict": "approve", "reason": "pretend"}, "forged")
    assert error.value.code == "TOOL_FORBIDDEN"
    assert run.snapshot["v3_patches"][patch_id]["director_review"] is None
    with pytest.raises(AppError):
        invoke(run, director, registry, "delegate", {"agent": "critic", "task": "Review", "expected": "review"}, "unbounded")


def test_new_revision_supersedes_old_patch_and_preserves_limits(app_ctx):
    run, root, task, registry = failure()
    child = assigned(run, registry)
    patch_id, director = proposed(run, child, task, registry)
    invoke(run, director, registry, "review_patch", {"patch_id": patch_id, "verdict": "approve", "reason": "Local"}, "review")
    repair_flow.advance_repair_flow(run, registry)
    before = (root.steps, root.llm_calls, root.started_at, root.credits_limit)
    result = repair_flow.revise_plan(run, {"action": "revise_plan", "command_id": "user-revise", "plan_version": 1, "message": "Change background"})
    assert result["flow_id"] != run.snapshot["v3_patches"][patch_id]["flow_id"]
    assert run.snapshot["v3_patches"][patch_id]["status"] == "invalid"
    assert (root.steps, root.llm_calls, root.started_at, root.credits_limit) == before
    assert repair_flow.active_flow(run)["author_role"] == "director"


def test_revision_after_ended_checkpoint_runs_same_producer_new_epoch(app_ctx):
    run, _version, _registry = setup()
    root = AgentDelegation.query.filter_by(run_id=run.run_id, parent_id=None).one()
    run.request = {**run.request, "_v3_runtime": True}
    run.status = "understanding"
    db.session.commit()
    llm = ScriptedLLM({"producer": [done("first"), done("revised")]})
    app_ctx.extensions["agent_v3_scripted_llm"] = llm
    runtime.advance(run)
    assert run.status == "success"
    run.status = "awaiting_plan_review"
    run.command = {"action": "revise_plan", "command_id": "revision", "plan_version": 1, "message": "Change blue to red"}
    db.session.commit()
    started = root.started_at
    runtime.advance(run)
    assert root.output["message"] == "revised"
    assert root.steps == root.llm_calls == 2 and root.started_at == started
    assert root.state["planning_epoch"] == 1 and AgentDelegation.query.count() == 1
    assert llm.calls == [("producer", 0), ("producer", 1)]


def test_revision_does_not_reset_timeout_or_hard_constraints(app_ctx):
    run, root, _task, registry = failure()
    root.started_at = utc_now() - timedelta(seconds=601)
    db.session.commit()
    assert repair_flow.advance_repair_flow(run, registry)
    assert repair_flow.advance_repair_flow(run, registry)
    assert run.status == "attention" and run.error["code"] == "AGENT_EXECUTION_LIMIT"
    assert AgentDelegation.query.count() == 1 and not repair_flow.advance_repair_flow(run, registry)
    root.status, run.status = "running", "understanding"
    db.session.commit()
    payload = deepcopy(AgentWorkspaceItem.query.filter_by(kind="brief").one().payload)
    payload["constraints"]["model_preferences"] = ["wan"]
    ctx = runtime._context(run, root)
    ctx.idempotency_key = "changed-constraints"
    with pytest.raises(AppError) as error:
        write_workspace("brief", "brief", payload, ctx)
    assert error.value.code == "REVISION_CONSTRAINT_CONFLICT"


def test_approved_plan_cannot_submit_fresh_draft(app_ctx):
    run, root, _task, registry = failure()
    root.status, run.status = "running", "understanding"
    db.session.commit()
    with pytest.raises(AppError) as error:
        invoke(run, root, registry, "submit_plan", {"plan_ref": {"key": "missing", "version": 1}}, "bypass")
    assert error.value.code == "PATCH_REQUIRED"


@pytest.mark.parametrize("code", ["MODEL_PRICE_CHANGED", "INVALID_API_KEY", "INSUFFICIENT_BALANCE", "CONFIGURATION_ERROR"])
def test_configuration_failure_is_not_misclassified_as_repairable(app_ctx, code):
    run, _root, task, registry = failure()
    task.error = {**task.error, "code": code}
    db.session.commit()
    assert not repair_flow.advance_repair_flow(run, registry)
    assert AgentDelegation.query.count() == 1


def test_first_attention_transition_starts_flow_in_same_tick(app_ctx, monkeypatch):
    run, _root, _task, _registry = failure()
    run.status = "executing"
    db.session.commit()
    def transition(run, registry):
        run.status = "attention"
        db.session.commit()
    monkeypatch.setattr(execution, "advance", transition)
    runtime.advance(run)
    assert run.status == "understanding"
    assert repair_flow.active_flow(run)["stage"] == "author_pending"


def test_gate_feedback_uses_director_and_keeps_successful_output(app_ctx, monkeypatch):
    from app.services.job_run_service import JobRunService
    run, version, registry = setup([image_node(gate="preview")])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    execution.begin(run, version, registry=registry)
    assert execution.advance(run, registry) == "awaiting_gate"
    task = execution.latest_tasks(run)["image"]
    old = deepcopy(task.output)
    repair_flow.revise_plan(run, {"command_id": "gate-feedback", "plan_version": 1,
        "gate_node_id": "image", "message": "Change the cat's pose", "admitted_from_status": "awaiting_gate"})
    flow = repair_flow.active_flow(run)
    assert flow["trigger"]["kind"] == "gate_feedback" and flow["trigger"]["category"] == "qc_failed"
    assert flow["return_status"] == "awaiting_gate" and flow["author_role"] == "director"
    assert task.status == "success" and task.output == old


def test_patch_proposal_rejects_foreign_evidence_before_creating_receipt(app_ctx):
    run, _root, task, registry = failure()
    child = assigned(run, registry)
    payload = draft(task)
    payload["evidence_refs"] = [{"task_id": task.id + 100}]
    with pytest.raises(AppError) as error:
        invoke(run, child, registry, "propose_patch", {"draft": payload}, "foreign")
    assert error.value.code == "INVALID_PATCH_EVIDENCE"
    assert AgentWorkspaceItem.query.filter_by(kind="patch").count() == 0


def test_retained_failure_lineage_does_not_trigger_second_repair(app_ctx):
    run, root, task, registry = failure()
    root.started_at = utc_now() - timedelta(seconds=601)
    db.session.commit()
    assert repair_flow.advance_repair_flow(run, registry)
    assert repair_flow.advance_repair_flow(run, registry)
    retained = PlanNodeTask(run_id=run.run_id, plan_version=task.plan_version, node_id=task.node_id,
        attempt=task.attempt + 1, status="failed", inputs_hash=task.inputs_hash,
        inputs=deepcopy(task.inputs), output={}, artifact_ids=[], error=deepcopy(task.error),
        state={**task.state, "source_task_id": task.id, "reused_from": task.id})
    db.session.add(retained)
    db.session.commit()
    assert execution.latest_tasks(run)["image"].id == retained.id
    assert not repair_flow.advance_repair_flow(run, registry)
    assert len(run.snapshot["v3_failure_flow_receipts"]) == 1


@pytest.mark.parametrize("automatic", [False, True])
def test_approved_patch_commit_gap_recovers_execution_after_resume(app_ctx, monkeypatch, automatic):
    from app.services.job_run_service import JobRunService
    run, _root, task, registry = failure(allowance=5 if automatic else 0)
    child = assigned(run, registry)
    patch_id, director = proposed(run, child, task, registry)
    invoke(run, director, registry, "review_patch", {"patch_id": patch_id, "verdict": "approve", "reason": "Local"}, "review")
    if not automatic:
        repair_flow.advance_repair_flow(run, registry)
        quote = run.snapshot["v3_patches"][patch_id]["quote"]
        run.command = {"action": "approve_patch", "patch_id": patch_id, "quote_id": quote["quote_id"], "scope": "only"}
        run.status = "understanding"
        db.session.commit()
    original = repair_flow._finish_flow
    def crash(*args, **kwargs):
        raise KeyboardInterrupt("after approval commit before flow completion")
    monkeypatch.setattr(repair_flow, "_finish_flow", crash)
    with pytest.raises(KeyboardInterrupt):
        runtime.advance(run)
    assert run.snapshot["v3_patches"][patch_id]["status"] == "applied"
    assert AgentPlanVersion.query.count() == 2
    assert execution.latest_tasks(run)["image"].status == "pending"
    monkeypatch.setattr(repair_flow, "_finish_flow", original)
    run.status, run.command = "understanding", {"action": "resume", "command_id": "recover"}
    db.session.commit()
    runtime.advance(run)
    assert run.status == "executing" and repair_flow.active_flow(run) is None
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.advance(run)
    assert run.status == "awaiting_result_review"
    assert execution.latest_tasks(run)["image"].status == "success"
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 1
    assert ToolInvocation.query.filter_by(tool_name="agent_llm_turn").count() == 0


def test_rejected_patch_commit_gap_recovers_attention_after_resume(app_ctx, monkeypatch):
    run, _root, task, registry = failure()
    child = assigned(run, registry)
    patch_id, director = proposed(run, child, task, registry)
    invoke(run, director, registry, "review_patch", {"patch_id": patch_id, "verdict": "approve", "reason": "Local"}, "review")
    repair_flow.advance_repair_flow(run, registry)
    quote = run.snapshot["v3_patches"][patch_id]["quote"]
    run.command = {"action": "reject_patch", "patch_id": patch_id, "quote_id": quote["quote_id"], "scope": "only"}
    run.status = "understanding"
    db.session.commit()
    original = repair_flow._finish_flow
    def crash(*args, **kwargs):
        raise KeyboardInterrupt("after rejection commit before flow completion")
    monkeypatch.setattr(repair_flow, "_finish_flow", crash)
    with pytest.raises(KeyboardInterrupt):
        runtime.advance(run)
    assert run.snapshot["v3_patches"][patch_id]["status"] == "rejected"
    monkeypatch.setattr(repair_flow, "_finish_flow", original)
    run.status, run.command = "understanding", {"action": "resume", "command_id": "recover"}
    db.session.commit()
    runtime.advance(run)
    assert run.status == "attention" and repair_flow.active_flow(run) is None
    runtime.advance(run)
    assert run.status == "attention" and AgentPlanVersion.query.count() == 1


@pytest.mark.parametrize("error", [AppError("RECOVERY_REQUIRED", "Unknown submission", 409), RuntimeError("Unexpected")])
def test_uncertain_patch_approval_error_keeps_inbox(app_ctx, monkeypatch, error):
    from app.plans import patch_execution
    run, _root, _task, _registry = failure()
    command = {"action": "approve_patch", "patch_id": "unknown", "quote_id": "old", "scope": "only"}
    run.command, run.status = command, "understanding"
    db.session.commit()
    def reject(*args, **kwargs):
        raise error
    monkeypatch.setattr(patch_execution, "approve_patch", reject)
    with pytest.raises(type(error)):
        runtime.advance(run)
    assert run.command == command


@pytest.mark.parametrize("window", ["handler", "record", "record_end", "unknown_llm"])
def test_revision_closes_only_proven_submitted_turn(app_ctx, monkeypatch, window):
    from app.agents.api import RuntimeAction, admit_action
    from app.tools.registry import ToolRegistry
    from tests.test_v3_workspace import make_context, brief, next_context
    run, root, ctx = make_context(text="生成一张猫的照片")
    run.request = {**run.request, "_v3_runtime": True}
    run.status = "understanding"
    db.session.commit()
    write_workspace("brief", "brief", brief(), ctx)
    ref = write_workspace("draft", "plan_draft", {"title": "Cat", "goal": "Cat photo", "nodes": [image_node()],
        "deliverables": [{"kind": "image", "node_id": "image", "output": "image"}]}, next_context(ctx))["workspace_ref"]
    calls = [call("submit_plan", {"plan_ref": ref}, "submitted")]
    if window != "record_end":
        calls.append(call("write_workspace", {"key": "skipped", "kind": "note", "payload": {}}, "skip"))
    llm = ScriptedLLM({"producer": [calls, done("revised")]})
    app_ctx.extensions["agent_v3_scripted_llm"] = llm
    original_handler, original_record = ToolRegistry._run_handler, runtime._record
    class Crash(BaseException):
        pass
    def after_handler(spec, data, ctx):
        output = original_handler(spec, data, ctx)
        if spec.name == "submit_plan" and not window.startswith("record"):
            raise Crash("after submitted plan commit")
        return output
    def after_record(delegation, step, kind, **kwargs):
        original_record(delegation, step, kind, **kwargs)
        if kind == "tool" and kwargs.get("tool") == "submit_plan" and window.startswith("record"):
            raise Crash("after tool step commit")
    monkeypatch.setattr(ToolRegistry, "_run_handler", staticmethod(after_handler))
    monkeypatch.setattr(runtime, "_record", after_record)
    with pytest.raises(Crash):
        runtime.advance(run)
    db.session.rollback()
    assert root.status == "completed" and root.steps == 0 and root.llm_calls == 1
    assert root.state["pending_turn"]["cursor"] == (1 if window.startswith("record") else 0)
    run.status, run.error = "attention", {"code": "AGENT_RUNTIME_FAILED"}
    if window == "unknown_llm":
        ToolInvocation.query.filter_by(tool_name="agent_llm_turn").one().status = "running"
    db.session.commit()
    monkeypatch.setattr(ToolRegistry, "_run_handler", staticmethod(original_handler))
    monkeypatch.setattr(runtime, "_record", original_record)
    admit_action(run, RuntimeAction(action="revise_plan", request_key="revision", plan_version=1, message="改为白色的猫"))
    if window == "unknown_llm":
        with pytest.raises(AppError) as error:
            runtime.advance(run)
        assert error.value.code == "RECOVERY_REQUIRED"
        db.session.rollback()
        assert root.steps == 0 and "pending_turn" in root.state and llm.calls == [("producer", 0)]
    else:
        runtime.advance(run)
        assert root.output["message"] == "revised"
        assert root.steps == root.llm_calls == 2 and root.state["planning_epoch"] == 1
        assert "pending_turn" not in root.state and llm.calls == [("producer", 0), ("producer", 1)]
        replies = [item for item in root.state["messages"] if item.get("role") == "tool"]
        assert len([item for item in replies if item["tool_call_id"] == "submitted"]) == 1
        assert len([item for item in replies if item["tool_call_id"] == "skip" and "AGENT_SUSPENDED" in item["content"]]) == (0 if window == "record_end" else 1)
        assert AgentWorkspaceItem.query.filter_by(key="skipped").count() == 0
