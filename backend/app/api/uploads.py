import json
from http import HTTPStatus

from flask import Blueprint, request

from app.api import AppError, api_success
from app.extensions import db
from app.schemas.artifact_schema import RegisterUploadArtifactSchema
from app.services.artifact_service import ArtifactService
from app.services.job_service import JobService
from app.services.storage_service import StorageService


bp = Blueprint("uploads", __name__, url_prefix="/api")


def _metadata() -> dict:
    raw = request.form.get("metadata")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise AppError("INVALID_INPUT", "metadata must be valid JSON", 422)


@bp.post("/jobs/<job_id>/uploads/reference-images")
def upload_reference_images(job_id: str):
    job = JobService.get_job(job_id)
    files = request.files.getlist("files") or request.files.getlist("reference_images")
    single = request.files.get("file")
    if single:
        files.append(single)
    if not files:
        raise AppError("INVALID_INPUT", "No files uploaded", 400)

    payload = RegisterUploadArtifactSchema.model_validate(
        {
            "artifact_type": request.form.get("artifact_type") or "reference_image",
            "branch_key": request.form.get("branch_key") or "reference",
            "metadata": _metadata(),
        }
    )
    artifacts = []
    for item in files:
        saved = StorageService.save_reference_upload(item, job.job_id)
        artifact = ArtifactService.register_artifact(
            job,
            saved["file_path"],
            payload.artifact_type,
            branch_key=payload.branch_key,
            metadata=payload.metadata,
        )
        artifacts.append(artifact.to_dict())
    db.session.commit()
    return api_success({"artifacts": artifacts}, HTTPStatus.CREATED)
