"""Offline regressions for D-038 timing across all paid-turn exit paths."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.agents import runtime
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentStep, ToolInvocation
from app.tools import build_v3_registry
from app.tools.budget import BudgetGuard
from tests.test_v3_runtime import call, done, env, question, script


class Clock:
    def __init__(self):
        self.value = 100.0

    def monotonic(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest.fixture
def timer(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=clock.monotonic))
    return clock


def timed_script(env, monkeypatch, timer, responses, seconds=12.0, error=None):
    llm = script(env, {"producer": responses})
    original = llm.complete
    def complete(*args, **kwargs):
        timer.advance(seconds)
        if error:
            llm.calls.append((args[0], args[1]))
            raise error
        return original(*args, **kwargs)
    monkeypatch.setattr(llm, "complete", complete)
    return llm


def active(root):
    db.session.refresh(root)
    return float((root.state or {}).get("active_seconds", 0.0))


@pytest.mark.parametrize("code", ["INVALID_LLM_RESPONSE", "MODEL_REQUEST_FAILED", "BUDGET_SETTLEMENT_EXCEEDED"])
def test_paid_llm_failure_counts_elapsed_and_preserves_receipt(env, monkeypatch, timer, code):
    _app, run, root = env
    llm = timed_script(env, monkeypatch, timer, [done()], error=AppError(code, "Injected paid response failure", 502))
    runtime._round(root.id, 0, build_v3_registry())
    assert active(root) == 12.0
    assert root.status == ("limit" if "BUDGET" in code else "failed")
    assert root.llm_calls == 1 and root.steps == 0
    receipt = ToolInvocation.query.filter_by(tool_name="agent_llm_turn").one()
    assert receipt.status == "failed"
    assert llm.calls == [("producer", 0)]
    assert AgentStep.query.filter_by(kind="llm").count() == 1
    before = active(root)
    timer.advance(3600)
    runtime._round(root.id, 0, build_v3_registry())
    assert active(root) == before


def test_argument_correction_return_counts_time_and_enforces_next_admission(env, monkeypatch, timer):
    app, run, root = env
    app.config["AGENT_V3_DELEGATION_ACTIVE_SEC"] = 10
    llm = timed_script(env, monkeypatch, timer, [[call("not_a_tool", {})], done()])
    registry = build_v3_registry()
    runtime._round(root.id, 0, registry)
    assert active(root) == 12.0 and root.steps == 1
    assert "Agent tool argument correction" in str(root.state["messages"])
    timer.advance(1800)
    runtime._round(root.id, 1, registry)
    assert root.status == "limit" and root.error["code"] == "AGENT_EXECUTION_LIMIT"
    assert active(root) == 12.0 and llm.calls == [("producer", 0)]


def test_three_bad_argument_turns_all_count_before_correction_limit(env, monkeypatch, timer):
    _app, _run, root = env
    llm = timed_script(env, monkeypatch, timer, [[call("not_a_tool", {})]] * 3)
    registry = build_v3_registry()
    for step in range(3):
        runtime._round(root.id, step, registry)
    assert active(root) == 36.0
    assert root.status == "failed" and root.error["code"] == "AGENT_ARGUMENT_CORRECTION_LIMIT"
    assert root.steps == 2 and root.llm_calls == 3 and len(llm.calls) == 3


def test_correction_message_builder_error_counts_paid_time(env, monkeypatch, timer):
    _app, _run, root = env
    timed_script(env, monkeypatch, timer, [[call("not_a_tool", {})]])
    def rejected(*args, **kwargs):
        raise AppError("INJECTED_CORRECTION_FAILURE", "Cannot construct correction", 422)
    monkeypatch.setattr(runtime, "tool_call_correction_messages", rejected)
    runtime._round(root.id, 0, build_v3_registry())
    assert active(root) == 12.0 and root.error["code"] == "INJECTED_CORRECTION_FAILURE"


@pytest.mark.parametrize("code", ["AGENT_BUDGET_EXCEEDED", "BUDGET_SETTLEMENT_EXCEEDED", "RECOVERY_REQUIRED"])
def test_tool_early_stop_preserves_latest_state_and_counts_time(env, monkeypatch, timer, code):
    _app, _run, root = env
    timed_script(env, monkeypatch, timer, [[call("list_agents", {})]])
    registry = build_v3_registry()
    original = registry.invoke
    def invoke(name, data, ctx):
        if name == "list_agents":
            timer.advance(5)
            root.state = {**deepcopy(root.state), "committed_tool_marker": {"receipt": "keep"}}
            db.session.commit()
            raise AppError(code, "Injected terminal tool error", 409)
        return original(name, data, ctx)
    monkeypatch.setattr(registry, "invoke", invoke)
    runtime._round(root.id, 0, registry)
    assert active(root) == 17.0
    assert root.state["committed_tool_marker"] == {"receipt": "keep"}
    assert root.state["pending_turn"]["cursor"] == 0
    assert root.error["code"] == code and root.steps == 0 and root.llm_calls == 1


@pytest.mark.parametrize("terminal", ["finish", "ask_user"])
def test_success_counts_once_and_keeps_coordination_state(env, monkeypatch, timer, terminal):
    _app, _run, root = env
    response = done() if terminal == "finish" else [call("ask_user", {"questions": [question()]})]
    timed_script(env, monkeypatch, timer, [response])
    root.state = {"active_seconds": 3.5, "existing_marker": True}
    db.session.commit()
    runtime._round(root.id, 0, build_v3_registry())
    assert active(root) == 15.5 and root.state["existing_marker"] is True
    assert root.steps == root.llm_calls == 1
    if terminal == "ask_user":
        assert root.state["pending_card"] and root.state["ask_receipts"]
        assert root.state["ask_key"]
    timer.advance(1800)
    runtime._round(root.id, 0, build_v3_registry())
    assert active(root) == 15.5


def test_unexpected_tool_exception_counts_and_does_not_commit_partial_state(env, monkeypatch, timer):
    _app, _run, root = env
    timed_script(env, monkeypatch, timer, [[call("list_agents", {})]])
    registry = build_v3_registry()
    original = registry.invoke
    def invoke(name, data, ctx):
        if name == "list_agents":
            timer.advance(5)
            root.state = {**deepcopy(root.state), "committed_marker": True}
            db.session.commit()
            root.state = {**deepcopy(root.state), "unfinished_mutation": True}
            raise RuntimeError("Injected unexpected tool crash")
        return original(name, data, ctx)
    monkeypatch.setattr(registry, "invoke", invoke)
    with pytest.raises(RuntimeError, match="Injected unexpected tool crash"):
        runtime._round(root.id, 0, registry)
    assert active(root) == 17.0 and root.state["committed_marker"] is True
    assert "unfinished_mutation" not in root.state


@pytest.mark.parametrize("gap", ["llm_receipt", "tool_receipt"])
def test_receipt_replay_adds_only_new_work_not_wait_or_original_call(env, monkeypatch, timer, gap):
    _app, run, root = env
    llm = timed_script(env, monkeypatch, timer, [[call("write_workspace", {"key": "n", "kind": "note", "payload": {"text": "ok"}})]])
    original = runtime._record
    def record(*args, **kwargs):
        original(*args, **kwargs)
        if args[2] == ("llm" if gap == "llm_receipt" else "tool"):
            raise RuntimeError("Injected gap after committed receipt")
    monkeypatch.setattr(runtime, "_record", record)
    registry = build_v3_registry()
    with pytest.raises(RuntimeError, match="Injected gap"):
        runtime._round(root.id, 0, registry)
    assert active(root) == 12.0
    spent = BudgetGuard.spent(run.run_id)
    frozen = deepcopy(root.state["pending_context"])
    timer.advance(7200)
    monkeypatch.setattr(runtime, "_record", original)
    original_invoke = registry.invoke
    def slow_local(name, data, ctx):
        if name == "write_workspace":
            timer.advance(2)
        return original_invoke(name, data, ctx)
    monkeypatch.setattr(registry, "invoke", slow_local)
    runtime._round(root.id, 0, registry)
    assert active(root) == (14.0 if gap == "llm_receipt" else 12.0)
    assert llm.calls == [("producer", 0)] and root.llm_calls == root.steps == 1
    assert BudgetGuard.spent(run.run_id) == spent
    assert root.state["pending_context"] == frozen


@pytest.mark.parametrize("limit", ["max_steps", "max_llm_calls"])
def test_existing_card_limits_still_stop_without_new_llm(env, monkeypatch, timer, limit):
    from app.agents.cards import get_catalog
    _app, _run, root = env
    monkeypatch.setattr(get_catalog().cards["producer"].limits, limit, 0)
    llm = timed_script(env, monkeypatch, timer, [done()])
    runtime._round(root.id, 0, build_v3_registry())
    assert root.status == "limit" and not llm.calls and active(root) == 0.0

