"""Deterministic request-only projection of old, freely rereadable tool data."""

from copy import deepcopy
from hashlib import sha256
import json


POLICY_VERSION = 4
SOFT_CHAR_TARGET = 60_000
MIN_RESULT_CHARS = 2_000
PROTECTED_ROUNDS = 2
REREADABLE_TOOLS = frozenset({
    "read_skill_resource", "load_skill", "read_workspace", "write_workspace",
})


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def message_digest(messages):
    return sha256(_json(messages).encode("utf-8")).hexdigest()


def _completed_rounds(messages):
    """Do not touch incomplete, ambiguous or non-contiguous call/reply batches."""
    rounds = []
    for index, message in enumerate(messages):
        calls = message.get("tool_calls") if message.get("role") == "assistant" else None
        if not isinstance(calls, list) or not calls:
            continue
        by_id = {}
        for call in calls:
            if (not isinstance(call, dict) or not isinstance(call.get("id"), str)
                    or not call["id"] or call["id"] in by_id
                    or not isinstance(call.get("function"), dict)):
                break
            by_id[call["id"]] = call["function"]
        else:
            replies = []
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].get("role") == "tool":
                reply = messages[cursor]
                replies.append((cursor, reply))
                cursor += 1
            ids = [reply.get("tool_call_id") for _, reply in replies]
            if (all(isinstance(item, str) for item in ids) and len(ids) == len(by_id)
                    and len(set(ids)) == len(ids)
                    and set(ids) == set(by_id)
                    and all(reply.get("name") == by_id[reply["tool_call_id"]].get("name")
                            for _, reply in replies)):
                rounds.append([(position, reply, by_id[reply["tool_call_id"]])
                               for position, reply in replies])
    return rounds


def _success(reply, function):
    if function.get("name") not in REREADABLE_TOOLS:
        return None
    try:
        output = json.loads(reply["content"])
        arguments = json.loads(function["arguments"])
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(output, dict) or "error" in output or not isinstance(arguments, dict):
        return None
    return output, arguments


def _resource_key(output, arguments):
    """Only an exact, complete resource read can supersede its older copy."""
    if ("context_projection" in output or not isinstance(output.get("content"), str)
            or not isinstance(output.get("name"), str) or not output["name"]
            or not isinstance(output.get("path"), str) or not output["path"]
            or output["name"] != arguments.get("name") or output["path"] != arguments.get("path")):
        return None
    return output["name"], output["path"]


def _reference(item):
    if (not isinstance(item, dict) or not isinstance(item.get("payload"), dict)
            or not isinstance(item.get("key"), str) or not item["key"]
            or type(item.get("version")) is not int or item["version"] < 1
            or item.get("workspace_ref") != {"key": item["key"], "version": item["version"]}):
        return None
    return {"tool": "read_workspace", "arguments": {"key": item["key"], "version": item["version"]}}


def _replacement(name, output, arguments, original, *, latest_load):
    """Only remove content that has an exact free read address."""
    value = deepcopy(output)
    reread = []
    if name in {"read_skill_resource", "load_skill"}:
        if not isinstance(output.get("name"), str) or output["name"] != arguments.get("name"):
            return None
        if name == "load_skill":
            if latest_load or not isinstance(output.get("body"), str):
                return None
            value.pop("body")
            reread.append({"tool": name, "arguments": {"name": output["name"]}})
        else:
            if (not isinstance(output.get("content"), str) or not isinstance(output.get("path"), str)
                    or output["path"] != arguments.get("path")):
                return None
            value.pop("content")
            reread.append({"tool": name, "arguments": {"name": output["name"], "path": output["path"]}})
    else:
        items = [value] if name == "write_workspace" else value.get("items")
        if not isinstance(items, list) or not items:
            return None
        for item in items:
            reference = _reference(item)
            if reference is None:
                return None
            if arguments.get("key") is not None and item["key"] != arguments["key"]:
                return None
            if name == "read_workspace" and arguments.get("version") is not None:
                if item["version"] != arguments["version"]:
                    return None
            if name == "write_workspace" and item.get("kind") != arguments.get("kind"):
                return None
            reread.append(reference)
            item.pop("payload")
    value["context_projection"] = {
        "policy_version": POLICY_VERSION,
        "omitted": True,
        "original_chars": len(original),
        "sha256_result_content": sha256(original.encode("utf-8")).hexdigest(),
        "reread": reread,
        "notice": "Incomplete model-context view only; the original receipt is retained. "
                  "Use the exact free read address when the omitted content is needed. "
                  "A Skill resource hash identifies the original response, not a guarantee "
                  "that a later server deployment serves the same content.",
    }
    return _json(value)


def project_messages(messages):
    """Return a fresh request view and metrics; never rewrite durable history.

    The target is a Unicode-character soft bound, not a tokenizer or a promise
    to fit every provider window. Protected information may exceed the target.
    """
    projected = deepcopy(messages)
    before = len(_json(messages))
    size = before
    rounds = _completed_rounds(messages)
    from app.agents.context_plans import project_saved_plans
    plan_stats = project_saved_plans(messages, projected, rounds, policy_version=POLICY_VERSION)
    from app.agents.context_receipts import project_superseded_receipts
    receipt_stats = project_superseded_receipts(messages, projected, rounds, policy_version=POLICY_VERSION)
    size = len(_json(projected))
    protected_plans = set(plan_stats["protected_plan_result_indexes"])
    latest_skills = {}
    latest_resources = {}
    for batch in rounds:
        for position, reply, function in batch:
            parsed = _success(reply, function)
            if parsed and function.get("name") == "load_skill":
                output, arguments = parsed
                if (isinstance(output.get("name"), str) and isinstance(output.get("body"), str)
                        and output.get("name") == arguments.get("name")):
                    latest_skills[output.get("name")] = position
            elif parsed and function.get("name") == "read_skill_resource":
                key = _resource_key(*parsed)
                if key is not None:
                    latest_resources[key] = position
    protected_resources = set(latest_resources.values())
    compacted = [*plan_stats["compacted_plan_result_indexes"],
        *receipt_stats["compacted_check_result_indexes"], *receipt_stats["compacted_catalog_result_indexes"]]
    for batch in rounds[:-PROTECTED_ROUNDS]:
        for position, reply, function in batch:
            if position in protected_plans or position in protected_resources:
                continue
            if size <= SOFT_CHAR_TARGET:
                break
            original = reply.get("content")
            if not isinstance(original, str) or len(original) < MIN_RESULT_CHARS:
                continue
            parsed = _success(reply, function)
            if parsed is None:
                continue
            output, arguments = parsed
            if function["name"] == "read_skill_resource" and _resource_key(output, arguments) is None:
                continue
            replacement = _replacement(function["name"], output, arguments, original,
                latest_load=latest_skills.get(output.get("name")) == position)
            if replacement is None or len(replacement) >= len(original):
                continue
            projected[position]["content"] = replacement
            size = len(_json(projected))
            compacted.append(position)
        if size <= SOFT_CHAR_TARGET:
            break
    compacted = sorted(set(compacted))
    metrics = {"policy_version": POLICY_VERSION, "before_chars": before, "after_chars": size,
        "soft_target_chars": SOFT_CHAR_TARGET, "compacted_result_count": len(compacted),
        "compacted_message_indexes": sorted(compacted), "over_soft_target": size > SOFT_CHAR_TARGET,
        "compacted_argument_count": plan_stats["compacted_argument_count"],
        "compacted_argument_indexes": plan_stats["compacted_argument_indexes"],
        "compacted_plan_result_count": len(plan_stats["compacted_plan_result_indexes"]),
        "compacted_check_result_count": len(receipt_stats["compacted_check_result_indexes"]),
        "compacted_catalog_result_count": len(receipt_stats["compacted_catalog_result_indexes"]),
        **receipt_stats}
    return projected, metrics
