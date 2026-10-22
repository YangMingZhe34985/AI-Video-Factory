"""Runtime-only measurement allowance; never changes approved intent bounds."""
import math

from app.api import AppError
from app.plans.duration import _canonical, duration_details


def segment_count(plan, reference):
    """Count actual final compose inputs, not dependencies or QC source lists."""
    nodes = {node["id"]: node for node in plan["nodes"]}
    source = _canonical(reference, nodes)
    if "ref" not in source:
        return 1
    node_id, field = source["ref"].split(".")
    node = nodes[node_id]
    if node["tool"] != "compose_video":
        return 1
    sources = node["inputs"].get("video_artifact_ids")
    if field != "artifact_id" or not isinstance(sources, list) or not 1 <= len(sources) <= 120:
        raise AppError("PLAN_QC_FAILED", "Approved composition has no valid segment list", 422)
    return len(sources)


def _positive(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0)


def measurement_allowance(observations):
    """Each observation is (approved segment count, freshly probed file FPS)."""
    frames, segments, unknown = 0.0, 0, 0
    for count, fps in observations:
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 120:
            raise AppError("PLAN_QC_FAILED", "Measured duration needs a valid segment count", 422)
        segments += count
        if _positive(fps):
            frames += count / fps
        else:
            unknown += count
    if not segments or not math.isfinite(frames):
        raise AppError("PLAN_QC_FAILED", "Measured duration allowance is unavailable", 422)
    return {"measurement_error_sec": max(0.5, frames),
        "measurement_frame_allowance_sec": frames, "measurement_segment_count": segments,
        "measurement_unknown_fps_segments": unknown}


def measured_details(actual, constraint, observations):
    allowance = measurement_allowance(observations)
    details = duration_details(actual, constraint)
    error = allowance["measurement_error_sec"]
    lower = max(0.0, details["minimum_duration_sec"] - error)
    upper = details["maximum_duration_sec"] + error
    return {**details, **allowance,
        "effective_minimum_duration_sec": lower, "effective_maximum_duration_sec": upper,
        "passed": _positive(actual) and lower - 1e-6 <= actual <= upper + 1e-6}
