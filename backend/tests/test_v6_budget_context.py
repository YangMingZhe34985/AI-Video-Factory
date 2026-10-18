"""Read-only quota context is current per step and stable across ledger replay."""

from copy import deepcopy
import json

import pytest

from app.agents import runtime
from app.agents.budget import planning_spent, remaining
from app.agents.cards import get_catalog
from app.extensions import db
from app.models import AgentDelegation, ToolInvocation
from app.tools import build_v3_registry
from app.tools.budget import BudgetGuard
from app.utils.ids import new_id
from tests.test_v3_runtime import call, done, env, returned, script


def quota(messages):
    found = [item for item in messages if item["role"] == "system"
             and (item.get("content") or "").startswith(runtime.QUOTA_CONTEXT_PREFIX)]
    assert len(found) == 1
    return json.loads(found[0]["content"][len(runtime.QUOTA_CONTEXT_PREFIX):])["quota_snapshot"]


def ledger(run, root, step):
    return ToolInvocation.query.filter_by(idempotency_key=f"{run.run_id}:{root.id}:{step}").one()


def test_quota_is_committed_before_llm_and_separate_from_user_data(env, monkeypatch):
    app, run, root = env
    script(env, {"producer": [done()]})
    actual = runtime.agent_chat
    seen = []
    def observe(role, messages, tools, *, ctx, registry):
        with app.app_context():
            stored = db.session.get(AgentDelegation, ctx.delegation_id).state["quota_snapshots"]["0"]
            seen.append(deepcopy(stored))
        assert quota(messages) == stored
        assert "Do not use HappyHorse" in messages[1]["content"]
        return actual(role, messages, tools, ctx=ctx, registry=registry)
    monkeypatch.setattr(runtime, "agent_chat", observe)
    runtime.advance(run)
    assert seen == [{"delegation_limit": 20.0, "delegation_remaining": 20.0,
        "run_planning_limit": 20.0, "run_planning_spent": 0, "run_budget_limit": 100.0, "run_spent": 0}]
    assert quota(ledger(run, root, 0).input_payload["messages"]) == seen[0]
    assert not any((item.get("content") or "").startswith(runtime.QUOTA_CONTEXT_PREFIX) for item in root.state["messages"])


def test_returned_child_releases_quota_in_next_parent_step(env):
    _app, run, root = env
    script(env, {"producer": [[call("delegate", {"agent": "research", "task": "Check a fact",
        "expected": "ResearchDossier", "planning_credits": 8})], done()], "research": [returned()]})
    runtime.advance(run)
    while_reserved = remaining(root)
    child = AgentDelegation.query.filter_by(parent_id=root.id).one()
    assert child.credits_limit == 8 and root.status == "waiting_children"
    runtime.advance(run)
    assert child.status == "returned"
    expected = {"delegation_remaining": remaining(root), "run_planning_spent": planning_spent(run.run_id),
                "run_spent": BudgetGuard.spent(run.run_id)}
    assert expected["delegation_remaining"] > while_reserved
    runtime.advance(run)
    snapshot = quota(ledger(run, root, 1).input_payload["messages"])
    assert all(snapshot[name] == value for name, value in expected.items())
    assert set(root.state["quota_snapshots"]) == {"0", "1"}
    assert quota(ledger(run, child, 0).input_payload["messages"])["delegation_limit"] == 8


def test_new_step_updates_total_spent_without_reclassifying_production_as_planning(env):
    _app, run, root = env
    script(env, {"producer": [[call("write_workspace", {"key": "note", "kind": "note", "payload": {"text": "ready"}})], done()]})
    runtime.advance(run)
    original = deepcopy(root.state["quota_snapshots"]["0"])
    db.session.add(ToolInvocation(tool_name="generate_image", caller_role="production", budget_scope=run.run_id,
        idempotency_key=new_id("stub_spent"), estimated_cost=3, status="success"))
    run.request = {**run.request, "budget_limit": 90}
    db.session.commit()
    before_planning, before_total = planning_spent(run.run_id), BudgetGuard.spent(run.run_id)
    runtime.advance(run)
    updated = root.state["quota_snapshots"]["1"]
    assert updated["run_budget_limit"] == 90
    assert updated["run_planning_spent"] == before_planning and updated["run_spent"] == before_total
    assert before_total - before_planning == 3
    assert root.state["quota_snapshots"]["0"] == original


@pytest.mark.parametrize("point", ["before_ledger", "after_response"])
def test_same_step_crash_keeps_original_quota_and_does_not_call_model_twice(env, monkeypatch, point):
    _app, run, root = env
    llm = script(env, {"producer": [[call("write_workspace", {"key": "note", "kind": "note", "payload": {"text": "saved"}})]]})
    registry, original_record, original_chat = build_v3_registry(), runtime._record, runtime.agent_chat
    def after_response(*args, **kwargs):
        original_record(*args, **kwargs)
        if args[2] == "llm":
            raise RuntimeError("After durable response")
    def before_ledger(*_args, **_kwargs):
        raise RuntimeError("Before provider submission")
    monkeypatch.setattr(runtime, "_record", after_response if point == "after_response" else original_record)
    monkeypatch.setattr(runtime, "agent_chat", before_ledger if point == "before_ledger" else original_chat)
    with pytest.raises(RuntimeError):
        runtime._round(root.id, 0, registry)
    frozen = deepcopy(root.state["quota_snapshots"]["0"])
    original_spent = BudgetGuard.spent(run.run_id)
    original_request = deepcopy(ledger(run, root, 0).input_payload) if point == "after_response" else None
    run.request = {**run.request, "budget_limit": 90}
    db.session.commit()
    monkeypatch.setattr(runtime, "_record", original_record)
    monkeypatch.setattr(runtime, "agent_chat", original_chat)
    runtime._round(root.id, 0, registry)
    assert llm.calls == [("producer", 0)]
    assert root.state["quota_snapshots"]["0"] == frozen and frozen["run_budget_limit"] == 100
    assert quota(ledger(run, root, 0).input_payload["messages"]) == frozen
    if point == "after_response":
        assert ledger(run, root, 0).input_payload == original_request
        assert BudgetGuard.spent(run.run_id) == original_spent


@pytest.mark.parametrize("outcome", ["success", "pending", "schema_changed"])
def test_legacy_step_without_snapshot_preserves_messages_and_schema_safety(env, outcome):
    _app, run, root = env
    llm = script(env, {"producer": [[call("write_workspace", {"key": "legacy", "kind": "note", "payload": {"text": "old"}})]]})
    registry = build_v3_registry()
    messages = runtime._initial_messages(run, root, registry)
    root.state = {"messages": deepcopy(messages)}
    db.session.commit()
    names = ["write_workspace"] if outcome == "schema_changed" else get_catalog().cards["producer"].tools
    runtime.agent_chat("producer", messages, registry.function_schemas(names), ctx=runtime._context(run, root), registry=registry)
    receipt = ledger(run, root, 0)
    original_request = deepcopy(receipt.input_payload)
    if outcome == "pending":
        receipt.status, receipt.output_payload = "pending", None
        db.session.commit()
    spent = BudgetGuard.spent(run.run_id)
    runtime._round(root.id, 0, registry)
    assert llm.calls == [("producer", 0)]
    assert receipt.input_payload == original_request and receipt.input_payload["messages"] == messages
    assert "quota_snapshots" not in root.state
    assert BudgetGuard.spent(run.run_id) == spent
    if outcome == "success":
        assert root.steps == 1 and root.status == "running"
    else:
        assert root.status == "failed"
        assert root.error["code"] == ("IDEMPOTENCY_KEY_CONFLICT" if outcome == "schema_changed" else "RECOVERY_REQUIRED")
