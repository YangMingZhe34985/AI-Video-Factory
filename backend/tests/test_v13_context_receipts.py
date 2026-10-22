"""Only proven superseded receipts shrink; immutable history and replay survive."""
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from app.agents import context, context_receipts, runtime
from app.agents.schemas import PlanDraft
from app.api import AppError
from app.plans.schemas import PlanEstimates


def batch(name, arguments, output, identity):
    return [{"role": "assistant", "content": None, "tool_calls": [{"id": identity, "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]},
        {"role": "tool", "tool_call_id": identity, "name": name, "content": json.dumps(output, ensure_ascii=False)}]


def plan(version=1):
    return {"title": "猫", "goal": "海报", "nodes": [{"id": "image", "tool": "generate_image",
        "inputs": {"prompt": f"第{version}版猫海报"}, "origin": {"agent": "director"}, "rationale": "create"}],
        "deliverables": [{"kind": "image", "node_id": "image", "output": "image"}]}


def write(version, *, key="draft", payload=None, identity=None):
    payload = payload or plan(version)
    normalized = PlanDraft.model_validate(payload).model_dump(mode="json")
    return batch("write_workspace", {"key": key, "kind": "plan_draft", "payload": payload},
        {"key": key, "version": version, "kind": "plan_draft", "workspace_ref": {"key": key, "version": version},
         "payload": normalized}, identity or f"write-{key}-{version}")


def check(version, *, key="draft", failed=True, inline=None, identity=None):
    arguments = {"plan": inline} if inline is not None else {"plan_ref": {"key": key, "version": version}}
    output = {"issues": [{"code": "PLAN_INVALID_CHARACTER_REFERENCE", "node_id": "image",
        "message": "真实编译字段诊断" * 2000, "details": {"fields": ["characters"]}}] if failed else [],
        "estimates": PlanEstimates().model_dump(mode="json"), "experimental": True,
        "resolved_models": {"image": "test-image"}, "order": ["image"]}
    return batch("check_plan", arguments, output, identity or f"check-{key}-{version}")


def catalog(identity="catalog", *, arguments=None, empty=False, short=False):
    output = {"models": [] if empty else [{"model_id": "test", "display_name": "测试", "provider": "mock",
        "family": "test", "modes": ["i2v"], "capabilities": {"notes": "模型能力演示" * (1 if short else 2000)},
        "parameter_schema": {}, "default_params": {}, "pricing": {},
        "integration_status": "integrated", "verification_status": "untested"}], "demo": True}
    return batch("list_models", {} if arguments is None else arguments, output, identity)


def decoded(messages, index):
    return json.loads(messages[index]["content"])


@pytest.mark.parametrize("new_failed", [True, False])
def test_later_higher_version_replaces_failed_receipt_even_in_last_two_rounds(new_failed):
    messages = check(1) + check(2, failed=new_failed)
    original = deepcopy(messages)
    projected, stats = context.project_messages(messages)
    info = decoded(projected, 1)["context_projection"]
    assert info["policy_version"] == 4 and info["request_view_only"] and info["not_executable"]
    assert info["plan_ref"] == {"key": "draft", "version": 1}
    assert info["superseded_by"] == {"key": "draft", "version": 2}
    assert info["reread"] == [{"tool": "read_workspace", "arguments": info["plan_ref"]}]
    assert info["recheck"] == {"tool": "check_plan", "arguments": {"plan_ref": info["plan_ref"]}}
    assert info["sha256_result_content"] == sha256(messages[1]["content"].encode()).hexdigest()
    assert decoded(projected, 1)["issue_summary"] == {"count": 1, "codes": {"PLAN_INVALID_CHARACTER_REFERENCE": 1}}
    assert projected[0] == messages[0] and projected[2:] == messages[2:] and messages == original
    assert stats["compacted_check_result_count"] == stats["compacted_result_count"] == 1
    assert stats["compacted_check_result_indexes"] == [1] and stats["compacted_argument_count"] == 0


@pytest.mark.parametrize("successor", ["same_version", "different_key", "only_write", "older_later", "higher_earlier"])
def test_unrelated_or_unchecked_version_does_not_replace_a_failure(successor):
    first = check(2)
    second = {"same_version": lambda: check(2, identity="again"),
        "different_key": lambda: check(3, key="other"), "only_write": lambda: write(3),
        "older_later": lambda: check(1), "higher_earlier": lambda: check(3)}[successor]()
    messages = second + first if successor == "higher_earlier" else first + second
    projected, stats = context.project_messages(messages)
    assert projected == messages and stats["compacted_check_result_count"] == 0


@pytest.mark.parametrize("defect", ["tool_error", "extra", "missing", "bad_issues", "negative_estimate", "order",
    "arguments", "both_inputs", "null", "bad_ref", "missing_reply", "duplicate_reply", "wrong_name", "projected"])
def test_bad_later_check_cannot_supersede_latest_valid_failure(defect):
    later = check(2)
    output = decoded(later, 1)
    if defect == "tool_error": output = {"error": {"code": "INVALID_INPUT", "message": "error" * 3000}}
    elif defect == "extra": output["unknown"] = "not a check result"
    elif defect == "missing": output.pop("estimates")
    elif defect == "bad_issues": output["issues"] = [{"code": "NO_MESSAGE"}]
    elif defect == "negative_estimate": output["estimates"]["total_credits"] = -1
    elif defect == "order": output["order"] = "image"
    elif defect == "projected": output["context_projection"] = {"omitted": True}
    later[1]["content"] = json.dumps(output, ensure_ascii=False)
    if defect == "arguments": later[0]["tool_calls"][0]["function"]["arguments"] = "bad JSON"
    elif defect == "both_inputs": later[0]["tool_calls"][0]["function"]["arguments"] = json.dumps({"plan_ref": {"key": "draft", "version": 2}, "plan": plan()})
    elif defect == "null": later[0]["tool_calls"][0]["function"]["arguments"] = '{"plan_ref":null}'
    elif defect == "bad_ref": later[0]["tool_calls"][0]["function"]["arguments"] = '{"plan_ref":{"key":"draft","version":true}}'
    elif defect == "missing_reply": later.pop()
    elif defect == "duplicate_reply": later.append(deepcopy(later[1]))
    elif defect == "wrong_name": later[1]["name"] = "other"
    messages = check(1) + later
    projected, stats = context.project_messages(messages)
    assert projected == messages and stats["compacted_check_result_count"] == 0


def test_saved_inline_failure_has_exact_proof_but_original_parameters_stay_full():
    messages = write(1) + check(1, inline=plan()) + write(2) + check(2)
    projected, stats = context.project_messages(messages)
    assert projected[2] == messages[2]
    info = decoded(projected, 3)["context_projection"]
    assert info["plan_ref"] == {"key": "draft", "version": 1}
    assert info["sha256_saved_payload"] == context_receipts._digest(PlanDraft.model_validate(plan()).model_dump(mode="json"))
    assert stats["compacted_check_result_indexes"] == [3]


@pytest.mark.parametrize("case", ["unsaved", "mismatch", "ambiguous_address", "conflicting_payload"])
def test_inline_failure_without_unique_unconflicted_save_address_is_kept(case):
    prefix = []
    if case == "mismatch": prefix = write(1, payload=plan(99))
    elif case == "ambiguous_address": prefix = write(1) + write(1, key="another")
    elif case == "conflicting_payload": prefix = write(1) + write(1, payload=plan(99), identity="conflict")
    messages = prefix + check(1, inline=plan()) + check(2)
    projected, stats = context.project_messages(messages)
    assert projected[len(prefix):] == messages[len(prefix):]
    assert stats["compacted_check_result_count"] == 0


def test_exact_read_proves_saved_inline_without_write_in_current_history():
    item = decoded(write(1), 1)
    messages = batch("read_workspace", {"key": "draft", "version": 1}, {"items": [item]}, "read")
    messages += check(1, inline=plan()) + check(2)
    projected, stats = context.project_messages(messages)
    assert "context_projection" in decoded(projected, 3)
    assert stats["compacted_check_result_indexes"] == [3]


def test_conflicting_saved_version_also_preserves_explicit_ref_check():
    messages = write(1) + write(1, payload=plan(99), identity="conflict") + check(1) + check(2)
    projected, stats = context.project_messages(messages)
    assert projected == messages and stats["compacted_check_result_count"] == 0


def test_schema_app_error_preserves_history_instead_of_breaking_projection(monkeypatch):
    from app.plans.tools import CheckInput
    def rejected(*_args, **_kwargs):
        raise AppError("PLAN_CONTEXT_PROJECTION", "Read the immutable source", 422)
    monkeypatch.setattr(CheckInput, "model_validate", rejected)
    messages = check(1) + check(2)
    projected, stats = context.project_messages(messages)
    assert projected == messages and stats["compacted_result_count"] == 0


@pytest.mark.parametrize("arguments", [{}, {"mode": None, "family": None}])
def test_model_catalog_defaults_share_key_and_latest_is_kept_in_recent_rounds(arguments):
    messages = catalog("old") + catalog("new", arguments=arguments)
    projected, stats = context.project_messages(messages)
    info = decoded(projected, 1)["context_projection"]
    assert info["reread"] == [{"tool": "list_models", "arguments": {"mode": None, "family": None}}]
    assert projected[0] == messages[0] and projected[2:] == messages[2:]
    assert stats["compacted_catalog_result_count"] == stats["compacted_result_count"] == 1


@pytest.mark.parametrize("filters", [{"mode": "i2v"}, {"family": "wan"}, {"family": "WAN"}])
def test_different_catalog_filters_do_not_erase_independent_evidence(filters):
    messages = catalog("old", arguments={"family": "Wan"}) + catalog("new", arguments=filters)
    projected, stats = context.project_messages(messages)
    assert projected == messages and stats["compacted_catalog_result_count"] == 0


@pytest.mark.parametrize("defect", ["error", "models", "entry", "extra", "bad_filter", "projected", "incomplete"])
def test_bad_later_catalog_cannot_replace_a_valid_prior_result(defect):
    later = catalog("bad")
    output = decoded(later, 1)
    if defect == "error": output = {"error": {"code": "FAILED"}}
    elif defect == "models": output["models"] = "not a list"
    elif defect == "entry": output["models"][0].pop("pricing")
    elif defect == "extra": output["extra"] = True
    elif defect == "projected": output["context_projection"] = {"omitted": True}
    later[1]["content"] = json.dumps(output, ensure_ascii=False)
    if defect == "bad_filter": later[0]["tool_calls"][0]["function"]["arguments"] = '{"mode":3}'
    elif defect == "incomplete": later.pop()
    messages = catalog("old") + later
    projected, stats = context.project_messages(messages)
    assert projected == messages and stats["compacted_catalog_result_count"] == 0


def test_valid_empty_catalog_can_replace_prior_nonempty_and_short_results_never_grow():
    messages = catalog("old") + catalog("empty", empty=True)
    projected, stats = context.project_messages(messages)
    assert "context_projection" in decoded(projected, 1) and projected[3] == messages[3]
    assert stats["compacted_catalog_result_count"] == 1
    short = catalog("empty1", empty=True) + catalog("empty2", empty=True)
    assert context.project_messages(short)[0] == short


@pytest.mark.parametrize("kind", ["check", "catalog"])
def test_large_valid_receipt_is_not_limited_by_workspace_payload_size(kind):
    old = check(1) if kind == "check" else catalog("old")
    value = decoded(old, 1)
    if kind == "check":
        value["issues"][0]["message"] = "编译诊断" * 50000
    else:
        value["models"][0]["capabilities"]["notes"] = "模型能力" * 50000
    old[1]["content"] = json.dumps(value, ensure_ascii=False)
    assert len(old[1]["content"].encode("utf-8")) > 256 * 1024
    messages = old + (check(2) if kind == "check" else catalog("new"))
    projected, stats = context.project_messages(messages)
    assert "context_projection" in decoded(projected, 1)
    assert projected[2:] == messages[2:]
    assert stats["compacted_result_count"] == 1


def test_oversized_plan_arguments_do_not_gain_projection_authority():
    raw = plan()
    raw["nodes"][0]["inputs"]["prompt"] = "计划内容" * 50000
    messages = write(1, payload=raw) + check(1, inline=raw) + check(2)
    projected, stats = context.project_messages(messages)
    assert projected[2:] == messages[2:] and stats["compacted_check_result_count"] == 0


def test_deterministic_projection_preserves_protected_evidence_and_is_idempotent():
    messages = [{"role": "system", "content": "禁止未经批准的生成"}, {"role": "user", "content": "约120秒，不换角色"}]
    messages += batch("read_skill_resource", {"name": "plan-review", "path": "resources/tools/qc_video.json"},
        {"name": "plan-review", "path": "resources/tools/qc_video.json", "content": "当前合同" * 20000}, "contract")
    messages += write(2) + check(1) + check(2) + catalog("old") + catalog("new")
    original = deepcopy(messages)
    projected, stats = context.project_messages(messages)
    assert projected[:6] == messages[:6]
    assert messages == original and context.project_messages(messages) == (projected, stats)
    assert context.project_messages(projected)[0] == projected
    assert stats["compacted_result_count"] == 2
    assert stats["compacted_message_indexes"] == sorted(set(stats["compacted_check_result_indexes"] + stats["compacted_catalog_result_indexes"]))
    assert stats["after_chars"] == len(context._json(projected))
    assert stats["over_soft_target"]


@pytest.mark.parametrize("policy", [2, 3])
@pytest.mark.parametrize("ledger", [False, True])
def test_policy_four_never_recomputes_an_old_frozen_step(monkeypatch, policy, ledger):
    frozen = check(1) + catalog()
    state = {"messages": check(2), "pending_context": {"step": "7", "policy_version": policy,
        "messages": deepcopy(frozen), "messages_hash": context.message_digest(frozen)}}
    original = deepcopy(state)
    monkeypatch.setattr(context, "project_messages", lambda *_a: pytest.fail("Frozen step cannot reproject or rebill"))
    prior = SimpleNamespace(input_payload={"messages": deepcopy(frozen)}) if ledger else None
    assert runtime._turn_messages(SimpleNamespace(), SimpleNamespace(steps=7), state, prior) == frozen
    assert state == original
