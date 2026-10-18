from pathlib import Path

from flask import Blueprint, current_app, request, send_file
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app.agent.attachments import is_private_agent_job, require_upload_job_owner
from app.api import AppError, api_success
from app.services.artifact_service import ArtifactService
from app.services.job_service import JobService
from app.services.storage_service import StorageService


bp = Blueprint("artifacts", __name__, url_prefix="/api")


def _owner():
    return get_jwt_identity() if current_app.config.get("API_AUTH_REQUIRED", True) else "local"


def _readable_artifact(artifact_id):
    artifact = ArtifactService.get_by_artifact_id(artifact_id)
    if is_private_agent_job(artifact.job):
        # Classic previews remain public; user-supplied Agent attachments do not.
        if current_app.config.get("API_AUTH_REQUIRED", True):
            verify_jwt_in_request()
        require_upload_job_owner(artifact.job, _owner())
    return artifact


@bp.get("/jobs/<job_id>/artifacts")
def list_job_artifacts(job_id: str):
    job = JobService.get_job(job_id)
    include_history = str(request.args.get("include_history") or "").lower() in {
        "1",
        "true",
        "yes",
    }
    return api_success(
        {"artifacts": ArtifactService.list_for_job(job, include_history=include_history, agent_upload_owner=_owner())}
    )


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
        agent_upload_owner=_owner(),
    )
    return api_success({"artifacts": artifacts, "total": len(artifacts)})


@bp.get("/artifacts/<artifact_id>/download")
def download_artifact(artifact_id: str):
    artifact = _readable_artifact(artifact_id)
    path = StorageService.resolve(artifact.file_path)
    if not path.exists():
        raise AppError("ARTIFACT_NOT_FOUND", "Artifact file not found", 404)
    return send_file(path, as_attachment=True, download_name=artifact.file_name)


@bp.get("/artifacts/<artifact_id>/preview")
def preview_artifact(artifact_id: str):
    artifact = _readable_artifact(artifact_id)
    path = StorageService.resolve(artifact.file_path)
    if not path.exists():
        raise AppError("ARTIFACT_NOT_FOUND", "Artifact file not found", 404)
    return send_file(Path(path), mimetype=artifact.mime_type, as_attachment=False)
