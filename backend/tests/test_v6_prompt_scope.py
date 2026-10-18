"""Offline Prompt Smith scopes, typed results and internal Repair delegation."""

from copy import deepcopy
import json

import pytest

from app.agents import runtime
from app.agents.tools import DelegateInput
from app.agents.workspace import write_workspace
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentRun, AgentWorkspaceItem, ToolInvocation
from app.tools import build_v3_registry
from app.utils.ids import new_id


@pytest.fixture
def scoped(app_ctx):
    run = AgentRun(owner_id="local", request_key=new_id("scope"), request={
        "schema_version": 3, "text": "A cat portrait. Do not use HappyHorse.",
        "attachment_ids": [], "budget_limit": 100}, snapshot={})
    db.session.add(run)
    db.session.commit()
    root = runtime.initialize(run)
    registry = build_v3_registry()
    result = registry.invoke("delegate", {"agent": "director", "task": "Make a portrait plan",
        "expected": "PlanDraft"}, runtime._context(run, root, suffix="director"))["output"]
    director = db.session.get(AgentDelegation, result["delegation_id"])
    plan = {"title": "Portrait", "goal": "One cat image", "deliverables": [
        {"kind": "image", "node_id": "cat", "output": "image"}], "nodes": [
        {"id": name, "tool": tool, "inputs": {"prompt": name} if tool != "qc_video" else {},
         "origin": {"agent": "director"}, "rationale": "Scope test"}
        for name, tool in (("cat", "generate_image"), ("dog", "generate_image"),
                           ("clip", "transform_video"), ("qc", "qc_video"))]}
    ref = write_workspace("draft", "plan_draft", plan,
        runtime._context(run, director, suffix="draft"))["workspace_ref"]
    return app_ctx, run, root, director, registry, ref


def request(ref, ids=None):
    return {"agent": "prompt_smith", "task": "Polish the assigned prompts only", "expected": "PromptUpdates",
        "context_refs": [ref], "prompt_scope": {"plan_ref": ref, "node_ids": ids or ["cat"]}}


def invoke(scoped, actor, name, payload, key=None):
    _app, run, _root, _director, registry, _ref = scoped
    return registry.invoke(name, payload, runtime._context(run, actor, suffix=key or new_id("call")))


def delegate(scoped, ids=None, key="smith"):
    actor, ref = scoped[3], scoped[5]
    output = invoke(scoped, actor, "delegate", request(ref, ids), key)["output"]
    return db.session.get(AgentDelegation, output["delegation_id"])


def update(node="cat", **fields):
    return {"kind": "completed", "updates": [{"node_id": node, "inputs_patch": fields or {"prompt": "A polished cat portrait"}}]}


def test_scope_is_frozen_in_child_and_shown_in_initial_context(scoped):
    _app, run, _root, _director, registry, ref = scoped
    child = delegate(scoped)
    frozen = deepcopy(child.state["prompt_scope"])
    messages = runtime._initial_messages(run, child, registry)
    assert json.loads(messages[1]["content"])["prompt_scope"] == {"plan_ref": ref, "node_ids": ["cat"]}
    assert "Do not use HappyHorse" in messages[1]["content"]
    assert len(frozen["plan_hash"]) == 64
    result = invoke(scoped, child, "finish", update())["output"]
    assert result["output"]["updates"] == update()["updates"]
    assert child.state["prompt_scope"] == frozen
    assert AgentWorkspaceItem.query.count() == 1
    assert AgentWorkspaceItem.query.one().payload["nodes"][0]["inputs"]["prompt"] == "cat"


@pytest.mark.parametrize("change", ["missing", "foreign_role", "empty", "duplicate", "unknown", "local_tool", "outside_context", "wrong_kind"])
def test_invalid_scope_is_rejected_before_child_or_quota_creation(scoped, change):
    _app, run, _root, director, _registry, ref = scoped
    payload = request(ref)
    if change == "missing":
        payload.pop("prompt_scope")
    elif change == "foreign_role":
        payload["agent"] = "creative"
    elif change == "empty":
        payload["prompt_scope"]["node_ids"] = []
    elif change == "duplicate":
        payload["prompt_scope"]["node_ids"] = ["cat", "cat"]
    elif change == "unknown":
        payload["prompt_scope"]["node_ids"] = ["unknown"]
    elif change == "local_tool":
        payload["prompt_scope"]["node_ids"] = ["qc"]
    elif change == "outside_context":
        payload["context_refs"] = []
    else:
        wrong = write_workspace("note", "note", {"text": "not a draft"},
            runtime._context(run, director, suffix="note"))["workspace_ref"]
        payload = request(wrong)
    before = AgentDelegation.query.count()
    from app.agents.budget import remaining
    balance = remaining(director)
    with pytest.raises(AppError):
        invoke(scoped, director, "delegate", payload)
    assert AgentDelegation.query.count() == before and remaining(director) == balance


@pytest.mark.parametrize("fields", [
    {"prompt": "good", "model_id": "wan3.0-video"},
    {"prompt": "good", "params": {"duration": 30}},
    {"prompt": "good", "first_frame_artifact_id": "another"},
    {"prompt": "good", "negative_prompt": "bad"},
    {"prompt": "good", "depends_on": []},
    {"prompt": "   "}, {"prompt": 9}, {"prompt": {"ref": "dog", "output": "image"}},
])
def test_prompt_output_cannot_expand_into_other_input_fields(scoped, fields):
    child = delegate(scoped)
    with pytest.raises(AppError):
        invoke(scoped, child, "finish", update(**fields))
    assert child.status == "pending" and child.output is None


@pytest.mark.parametrize("which", ["outside", "duplicate", "empty_patch", "long_transform"])
def test_updates_are_unique_scoped_and_use_tool_text_limit(scoped, which):
    child = delegate(scoped, ["clip"] if which == "long_transform" else None)
    payload = update()
    if which == "outside":
        payload = update("dog")
    elif which == "duplicate":
        payload["updates"] *= 2
    elif which == "empty_patch":
        payload["updates"][0]["inputs_patch"] = {}
    else:
        payload = update("clip", prompt="x" * 5001)
    with pytest.raises(AppError):
        invoke(scoped, child, "finish", payload)
    assert child.status == "pending"


def test_empty_updates_cannot_complete_prompt_smith(scoped):
    child = delegate(scoped)
    with pytest.raises(AppError) as error:
        invoke(scoped, child, "finish", {"kind": "completed", "updates": []})
    assert error.value.code == "INVALID_INPUT"
    assert child.status == "pending" and child.output is None


def test_whitespace_only_prompt_cannot_complete_prompt_smith(scoped):
    child = delegate(scoped)
    with pytest.raises(AppError) as error:
        invoke(scoped, child, "finish", update(prompt=" \t\n "))
    assert error.value.code == "INVALID_INPUT"
    assert child.status == "pending" and child.output is None


def test_prompt_smith_can_return_when_no_update_is_appropriate(scoped):
    child = delegate(scoped)
    result = invoke(scoped, child, "finish", {"kind": "returned", "reason": "No prompt change is needed"})
    assert result["output"]["status"] == "returned"
    assert result["output"]["output"] == {"kind": "returned", "reason": "No prompt change is needed"}


def test_foreign_run_reference_cannot_authorize_prompt_scope(scoped):
    from tests.test_v3_workspace import make_context, plan
    _other, _author, ctx = make_context()
    foreign = write_workspace("private_draft", "plan_draft", plan(), ctx)["workspace_ref"]
    before = AgentDelegation.query.count()
    with pytest.raises(AppError) as error:
        invoke(scoped, scoped[3], "delegate", request(foreign))
    assert error.value.code == "WORKSPACE_ITEM_NOT_FOUND"
    assert AgentDelegation.query.count() == before


def test_later_draft_version_does_not_expand_original_scope(scoped):
    _app, run, _root, director, _registry, ref = scoped
    child = delegate(scoped)
    payload = deepcopy(AgentWorkspaceItem.query.one().payload)
    payload["nodes"][0]["tool"] = "qc_video"
    second = write_workspace("draft", "plan_draft", payload,
        runtime._context(run, director, suffix="draft2"))["workspace_ref"]
    assert second["version"] == ref["version"] + 1
    assert invoke(scoped, child, "finish", update())["output"]["status"] == "completed"
    assert child.state["prompt_scope"]["plan_ref"] == ref


def test_old_unscoped_smith_returns_before_any_llm_call(scoped):
    _app, run, _root, director, registry, _ref = scoped
    child = AgentDelegation(run_id=run.run_id, parent_id=director.id, agent="prompt_smith", task="legacy",
        expected="PromptUpdates", credits_limit=2, request_key="legacy", depth=2, state={})
    db.session.add(child)
    db.session.commit()
    runtime._round(child.id, 0, registry)
    assert child.status == "returned" and child.output["kind"] == "returned"
    assert child.output["reason"] == "PROMPT_SCOPE_REQUIRED"
    assert ToolInvocation.query.filter_by(tool_name="agent_llm_turn").count() == 0


def test_frozen_hash_drift_cannot_be_used_to_finish(scoped):
    child = delegate(scoped)
    child.state = {**child.state, "prompt_scope": {**child.state["prompt_scope"], "plan_hash": "0" * 64}}
    db.session.commit()
    with pytest.raises(AppError) as error:
        invoke(scoped, child, "finish", update())
    assert error.value.code == "PROMPT_SCOPE_CHANGED"


def test_delegate_commit_gap_recovers_scope_and_rejects_changed_inputs(scoped):
    _app, run, _root, director, registry, ref = scoped
    child = delegate(scoped)
    ctx = runtime._context(run, director, suffix="smith")
    receipt = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).one()
    receipt.status, receipt.output_payload = "pending", None
    db.session.commit()
    runtime._recover_local_receipt("delegate", request(ref), ctx, registry)
    assert receipt.status == "success" and receipt.output_payload["delegation_id"] == child.id
    assert registry.invoke("delegate", request(ref), ctx)["replayed"]
    with pytest.raises(AppError) as error:
        registry.invoke("delegate", request(ref, ["dog"]), ctx)
    assert error.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert AgentDelegation.query.filter_by(parent_id=director.id).count() == 1


def test_ordinary_delegate_serialization_remains_v3_compatible(scoped):
    payload = {"agent": "research", "task": "Find evidence", "context_refs": [],
        "expected": "ResearchDossier", "planning_credits": None}
    assert DelegateInput.model_validate(payload).model_dump(mode="json") == payload
    assert DelegateInput.model_validate({**payload, "prompt_scope": None}).model_dump(mode="json") == payload


def test_ordinary_producer_cannot_spawn_or_advertise_repair(scoped):
    _app, run, root, _director, registry, _ref = scoped
    with pytest.raises(AppError) as error:
        invoke(scoped, root, "delegate", {"agent": "repair", "task": "Pretend a failure", "expected": "PatchDraft"})
    assert error.value.code == "DELEGATION_FORBIDDEN"
    listed = invoke(scoped, root, "list_agents", {})["output"]
    assert "repair" not in {item["name"] for item in listed}
    system = runtime._initial_messages(run, root, registry)[0]["content"]
    collaborators = json.loads(system.split("Available collaborators:\n", 1)[1])
    assert "repair" not in {item["name"] for item in collaborators}


def test_server_repair_delegate_still_uses_original_receipt_and_assignment(app_ctx):
    from tests.test_v5_repair_flow import assigned, failure
    from app.agents import repair_flow
    run, root, _task, registry = failure()
    child = assigned(run, registry)
    assert child.agent == "repair" and child.parent_id == root.id
    flow = repair_flow.active_flow(run)
    assert child.request_key == f"{flow['flow_id']}:delegate:author"
    assert ToolInvocation.query.filter_by(tool_name="delegate", idempotency_key=child.request_key).one().status == "success"


def test_active_flow_rejects_unassigned_keys_and_mismatched_target(app_ctx):
    from tests.test_v5_repair_flow import failure
    from app.agents import repair_flow
    run, root, _task, registry = failure()
    assert repair_flow.advance_repair_flow(run, registry)
    flow = repair_flow.active_flow(run)
    for key, role in (("ordinary", "repair"), (f"{flow['flow_id']}:delegate:author", "director")):
        ctx = runtime._context(run, root)
        ctx.idempotency_key = key
        with pytest.raises(AppError) as error:
            registry.invoke("delegate", {"agent": role, "task": "Unassigned", "expected": "PatchDraft"}, ctx)
        assert error.value.code == "DELEGATION_FORBIDDEN"
    assert AgentDelegation.query.count() == 1
