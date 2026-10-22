"""Request-only projections for proven obsolete checks and model catalogs."""
from copy import deepcopy
from hashlib import sha256
import json

from app.api import AppError
from app.agents.context_plans import _append_proof, _digest, _read_proofs, _write_proof


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _parsed(reply, function):
    from app.agents.schemas import finite_json
    try:
        arguments = json.loads(function["arguments"])
        output = json.loads(reply["content"])
        if (not isinstance(arguments, dict) or not isinstance(output, dict)
                or "context_projection" in arguments or "context_projection" in output or "error" in output):
            return None
        finite_json(arguments)
        _json(output)
        return arguments, output
    except (AppError, TypeError, ValueError, KeyError, RecursionError):
        return None


def _saved_proofs(rounds):
    from app.agents.schemas import WorkspaceRef
    records = []
    for batch in rounds:
        for position, reply, function in batch:
            name = function.get("name")
            if name not in {"write_workspace", "append_plan_nodes", "read_workspace"}:
                continue
            parsed = _parsed(reply, function)
            if parsed is None:
                continue
            arguments, output = parsed
            try:
                if name == "read_workspace":
                    proofs = _read_proofs(arguments, output)
                else:
                    proof = (_write_proof if name == "write_workspace" else _append_proof)(arguments, output)
                    proofs = [proof] if proof else []
                for proof in proofs:
                    ref = WorkspaceRef.model_validate(proof["ref"]).model_dump(mode="json")
                    records.append({"ref": ref, "payload_hash": proof["payload_hash"], "position": position})
            except (AppError, ImportError, TypeError, ValueError, KeyError, RecursionError):
                continue
    hashes = {}
    for record in records:
        identity = record["ref"]["key"], record["ref"]["version"]
        hashes.setdefault(identity, set()).add(record["payload_hash"])
    conflicts = {identity for identity, values in hashes.items() if len(values) != 1}
    return [item for item in records if (item["ref"]["key"], item["ref"]["version"]) not in conflicts], conflicts


def _check(arguments, output, saved, conflicts):
    from app.plans.schemas import PlanEstimates, PlanIssue
    from app.plans.tools import CheckInput
    value = CheckInput.model_validate(arguments).model_dump(mode="json")
    if (set(output) != {"issues", "estimates", "experimental", "resolved_models", "order"}
            or not isinstance(output["issues"], list) or type(output["experimental"]) is not bool
            or not isinstance(output["resolved_models"], dict) or not isinstance(output["order"], list)
            or any(not isinstance(key, str) or not isinstance(model, str)
                   for key, model in output["resolved_models"].items())
            or any(not isinstance(item, str) for item in output["order"])):
        return None
    PlanEstimates.model_validate(output["estimates"])
    issues = [PlanIssue.model_validate(item).model_dump(mode="json") for item in output["issues"]]
    if "plan_ref" in value:
        ref = value["plan_ref"]
        payload_hash = None
    else:
        payload_hash = _digest(value["plan"])
        identities = {(item["ref"]["key"], item["ref"]["version"]) for item in saved
                      if item["payload_hash"] == payload_hash}
        if len(identities) != 1:
            return None
        key, version = next(iter(identities))
        ref = {"key": key, "version": version}
    if (ref["key"], ref["version"]) in conflicts:
        return None
    return {"ref": ref, "payload_hash": payload_hash, "issues": issues}


def _catalog(arguments, output):
    from app.tools.specs.list_models import ListModelsInput, ListModelsOutput
    normalized = ListModelsInput.model_validate(arguments).model_dump(mode="json")
    value = ListModelsOutput.model_validate(output)
    return {"arguments": normalized, "key": _json(normalized), "model_count": len(value.models)}


def _marker(original, policy_version):
    return {"policy_version": policy_version, "omitted": True, "request_view_only": True,
        "not_executable": True, "original_chars": len(original),
        "sha256_result_content": sha256(original.encode("utf-8")).hexdigest()}


def _check_replacement(record, newer, original, policy_version):
    counts = {}
    for issue in record["issues"]:
        counts[issue["code"]] = counts.get(issue["code"], 0) + 1
    ref = deepcopy(record["ref"])
    return _json({"issue_summary": {"count": len(record["issues"]), "codes": counts},
        "context_projection": {**_marker(original, policy_version), "kind": "superseded_plan_check",
            "plan_ref": ref, "sha256_saved_payload": record["payload_hash"],
            "superseded_by": deepcopy(newer["ref"]),
            "reread": [{"tool": "read_workspace", "arguments": ref}],
            "recheck": {"tool": "check_plan", "arguments": {"plan_ref": ref}},
            "notice": "Obsolete failed check result in the model request only; the original result remains in durable history. "
                      "Read the immutable draft at the exact free address. Rechecking uses the current compiler and catalog, "
                      "not the original historical diagnostics. This projection is not executable tool input."}})


def _catalog_replacement(record, original, policy_version):
    return _json({"model_count": record["model_count"], "filters": deepcopy(record["arguments"]),
        "context_projection": {**_marker(original, policy_version), "kind": "superseded_model_catalog",
            "reread": [{"tool": "list_models", "arguments": deepcopy(record["arguments"])}],
            "notice": "An obsolete model catalog in the request view only; a newer valid result with these filters is retained. "
                      "The original result remains in durable history. The free catalog read is current and may differ from "
                      "the historical response. This projection is not executable tool input."}})


def project_superseded_receipts(messages, projected, rounds, *, policy_version):
    """Only replace tool results; recent superseded copies have no exemption."""
    saved, conflicts = _saved_proofs(rounds)
    checks, catalogs = [], []
    for batch in rounds:
        for position, reply, function in batch:
            name = function.get("name")
            if name not in {"check_plan", "list_models"}:
                continue
            parsed = _parsed(reply, function)
            if parsed is None:
                continue
            try:
                record = (_check(*parsed, saved, conflicts) if name == "check_plan" else _catalog(*parsed))
            except (AppError, ImportError, TypeError, ValueError, KeyError, RecursionError):
                continue
            if record is not None:
                (checks if name == "check_plan" else catalogs).append({**record, "position": position})
    compacted_checks, compacted_catalogs = [], []
    for record in checks:
        if not record["issues"]:
            continue
        newer = [item for item in checks if item["position"] > record["position"]
                 and item["ref"]["key"] == record["ref"]["key"]
                 and item["ref"]["version"] > record["ref"]["version"]]
        if not newer:
            continue
        source = max(newer, key=lambda item: item["position"])
        original = messages[record["position"]]["content"]
        replacement = _check_replacement(record, source, original, policy_version)
        if len(replacement) < len(original):
            projected[record["position"]]["content"] = replacement
            compacted_checks.append(record["position"])
    latest = {record["key"]: record["position"] for record in catalogs}
    for record in catalogs:
        if record["position"] == latest[record["key"]]:
            continue
        original = messages[record["position"]]["content"]
        replacement = _catalog_replacement(record, original, policy_version)
        if len(replacement) < len(original):
            projected[record["position"]]["content"] = replacement
            compacted_catalogs.append(record["position"])
    return {"compacted_check_result_indexes": compacted_checks,
            "compacted_catalog_result_indexes": compacted_catalogs}
