"""Exact saved-plan projections for model requests, never replayable tool input."""
from copy import deepcopy
from hashlib import sha256
import json
import re

from app.api import AppError


_HASH = re.compile(r"^[a-f0-9]{64}$")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _parsed(value):
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else None
    except (TypeError, ValueError, RecursionError):
        return None


def _workspace(output, *, payload=False):
    if (not isinstance(output, dict) or output.get("kind") != "plan_draft"
            or not isinstance(output.get("key"), str) or not output["key"]
            or type(output.get("version")) is not int or output["version"] < 1
            or output.get("workspace_ref") != {"key": output["key"], "version": output["version"]}
            or payload and not isinstance(output.get("payload"), dict)):
        return None
    return {"key": output["key"], "version": output["version"]}


def _write_proof(arguments, output):
    from app.agents.schemas import PlanDraft
    from app.agents.tools import WriteInput
    normalized = WriteInput.model_validate(arguments).model_dump(mode="json")
    ref = _workspace(output, payload=True)
    if ref is None or normalized["kind"] != "plan_draft" or normalized["key"] != ref["key"]:
        return None
    normalized["payload"] = PlanDraft.model_validate(normalized["payload"]).model_dump(mode="json")
    digest = _digest(output["payload"])
    if digest != _digest(normalized["payload"]):
        return None
    return {"ref": ref, "payload_hash": digest, "input_hash": _digest(normalized), "field": "payload"}


def _append_proof(arguments, output):
    from app.plans.tools import AppendInput
    normalized = AppendInput.model_validate(arguments).model_dump(mode="json")
    ref = _workspace(output)
    source = normalized["plan_ref"]
    if (ref is None or ref["key"] != source["key"] or ref["version"] != source["version"] + 1
            or type(output.get("node_count")) is not int
            or not len(normalized["nodes"]) < output["node_count"] <= 200
            or not isinstance(output.get("payload_hash"), str) or not _HASH.fullmatch(output["payload_hash"])
            or output.get("input_hash") != _digest(normalized)):
        return None
    return {"ref": ref, "payload_hash": output["payload_hash"], "input_hash": output["input_hash"], "field": "nodes"}


def _read_proofs(arguments, output):
    from app.agents.schemas import PlanDraft
    from app.agents.tools import ReadInput
    normalized = ReadInput.model_validate(arguments).model_dump(mode="json")
    results = []
    if not isinstance(output.get("items"), list):
        return results
    for item in output["items"]:
        ref = _workspace(item, payload=True)
        if (ref is None or normalized.get("key") != ref["key"]
                or normalized.get("kind") not in {None, "plan_draft"}
                or normalized.get("version") is not None and normalized["version"] != ref["version"]):
            continue
        normalized_payload = PlanDraft.model_validate(item["payload"]).model_dump(mode="json")
        if _digest(normalized_payload) == _digest(item["payload"]):
            results.append({"ref": ref, "payload_hash": _digest(item["payload"]), "field": None})
    return results


def _marker(record, function, policy_version):
    return {"policy_version": policy_version, "omitted": True, "request_view_only": True,
        "not_executable": True, "original_arguments_chars": len(function["arguments"]),
        "sha256_arguments": sha256(function["arguments"].encode("utf-8")).hexdigest(),
        "sha256_saved_payload": record["payload_hash"],
        "sha256_normalized_input": record.get("input_hash"),
        "reread": [{"tool": "read_workspace", "arguments": deepcopy(record["ref"])}],
        "notice": "Incomplete historical model-request view, not valid tool input. The immutable saved Plan is available at this exact free read address. Original arguments and receipt remain in durable history."}


def project_saved_plans(messages, projected, rounds, *, policy_version):
    """Project proven old producers and redundant successful Plan checks only."""
    locations = {}
    for index, message in enumerate(messages):
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for number, call in enumerate(calls):
            if isinstance(call, dict) and isinstance(call.get("function"), dict):
                locations.setdefault(id(call["function"]), []).append((index, number))
    records, checks, protected = [], [], set()
    for batch in rounds:
        for position, reply, function in batch:
            name = function.get("name")
            if name not in {"write_workspace", "append_plan_nodes", "read_workspace", "check_plan"}:
                continue
            arguments, output = _parsed(function.get("arguments")), _parsed(reply.get("content"))
            plan_write = name == "write_workspace" and (
                isinstance(arguments, dict) and arguments.get("kind") == "plan_draft"
                or isinstance(output, dict) and output.get("kind") == "plan_draft")
            if plan_write:
                # Generic V9 receipt compaction has no payload/input proof. A
                # rejected or ambiguous Plan write must not fall back to it.
                protected.add(position)
            if (arguments is None or output is None or "error" in output
                    or len(locations.get(id(function), [])) != 1):
                continue
            location = locations[id(function)][0]
            common = {"position": position, "location": location, "function": function,
                      "arguments": arguments, "output": output, "name": name}
            try:
                if plan_write:
                    proof = _write_proof(arguments, output)
                    if proof:
                        records.append({**common, **proof})
                elif name == "append_plan_nodes":
                    proof = _append_proof(arguments, output)
                    if proof:
                        records.append({**common, **proof})
                elif name == "read_workspace":
                    for proof in _read_proofs(arguments, output):
                        records.append({**common, **proof})
                elif (name == "check_plan" and output.get("issues") == [] and "plan" in arguments
                      and set(arguments) <= {"plan", "plan_ref"} and arguments.get("plan_ref") is None):
                    from app.agents.schemas import PlanDraft
                    normalized = PlanDraft.model_validate(arguments["plan"]).model_dump(mode="json")
                    checks.append({**common, "payload_hash": _digest(normalized), "input_hash": _digest({"plan": normalized})})
            except (AppError, ImportError, TypeError, ValueError, KeyError, RecursionError):
                # Schema drift and old/malformed receipts are kept verbatim.
                continue

    hashes = {}
    for record in records:
        identity = record["ref"]["key"], record["ref"]["version"]
        hashes.setdefault(identity, set()).add(record["payload_hash"])
    ambiguous = {identity for identity, values in hashes.items() if len(values) != 1}
    for record in records:
        if (record["ref"]["key"], record["ref"]["version"]) in ambiguous:
            protected.add(record["position"])
    records = [record for record in records if (record["ref"]["key"], record["ref"]["version"]) not in ambiguous]
    latest_versions = {}
    for record in records:
        key = record["ref"]["key"]
        latest_versions[key] = max(latest_versions.get(key, 0), record["ref"]["version"])
    latest_producers, latest_reads = {}, {}
    for record in records:
        key = record["ref"]["key"]
        if record["ref"]["version"] != latest_versions[key]:
            continue
        target = latest_reads if record["name"] == "read_workspace" else latest_producers
        old = target.get(key)
        if old is None or record["position"] > old["position"]:
            target[key] = record
    # A child may publish a new version observed only by an exact workspace read.
    # Keep that newest complete view, even when V9's generic result budget is low.
    protected.update(record["position"] for record in latest_reads.values())
    candidates = [record for record in records if record["name"] in {"write_workspace", "append_plan_nodes"}
                  and record is not latest_producers.get(record["ref"]["key"])]
    for check in checks:
        matches = [record for record in records if record["payload_hash"] == check["payload_hash"]]
        if matches:
            source = max(matches, key=lambda item: (item["position"], item["ref"]["key"], item["ref"]["version"]))
            candidates.append({**check, "ref": source["ref"], "field": "plan"})

    compacted_arguments, compacted_results = [], []
    for record in sorted(candidates, key=lambda item: item["position"]):
        function = record["function"]
        marker = _marker(record, function, policy_version)
        arguments = deepcopy(record["arguments"])
        if record["name"] == "check_plan":
            arguments = {"plan_ref": deepcopy(record["ref"]), "context_projection": marker}
        else:
            arguments[record["field"]] = {"context_projection": marker}
        replacement = _json(arguments)
        if len(replacement) < len(function["arguments"]):
            message_index, call_index = record["location"]
            projected[message_index]["tool_calls"][call_index]["function"]["arguments"] = replacement
            compacted_arguments.append({"message_index": message_index, "call_index": call_index})
        if record["name"] == "write_workspace":
            original = messages[record["position"]]["content"]
            value = deepcopy(record["output"])
            value.pop("payload")
            value["context_projection"] = {**marker, "original_chars": len(original),
                "sha256_result_content": sha256(original.encode("utf-8")).hexdigest()}
            replacement = _json(value)
            if len(replacement) < len(original):
                projected[record["position"]]["content"] = replacement
                compacted_results.append(record["position"])
    return {"compacted_argument_count": len(compacted_arguments), "compacted_argument_indexes": compacted_arguments,
            "compacted_plan_result_indexes": compacted_results, "protected_plan_result_indexes": sorted(protected)}
