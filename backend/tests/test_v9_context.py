"""Offline request projection, exact replay and failure-injection regressions."""

from copy import deepcopy
import json

import pytest

from app.agents import context, runtime
from app.agents.cards import get_catalog
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, ToolInvocation
from app.tools import build_v3_registry
from app.tools.budget import BudgetGuard
from tests.test_v3_runtime import call, done, env, script


def batch(name, arguments, output, identity):
    return [
        {"role": "assistant", "content": None, "tool_calls": [{"id": identity, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]},
        {"role": "tool", "tool_call_id": identity, "name": name, "content": json.dumps(output, ensure_ascii=False)},
    ]


def tail():
    return batch("list_skills", {}, [], "recent-a") + batch("list_models", {}, {}, "recent-b")


def long_history():
    messages = [{"role": "system", "content": "Follow original permissions; never generate without approval."},
                {"role": "user", "content": '{"text":"猫的故事，禁止 HappyHorse，120 秒","budget_limit":100}'}]
    for index in range(8):
        messages += batch("read_skill_resource",
            {"name": "plan-review", "path": f"resources/reference-{index}.json"},
            {"name": "plan-review", "path": f"resources/reference-{index}.json", "content": "中文资料" * 5000},
            f"resource-{index}")
    return messages


def item(key="draft", version=1, text="画面" * 5000):
    return {"key": key, "version": version, "workspace_ref": {"key": key, "version": version},
            "kind": "note", "author_agent": "producer", "delegation_id": 1,
            "artifact_ids": ["reference_a"], "created_at": "2026-10-19T00:00:00+00:00",
            "payload": {"text": text}}


def test_projection_is_deterministic_reduces_old_manuals_and_never_mutates_source():
    original = long_history()
    snapshot = deepcopy(original)
    first, stats = context.project_messages(original)
    second, again = context.project_messages(original)
    assert original == snapshot and first == second and stats == again
    assert stats["after_chars"] < stats["before_chars"] * 0.35
    assert stats["after_chars"] <= context.SOFT_CHAR_TARGET
    assert stats["compacted_result_count"] == 6 and not stats["over_soft_target"]
    assert len(first) == len(original)
    assert first[:2] == original[:2] and first[-4:] == original[-4:]
    for index in range(len(first)):
        assert {k: v for k, v in first[index].items() if k != "content"} == {
            k: v for k, v in original[index].items() if k != "content"}
        if original[index]["role"] != "tool":
            assert first[index] == original[index]
    marker = json.loads(first[3]["content"])["context_projection"]
    assert marker["omitted"] and len(marker["sha256_result_content"]) == 64
    assert marker["reread"] == [{"tool": "read_skill_resource",
        "arguments": {"name": "plan-review", "path": "resources/reference-0.json"}}]


def test_small_history_is_unchanged():
    messages = [{"role": "system", "content": "rules"}] + tail()
    projected, stats = context.project_messages(messages)
    assert projected == messages and projected is not messages
    assert stats["compacted_result_count"] == 0


@pytest.mark.parametrize("name,output", [
    ("analyze_images", {"images": [{"analysis": "视觉证据" * 20000}]}),
    ("fetch_page", {"url": "https://example.test", "text": "外部证据" * 20000}),
    ("check_plan", {"valid": False, "issues": ["必须修复" * 20000]}),
    ("ask_user", {"answers": {"look": "用户已确定" * 20000}}),
    ("delegate", {"output": {"story": "创作结果" * 20000}}),
    ("read_skill_resource", {"error": {"code": "NOT_FOUND", "message": "错误" * 40000}}),
])
def test_nonrereadable_results_and_errors_are_preserved_even_above_soft_target(name, output):
    messages = batch(name, {"name": "plan-review", "path": "x"}, output, "old") + tail()
    projected, stats = context.project_messages(messages)
    assert projected == messages
    assert stats["over_soft_target"] and stats["compacted_result_count"] == 0


def test_latest_skill_body_is_retained_and_only_older_duplicate_is_compacted():
    output = {"name": "plan-review", "version": 3, "resources": ["x"], "body": "规则" * 20000}
    messages = batch("load_skill", {"name": "plan-review"}, output, "old")
    messages += batch("load_skill", {"name": "plan-review"}, output, "latest") + tail()
    projected, _stats = context.project_messages(messages)
    assert "body" not in json.loads(projected[1]["content"])
    assert projected[3] == messages[3]
    assert json.loads(projected[1]["content"])["context_projection"]["reread"] == [
        {"tool": "load_skill", "arguments": {"name": "plan-review"}}]


@pytest.mark.parametrize("name", ["read_workspace", "write_workspace"])
def test_old_workspace_payload_keeps_exact_versions_and_artifact_metadata(name, monkeypatch):
    monkeypatch.setattr(context, "SOFT_CHAR_TARGET", 5_000)
    row = item()
    output = row if name == "write_workspace" else {"items": [row, item("other", 3)]}
    args = {"key": row["key"], "kind": "note", "payload": row["payload"]} if name == "write_workspace" else {}
    messages = batch(name, args, output, "workspace") + tail()
    projected, stats = context.project_messages(messages)
    result = json.loads(projected[1]["content"])
    rows = [result] if name == "write_workspace" else result["items"]
    assert all("payload" not in entry and entry["artifact_ids"] == ["reference_a"] for entry in rows)
    assert result["context_projection"]["reread"][0] == {
        "tool": "read_workspace", "arguments": {"key": "draft", "version": 1}}
    if name == "read_workspace":
        assert result["context_projection"]["reread"][1]["arguments"] == {"key": "other", "version": 3}
    assert stats["compacted_result_count"] == 1
    # Assistant arguments remain verbatim, even if that prevents the soft target.
    assert projected[0] == messages[0]


@pytest.mark.parametrize("defect", ["path", "incomplete", "duplicate_reply", "unparseable", "invalid_identity"])
def test_mismatched_or_incomplete_history_is_not_summarized(defect):
    messages = batch("read_skill_resource", {"name": "plan-review", "path": "original"},
        {"name": "plan-review", "path": "original", "content": "资料" * 40000}, "a")
    if defect == "path":
        messages[1]["content"] = json.dumps({"name": "plan-review", "path": "different", "content": "x" * 80000})
    elif defect == "incomplete":
        messages[0]["tool_calls"].append({"id": "missing", "function": {"name": "list_skills", "arguments": "{}"}})
    elif defect == "duplicate_reply":
        messages.append(deepcopy(messages[1]))
    elif defect == "unparseable":
        messages[0]["tool_calls"][0]["function"]["arguments"] = "invalid"
    else:
        messages[1]["tool_call_id"] = {"untrusted": "object"}
    messages += tail()
    projected, _stats = context.project_messages(messages)
    assert projected == messages


def test_user_clarifications_system_corrections_and_untrusted_tool_roles_stay_intact():
    messages = long_history()
    messages.insert(4, {"role": "user", "content": "改为白色，预算仍为原上限"})
    messages += [{"role": "system", "content": "Agent tool argument correction (server): original constraint"},
                 {"role": "user", "content": '{"untrusted_delegation_results":[{"reason":"需要确认"}]}'}]
    projected, _stats = context.project_messages(messages)
    for old, new in zip(messages, projected):
        if old["role"] in {"user", "system"}:
            assert new == old
    assert sum(entry["role"] == "system" for entry in projected) == 2


def test_small_results_are_retained_when_other_protected_data_is_large():
    messages = [{"role": "user", "content": "原始长请求" * 20000}]
    messages += batch("read_skill_resource", {"name": "plan-review", "path": "x"},
        {"name": "plan-review", "path": "x", "content": "short"}, "short") + tail()
    projected, stats = context.project_messages(messages)
    assert projected == messages and stats["over_soft_target"]


def seed_history(env):
    _app, run, root = env
    root.state = {"messages": long_history(), "active_seconds": 17.25}
    db.session.commit()
    return run, root


def receipt(run, root, step=0):
    return ToolInvocation.query.filter_by(idempotency_key=f"{run.run_id}:{root.id}:{step}").one()


def test_projected_request_is_committed_before_model_and_original_history_is_retained(env, monkeypatch):
    app, run, root = env
    seed_history(env)
    original_history = deepcopy(root.state["messages"])
    script(env, {"producer": [done()]})
    actual = runtime.agent_chat
    def inspect(role, messages, tools, *, ctx, registry):
        with app.app_context():
            frozen = deepcopy(db.session.get(AgentDelegation, root.id).state["pending_context"])
        assert frozen["messages"] == messages
        assert frozen["messages_hash"] == context.message_digest(messages)
        assert frozen["metrics"]["compacted_result_count"] > 0
        assert len([entry for entry in messages if (entry.get("content") or "").startswith(runtime.QUOTA_CONTEXT_PREFIX)]) == 1
        return actual(role, messages, tools, ctx=ctx, registry=registry)
    monkeypatch.setattr(runtime, "agent_chat", inspect)
    runtime._round(root.id, 0, build_v3_registry())
    assert root.state["messages"][:len(original_history)] == original_history
    assert root.state["active_seconds"] >= 17.25
    assert receipt(run, root).input_payload["messages"] == root.state["pending_context"]["messages"]


@pytest.mark.parametrize("point", ["before_ledger", "after_receipt"])
def test_crash_replay_uses_frozen_request_despite_policy_budget_or_history_change(env, monkeypatch, point):
    _app, run, root = env
    seed_history(env)
    llm = script(env, {"producer": [done()]})
    actual_chat, actual_record = runtime.agent_chat, runtime._record
    def before(*_args, **_kwargs):
        raise RuntimeError("Injected crash before ledger")
    def after(*args, **kwargs):
        actual_record(*args, **kwargs)
        if args[2] == "llm":
            raise RuntimeError("Injected crash after receipt")
    monkeypatch.setattr(runtime, "agent_chat", before if point == "before_ledger" else actual_chat)
    monkeypatch.setattr(runtime, "_record", after if point == "after_receipt" else actual_record)
    registry = build_v3_registry()
    with pytest.raises(RuntimeError):
        runtime._round(root.id, 0, registry)
    frozen = deepcopy(root.state["pending_context"])
    spent = BudgetGuard.spent(run.run_id)
    raw = deepcopy(root.state)
    raw["messages"].append({"role": "user", "content": "A later state write must not alter this recorded step"})
    if point == "after_receipt":
        # The ledger is authoritative even if an obsolete request cache was changed.
        raw["pending_context"]["messages"] = [{"role": "system", "content": "wrong cached view"}]
    root.state = raw
    run.request = {**run.request, "budget_limit": 90}
    db.session.commit()
    def no_reprojection(_messages):
        pytest.fail("An already frozen request must not be projected again")
    monkeypatch.setattr(context, "project_messages", no_reprojection)
    monkeypatch.setattr(context, "POLICY_VERSION", 999)
    monkeypatch.setattr(runtime, "agent_chat", actual_chat)
    monkeypatch.setattr(runtime, "_record", actual_record)
    runtime._round(root.id, 0, registry)
    assert receipt(run, root).input_payload["messages"] == frozen["messages"]
    assert root.state["quota_snapshots"]["0"]["run_budget_limit"] == 100
    assert llm.calls == [("producer", 0)]
    if point == "after_receipt":
        assert BudgetGuard.spent(run.run_id) == spent


def test_new_step_projects_again_and_replaces_only_the_pending_request(env, monkeypatch):
    _app, run, root = env
    seed_history(env)
    script(env, {"producer": [[call("write_workspace", {"key": "x", "kind": "note", "payload": {"text": "next"}})], done()]})
    registry = build_v3_registry()
    runtime._round(root.id, 0, registry)
    first = deepcopy(receipt(run, root).input_payload)
    projected = context.project_messages
    observed = []
    def observe(messages):
        observed.append(deepcopy(messages))
        return projected(messages)
    monkeypatch.setattr(context, "project_messages", observe)
    runtime._round(root.id, 1, registry)
    assert len(observed) == 1 and root.state["pending_context"]["step"] == "1"
    assert receipt(run, root).input_payload == first
    assert "next" in str(receipt(run, root, 1).input_payload["messages"])


@pytest.mark.parametrize("schema_changed", [False, True])
def test_legacy_unprojected_receipt_replays_exactly_and_schema_drift_still_stops(env, schema_changed):
    _app, run, root = env
    seed_history(env)
    llm = script(env, {"producer": [[call("write_workspace", {"key": "x", "kind": "note", "payload": {"text": "legacy"}})]]})
    registry = build_v3_registry()
    names = ["write_workspace"] if schema_changed else get_catalog().cards["producer"].tools
    original = deepcopy(root.state["messages"])
    runtime.agent_chat("producer", original, registry.function_schemas(names),
        ctx=runtime._context(run, root), registry=registry)
    frozen = deepcopy(receipt(run, root).input_payload)
    spent = BudgetGuard.spent(run.run_id)
    runtime._round(root.id, 0, registry)
    assert receipt(run, root).input_payload == frozen
    assert "pending_context" not in root.state and "quota_snapshots" not in root.state
    assert llm.calls == [("producer", 0)] and BudgetGuard.spent(run.run_id) == spent
    if schema_changed:
        assert root.status == "failed" and root.error["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    else:
        assert root.steps == 1


def test_corrupted_preledger_context_is_refused_without_model_dispatch(env):
    _app, run, root = env
    seed_history(env)
    state = deepcopy(root.state)
    runtime._turn_messages(run, root, state, None)
    state["pending_context"]["messages"][0]["content"] = "tampered"
    llm = script(env, {"producer": [done()]})
    with pytest.raises(AppError) as error:
        runtime._turn_messages(run, root, state, None)
    assert error.value.code == "RECOVERY_REQUIRED" and llm.calls == []



def test_compacted_resource_can_be_read_again_via_registry_without_model_or_cost(env, monkeypatch):
    _app, run, root = env
    registry = build_v3_registry()
    arguments = {"name": "plan-review", "path": "resources/workspace/plan_draft.schema.json"}
    first = registry.invoke("read_skill_resource", arguments, runtime._context(run, root, suffix="manual-first"))
    assert len(json.dumps(first["output"])) > context.MIN_RESULT_CHARS
    messages = batch("read_skill_resource", arguments, first["output"], "manual") + tail()
    monkeypatch.setattr(context, "SOFT_CHAR_TARGET", 1_000)
    projected, stats = context.project_messages(messages)
    assert stats["compacted_result_count"] == 1
    address = json.loads(projected[1]["content"])["context_projection"]["reread"][0]
    again = registry.invoke(address["tool"], address["arguments"],
        runtime._context(run, root, suffix="manual-reread"))
    assert again["output"] == first["output"]
    assert json.loads(messages[1]["content"]) == first["output"]
    assert first["invocation_id"] is None and again["invocation_id"] is None
    assert BudgetGuard.spent(run.run_id) == 0
    assert ToolInvocation.query.filter_by(tool_name="agent_llm_turn").count() == 0
