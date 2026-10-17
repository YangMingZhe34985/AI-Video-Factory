"""Owned source uploads and validated source references for Agent remix runs."""

from pathlib import Path

from app.agent.attachments import VIDEO_SUFFIXES, attachment_for_owner, upload_attachment
from app.api import AppError
from app.models import AgentRun, Artifact
from app.services.storage_service import StorageService


def source_for_owner(artifact_id: str, owner_id: str) -> Artifact:
    artifact = Artifact.query.filter_by(artifact_id=artifact_id, artifact_type="source_video").first()
    if artifact and artifact.job.strategy == "agent_upload":
        try:
            return attachment_for_owner(artifact_id, owner_id)
        except AppError as error:
            raise AppError("SOURCE_NOT_FOUND", "Source video not found", 404) from error
    if not artifact or (artifact.job.config or {}).get("agent_source_owner") != owner_id:
        raise AppError("SOURCE_NOT_FOUND", "Source video not found", 404)
    if not StorageService.resolve(artifact.file_path).is_file():
        raise AppError("SOURCE_NOT_FOUND", "Source video file is missing", 404)
    return artifact


def source_for_run(run: AgentRun) -> Artifact:
    if run.request.get("schema_version", 1) == 2:
        spec = (run.snapshot or {}).get("request_spec") or {}
        sources = [item["attachment_id"] for item in spec.get("attachments", [])
                   if item.get("role") == "remix_source" and item.get("kind") == "video"]
        if spec.get("recipe_hint") != "remix" or len(sources) != 1:
            raise AppError("INVALID_SOURCE", "This run has no unique remix source", 422)
        return source_for_owner(sources[0], run.owner_id)
    if run.request.get("mode") != "remix":
        raise AppError("INVALID_SOURCE", "This run is not a remix", 422)
    return source_for_owner(run.request["source_artifact_id"], run.owner_id)


def describe_source(artifact: Artifact) -> dict:
    return {"artifact_id": artifact.artifact_id, "file_name": artifact.file_name,
            **artifact.meta["video"], "preview_url": f"/api/artifacts/{artifact.artifact_id}/preview"}


def upload_source(file, owner_id: str) -> dict:
    if not file or Path(file.filename or "").suffix.lower() not in VIDEO_SUFFIXES:
        raise AppError("INVALID_SOURCE", "Upload an MP4, MOV, MKV or WebM video", 422)
    try:
        uploaded = upload_attachment(file, owner_id)
    except AppError as error:
        if error.code == "INVALID_ATTACHMENT":
            raise AppError("INVALID_SOURCE", error.payload["reason"], 422) from error
        raise
    return describe_source(attachment_for_owner(uploaded["attachment_id"], owner_id))
