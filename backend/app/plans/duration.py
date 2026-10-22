"""Explicit user duration and canonical delivery accounting, without execution."""

from copy import deepcopy
import math

from app.agents.schemas import DurationConstraint
from app.api import AppError


def constraint_from_brief(brief):
    if brief.target_duration_sec is None:
        return None
    return DurationConstraint(target_duration_sec=brief.target_duration_sec,
        duration_tolerance_sec=brief.duration_tolerance_sec,
        mode=brief.duration_mode or "approx").model_dump(mode="json")


def bind_constraint(plan, brief):
    expected = constraint_from_brief(brief)
    if plan.get("duration_constraint") is not None and plan["duration_constraint"] != expected:
        raise AppError("PLAN_DURATION_CONSTRAINT_CONFLICT",
            "Plan duration bounds must match the validated user brief", 422)
    if expected is not None:
        plan["duration_constraint"] = expected


def duration_details(actual, constraint):
    value = DurationConstraint.model_validate(constraint)
    target, tolerance = value.target_duration_sec, value.duration_tolerance_sec
    return {"current_duration_sec": actual, "target_duration_sec": target,
        "duration_tolerance_sec": tolerance, "mode": value.mode,
        "minimum_duration_sec": 0.0 if value.mode == "at_most" else max(0.0, target - tolerance),
        "maximum_duration_sec": target + tolerance}


def matches_duration(actual, constraint):
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual) or actual <= 0:
        return False
    detail = duration_details(actual, constraint)
    return detail["minimum_duration_sec"] - 1e-6 <= actual <= detail["maximum_duration_sec"] + 1e-6


def _canonical(reference, nodes):
    if isinstance(reference, str) and reference:
        return {"artifact": reference}
    if not isinstance(reference, dict) or len(reference) != 1:
        raise AppError("PLAN_DURATION_UNKNOWN", "Final video needs a typed media reference", 422)
    if "artifact" in reference and isinstance(reference["artifact"], str) and reference["artifact"]:
        return deepcopy(reference)
    if "ref" not in reference or not isinstance(reference["ref"], str):
        raise AppError("PLAN_DURATION_UNKNOWN", "Final video needs a typed media reference", 422)
    parts = reference["ref"].split(".")
    if len(parts) != 2 or parts[0] not in nodes:
        raise AppError("PLAN_DURATION_UNKNOWN", "Final video references an unavailable output", 422)
    node = nodes[parts[0]]
    if node["tool"] == "compose_video" and parts[1] == "compressed_artifact_id":
        return {"ref": f"{parts[0]}.artifact_id"}
    return deepcopy(reference)


def duration_targets(plan):
    """Count independent final videos once; preserve repeats inside compositions."""
    nodes = {node["id"]: node for node in plan["nodes"]}
    targets = []
    for delivery in plan["deliverables"]:
        if delivery["kind"] == "video":
            source = {"ref": f"{delivery['node_id']}.{delivery['output']}"}
        elif delivery["kind"] == "package":
            node = nodes.get(delivery["node_id"], {})
            if node.get("tool") != "package_story":
                raise AppError("PLAN_DURATION_UNKNOWN", "Package has no final video source", 422)
            source = node.get("inputs", {}).get("artifact_id")
        else:
            continue
        reference = _canonical(source, nodes)
        if reference not in targets:
            targets.append(reference)
    return targets


def bind_qc_constraint(node, plan):
    if node["tool"] != "qc_video":
        return
    constraint = plan.get("duration_constraint")
    targets = duration_targets(plan) if constraint else []
    source = node["inputs"].get("artifact_id")
    expected = (constraint if len(targets) == 1 and
        _canonical(source, {item["id"]: item for item in plan["nodes"]}) == targets[0] else None)
    supplied = node["inputs"].get("duration_constraint")
    if supplied is not None and supplied != expected:
        raise AppError("PLAN_DURATION_CONSTRAINT_CONFLICT",
            "QC duration bounds must match the approved single final video target", 422)
    if expected is not None:
        node["inputs"]["duration_constraint"] = deepcopy(expected)


def delivery_seconds(plan, outputs, artifact_info):
    total = 0.0
    targets = duration_targets(plan)
    for reference in targets:
        if "artifact" in reference:
            metadata = artifact_info(reference["artifact"])
        else:
            node, field = reference["ref"].split(".")
            metadata = outputs.get(node, {}).get(field, {})
        seconds = metadata.get("duration_sec")
        if (metadata.get("type") != "video" or isinstance(seconds, bool)
                or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0):
            raise AppError("PLAN_DURATION_UNKNOWN", "Final video needs a verified positive duration", 422)
        total += seconds
    if plan.get("duration_constraint") is not None and not targets:
        raise AppError("PLAN_DURATION_UNKNOWN", "User duration requires a final video delivery", 422)
    return total
