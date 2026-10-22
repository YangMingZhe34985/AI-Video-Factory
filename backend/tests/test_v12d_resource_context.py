"""Keep current contracts intact; compact only genuinely superseded reads."""
from copy import deepcopy
import json

import pytest

from app.agents import context
from tests.test_v9_context import batch, tail


def resource(identity, name="plan-review", path="resources/tools/generate_video.json", content=None):
    arguments = {"name": name, "path": path}
    return batch("read_skill_resource", arguments, {**arguments, "content": content if content is not None else "契约字段" * 20000}, identity)


def decoded(messages, index):
    return json.loads(messages[index]["content"])


def test_only_resource_is_protected_even_before_recent_rounds_and_above_soft_target():
    messages = resource("only") + tail()
    original = deepcopy(messages)
    projected, stats = context.project_messages(messages)
    assert messages == original == projected
    assert stats["over_soft_target"] and stats["compacted_result_count"] == 0
    assert stats["policy_version"] == 4


def test_latest_exact_resource_preserved_and_prior_full_copy_can_be_reread():
    messages = resource("old") + resource("new", content="当前契约" * 20000) + tail()
    original = deepcopy(messages)
    projected, stats = context.project_messages(messages)
    assert messages == original
    assert projected[3:] == messages[3:]
    assert "content" not in decoded(projected, 1)
    info = decoded(projected, 1)["context_projection"]
    assert info["reread"] == [{"tool": "read_skill_resource", "arguments": {
        "name": "plan-review", "path": "resources/tools/generate_video.json"}}]
    assert info["policy_version"] == 4 and stats["compacted_result_count"] == 1
    assert stats["over_soft_target"]
    assert all(old == new for old,new in zip(messages, projected) if old["role"] != "tool")


def test_latest_is_keyed_by_both_name_and_path_without_collapsing_distinct_contracts():
    messages = resource("a", name="one", path="same")
    messages += resource("b", name="two", path="same")
    messages += resource("c", name="one", path="other")
    messages += resource("d", name="one", path="same") + tail()
    original = deepcopy(messages)
    projected, stats = context.project_messages(messages)
    assert messages == original and stats["compacted_result_count"] == 1
    assert "context_projection" in decoded(projected, 1)
    assert projected[3:] == messages[3:]


@pytest.mark.parametrize("defect", ["error", "wrong_name", "wrong_path", "missing_content", "bad_content",
    "invalid_json", "arguments_json", "incomplete", "duplicate_reply", "wrong_call_id", "already_projected"])
def test_bad_later_result_neither_shadows_the_last_good_copy_nor_gets_projected(defect):
    first = resource("good")
    bad = resource("bad")
    if defect == "error":
        bad[1]["content"] = json.dumps({"error": {"code": "FAILED", "message": "x" * 80000}})
    elif defect in {"wrong_name", "wrong_path", "missing_content", "bad_content", "already_projected"}:
        output = decoded(bad, 1)
        if defect == "wrong_name": output["name"] = "other"
        elif defect == "wrong_path": output["path"] = "other"
        elif defect == "missing_content": output.pop("content")
        elif defect == "bad_content": output["content"] = {"unknown": "x" * 80000}
        else: output["context_projection"] = {"omitted": True}
        bad[1]["content"] = json.dumps(output)
    elif defect == "invalid_json": bad[1]["content"] = "not JSON" * 20000
    elif defect == "arguments_json": bad[0]["tool_calls"][0]["function"]["arguments"] = "invalid"
    elif defect == "incomplete":
        bad[0]["tool_calls"].append({"id": "missing", "function": {"name": "list_models", "arguments": "{}"}})
    elif defect == "duplicate_reply": bad.append(deepcopy(bad[1]))
    else: bad[1]["tool_call_id"] = "not-the-call"
    messages = first + bad + tail()
    projected, stats = context.project_messages(messages)
    assert projected == messages
    assert stats["over_soft_target"] and stats["compacted_result_count"] == 0


@pytest.mark.parametrize("content", ["", "short"])
def test_later_small_valid_read_replaces_large_old_copy(content, monkeypatch):
    monkeypatch.setattr(context, "SOFT_CHAR_TARGET", 1000)
    messages = resource("old") + resource("latest", content=content) + tail()
    projected, stats = context.project_messages(messages)
    assert stats["compacted_result_count"] == 1
    assert "content" not in decoded(projected, 1)
    assert projected[3:] == messages[3:]


def test_unique_contracts_may_exceed_soft_target_without_claiming_token_success():
    messages = []
    for index in range(6):
        messages += resource(str(index), path=f"resources/tool-{index}.json")
    messages += tail()
    projected, stats = context.project_messages(messages)
    assert projected == messages
    assert stats["after_chars"] == stats["before_chars"]
    assert stats["after_chars"] > stats["soft_target_chars"] and stats["over_soft_target"]


def test_different_resource_names_do_not_replace_latest_loaded_skill():
    loaded = batch("load_skill", {"name": "plan-review"}, {"name": "plan-review", "body": "规则" * 40000}, "skill")
    messages = loaded + resource("resource") + tail()
    projected, stats = context.project_messages(messages)
    assert projected == messages and stats["over_soft_target"]


def test_old_resource_in_recent_round_still_retains_existing_recency_protection():
    messages = resource("old") + resource("latest")
    projected, stats = context.project_messages(messages)
    assert projected == messages and stats["compacted_result_count"] == 0
