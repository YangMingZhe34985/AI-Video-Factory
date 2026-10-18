"""Planning tools persist reviewable drafts; no call grants generation approval."""

from copy import deepcopy

import pytest

from app.agents.workspace import write_workspace
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentPlanVersion, AgentRun, AgentWorkspaceItem, Job, ToolInvocation
from app.plans import tools
from app.plans.compiler import compile_plan
from app.tools import build_v3_registry
from app.tools.spec import ToolContext
from tests.test_v3_plan_compiler import make_run, node, plan


def registry():
    value = build_v3_registry()
    if "submit_plan" not in value._specs:
        tools.register_plan_tools(value)
    return value


def context(run, key="instantiate", role="producer"):
    delegation = AgentDelegation.query.filter_by(run_id=run.run_id, agent=role).first()
    if delegation is None:
        delegation = AgentDelegation(run_id=run.run_id, agent=role, task="plan", request_key=role, credits_limit=10)
        db.session.add(delegation)
        db.session.commit()
    return ToolContext(role=role, caller_agent=role, delegation_id=delegation.id, budget_scope=run.run_id,
                       idempotency_key=key, budget_limit=1000)


def blueprint_input():
    return {"name": "image-create", "params": {"plan": {"recipe": "image_create", "title": "cat", "rationale": "one image",
        "image": {"mode": "t2i", "prompt": "A cat", "model_id": "wan2.6-image", "n": 1}}}}


def invoke(value, name, payload, run, key, role="producer"):
    return value.invoke(name, payload, context(run, key, role))["output"]


def save(run, draft, key="draft", request_key="write"):
    return write_workspace(key, "plan_draft", draft, context(run, request_key))["workspace_ref"]


def test_check_plan_is_read_only_and_cannot_submit(app_ctx):
    run = make_run()
    before = (Job.query.count(), ToolInvocation.query.count(), AgentWorkspaceItem.query.count(), AgentPlanVersion.query.count())
    result = invoke(registry(), "check_plan", {"plan": plan()}, run, "check")
    assert result["issues"] == [] and result["estimates"]["total_credits"] > 0
    assert (Job.query.count(), ToolInvocation.query.count(), AgentWorkspaceItem.query.count(), AgentPlanVersion.query.count()) == before
    assert run.status == "queued"


def test_blueprint_creates_one_workspace_and_server_origin_receipt(app_ctx):
    run = make_run()
    value = registry()
    result = invoke(value, "instantiate_blueprint", blueprint_input(), run, "build")
    assert result["issues"] == [] and result["experimental"] is False
    item = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, kind="plan_draft").one()
    assert result["workspace_ref"] == {"key": item.key, "version": 1}
    assert len(run.snapshot["v3_blueprint_receipts"]) == 1
    assert compile_plan(item.payload, run)["experimental"] is False
    assert invoke(value, "instantiate_blueprint", blueprint_input(), run, "build") == result
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 1
    assert AgentPlanVersion.query.count() == 0
    assert all(row.estimated_cost == 0 for row in ToolInvocation.query.all())


def test_blueprint_cannot_accept_forged_server_prices_or_unknown_names(app_ctx):
    run = make_run()
    value = registry()
    forged = blueprint_input()
    forged["params"]["plan"]["estimated_cost"] = 0
    with pytest.raises(AppError):
        invoke(value, "instantiate_blueprint", forged, run, "forged")
    with pytest.raises(AppError, match="Unknown registered Blueprint"):
        invoke(value, "instantiate_blueprint", {"name": "not-registered", "params": {}}, run, "unknown")
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 0
    assert "v3_blueprint_receipts" not in run.snapshot


def test_submit_requires_producer_and_never_executes(app_ctx):
    run = make_run()
    ref = save(run, plan())
    value = registry()
    with pytest.raises(AppError):
        invoke(value, "submit_plan", {"plan_ref": ref}, run, "director-submit", "director")
    before_jobs = Job.query.count()
    result = invoke(value, "submit_plan", {"plan_ref": ref}, run, "producer-submit")
    assert result["submitted"] and result["plan_version"] == 1 and result["dry_run"]["passed"]
    assert run.status == "awaiting_plan_review"
    producer = AgentDelegation.query.filter_by(run_id=run.run_id, agent="producer").one()
    assert producer.status == "completed"
    assert producer.output == {"kind": "completed", "outcome": "plan_submitted", "plan_ref": ref,
                               "message": "计划已提交，请审核后开始生成。"}
    assert Job.query.count() == before_jobs
    version = AgentPlanVersion.query.one()
    assert version.check["dry_run"]["passed"]
    assert version.check["dag"]["order"] == ["image"]
    assert version.check["output_metadata"]["image"]["image"]["type"] == "image"
    assert "v3_execution" not in run.snapshot
    assert invoke(value, "submit_plan", {"plan_ref": ref}, run, "producer-submit") == result
    assert AgentPlanVersion.query.count() == 1


def test_invalid_plan_remains_editable_and_new_workspace_version_can_submit(app_ctx):
    run = make_run()
    ref = save(run, plan([node(model_id="not_a_model")]))
    value = registry()
    rejected = invoke(value, "submit_plan", {"plan_ref": ref}, run, "bad-submit")
    assert not rejected["submitted"] and rejected["issues"]
    assert AgentPlanVersion.query.count() == 0
    assert run.status == "queued"
    assert AgentDelegation.query.filter_by(run_id=run.run_id, agent="producer").one().status == "pending"
    repaired = save(run, plan(), request_key="repaired")
    assert repaired["version"] == 2
    assert invoke(value, "submit_plan", {"plan_ref": repaired}, run, "good-submit")["submitted"]
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 2


def test_submit_binds_exact_workspace_version_and_rejects_other_run(app_ctx):
    run = make_run()
    ref = save(run, plan())
    other = make_run()
    with pytest.raises(AppError):
        invoke(registry(), "submit_plan", {"plan_ref": ref}, other, "foreign")
    with pytest.raises(AppError):
        invoke(registry(), "submit_plan", {"plan_ref": {"key": "brief", "version": 1}}, run, "wrongkind")
    assert AgentPlanVersion.query.count() == 0


def test_mutation_key_conflict_cannot_reuse_another_draft(app_ctx):
    run = make_run()
    value = registry()
    invoke(value, "instantiate_blueprint", blueprint_input(), run, "same")
    changed = blueprint_input()
    changed["params"]["plan"]["image"]["prompt"] = "a dog"
    with pytest.raises(AppError):
        invoke(value, "instantiate_blueprint", changed, run, "same")
    with pytest.raises(AppError, match="different operation"):
        tools.recover_receipt("instantiate_blueprint", changed, context(run, "same"))
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 1


@pytest.mark.parametrize("name", ["instantiate_blueprint", "submit_plan"])
def test_local_commit_survives_lost_registry_receipt_without_duplicate_work(app_ctx, monkeypatch, name):
    run = make_run()
    value = registry()
    payload = blueprint_input() if name == "instantiate_blueprint" else {"plan_ref": save(run, plan())}
    original = value._run_handler
    class WorkerCrash(BaseException):
        pass
    def crash(spec, data, ctx):
        output = original(spec, data, ctx)
        if spec.name == name:
            raise WorkerCrash()
        return output
    monkeypatch.setattr(value, "_run_handler", crash)
    ctx = context(run, "crash")
    with pytest.raises(WorkerCrash):
        value.invoke(name, payload, ctx)
    db.session.remove()
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).one()
    row_counts = (AgentWorkspaceItem.query.count(), AgentPlanVersion.query.count())
    recovered = tools.recover_receipt(name, payload, ctx)
    assert recovered is not None
    if name == "submit_plan":
        producer = db.session.get(AgentDelegation, ctx.delegation_id)
        assert producer.status == "completed" and producer.output["plan_ref"] == payload["plan_ref"]
        assert run.status == "awaiting_plan_review"
    # Runtime recovery can restore the tool receipt without executing a handler.
    ledger = ToolInvocation.query.filter_by(idempotency_key="crash").one()
    assert ledger.status == "pending" and not ledger.output_payload
    ledger.output_payload, ledger.status = recovered, "success"
    db.session.commit()
    assert value.invoke(name, payload, ctx)["replayed"]
    assert (AgentWorkspaceItem.query.count(), AgentPlanVersion.query.count()) == row_counts


def test_blueprint_transaction_rolls_back_workspace_and_provenance_together(app_ctx, monkeypatch):
    run = make_run()
    ctx = context(run, "rollback")
    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit fault")))
    with pytest.raises(RuntimeError, match="commit fault"):
        tools.instantiate_blueprint(tools.InstantiateInput.model_validate(blueprint_input()), ctx)
    monkeypatch.undo()
    db.session.refresh(run)
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 0
    assert "v3_blueprint_receipts" not in run.snapshot
    assert "v3_plan_tool_receipts" not in run.snapshot


def test_submit_transaction_keeps_delegation_version_and_receipt_atomic(app_ctx, monkeypatch):
    run = make_run()
    ref = save(run, plan())
    ctx = context(run, "submit-rollback")
    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit fault")))
    with pytest.raises(RuntimeError, match="commit fault"):
        tools.submit_plan(tools.SubmitInput(plan_ref=ref), ctx)
    monkeypatch.undo()
    db.session.refresh(run)
    producer = db.session.get(AgentDelegation, ctx.delegation_id)
    assert producer.status == "pending" and producer.output is None
    assert run.status == "queued" and AgentPlanVersion.query.count() == 0
    assert "v3_plan_submission" not in run.snapshot and "v3_plan_tool_receipts" not in run.snapshot


def test_optional_finish_still_requires_the_exact_submitted_receipt(app_ctx):
    run = make_run()
    ref = save(run, plan())
    another = save(run, plan(), request_key="another-draft")
    run.request = {**run.request, "_v3_runtime": True}
    db.session.commit()
    value = registry()
    invoke(value, "submit_plan", {"plan_ref": ref}, run, "submit")
    data = {"kind": "completed", "outcome": "plan_submitted", "plan_ref": another, "message": "ready"}
    with pytest.raises(AppError, match="server-submitted Plan"):
        invoke(value, "finish", data, run, "wrong-finish")
    data["plan_ref"] = ref
    assert invoke(value, "finish", data, run, "valid-finish")["status"] == "completed"


def test_completed_delegation_can_replay_but_cannot_create_another_blueprint(app_ctx):
    run = make_run()
    value = registry()
    result = invoke(value, "instantiate_blueprint", blueprint_input(), run, "existing")
    delegation = AgentDelegation.query.filter_by(run_id=run.run_id, agent="producer").one()
    delegation.status = "completed"
    run.status = "success"
    db.session.commit()
    assert tools.recover_receipt("instantiate_blueprint", blueprint_input(), context(run, "existing")) == result
    with pytest.raises(AppError, match="active planning"):
        invoke(value, "instantiate_blueprint", blueprint_input(), run, "new")


def test_submit_uses_dry_run_result_before_creating_version(app_ctx, monkeypatch):
    run = make_run()
    ref = save(run, plan())
    monkeypatch.setattr(tools, "dry_run", lambda compiled: {"passed": False, "issues": [{"code": "INJECTED_DATA_FLOW_ERROR", "node_id": "image", "message": "fault"}]})
    output = invoke(registry(), "submit_plan", {"plan_ref": ref}, run, "dry-fault")
    assert not output["submitted"] and output["issues"][0]["code"] == "INJECTED_DATA_FLOW_ERROR"
    assert AgentPlanVersion.query.count() == 0 and run.status == "queued"


def test_submitted_plan_is_immutable_and_second_submit_needs_revision_phase(app_ctx):
    run = make_run()
    ref = save(run, plan())
    value = registry()
    invoke(value, "submit_plan", {"plan_ref": ref}, run, "first")
    with pytest.raises(AppError, match="active planning"):
        invoke(value, "submit_plan", {"plan_ref": ref}, run, "second")
    row = AgentPlanVersion.query.one()
    row.plan = {**row.plan, "title": "tampered"}
    with pytest.raises(ValueError, match="immutable"):
        db.session.commit()
    db.session.rollback()


def test_blueprint_with_future_references_can_be_written_and_submitted(app_ctx):
    run = make_run(deliverable="video")
    payload = blueprint_input()
    payload["name"] = "single-clip"
    payload["params"]["plan"].update(recipe="single_clip", video={"mode": "i2v", "prompt": "cat dances", "model_id": "wan2.7-i2v",
        "first_frame": "generated_image", "params": {"duration": 5}})
    value = registry()
    built = invoke(value, "instantiate_blueprint", payload, run, "clip-build")
    assert not built["issues"]
    assert invoke(value, "submit_plan", {"plan_ref": built["workspace_ref"]}, run, "clip-submit")["submitted"]
