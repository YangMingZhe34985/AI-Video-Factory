"""Policy v2 proofs are pure model-view changes; no app, DB or HTTP needed."""
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from app.agents import context, runtime
from app.agents.schemas import PlanDraft
from app.plans import tools


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(canon(value).encode("utf-8")).hexdigest()


def node(node_id="image", text=None):
    return {"id": node_id, "tool": "generate_image", "inputs": {"prompt": text or "场景细节" * 3500},
        "origin": {"agent": "director"}, "rationale": "frame"}


def plan(text=None):
    return {"title": "Story", "goal": "Video", "nodes": [node(text=text)],
        "deliverables": [{"kind": "image", "node_id": "image", "output": "image"}]}


def batch(name, arguments, output, call_id):
    return [{"role": "assistant", "content": None, "tool_calls": [{"id": call_id, "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]},
        {"role": "tool", "tool_call_id": call_id, "name": name, "content": json.dumps(output, ensure_ascii=False)}]


def write(version, payload=None, key="draft", call_id=None):
    raw = payload or plan("版本" + str(version) + "画面" * 8000)
    normalized = PlanDraft.model_validate(raw).model_dump(mode="json")
    output = {"key": key, "version": version, "kind": "plan_draft", "workspace_ref": {"key": key, "version": version},
              "author_agent": "director", "payload": normalized}
    return batch("write_workspace", {"key": key, "kind": "plan_draft", "payload": raw}, output, call_id or f"write{version}")


def args(messages, index):
    return json.loads(messages[index]["tool_calls"][0]["function"]["arguments"])


def marker(messages, index, field="payload"):
    return args(messages, index)[field]["context_projection"]


def tail():
    return batch("list_skills", {}, {}, "tail1") + batch("list_models", {}, {}, "tail2")


def test_old_saved_plan_arguments_and_result_project_even_within_recent_rounds():
    messages = write(1) + write(2)
    original = deepcopy(messages)
    projected, metrics = context.project_messages(messages)
    assert messages == original
    assert context.POLICY_VERSION == 2
    assert metrics["compacted_argument_count"] == metrics["compacted_plan_result_count"] == 1
    assert len(canon(projected)) < len(canon(messages)) * .65
    info = marker(projected, 0)
    assert info["request_view_only"] and info["not_executable"]
    assert info["reread"] == [{"tool": "read_workspace", "arguments": {"key": "draft", "version": 1}}]
    assert info["sha256_arguments"] == sha256(messages[0]["tool_calls"][0]["function"]["arguments"].encode()).hexdigest()
    assert "payload" not in json.loads(projected[1]["content"])
    assert projected[2:] == messages[2:]


def test_latest_is_kept_per_workspace_key_and_highest_version_not_position():
    messages = write(2) + write(1) + write(1, key="other", call_id="other")
    projected, metrics = context.project_messages(messages)
    assert projected[0] == messages[0] and projected[4] == messages[4]
    assert marker(projected, 2)["reread"][0]["arguments"]["version"] == 1
    assert metrics["compacted_argument_count"] == 1


def test_redundant_same_version_write_keeps_latest_occurrence_only():
    messages = write(1, call_id="first") + write(1, call_id="replayed")
    projected, metrics = context.project_messages(messages)
    assert metrics["compacted_argument_count"] == 1
    assert projected[2:] == messages[2:]


@pytest.mark.parametrize("defect", ["payload", "key", "version", "kind", "error", "arguments"])
def test_unproven_write_is_preserved_even_beyond_v9_budget(defect, monkeypatch):
    messages = write(1)
    output = json.loads(messages[1]["content"])
    if defect == "payload":
        output["payload"]["goal"] = "different"
    elif defect == "key":
        output["key"] = "different"
    elif defect == "version":
        output["version"] = 0
    elif defect == "kind":
        output["kind"] = "note"
    elif defect == "error":
        output["error"] = {"code": "SAVE_FAILED"}
    else:
        messages[0]["tool_calls"][0]["function"]["arguments"] = "{invalid"
    messages[1]["content"] = json.dumps(output, ensure_ascii=False)
    messages += write(2) + tail()
    monkeypatch.setattr(context, "SOFT_CHAR_TARGET", 100)
    projected, _metrics = context.project_messages(messages)
    assert projected[:2] == messages[:2]


def test_conflicting_payload_hashes_for_same_saved_version_are_never_projected(monkeypatch):
    messages = write(1, plan("一" * 10000), call_id="a") + write(1, plan("二" * 10000), call_id="b") + write(2) + tail()
    monkeypatch.setattr(context, "SOFT_CHAR_TARGET", 100)
    projected, _metrics = context.project_messages(messages)
    assert projected[:4] == messages[:4]


def test_two_calls_in_one_batch_preserve_pairing_other_arguments_and_order():
    first, second = write(1), write(2)
    calls = deepcopy(first[0]["tool_calls"] + second[0]["tool_calls"])
    calls.append({"id": "other", "type": "function", "function": {"name": "list_models", "arguments": "{}"}})
    messages = [{"role": "assistant", "content": "drafts", "tool_calls": calls}, first[1], second[1],
                {"role": "tool", "name": "list_models", "tool_call_id": "other", "content": "{}"}]
    projected, metrics = context.project_messages(messages)
    assert metrics["compacted_argument_count"] == 1
    assert projected[0]["content"] == "drafts"
    assert [c["id"] for c in projected[0]["tool_calls"]] == [c["id"] for c in calls]
    assert projected[0]["tool_calls"][1:] == messages[0]["tool_calls"][1:]
    assert [m.get("tool_call_id") for m in projected] == [m.get("tool_call_id") for m in messages]


@pytest.mark.parametrize("defect", ["missing", "duplicate", "name"])
def test_incomplete_or_ambiguous_batches_stay_unchanged(defect):
    messages = write(1)
    if defect == "missing":
        messages.pop()
    elif defect == "duplicate":
        messages.append(deepcopy(messages[-1]))
    else:
        messages[1]["name"] = "different"
    messages += write(2)
    projected, _metrics = context.project_messages(messages)
    assert projected == messages


@pytest.fixture
def append_schema():
    return tools.AppendInput


def append(base_version, schema, key="draft"):
    value = {"plan_ref": {"key": key, "version": base_version}, "nodes": [node(f"image{base_version}")]}
    normalized = schema.model_validate(value).model_dump(mode="json")
    saved = PlanDraft.model_validate(plan()).model_dump(mode="json")
    saved["nodes"] += normalized["nodes"]
    output = {"workspace_ref": {"key": key, "version": base_version + 1}, "key": key, "version": base_version + 1,
              "kind": "plan_draft", "node_count": len(saved["nodes"]), "input_hash": digest(normalized), "payload_hash": digest(saved)}
    return batch("append_plan_nodes", value, output, f"append{base_version}")


def test_append_receipt_proves_old_batches_and_does_not_synthesize_full_latest_plan(append_schema):
    messages = write(1) + append(1, append_schema) + append(2, append_schema)
    projected, metrics = context.project_messages(messages)
    assert metrics["compacted_argument_count"] == 2
    assert marker(projected, 2, "nodes")["reread"][0]["arguments"] == {"key": "draft", "version": 2}
    assert projected[4:] == messages[4:]
    assert projected[3] == messages[3]  # Already light append receipt is not rewritten.


@pytest.mark.parametrize("defect", ["input_hash", "payload_hash", "key", "version", "count", "missing_hash"])
def test_malformed_append_receipt_never_authorizes_projection(append_schema, defect):
    messages = append(1, append_schema)
    receipt = json.loads(messages[1]["content"])
    if defect == "missing_hash":
        receipt.pop("input_hash")
    elif defect == "count":
        receipt["node_count"] = 1
    elif defect == "version":
        receipt["version"] = 5
        receipt["workspace_ref"]["version"] = 5
    elif defect == "key":
        receipt["key"] = "another"
        receipt["workspace_ref"]["key"] = "another"
    else:
        receipt[defect] = "wrong"
    messages[1]["content"] = json.dumps(receipt)
    messages += append(2, append_schema)
    projected, _metrics = context.project_messages(messages)
    assert projected == messages


def test_redundant_successful_check_of_latest_saved_plan_uses_exact_ref():
    value = plan()
    messages = write(1, value) + batch("check_plan", {"plan": value}, {"issues": [], "estimates": {}}, "check")
    projected, metrics = context.project_messages(messages)
    assert metrics["compacted_argument_count"] == 1
    assert projected[:2] == messages[:2] and projected[3] == messages[3]
    check = args(projected, 2)
    assert check["plan_ref"] == {"key": "draft", "version": 1}
    assert check["context_projection"]["not_executable"]


@pytest.mark.parametrize("saved, issues", [(False, []), (True, [{"code": "MISSING_INPUT"}])])
def test_unsaved_or_failed_check_keeps_original_parameters(saved, issues):
    value = plan()
    messages = (write(1, value) if saved else []) + batch("check_plan", {"plan": value}, {"issues": issues}, "check")
    projected, _metrics = context.project_messages(messages)
    assert projected == messages


def test_plan_check_can_use_exact_saved_read_receipt_without_any_write_in_this_history():
    value = plan()
    record = json.loads(write(1, value)[1]["content"])
    messages = batch("read_workspace", {"key": "draft", "version": 1}, {"items": [record]}, "read")
    messages += batch("check_plan", {"plan": value}, {"issues": []}, "check")
    projected, _metrics = context.project_messages(messages)
    assert args(projected, 2)["plan_ref"] == {"key": "draft", "version": 1}


def test_user_system_errors_and_other_recent_tools_keep_original_content():
    messages = [{"role": "system", "content": "never change constraints"}, {"role": "user", "content": "core intent"}]
    messages += write(1) + write(2)
    messages += batch("analyze_images", {"artifact_ids": ["source"]}, {"images": ["evidence" * 10000]}, "vision")
    messages += [{"role": "system", "content": "server error correction"}]
    original = deepcopy(messages)
    projected, _metrics = context.project_messages(messages)
    assert projected[:2] == messages[:2] and projected[-3:] == messages[-3:]
    assert messages == original


@pytest.mark.parametrize("use_ledger", [False, True])
def test_runtime_recovery_never_reprojects_existing_frozen_request(monkeypatch, use_ledger):
    frozen, _metrics = context.project_messages(write(1) + write(2))
    state = {"messages": write(3), "pending_context": {"step": "7", "messages": frozen,
             "messages_hash": context.message_digest(frozen)}}
    monkeypatch.setattr(context, "project_messages", lambda *_: pytest.fail("Recovery must not project"))
    monkeypatch.setattr(context, "POLICY_VERSION", 999)
    prior = SimpleNamespace(input_payload={"messages": deepcopy(frozen)}) if use_ledger else None
    if use_ledger:
        state["pending_context"]["messages"] = [{"role": "system", "content": "wrong cache"}]
    assert runtime._turn_messages(SimpleNamespace(), SimpleNamespace(steps=7), state, prior) == frozen


@pytest.mark.parametrize("calls", [1, {"id": "bad"}, "not-list"])
def test_malformed_call_container_is_preserved(calls):
    messages = [{"role": "assistant", "content": None, "tool_calls": calls}] + write(1)
    projected, _metrics = context.project_messages(messages)
    assert projected == messages


def test_check_with_nullable_alternative_preserves_saved_proof():
    value = plan()
    messages = write(1, value) + batch("check_plan", {"plan": value, "plan_ref": None}, {"issues": []}, "check")
    projected, _metrics = context.project_messages(messages)
    assert args(projected, 2)["plan_ref"] == {"key": "draft", "version": 1}


def read_saved(version, *, key="draft", call_id="read"):
    item = json.loads(write(version, key=key)[1]["content"])
    return batch("read_workspace", {"key": key, "version": version}, {"items": [item]}, call_id)


def test_child_saved_new_version_read_replaces_obsolete_producer_context(monkeypatch):
    messages = write(1) + read_saved(2) + tail()
    original = deepcopy(messages)
    monkeypatch.setattr(context, "SOFT_CHAR_TARGET", 100)
    projected, metrics = context.project_messages(messages)
    assert metrics["compacted_argument_count"] == 1
    assert marker(projected, 0)["reread"][0]["arguments"]["version"] == 1
    assert projected[2:4] == messages[2:4]
    assert messages == original


def test_latest_read_does_not_evict_latest_same_version_producer(monkeypatch):
    messages = write(1) + write(2) + read_saved(2) + tail()
    monkeypatch.setattr(context, "SOFT_CHAR_TARGET", 100)
    projected, metrics = context.project_messages(messages)
    assert metrics["compacted_argument_count"] == 1
    assert projected[2:6] == messages[2:6]


def test_only_latest_same_version_full_read_bypasses_v9_compaction(monkeypatch):
    messages = read_saved(2, call_id="earlier") + read_saved(2, call_id="latest") + tail()
    monkeypatch.setattr(context, "SOFT_CHAR_TARGET", 100)
    projected, _metrics = context.project_messages(messages)
    assert "payload" not in json.loads(projected[1]["content"])["items"][0]
    assert projected[2:4] == messages[2:4]


def test_older_read_cannot_make_obsolete_producer_latest():
    messages = read_saved(2) + write(1)
    projected, metrics = context.project_messages(messages)
    assert metrics["compacted_argument_count"] == 1
    assert projected[:2] == messages[:2]


@pytest.mark.parametrize("value", [{"中文": "视觉", "a": [1, 1.0, None, True, False]},
    {"nodes": [{"id": "node", "inputs": {"text": "\\\"\n"}}], "rate": -0.0}])
def test_payload_digest_matches_project_canonical_inputs_hash(value):
    from app.agents.context_plans import _digest
    from app.agent.plan_versions import inputs_hash
    assert _digest(value) == inputs_hash(value)
