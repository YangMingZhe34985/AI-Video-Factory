"""Owned source uploads and validated source references for Agent remix runs."""

from pathlib import Path

from app.api import AppError
from app.extensions import db
from app.models import AgentRun, Artifact
from app.services.artifact_service import ArtifactService
from app.services.job_service import JobService
from app.services.storage_service import StorageService
from app.services.video_media_service import VideoMediaService
from app.skills.job_backed import ensure_agent_template, node_selection
from app.utils.ids import new_id


def source_for_owner(artifact_id: str, owner_id: str) -> Artifact:
    artifact = Artifact.query.filter_by(artifact_id=artifact_id, artifact_type="source_video").first()
    if not artifact or (artifact.job.config or {}).get("agent_source_owner") != owner_id:
        raise AppError("SOURCE_NOT_FOUND", "Source video not found", 404)
    if not StorageService.resolve(artifact.file_path).is_file():
        raise AppError("SOURCE_NOT_FOUND", "Source video file is missing", 404)
    return artifact


def source_for_run(run: AgentRun) -> Artifact:
    if run.request.get("mode") != "remix":
        raise AppError("INVALID_SOURCE", "This run is not a remix", 422)
    return source_for_owner(run.request["source_artifact_id"], run.owner_id)


def describe_source(artifact: Artifact) -> dict:
    return {"artifact_id": artifact.artifact_id, "file_name": artifact.file_name,
            **artifact.meta["video"], "preview_url": f"/api/artifacts/{artifact.artifact_id}/preview"}


def upload_source(file, owner_id: str) -> dict:
    if not file or Path(file.filename or "").suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise AppError("INVALID_SOURCE", "Upload an MP4, MOV, MKV or WebM video", 422)
    saved = StorageService.save_source_video(file, new_id("source"))
    path = StorageService.resolve(saved["file_path"])
    try:
        video = VideoMediaService.inspect(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    template = ensure_agent_template()
    job = JobService.create_job({"template_id": template.template_id, "strategy": "agent_source",
                                 **node_selection([]), "source_video_path": str(path),
                                 "job_config": {"agent_source_owner": owner_id}})
    artifact = ArtifactService.latest_for_job(job, "source_video")
    artifact.file_name = saved["file_name"]
    job.source_file_name = saved["file_name"]
    artifact.meta = {**artifact.meta, "video": video}
    job.status = "success"
    db.session.commit()
    return describe_source(artifact)
