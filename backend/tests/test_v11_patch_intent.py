"""Intent evidence, conservative Patch approval and crash recovery; Mock only."""
from copy import deepcopy
from dataclasses import replace
import pytest
from pydantic import ValidationError
from app.agents import repair_flow, runtime
from app.api import AppError
from app.extensions import db
from app.models import AgentPlanVersion, AgentWorkspaceItem, ToolInvocation
from app.plans import patches
from app.plans.patch_execution import approve_patch, reject_patch
from app.plans.patch_intent import IntentAssessment, assessment_key, verified_assessment
from app.plans.patch_tools import ReviewInput
from app.plans.views import public_patches
from tests.test_v5_patches import failed_case
from tests.test_v5_repair_flow import assigned, failure, invoke, proposed

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)
CHANGED = {"element": "猫跳舞", "change": "changed", "before": "随音乐节拍跳舞", "after": "自然抬爪摆动", "reason": "舞蹈动作被弱化"}

def reviewed(*, preserved=True, changes=(), allowance=20):
    run, root, task, registry = failure(category="content_policy", allowance=allowance)
    run.request = {**run.request, "text": "生成猫跟随音乐跳舞的视频"}
    db.session.commit()
    patch_id, director = proposed(run, assigned(run, registry), task, registry)
    payload = {"patch_id": patch_id, "verdict": "approve", "reason": "核对用户点名动作与最终草稿", "intent_preserved": preserved, "changed_elements": list(changes)}
    invoke(run, director, registry, "review_patch", payload, "intent-review")
    return run, root, task, registry, patch_id, director, payload

def record(run, patch_id):
    return run.snapshot["v3_patches"][patch_id]

@pytest.mark.parametrize("missing", ["intent_preserved", "changed_elements"])
def test_review_requires_explicit_assessment(missing):
    payload = {"patch_id": "patch", "verdict": "approve", "reason": "checked", "intent_preserved": True, "changed_elements": []}
    payload.pop(missing)
    with pytest.raises(ValidationError): ReviewInput.model_validate(payload)

@pytest.mark.parametrize("value", [None, "true", "false", 0, 1, [], {}])
def test_intent_boolean_is_strict(value):
    with pytest.raises(ValidationError): IntentAssessment.model_validate({"intent_preserved": value, "changed_elements": []})

@pytest.mark.parametrize("change", [{**CHANGED, "after": ""}, {**CHANGED, "after": " \t"}, {**CHANGED, "element": " "}, {**CHANGED, "before": ""}, {**CHANGED, "reason": "\t"}, {**CHANGED, "change": "unknown"}, {**CHANGED, "reason": "x" * 1001}, {**CHANGED, "approved": True}])
def test_changes_are_bounded_and_not_authority(change):
    with pytest.raises(ValidationError): IntentAssessment.model_validate({"intent_preserved": False, "changed_elements": [change]})

def test_changes_limit():
    with pytest.raises(ValidationError): IntentAssessment.model_validate({"intent_preserved": False, "changed_elements": [CHANGED] * 41})

def test_distinct_immutable_note_binds_request_and_director(app_ctx):
    run, _root, _task, _registry, patch_id, director, _payload = reviewed()
    review = record(run, patch_id)["director_review"]
    note = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key=review["assessment_ref"]["key"]).one()
    draft = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key=review["review_ref"]["key"]).one()
    assert note.kind == "note" and note.author_agent == "director" and note.delegation_id == director.id
    assert note.request_key == assessment_key(review["request_key"]) != draft.request_key
    assert note.payload["request_key"] == draft.request_key == "intent-review"
    assert verified_assessment(run, record(run, patch_id), patches.patch_digest(record(run, patch_id)["draft"])) == {"intent_preserved": True, "changed_elements": []}
    note.payload = {**note.payload, "intent_preserved": False}
    with pytest.raises(ValueError, match="immutable"): db.session.flush()
    db.session.rollback()

@pytest.mark.parametrize("preserved,changes,reason", [(False, [], "PATCH_INTENT_UNCERTAIN"), (False, [CHANGED], "PATCH_INTENT_CHANGED"), (True, [CHANGED], "PATCH_INTENT_CHANGED")])
def test_changed_or_uncertain_intent_requires_manual_approval(app_ctx, preserved, changes, reason):
    run, _root, _task, registry, patch_id, _director, _payload = reviewed(preserved=preserved, changes=changes)
    assert repair_flow.advance_repair_flow(run, registry)
    patch = record(run, patch_id)
    assert run.status == "attention" and patch["status"] == "awaiting_approval"
    quote = patch["quote"]
    assert quote["can_apply"] and quote["manual_can_apply"] and not quote["automatic"]["eligible"]
    assert reason in quote["automatic"]["reasons"] and AgentPlanVersion.query.count() == 1
    assert ToolInvocation.query.filter(ToolInvocation.tool_name.in_(["generate_image", "generate_video", "animate_shot"])).count() == 0
    with pytest.raises(AppError) as denied: approve_patch(run, patch_id, quote["quote_id"], quote["scope"], automatic=True, registry=registry)
    assert denied.value.code == "PATCH_APPROVAL_REQUIRED"
    version = approve_patch(run, patch_id, quote["quote_id"], quote["scope"], registry=registry)
    assert version.version == 2 and not record(run, patch_id)["auto_approved"]
    assert approve_patch(run, patch_id, quote["quote_id"], quote["scope"], registry=registry).id == version.id

def test_preserved_intent_keeps_existing_low_risk_auto_flow(app_ctx):
    run, _root, _task, registry, patch_id, _director, _payload = reviewed()
    repair_flow.advance_repair_flow(run, registry)
    assert run.status == "executing" and record(run, patch_id)["auto_approved"] and AgentPlanVersion.query.count() == 2

def test_preserved_intent_does_not_override_budget(app_ctx):
    run, _root, _task, registry, patch_id, _director, _payload = reviewed(allowance=0)
    quote = patches.quote_patch(run, record(run, patch_id), registry=registry)["quote"]
    assert not quote["automatic"]["eligible"] and "REPAIR_BUDGET_EXCEEDED" in quote["automatic"]["reasons"]

def test_historical_missing_assessment_is_manual_and_readable(app_ctx):
    run, _version, registry, _task, patch = failed_case()
    # Historical persisted reviews predate all three fields, not partially forged evidence.
    for field in ("intent_preserved", "changed_elements", "assessment_ref"):
        patch["director_review"].pop(field)
    quote = patches.quote_patch(run, patch, registry=registry)["quote"]
    assert quote["manual_can_apply"] and "PATCH_INTENT_UNCERTAIN" in quote["automatic"]["reasons"]
    run.snapshot = {**run.snapshot, "v3_patches": {patch["patch_id"]: patch}}
    assert public_patches(run)[0]["review"]["intent_preserved"] is None

@pytest.mark.parametrize("field,value", [("intent_preserved", False), ("changed_elements", [CHANGED]), ("reason", "different rationale"), ("request_key", "other-request"), ("assessment_ref", {"key": "foreign", "version": 1})])
def test_snapshot_tamper_cannot_change_authorization(app_ctx, field, value):
    run, _root, _task, registry, patch_id, _director, _payload = reviewed()
    changed = deepcopy(record(run, patch_id)); changed["director_review"][field] = value
    with pytest.raises(AppError) as error: patches.quote_patch(run, changed, registry=registry)
    assert error.value.code == "PATCH_REVIEW_REQUIRED"

def test_false_cannot_be_forged_true(app_ctx):
    run, _root, _task, registry, patch_id, _director, _payload = reviewed(preserved=False)
    changed = deepcopy(record(run, patch_id)); changed["director_review"]["intent_preserved"] = True
    with pytest.raises(AppError) as error: patches.quote_patch(run, changed, registry=registry)
    assert error.value.code == "PATCH_REVIEW_REQUIRED"

@pytest.mark.parametrize("field", ["intent_preserved", "changed_elements", "assessment_ref"])
def test_partial_assessment_not_downgraded_to_legacy(app_ctx, field):
    run, _root, _task, registry, patch_id, _director, _payload = reviewed()
    changed = deepcopy(record(run, patch_id)); changed["director_review"].pop(field)
    with pytest.raises(AppError): patches.quote_patch(run, changed, registry=registry)

@pytest.mark.parametrize("mutation", ["key", "hash", "delegation", "author", "payload"])
def test_note_identity_content_verified(app_ctx, mutation):
    run, _root, _task, registry, patch_id, _director, _payload = reviewed()
    patch = record(run, patch_id)
    row = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key=patch["director_review"]["assessment_ref"]["key"]).one()
    if mutation == "key": row.request_key = "forged"
    elif mutation == "hash": row.inputs_hash = "0" * 64
    elif mutation == "delegation": row.delegation_id = patch["author_delegation_id"]
    elif mutation == "author": row.author_agent = "repair"
    else: row.payload = {**row.payload, "base_version": 999}
    with pytest.raises(AppError) as error: patches.quote_patch(run, patch, registry=registry)
    assert error.value.code == "PATCH_REVIEW_REQUIRED"
    db.session.rollback()

def test_review_commit_recovery_does_not_duplicate_note(app_ctx, monkeypatch):
    run, _root, task, registry = failure()
    patch_id, director = proposed(run, assigned(run, registry), task, registry)
    payload = {"patch_id": patch_id, "verdict": "approve", "reason": "preserved", "intent_preserved": True, "changed_elements": []}
    spec = registry.get("review_patch")
    def interrupted(data, ctx):
        spec.handler(data, ctx)
        raise KeyboardInterrupt("after local commit")
    monkeypatch.setitem(registry._specs, "review_patch", replace(spec, handler=interrupted))
    with pytest.raises(KeyboardInterrupt): invoke(run, director, registry, "review_patch", payload, "crash-intent")
    count = AgentWorkspaceItem.query.count()
    monkeypatch.setitem(registry._specs, "review_patch", spec)
    runtime.advance(run)
    assert AgentWorkspaceItem.query.count() == count
    receipt = ToolInvocation.query.filter_by(idempotency_key="crash-intent").one()
    assert receipt.status == "success" and receipt.attempt == 1 and receipt.estimated_cost == 0

def test_manual_rejection_keeps_old_plan(app_ctx):
    run, _root, _task, registry, patch_id, _director, _payload = reviewed(preserved=False, changes=[CHANGED])
    repair_flow.advance_repair_flow(run, registry); quote = record(run, patch_id)["quote"]
    reject_patch(run, patch_id, quote["quote_id"], quote["scope"], registry=registry)
    assert AgentPlanVersion.query.count() == 1 and record(run, patch_id)["status"] == "rejected"

def test_public_view_exact_changes_no_internal_evidence(app_ctx):
    run, _root, _task, _registry, _patch_id, _director, _payload = reviewed(preserved=False, changes=[CHANGED])
    review = public_patches(run)[0]["review"]
    assert review["intent_preserved"] is False and review["changed_elements"] == [CHANGED]
    assert set(review) == {"verdict", "reason", "intent_preserved", "changed_elements"}

def test_dancing_cat_video_prompt_downgrade_requires_human_review(app_ctx):
    from app.models import AgentDelegation
    from app.plans import runtime as execution
    from tests.test_v4_execution import setup
    node = {"id": "video", "tool": "generate_video", "inputs": {"mode": "t2v", "prompt": "An orange cat dancing rhythmically to music"},
        "model_id": "wan2.7-t2v", "params": {"duration": 5}, "origin": {"agent": "director", "skills": []}, "rationale": "The user requested dancing"}
    run, version, registry = setup([node], deliverables=[{"kind": "video", "node_id": "video", "output": "video"}])
    run.request = {**run.request, "_v3_runtime": True, "text": "生成一只猫跳舞的视频"}
    root = AgentDelegation.query.filter_by(run_id=run.run_id, parent_id=None).one()
    root.status = "completed"; root.output = {"kind": "completed", "outcome": "plan_submitted"}
    execution.begin(run, version, repair_budget_credits=20, registry=registry)
    task = execution.latest_tasks(run)["video"]
    task.status = "failed"; task.error = {"category": "content_policy", "submission_state": "not_submitted"}
    run.status = "attention"; db.session.commit()
    author = assigned(run, registry)
    draft = {"base_version": 1, "reason": "改写动作；失败原因仅为测试注入，不推断供应商政策", "evidence_refs": [{"task_id": task.id}],
        "ops": [{"op": "update_inputs", "node_id": "video", "inputs": {"prompt": "An orange cat naturally swaying and lifting its paws"}}]}
    proposal = invoke(run, author, registry, "propose_patch", {"draft": draft}, "cat-downgrade-proposal")
    repair_flow.advance_repair_flow(run, registry)
    director = repair_flow.planning_delegation(run)
    invoke(run, director, registry, "review_patch", {"patch_id": proposal["patch_id"], "verdict": "approve", "reason": "舞蹈被自然摆动替换，需用户同意", "intent_preserved": False, "changed_elements": [CHANGED]}, "cat-downgrade-review")
    repair_flow.advance_repair_flow(run, registry)
    patch = record(run, proposal["patch_id"])
    assert patch["status"] == "awaiting_approval" and run.status == "attention"
    assert patch["quote"]["automatic"]["reasons"] == ["PATCH_INTENT_CHANGED"]
    assert patch["quote"]["manual_can_apply"] and AgentPlanVersion.query.count() == 1
    assert ToolInvocation.query.filter_by(tool_name="generate_video").count() == 0
    diff = public_patches(run)[0]["diff_preview"][0]
    assert "dancing" in diff["before"]["prompt"] and "swaying" in diff["after"]["prompt"]


def test_removed_element_may_have_empty_after():
    value = IntentAssessment.model_validate({"intent_preserved": False, "changed_elements": [{**CHANGED, "change": "removed", "after": ""}]})
    assert value.changed_elements[0].after == ""
