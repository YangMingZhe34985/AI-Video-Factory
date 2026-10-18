"""V3 planning turns: deterministic scripts, replay, isolation and settlement."""

import importlib
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ToolInvocation
from app.services.model_service import ModelService
from app.tools.agent_chat import (
    AGENT_ROLES, agent_chat, resolve_agent_model, tool_call_correction_messages,
)
from app.tools.budget import BudgetGuard
from app.tools.chat_cost import reserve_chat_cost, settle_chat_cost, usage_token_count
from app.tools.registry import ToolRegistry
from app.tools.scripted_llm import ScriptedLLM, get_scripted_llm
from app.tools.spec import ToolContext, ToolSpec

MESSAGES = [{"role": "user", "content": "Create a short idea."}]


class LookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str


class LookupOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: str


@pytest.fixture
def chat_env(app_ctx):
    run = AgentRun(run_id="agent_v3_chat", owner_id="local", request_key="v3-chat",
                   request={"schema_version": 3, "text": "A test", "budget_limit": 100})
    db.session.add(run)
    db.session.commit()
    registry = ToolRegistry()
    registry.register(ToolSpec(name="lookup", description="Read a fact", input_model=LookupInput,
        output_model=LookupOutput, handler=lambda data, ctx: {"result": data.query},
        permission="read", allowed_roles=AGENT_ROLES, agent_visible=True))
    return app_ctx, run, registry


def context(run, *, step=0, delegation=1, **overrides):
    values = {"role": "producer", "caller_agent": "producer", "delegation_id": delegation,
              "agent_step": step, "budget_scope": run.run_id, "budget_limit": 100}
    return ToolContext(**{**values, **overrides})


def install(app, scripts):
    llm = ScriptedLLM(scripts)
    app.extensions["agent_v3_scripted_llm"] = llm
    return llm


def call(env, *, step=0, messages=None, tools=None, **kwargs):
    _app, run, registry = env
    return agent_chat("producer", messages or MESSAGES,
        registry.function_schemas(["lookup"]) if tools is None else tools,
        ctx=context(run, step=step), registry=registry, **kwargs)


def token_pricing(rate=1):
    model = ModelService.get_model("deepseek-v4.1-flash")
    model.capabilities = {**model.capabilities, "pricing": {"unit": "call", "credits_per_unit": 1,
                                                              "credits_per_1k_tokens": rate}}
    db.session.commit()
    return model


def test_scripted_llm_fixed_keys_sequences_and_defensive_copies():
    llm = ScriptedLLM({("producer", 7): "done", "research": [[{"id": "call_1", "name": "lookup", "arguments": {"query": "x"}}]]})
    assert llm.complete("producer", 7)["content"] == "done"
    first = llm.complete("research", 0)
    first["tool_calls"][0]["arguments"]["query"] = "mutated"
    assert llm.complete("research", 0)["tool_calls"][0]["arguments"]["query"] == "x"
    assert llm.calls == [("producer", 7), ("research", 0), ("research", 0)]


@pytest.mark.parametrize("scripts", [{"producer": []}, {("producer", 0): "done"}])
def test_explicit_script_exhaustion_never_falls_back(scripts):
    llm = ScriptedLLM(scripts)
    with pytest.raises(AppError, match="No scripted response") as exc:
        llm.complete("producer", 1, default_response="a misleading fallback")
    assert exc.value.code == "SCRIPT_EXHAUSTED"


def test_default_script_is_marked_and_finish_is_minimal():
    llm = ScriptedLLM()
    turn = llm.complete("producer", 0)
    assert "Mock 示例" in turn["content"]
    assert turn["tool_calls"][0]["name"] == "finish"
    assert turn["tool_calls"][0]["arguments"]["outcome"] == "answer"
    assert "Mock 示例" in llm.complete("producer", 0, tools=[])["content"]
    assert llm.complete("vision", 0, default_response={"content": '{"images": []}'})["content"] == '{"images": []}'


def test_explicit_empty_response_is_not_success():
    with pytest.raises(AppError) as exc:
        ScriptedLLM({("producer", 0): {}}).complete("producer", 0)
    assert exc.value.code == "INVALID_LLM_SCRIPT"


def test_v3_model_defaults_and_fallback_do_not_modify_v2(app_ctx):
    from app.agent.planning import resolve_agent_model as v2_model
    app_ctx.config.update(AGENT_PLANNER_MODEL="", AGENT_PRODUCER_MODEL="", AGENT_VISION_MODEL="",
        AGENT_V3_DEFAULT_TEXT_MODEL="deepseek-v4.1-flash", AGENT_V3_DEFAULT_VISION_MODEL="qwen3.7-plus")
    assert resolve_agent_model("producer").model_id == "deepseek-v4.1-flash"
    assert resolve_agent_model("vision").model_id == "qwen3.7-plus"
    assert v2_model("director").model_id == app_ctx.config["DEFAULT_PROMPT_REWRITE_MODEL"]
    app_ctx.config["AGENT_PLANNER_MODEL"] = "qwen3.5-plus"
    assert resolve_agent_model("producer").model_id == "qwen3.5-plus"
    app_ctx.config["AGENT_PRODUCER_MODEL"] = "qwen3.7-max"
    assert resolve_agent_model("producer").model_id == "qwen3.7-max"
    app_ctx.config.update(AGENT_PRODUCER_MODEL="", AGENT_PLANNER_MODEL="", AGENT_V3_DEFAULT_TEXT_MODEL="")
    assert resolve_agent_model("producer").model_id == app_ctx.config["DEFAULT_PROMPT_REWRITE_MODEL"]
    with pytest.raises(AppError) as exc:
        resolve_agent_model("production")
    assert exc.value.code == "INVALID_AGENT_ROLE"


def test_multiple_calls_are_returned_without_executing_them(chat_env):
    app, run, _registry = chat_env
    script = {"tool_calls": [{"id": "a", "name": "lookup", "arguments": {"query": "one"}},
                             {"id": "b", "name": "lookup", "arguments": {"query": "two"}}],
              "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
    llm = install(app, {("producer", 0): script})
    result = call(chat_env)
    assert [item["id"] for item in result["tool_calls"]] == ["a", "b"]
    assert llm.calls == [("producer", 0)]
    invocation = ToolInvocation.query.one()
    assert invocation.tool_name == "agent_llm_turn"
    assert invocation.idempotency_key == f"{run.run_id}:1:0"
    assert invocation.caller_agent == "producer" and invocation.delegation_id == 1


def test_success_replay_does_not_call_or_charge_again_after_config_change(chat_env):
    app, run, _registry = chat_env
    token_pricing()
    llm = install(app, {("producer", 0): {"content": "done", "usage": {"prompt_tokens": 20, "completion_tokens": 30}}})
    first = call(chat_env)
    assert BudgetGuard.spent(run.run_id) == pytest.approx(0.05)
    app.config["AGENT_PRODUCER_MODEL"] = "removed-model"
    model = ModelService.get_model("deepseek-v4.1-flash")
    model.enabled = False
    db.session.commit()
    assert call(chat_env) == first
    assert BudgetGuard.spent(run.run_id) == pytest.approx(0.05)
    assert llm.calls == [("producer", 0)]
    assert ToolInvocation.query.count() == 1


@pytest.mark.parametrize("status", ["pending", "running", "failed"])
def test_unknown_or_failed_turn_never_resends(chat_env, status):
    app, run, _registry = chat_env
    llm = install(app, {("producer", 0): "done"})
    call(chat_env)
    row = ToolInvocation.query.one()
    row.status = status
    row.output_payload = {}
    db.session.commit()
    cost = BudgetGuard.spent(run.run_id)
    with pytest.raises(AppError) as exc:
        call(chat_env)
    assert exc.value.code in {"RECOVERY_REQUIRED", "UNSAFE_RETRY", "RETRY_LIMIT_EXCEEDED"}
    assert llm.calls == [("producer", 0)] and BudgetGuard.spent(run.run_id) == cost


def test_changed_input_or_server_identity_conflicts(chat_env):
    app, run, registry = chat_env
    install(app, {("producer", 0): "done"})
    call(chat_env)
    with pytest.raises(AppError) as exc:
        call(chat_env, messages=[{"role": "user", "content": "different input"}])
    assert exc.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    ctx = context(run, idempotency_key="another-key")
    with pytest.raises(AppError) as exc:
        agent_chat("producer", MESSAGES, [], ctx=ctx, registry=registry)
    assert exc.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    ctx = context(run, caller_agent="director")
    with pytest.raises(AppError) as exc:
        agent_chat("producer", MESSAGES, [], ctx=ctx, registry=registry)
    assert exc.value.code == "INVALID_AGENT_CONTEXT"


def test_budget_is_reserved_before_mock_or_transport_call(chat_env):
    app, run, _registry = chat_env
    token_pricing(100)
    llm = install(app, {("producer", 0): "must not run"})
    with pytest.raises(AppError) as exc:
        call(chat_env)
    assert exc.value.code == "BUDGET_EXCEEDED"
    assert llm.calls == []
    assert BudgetGuard.spent(run.run_id) == 0


def test_actual_usage_above_reservation_records_cost_and_stops(chat_env):
    app, run, _registry = chat_env
    token_pricing()
    llm = install(app, {("producer", 0): {"content": "done", "usage": {"prompt_tokens": 90000, "completion_tokens": 90000}}})
    with pytest.raises(AppError) as exc:
        call(chat_env, max_tokens=10)
    assert exc.value.code == "BUDGET_SETTLEMENT_EXCEEDED"
    assert BudgetGuard.spent(run.run_id) == 180
    assert ToolInvocation.query.one().status == "failed"
    with pytest.raises(AppError):
        call(chat_env, max_tokens=10)
    assert llm.calls == [("producer", 0)]


def test_missing_usage_keeps_reservation_and_missing_rate_falls_back_to_call(chat_env):
    app, run, registry = chat_env
    install(app, {("producer", 0): {"content": "done", "usage": None}})
    model = token_pricing()
    tools = registry.function_schemas(["lookup"])
    reserved = reserve_chat_cost(model, MESSAGES, tools, 8000)
    call(chat_env)
    assert BudgetGuard.spent(run.run_id) == pytest.approx(reserved)
    model.capabilities = {**model.capabilities, "pricing": {"unit": "call", "credits_per_unit": 2}}
    db.session.commit()
    install(app, {("producer", 1): {"content": "next", "usage": {"prompt_tokens": 800, "completion_tokens": 900}}})
    call(chat_env, step=1)
    assert BudgetGuard.spent(run.run_id) == pytest.approx(reserved + 2)


def test_script_exhaustion_is_failed_and_keeps_reserved_budget(chat_env):
    app, run, _registry = chat_env
    llm = install(app, {"producer": []})
    with pytest.raises(AppError) as exc:
        call(chat_env)
    assert exc.value.code == "SCRIPT_EXHAUSTED"
    row = ToolInvocation.query.one()
    assert row.status == "failed" and row.estimated_cost > 0
    with pytest.raises(AppError):
        call(chat_env)
    assert llm.calls == [("producer", 0)]


def invalid_turn():
    return {"content": None, "tool_calls": [{"id": "safe", "name": "lookup", "arguments": {"query": "safe"}}],
            "tool_call_errors": [{"index": 1, "id": "bad", "name": "lookup", "code": "INVALID_TOOL_ARGUMENTS",
                                  "message": "Arguments are not valid JSON", "arguments": "{"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10}}


def test_invalid_sibling_clears_all_calls_and_each_correction_is_a_new_turn(chat_env):
    app, run, _registry = chat_env
    llm = install(app, {"producer": [invalid_turn(), invalid_turn(), invalid_turn()]})
    messages = deepcopy(MESSAGES)
    for step in range(2):
        turn = call(chat_env, step=step, messages=messages)
        assert turn["tool_calls"] == [] and turn["tool_call_errors"]
        messages = tool_call_correction_messages(messages, turn)
        assert all(not message.get("tool_calls") for message in messages)
    with pytest.raises(AppError) as exc:
        call(chat_env, step=2, messages=messages)
    assert exc.value.code == "AGENT_ARGUMENT_CORRECTION_LIMIT"
    assert ToolInvocation.query.count() == 3
    assert all(row.status == "success" for row in ToolInvocation.query.all())
    assert len(llm.calls) == 3
    with pytest.raises(AppError):
        call(chat_env, step=2, messages=messages)
    assert len(llm.calls) == 3
    with pytest.raises(AppError) as exc:
        tool_call_correction_messages(messages, invalid_turn())
    assert exc.value.code == "AGENT_ARGUMENT_CORRECTION_LIMIT"


@pytest.mark.parametrize("calls,limit,code", [
    ([{"id": "x", "name": "generate_video", "arguments": {}}], 8, "TOOL_NOT_ALLOWED"),
    ([{"id": "x", "name": "lookup", "arguments": {"query": "a"}},
      {"id": "x", "name": "lookup", "arguments": {"query": "b"}}], 8, "INVALID_TOOL_CALL"),
    ([{"id": "x", "name": "lookup", "arguments": {"query": "a"}},
      {"id": "y", "name": "lookup", "arguments": {"query": "b"}}], 1, "TOOL_CALL_LIMIT"),
])
def test_unsafe_or_excess_calls_are_structured_errors(chat_env, calls, limit, code):
    app, _run, _registry = chat_env
    install(app, {("producer", 0): {"tool_calls": calls}})
    turn = call(chat_env, max_tool_calls=limit)
    assert turn["tool_calls"] == []
    assert turn["tool_call_errors"][0]["code"] == code


def test_tool_schema_tampering_is_rejected_before_call(chat_env):
    app, _run, registry = chat_env
    llm = install(app, {("producer", 0): "must not run"})
    schemas = registry.function_schemas(["lookup"])
    schemas[0]["function"]["parameters"] = {"type": "object", "additionalProperties": True}
    with pytest.raises(AppError) as exc:
        call(chat_env, tools=schemas)
    assert exc.value.code == "INVALID_INPUT"
    assert llm.calls == [] and ToolInvocation.query.count() == 0


def test_generation_tool_cannot_enter_agent_prompt(chat_env):
    app, _run, registry = chat_env
    llm = install(app, {("producer", 0): "must not run"})
    registry.register(ToolSpec(name="generate_video", description="Generate", input_model=LookupInput,
        output_model=LookupOutput, handler=lambda *_: {"result": "never"}, permission="generate",
        allowed_roles=AGENT_ROLES))
    schema = {"type": "function", "function": {"name": "generate_video", "description": "Generate",
                                                 "parameters": LookupInput.model_json_schema()}}
    with pytest.raises(AppError) as exc:
        call(chat_env, tools=[schema])
    assert exc.value.code == "TOOL_FORBIDDEN"
    assert llm.calls == [] and ToolInvocation.query.count() == 0


def test_raw_internal_request_cannot_supply_a_cheaper_rate(chat_env):
    app, run, registry = chat_env
    token_pricing()
    llm = install(app, {("producer", 0): "done", ("producer", 1): "must not run"})
    call(chat_env)
    raw = deepcopy(ToolInvocation.query.one().input_payload)
    raw["credits_per_1k_tokens"] = 0
    with pytest.raises(AppError) as exc:
        registry.invoke("agent_llm_turn", raw, context(run, step=1))
    assert exc.value.code == "INVALID_AGENT_CONTEXT"
    assert ToolInvocation.query.count() == 1 and llm.calls == [("producer", 0)]


def test_default_registry_is_not_modified_by_private_llm_turn(chat_env):
    from app.tools import get_registry
    _app, run, _registry = chat_env
    before = get_registry().names()
    result = agent_chat("producer", MESSAGES, [], ctx=context(run))
    assert "Mock 示例" in result["content"]
    assert get_registry().names() == before
    assert "agent_llm_turn" not in before


def test_real_transport_stub_receives_one_frozen_turn(chat_env, monkeypatch):
    app, _run, _registry = chat_env
    app.config["MODEL_ADAPTER_MODE"] = "real"
    requests = []

    class Adapter:
        use_mock = False
        def build_payload(self, inputs, params):
            return {**inputs, **params}
        def submit(self, payload):
            requests.append(payload)
            return {"content": "stub result", "tool_calls": [], "usage": {"prompt_tokens": 5, "completion_tokens": 5}}

    module = importlib.import_module("app.tools.agent_chat")
    monkeypatch.setattr(module, "get_adapter", lambda *args, **kwargs: Adapter())
    turn = call(chat_env, max_tokens=100)
    assert turn["content"] == "stub result"
    assert len(requests) == 1 and requests[0]["tool_choice"] == "auto"
    assert requests[0]["max_tokens"] == 100
    assert requests[0]["messages"] == MESSAGES
    call(chat_env, max_tokens=100)
    assert len(requests) == 1


def test_provider_client_error_keeps_reservation_and_does_not_retry(chat_env, monkeypatch):
    app, run, _registry = chat_env
    app.config["MODEL_ADAPTER_MODE"] = "real"
    requests = []

    class Adapter:
        use_mock = False
        def build_payload(self, inputs, params):
            return {**inputs, **params}
        def submit(self, payload):
            requests.append(payload)
            raise AppError("API_TASK_FAILED", "Provider rejected request", 429)

    module = importlib.import_module("app.tools.agent_chat")
    monkeypatch.setattr(module, "get_adapter", lambda *args, **kwargs: Adapter())
    with pytest.raises(AppError) as exc:
        call(chat_env)
    assert exc.value.code == "API_TASK_FAILED"
    assert ToolInvocation.query.one().status == "failed"
    cost = BudgetGuard.spent(run.run_id)
    assert cost > 0
    with pytest.raises(AppError):
        call(chat_env)
    assert len(requests) == 1 and BudgetGuard.spent(run.run_id) == cost


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": None, "completion_tokens": 1}])
def test_missing_usage_is_not_zero(usage):
    model = SimpleNamespace(capabilities={"pricing": {"credits_per_1k_tokens": 1}})
    assert usage_token_count(usage) is None
    assert settle_chat_cost(model, usage) is None


@pytest.mark.parametrize("value", [-1, True, 2.1, "2", float("nan")])
def test_invalid_usage_does_not_become_free(value):
    with pytest.raises(AppError) as exc:
        usage_token_count({"prompt_tokens": value, "completion_tokens": 0})
    assert exc.value.code == "INVALID_LLM_USAGE"


def test_default_mock_uses_per_app_scripted_instance(chat_env):
    app, _run, _registry = chat_env
    turn = call(chat_env, tools=[])
    assert "Mock 示例" in turn["content"]
    assert get_scripted_llm().calls == [("producer", 0)]
    assert app.extensions["agent_v3_scripted_llm"] is get_scripted_llm()
