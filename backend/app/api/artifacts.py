from pathlib import Path

from flask import Blueprint, request, send_file

from app.api import AppError, api_success
from app.services.artifact_service import ArtifactService
from app.services.job_service import JobService
from app.services.storage_service import StorageService


bp = Blueprint("artifacts", __name__, url_prefix="/api")


@bp.get("/jobs/<job_id>/artifacts")
def list_job_artifacts(job_id: str):
    job = JobService.get_job(job_id)
    return api_success({"artifacts": ArtifactService.list_for_job(job)})


@bp.get("/artifacts")
def list_artifacts():
    artifacts = ArtifactService.search_artifacts(
        job_id=request.args.get("job_id"),
        template_id=request.args.get("template_id"),
        template_name=request.args.get("template_name"),
        artifact_type=request.args.get("artifact_type"),
        branch_key=request.args.get("branch_key"),
        search=request.args.get("search"),
        series_id=request.args.get("series_id"),
    )
    return api_success({"artifacts": artifacts, "total": len(artifacts)})


@bp.get("/artifacts/<artifact_id>/download")
def download_artifact(artifact_id: str):
    artifact = ArtifactService.get_by_artifact_id(artifact_id)
    path = StorageService.resolve(artifact.file_path)
    if not path.exists():
        raise AppError("ARTIFACT_NOT_FOUND", "Artifact file not found", 404)
    return send_file(path, as_attachment=True, download_name=artifact.file_name)


@bp.get("/artifacts/<artifact_id>/preview")
def preview_artifact(artifact_id: str):
    artifact = ArtifactService.get_by_artifact_id(artifact_id)
    path = StorageService.resolve(artifact.file_path)
    if not path.exists():
        raise AppError("ARTIFACT_NOT_FOUND", "Artifact file not found", 404)
    return send_file(Path(path), mimetype=artifact.mime_type, as_attachment=False)
