"""Server-owned delivery approval and immutable source/output provenance."""
from flask import current_app

from app.agent import plan_versions as versions
from app.agent.attachments import require_upload_job_owner
from app.agent.search.scope import require_run
from app.api import AppError
from app.models import Artifact
from app.services.generation_outputs import digest
from app.services.storage_service import StorageService


def resolve_source(artifact):
    """Prefer a recorded original; a missing original never falls back to its proxy."""
    registered = StorageService.resolve(artifact.file_path).resolve()
    compression = (artifact.meta or {}).get("compression") or {}
    original = compression.get("original_file_path")
    source = StorageService.resolve(original).resolve() if original else registered
    if (not registered.is_relative_to(StorageService.root()) or not source.is_relative_to(StorageService.root())
            or (original and source.parent != registered.parent)):
        raise AppError("INVALID_REFERENCE", "Media source is outside its managed location", 422)
    if not source.is_file() or not source.stat().st_size:
        raise AppError("VIDEO_INCOMPLETE", "An approved original video is missing or empty", 409)
    return source


def approved_sources(run, version):
    if isinstance(version, int):
        version = versions.require_current_version(run, version)
    else:
        versions.require_current_version(run, version.version)
    production = (run.snapshot or {}).get("production") or {}
    if production.get("approved_version") != version.version:
        raise AppError("PLAN_VERSION_CONFLICT", "Delivery requires the current approved production version", 409)
    result = []
    for shot in version.plan["shots"]:
        task = versions.latest_task(run, version.version, "video", shot["shot_id"])
        if not task or task.status != "success" or len(task.artifact_ids or []) != 1:
            raise AppError("VIDEO_INCOMPLETE", "All approved shots must have one successful video", 409)
        artifact = Artifact.query.filter_by(artifact_id=task.artifact_ids[0]).first()
        if not artifact or not artifact.job or not str(artifact.mime_type or "").startswith("video/"):
            raise AppError("VIDEO_INCOMPLETE", "An approved video artifact is unavailable", 409)
        config = artifact.job.config or {}
        marker = config.get("agent_story_production") or {}
        if marker.get("run_id") != run.run_id or config.get("skill", {}).get("budget_scope") != run.run_id:
            raise AppError("INVALID_REFERENCE", "Approved source does not belong to this Run", 422)
        require_upload_job_owner(artifact.job, run.owner_id)
        resolve_source(artifact)
        result.append((shot, task, artifact))
    if not result:
        raise AppError("VIDEO_INCOMPLETE", "No approved shots are available", 409)
    return result


def require_delivery_authorization(ctx, plan_version=None):
    if not current_app.config.get("AGENT_STORY_DELIVERY_ENABLED"):
        raise AppError("DELIVERY_DISABLED", "Story delivery is disabled", 409)
    server_version = getattr(ctx, "delivery_version", None)
    if not isinstance(server_version, int) or isinstance(server_version, bool):
        raise AppError("TOOL_FORBIDDEN", "Delivery requires server-owned approval", 403)
    run = require_run(ctx)
    version = versions.require_current_version(run, server_version)
    delivery = (run.snapshot or {}).get("delivery") or {}
    if (plan_version is not None and plan_version != server_version) or (delivery.get("authorized") is not True
            or delivery.get("plan_version") != server_version or delivery.get("approved_version") != server_version):
        raise AppError("PLAN_VERSION_CONFLICT", "Delivery approval no longer matches the current plan", 409)
    sources = approved_sources(run, version)
    compressed = ((run.snapshot or {}).get("request_spec") or {}).get("constraints", {}).get("compress_output") is True
    payload = {"plan_version": server_version, "video_artifact_ids": [item[2].artifact_id for item in sources],
               "compress_output": compressed}
    if (delivery.get("source_artifact_ids") != payload["video_artifact_ids"]
            or delivery.get("compress_output") is not compressed
            or delivery.get("inputs_hash") != versions.inputs_hash(payload)
            or delivery.get("source_sha256") != source_hashes(sources)):
        raise AppError("PLAN_VERSION_CONFLICT", "Delivery sources or settings changed after approval", 409)
    return run, version


def source_hashes(sources):
    return [digest(resolve_source(item[2])) for item in sources]


def resolve_delivery_artifact(run, version, artifact_id, *, kind="master"):
    version = versions.require_current_version(run, version.version if hasattr(version, "version") else version)
    delivery = (run.snapshot or {}).get("delivery") or {}
    output = delivery.get("composition") or {}
    field = "artifact_id" if kind == "master" else "compressed_artifact_id"
    if kind not in {"master", "compressed"} or not artifact_id or output.get(field) != artifact_id:
        raise AppError("INVALID_REFERENCE", "Media is not this approved delivery rendition", 422)
    artifact = Artifact.query.filter_by(artifact_id=artifact_id).first()
    if not artifact or not artifact.job:
        raise AppError("DELIVERY_INCOMPLETE", "Delivery media is missing", 409)
    config = artifact.job.config or {}
    marker = config.get("agent_story_production") or {}
    meta = (artifact.meta or {}).get("composition") or {}
    sources = approved_sources(run, version)
    if (marker.get("run_id") != run.run_id or marker.get("plan_version") != version.version
            or marker.get("target_type") != "delivery" or config.get("skill", {}).get("budget_scope") != run.run_id
            or meta.get("plan_version") != version.version or meta.get("input_hash") != delivery.get("inputs_hash")
            or meta.get("source_artifact_ids") != [item[2].artifact_id for item in sources]
            or meta.get("source_sha256") != source_hashes(sources) or (artifact.meta or {}).get("rendition") != kind):
        raise AppError("INVALID_REFERENCE", "Delivery source manifest does not match approved media", 422)
    require_upload_job_owner(artifact.job, run.owner_id)
    path = resolve_source(artifact)
    if digest(path) != meta.get("master_sha256" if kind == "master" else "compressed_sha256"):
        raise AppError("DELIVERY_INCOMPLETE", "Delivery media changed after composition", 409)
    return artifact
