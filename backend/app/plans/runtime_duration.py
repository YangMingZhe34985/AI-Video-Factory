"""Verify approved delivery duration from owned, unchanged final media."""
import math

from app.api import AppError
from app.plans import execution
from app.plans.duration import duration_targets
from app.plans.measured_duration import measured_details, segment_count
from app.services.media_probe_service import MediaProbeService
from app.services.storage_service import StorageService


def _failure(message, *, details=None):
    return AppError("PLAN_QC_FAILED", message, 422, payload=details)


def _target_artifact(run, target, tasks, receipt):
    if set(target) == {"artifact"}:
        artifact_id = target["artifact"]
        expected = receipt.get("source_fingerprints", {}).get(artifact_id)
    elif set(target) == {"ref"}:
        node_id, field = target["ref"].split(".", 1)
        task = tasks.get(node_id)
        if task is None or not execution.usable(run, task):
            raise _failure("A final video has no valid completed output")
        artifact_id = (task.output or {}).get(field)
        expected = (task.state or {}).get("output_fingerprints", {}).get(artifact_id)
    else:
        raise _failure("A final video has no verifiable media reference")
    if not isinstance(artifact_id, str) or not artifact_id or not expected:
        raise _failure("A final video has no approved artifact fingerprint")
    return artifact_id, expected


def check_delivery_duration(run, plan, tasks, receipt):
    """A missing legacy constraint remains a no-op; all new checks fail closed."""
    constraint = plan.get("duration_constraint")
    if constraint is None:
        return None
    try:
        targets = duration_targets(plan)
        if not targets:
            raise _failure("The approved duration has no measurable final video")
        total, observations = 0.0, []
        for target in targets:
            artifact_id, expected = _target_artifact(run, target, tasks, receipt)
            artifact = execution.artifact_for_run(run, artifact_id, "video")
            before = execution.fingerprint(run, artifact_id, "video")
            if before != expected:
                raise _failure("A final video changed after its approved output was recorded")
            metadata = artifact.meta or {}
            hint = metadata.get("plan_output", {}).get("duration_sec")
            if hint is None:
                source = metadata.get("media") or {}
                hint = source.get("duration_sec", source.get("duration"))
            media = MediaProbeService.probe(StorageService.resolve(artifact.file_path),
                decode=True, mock_duration_sec=hint)
            seconds = media.get("duration_sec")
            if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                    or not math.isfinite(seconds) or seconds <= 0):
                raise _failure("A final video has no measurable positive duration")
            if execution.fingerprint(run, artifact_id, "video") != before:
                raise _failure("A final video changed during the duration check")
            total += seconds
            observations.append((segment_count(plan, target), media.get("fps")))
        details = measured_details(total, constraint, observations)
        if not details["passed"]:
            raise _failure("Measured delivery duration does not meet the approved user target", details=details)
        return details
    except AppError as error:
        if error.code == "PLAN_QC_FAILED":
            raise
        raise _failure("The final video duration could not be verified") from error
    except (KeyError, TypeError, ValueError, OSError, OverflowError) as error:
        raise _failure("The final video duration could not be verified") from error
