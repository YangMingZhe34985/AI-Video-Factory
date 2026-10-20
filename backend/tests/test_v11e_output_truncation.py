"""Provider finish reasons survive accounting; truncated batches never execute."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.api import AppError
from app.agents import runtime
from app.extensions import db
from app.models import AgentDelegation, AgentWorkspaceItem, ToolInvocation
from app.tools import build_v3_registry
from app.tools.agent_chat import tool_call_correction_messages
from app.tools.budget import BudgetGuard
from app.tools.chat_cost import reserve_chat_cost
from scripts.v3_eval.metrics import summarize_turns
from tests.test_v3_agent_chat import MESSAGES, call, chat_env, install, token_pricing
from tests.test_v3_chat_adapter import completion, function_call, make_adapter, protocol_app, submit_stub
from tests.test_v3_plan_compiler import make_run


@pytest.mark.parametrize("calls", [
    [], [function_call()], [function_call(arguments='{"unfinished":')],
    [function_call(), function_call("broken", arguments='{"unfinished":')],
    [None], [{"bad": True}],
])
def test_provider_length_rejects_entire_batch_with_original_evidence(protocol_app, monkeypatch, calls):
    raw = completion(*calls, content="unfinished long answer")
    raw["choices"][0]["finish_reason"] = "length"
    result, requests = submit_stub(make_adapter(), monkeypatch, raw, expect_json=True)
    assert len(requests) == 1
    assert result["finish_reason"] == "length" and result["tool_calls"] == []
    assert result["usage"] == {"prompt_tokens": 30, "completion_tokens": 12}
    assert all(error["code"] == "AGENT_OUTPUT_TRUNCATED" for error in result["tool_call_errors"])
    assert result["raw_response"] == raw
    if calls and isinstance(calls[-1], dict) and "function" in calls[-1]:
        assert result["tool_call_errors"][-1]["arguments"] == calls[-1]["function"]["arguments"]


@pytest.mark.parametrize("reason", [None, "stop", "tool_calls", "content_filter", "new_provider_value"])
def test_other_finish_reasons_are_preserved_without_inventing_truncation(protocol_app, monkeypatch, reason):
    raw = completion(function_call())
    if reason is not None:
        raw["choices"][0]["finish_reason"] = reason
    result, requests = submit_stub(make_adapter(), monkeypatch, raw)
    assert result["finish_reason"] == reason
    assert len(result["tool_calls"]) == 1 and not result.get("tool_call_errors")
    assert len(requests) == 1


def length_turn():
    return {"finish_reason": "length", "content": "unfinished" * 3000,
            "tool_calls": [{"id": "safe", "name": "lookup", "arguments": {"query": "valid sibling"}}],
            "tool_call_errors": [{"index": 1, "id": "partial", "name": "lookup",
                "code": "INVALID_TOOL_ARGUMENTS", "message": "JSON incomplete", "arguments": "RAW_PARTIAL" * 3000}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}}


def test_length_is_a_successful_billed_turn_replay_is_free_and_valid_sibling_not_offered(chat_env):
    app, run, _registry = chat_env
    token_pricing()
    llm = install(app, {"producer": [length_turn()]})
    first = call(chat_env)
    assert first["tool_calls"] == [] and first["finish_reason"] == "length"
    assert first["tool_call_errors"][0]["code"] == "AGENT_OUTPUT_TRUNCATED"
    assert BudgetGuard.spent(run.run_id) == pytest.approx(.03)
    row = ToolInvocation.query.one()
    assert row.status == "success" and row.output_payload["finish_reason"] == "length"
    assert row.input_payload["max_tokens"] == 8000
    assert "RAW_PARTIAL" in json.dumps(row.output_payload)
    assert call(chat_env) == first
    assert llm.calls == [("producer", 0)] and ToolInvocation.query.count() == 1
    assert BudgetGuard.spent(run.run_id) == pytest.approx(.03)


def test_truncated_empty_stub_is_explicit_and_unknown_usage_keeps_reservation(chat_env):
    app, run, registry = chat_env
    model = token_pricing()
    install(app, {"producer": [{"finish_reason": "length", "usage": None}]})
    turn = call(chat_env)
    assert turn["tool_calls"] == [] and turn["tool_call_errors"][0]["code"] == "AGENT_OUTPUT_TRUNCATED"
    reserved = reserve_chat_cost(model, MESSAGES, registry.function_schemas(["lookup"]), 8000)
    assert BudgetGuard.spent(run.run_id) == pytest.approx(reserved)


def test_correction_is_small_explicit_and_preserves_original_receipt(chat_env):
    app, _run, _registry = chat_env
    install(app, {"producer": [length_turn()]})
    turn = call(chat_env)
    original = deepcopy(turn)
    messages = tool_call_correction_messages(MESSAGES, turn)
    assert turn == original
    correction = json.dumps(messages[-2:])
    assert len(correction) < 1800
    assert "RAW_PARTIAL" not in correction and "unfinished" not in correction
    assert "append_plan_nodes" in correction and "12" in correction and "no tool" in correction.lower()
    assert not any(message.get("tool_calls") for message in messages)


def test_truncation_corrections_remain_bounded_and_each_paid_turn_is_accounted(chat_env):
    app, run, _registry = chat_env
    token_pricing()
    llm = install(app, {"producer": [length_turn(), length_turn(), length_turn()]})
    messages = deepcopy(MESSAGES)
    for step in range(2):
        turn = call(chat_env, step=step, messages=messages)
        messages = tool_call_correction_messages(messages, turn)
    with pytest.raises(AppError) as exc:
        call(chat_env, step=2, messages=messages)
    assert exc.value.code == "AGENT_ARGUMENT_CORRECTION_LIMIT"
    assert len(llm.calls) == 3 and ToolInvocation.query.count() == 3
    assert BudgetGuard.spent(run.run_id) == pytest.approx(.09)
    assert all(row.status == "success" and row.output_payload["finish_reason"] == "length"
               for row in ToolInvocation.query.all())
    with pytest.raises(AppError):
        call(chat_env, step=2, messages=messages)
    assert len(llm.calls) == 3


def test_finish_reason_metrics_do_not_infer_length_from_token_count():
    rows = []
    for index, reason in enumerate(["length", "stop", None]):
        rows.append(SimpleNamespace(tool_name="agent_llm_turn", invocation_id=str(index),
            caller_agent="producer", delegation_id=1, status="success", estimated_cost=.1,
            error_code=None, output_payload={"finish_reason": reason,
                "usage": {"prompt_tokens": 100, "completion_tokens": 8000}}))
    result = summarize_turns(rows)
    assert [item["finish_reason"] for item in result["turns"]] == ["length", "stop", None]
    assert result["llm"]["input_tokens_sum"] == 300 and result["llm"]["output_tokens_sum"] == 24000


def test_runtime_never_executes_valid_sibling_from_a_truncated_turn(app_ctx):
    run = make_run()
    root = AgentDelegation.query.filter_by(run_id=run.run_id, agent="producer").one()
    root.state = {"messages": [{"role": "user", "content": "Continue the stored draft."}]}
    db.session.commit()
    response = {"finish_reason": "length", "tool_calls": [{"id": "valid", "name": "write_workspace",
        "arguments": {"key": "must_not_exist", "kind": "note", "payload": {"text": "valid sibling"}}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 7}}
    llm = install(app_ctx, {"producer": [response]})
    before = AgentWorkspaceItem.query.count()
    runtime._round(root.id, 0, build_v3_registry())
    db.session.refresh(root)
    assert root.steps == 1 and root.llm_calls == 1
    assert AgentWorkspaceItem.query.count() == before
    assert AgentWorkspaceItem.query.filter_by(key="must_not_exist").count() == 0
    assert ToolInvocation.query.filter_by(tool_name="write_workspace").count() == 0
    assert ToolInvocation.query.filter_by(tool_name="agent_llm_turn").count() == 1
    assert llm.calls == [("producer", 0)]
