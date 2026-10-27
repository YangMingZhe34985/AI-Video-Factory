"""Resolve real inputs and typed outputs without trusting launch receipts."""
from copy import deepcopy
import math

from app.agent.plan_versions import inputs_hash
from app.api import AppError
from app.extensions import db
from app.models import Artifact, Job, PlanNodeTask, ToolInvocation
from app.services.file_fingerprint import cached_digest
from app.services.storage_service import StorageService
from app.tools.spec import ToolContext

ASYNC_OUTPUTS = {
    "generate_image": "first_frame_image", "animate_shot": "i2v_video",
    "transform_video": "r2v_flash_video",
}
MEDIA_TYPES = {"image", "video", "audio", "document", "package"}


def artifact_for_run(run, artifact_id, expected=None):
    from app.agents.workspace import require_artifact
    artifact = require_artifact(artifact_id, ToolContext(role="production", budget_scope=run.run_id), run=run)
    path = StorageService.resolve(artifact.file_path).resolve()
    if not path.is_relative_to(StorageService.root()) or not path.is_file() or path.stat().st_size == 0:
        raise AppError("PLAN_ARTIFACT_UNAVAILABLE", "Plan media is missing or empty", 409)
    mime = str(artifact.mime_type or "")
    if expected in {"image", "video", "audio"} and not mime.startswith(expected + "/"):
        raise AppError("PLAN_OUTPUT_TYPE_MISMATCH", "Plan media has an unexpected type", 422)
    if expected == "package" and mime not in {"application/zip", "application/x-zip-compressed"}:
        raise AppError("PLAN_OUTPUT_TYPE_MISMATCH", "Plan package is not an archive", 422)
    return artifact


def fingerprint(run, artifact_id, expected=None):
    artifact = artifact_for_run(run, artifact_id, expected)
    return {"artifact_id": artifact_id, "sha256": cached_digest(StorageService.resolve(artifact.file_path)),
            "mime_type": artifact.mime_type, "size": StorageService.resolve(artifact.file_path).stat().st_size}


def _ids(value, kind):
    if value is None:
        return []
    if kind.endswith("[]"):
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise AppError("PLAN_OUTPUT_TYPE_MISMATCH", "Media arrays require artifact IDs", 422)
        return value
    if not isinstance(value, str):
        raise AppError("PLAN_OUTPUT_TYPE_MISMATCH", "Media inputs require artifact IDs", 422)
    return [value]


def input_fingerprints(run, data, spec):
    result = {}
    for field, kind in spec.io_types.get("inputs", {}).items():
        if kind.removesuffix("[]") in MEDIA_TYPES:
            for artifact_id in _ids(data.get(field), kind):
                result[artifact_id] = fingerprint(run, artifact_id, kind.removesuffix("[]"))
    # Transform media is a typed object array rather than an IoType array.
    for media in data.get("media", []) if spec.name == "transform_video" else []:
        artifact_id = media.get("artifact_id")
        if artifact_id:
            kind = {"reference_image": "image", "reference_video": "video", "reference_audio": "audio", "file": "document"}.get(media.get("type"))
            result[artifact_id] = fingerprint(run, artifact_id, kind)
    return result


def resolve_node(run, node, version, outputs, registry, *, choice_receipt=None):
    from app.plans.compiler import node_inputs, resolve_inputs
    spec = registry.get(node["tool"])
    resolved = resolve_inputs(node_inputs(node, plan_version=version), outputs)
    data = registry._validate_input(spec, resolved).model_dump(mode="json")
    sources = input_fingerprints(run, data, spec)
    if node["tool"] == "select_image":
        from app.plans.choices import resolved_selection
        data["selected_artifact_id"] = resolved_selection(run, node, version, data, sources, receipt=choice_receipt)
    digest = inputs_hash({"tool": node["tool"], "inputs": data, "sources": sources})
    return data, sources, digest


def validate_outputs(run, task, spec, output):
    result = deepcopy(output or {})
    artifacts = {}
    for field, kind in spec.io_types.get("outputs", {}).items():
        if field not in result:
            raise AppError("PLAN_OUTPUT_MISSING", "A required named output is missing", 502)
        if result[field] is None and field == "compressed_artifact_id" and not task.inputs.get("compress_output"):
            continue
        if spec.name == "run_workflow_template" and result[field] in ([], None):
            from app.plans.workflow import produced_outputs
            if field not in produced_outputs(task.inputs):
                continue
        if kind.removesuffix("[]") in MEDIA_TYPES:
            values = _ids(result[field], kind)
            if kind.endswith("[]") and not values:
                raise AppError("PLAN_OUTPUT_MISSING", "An output media array is empty", 502)
            for artifact_id in values:
                record = fingerprint(run, artifact_id, kind.removesuffix("[]"))
                expected = task.state.get("output_metadata", {}).get(field, {})
                if kind == "video" and expected.get("duration_sec") is not None:
                    from app.services.media_probe_service import MediaProbeService
                    from app.plans.measured_duration import measurement_allowance
                    artifact = artifact_for_run(run, artifact_id, "video")
                    duration = float(expected["duration_sec"])
                    media = MediaProbeService.probe(StorageService.resolve(artifact.file_path),
                        decode=True, mock_duration_sec=duration)
                    count = len(task.inputs["video_artifact_ids"]) if spec.name == "compose_video" else 1
                    allowance = measurement_allowance([(count, media.get("fps"))])
                    actual = media.get("duration_sec")
                    if (isinstance(actual, bool) or not isinstance(actual, (int, float))
                            or not math.isfinite(actual) or actual <= 0
                            or actual > duration + allowance["measurement_error_sec"] + 1e-6):
                        raise AppError("PLAN_OUTPUT_DURATION_EXCEEDED", "Output video exceeds its approved duration bound", 422,
                            payload={"approved_duration_sec": duration, "measured_duration_sec": actual, **allowance})
                    if fingerprint(run, artifact_id, "video") != record:
                        raise AppError("PLAN_INPUT_CHANGED", "Output video changed during measurement", 409)
                    artifact.meta = {**deepcopy(artifact.meta or {}), "plan_output": {"duration_sec": duration,
                        "task_id": task.id, "run_id": run.run_id, "mock": bool(media.get("mock"))}}
                artifacts[artifact_id] = record
    if spec.name == "generate_image":
        count = task.inputs.get("n") or task.inputs.get("params", {}).get("n", 1)
        if len(result.get("images", [])) != count or result.get("image") != result["images"][0]:
            raise AppError("PLAN_OUTPUT_COUNT_MISMATCH", "Image outputs differ from the approved count", 502)
    if spec.name == "qc_video" and result.get("passed") is not True:
        raise AppError("PLAN_QC_FAILED", "The video did not pass structural quality checks", 422)
    if spec.name == "select_image":
        from app.plans.choices import receipt_for_task
        receipt = receipt_for_task(run, task)
        if result != {"image": receipt["selected_artifact_id"]}:
            raise AppError("INVALID_CHOICE", "Choice output differs from the approved image", 409)
    return result, artifacts


def complete(run, task, spec, output):
    result, fingerprints = validate_outputs(run, task, spec, output)
    task.output = result
    task.artifact_ids = list(fingerprints)
    task.state = {**(task.state or {}), "output_fingerprints": fingerprints}
    task.status, task.error = "success", None
    db.session.commit()


def job_outputs(run, task, spec, job):
    if task.job_id != job.job_id or (job.config or {}).get("skill", {}).get("budget_scope") != run.run_id:
        raise AppError("PLAN_OUTPUT_SCOPE_MISMATCH", "Output Job does not belong to this node", 403)
    invocation = ToolInvocation.query.filter_by(invocation_id=task.invocation_id, budget_scope=run.run_id).first()
    if not invocation or invocation.job_id != job.id:
        raise AppError("PLAN_OUTPUT_SCOPE_MISMATCH", "Output Job has no matching invocation", 403)
    if spec.name == "run_workflow_template":
        from app.plans.workflow import job_outputs as workflow_outputs
        return workflow_outputs(task, job)
    artifact_type = ASYNC_OUTPUTS.get(spec.name)
    if spec.name == "generate_video":
        artifact_type = {"t2v": "t2v_video", "i2v": "i2v_video", "r2v": "r2v_flash_video"}[task.inputs["mode"]]
    if artifact_type is None:
        return deepcopy(invocation.output_payload or {})
    rows = Artifact.query.filter_by(job_id=job.id, artifact_type=artifact_type).order_by(Artifact.id).all()
    ids = [item.artifact_id for item in rows]
    if spec.name == "generate_image":
        if not ids:
            raise AppError("PLAN_OUTPUT_MISSING", "Completed image Job has no image outputs", 502)
        return {"image": ids[0], "images": ids}
    if len(ids) != 1:
        raise AppError("PLAN_OUTPUT_COUNT_MISMATCH", "Completed video Job must contain exactly one output", 502)
    return {"video": ids[0]}


def usable(run, task):
    if not task or task.status != "success":
        return False
    expected = (task.state or {}).get("output_fingerprints", {})
    if set(expected) != set(task.artifact_ids or []):
        return False
    try:
        if task.state.get("tool") == "select_image":
            from app.plans.choices import receipt_for_task
            receipt_for_task(run, task)
        return all(fingerprint(run, artifact_id) == record for artifact_id, record in expected.items())
    except (AppError, OSError, ValueError):
        return False


def reusable(run, task):
    rows = PlanNodeTask.query.filter_by(run_id=run.run_id, inputs_hash=task.inputs_hash, status="success").filter(
        PlanNodeTask.id != task.id).order_by(PlanNodeTask.id.desc()).all()
    return next((row for row in rows if row.state.get("tool") == task.state.get("tool") and usable(run, row)), None)


def reuse(task, previous):
    task.output, task.artifact_ids = deepcopy(previous.output), deepcopy(previous.artifact_ids)
    task.state = {**task.state, "output_fingerprints": deepcopy(previous.state.get("output_fingerprints", {})),
                  "reused_from": previous.id}
    task.invocation_id, task.job_id = previous.invocation_id, previous.job_id
    task.status, task.estimated_cost = "success", 0.0
    db.session.commit()


def carry_forward(task, previous, *, retained_by_only=False):
    """Copy immutable evidence into a new version without pretending it reran."""
    original, seen = previous, set()
    while original.state.get("reused_from") and original.id not in seen:
        seen.add(original.id)
        source = db.session.get(PlanNodeTask, original.state["reused_from"])
        if source is None or source.run_id != previous.run_id or source.output != previous.output:
            break
        original = source
    task.inputs_hash, task.inputs = previous.inputs_hash, deepcopy(previous.inputs)
    task.output, task.artifact_ids = deepcopy(previous.output), deepcopy(previous.artifact_ids)
    state = deepcopy(previous.state or {})
    state.update(patch_id=task.state["patch_id"], force_execute=False, reused_from=previous.id,
        source_task_id=state.get("source_task_id", original.id),
        source_plan_version=state.get("source_plan_version", original.plan_version),
        source_node_id=state.get("source_node_id", original.node_id),
        retained_by_only=bool(retained_by_only or state.get("retained_by_only")),
        continuity_risk_accepted=bool(retained_by_only or state.get("continuity_risk_accepted")))
    task.state = state
    task.invocation_id, task.job_id = previous.invocation_id, previous.job_id
    task.status, task.error = previous.status, deepcopy(previous.error)
    task.attempt, task.estimated_cost = previous.attempt, 0.0


def failure(error, *, known_not_submitted=False):
    code = getattr(error, "code", "PLAN_EXECUTION_FAILED")
    category = "qc_failed" if code == "PLAN_QC_FAILED" else "invalid_parameters" if (
        code.startswith("PLAN_OUTPUT") or code in {"INVALID_INPUT", "INVALID_REFERENCE", "MODEL_PRICE_CHANGED",
        "PLAN_INPUT_CHANGED", "MODEL_CAPABILITY_MISMATCH", "PLAN_ARTIFACT_UNAVAILABLE"}) else "permanent"
    return {"category": category if known_not_submitted else "submit_unknown", "code": code,
            "summary": "Node execution stopped; inspect its saved receipt.", "stage": "local" if known_not_submitted else "submit",
            "submission_state": "not_submitted" if known_not_submitted else "unknown", "provider_task_id": None,
            "recovery_action": "replan" if known_not_submitted and category in {"invalid_parameters", "qc_failed"} else "stop"}
