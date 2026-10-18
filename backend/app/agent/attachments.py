"""Validated, owner-scoped uploads shared by Agent input and remix."""

from pathlib import Path
import warnings

from flask import current_app
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_

from app.api import AppError
from app.extensions import db
from app.models import Artifact, Job
from app.services.artifact_service import ArtifactService
from app.services.job_service import JobService
from app.services.storage_service import StorageService
from app.services.video_media_service import VideoMediaService
from app.services.wan3_media_service import Wan3MediaService, MIMES
from app.skills.job_backed import ensure_agent_template, node_selection
from app.utils.ids import new_id

IMAGE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
AUDIO_SUFFIXES = {".wav", ".mp3"}
FILE_SUFFIXES = {".txt", ".md", ".pdf"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
              ".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska", ".webm": "video/webm"}


def invalid_attachment(reason: str) -> AppError:
    return AppError("INVALID_ATTACHMENT", "Invalid Agent attachment", 422, payload={"reason": reason})


def attachment_for_owner(artifact_id: str, owner_id: str, *, run_id: str | None = None) -> Artifact:
    artifact = Artifact.query.filter_by(artifact_id=artifact_id).first()
    if (not artifact or artifact.artifact_type not in {"agent_attachment_image", "source_video", "agent_reference_image",
                "agent_attachment_audio", "agent_attachment_document", "agent_reference_document"}
            or artifact.job.strategy != "agent_upload"):
        raise AppError("ATTACHMENT_NOT_FOUND", "Attachment not found", 404)
    require_upload_job_owner(artifact.job, owner_id)
    if (artifact.artifact_type in {"agent_reference_image", "agent_reference_document"}
            and (not run_id or (artifact.meta or {}).get("reference", {}).get("run_id") != run_id)):
        raise AppError("ATTACHMENT_NOT_FOUND", "Reference image is not part of this run", 404)
    path = StorageService.resolve(artifact.file_path)
    if not path.resolve().is_relative_to(StorageService.root()) or not path.is_file():
        raise AppError("ATTACHMENT_NOT_FOUND", "Attachment not found", 404)
    return artifact


def is_private_agent_job(job: Job) -> bool:
    return job.strategy == "agent_upload" or any((job.config or {}).get(key) for key in ("agent_story_preview", "agent_story_production", "agent_transform", "agent_plan", "agent_plan_preview"))


def require_upload_job_owner(job: Job, owner_id: str) -> None:
    """Keep classic artifacts public while protecting Agent uploads/previews."""
    preview = ((job.config or {}).get("agent_story_preview") or (job.config or {}).get("agent_story_production")
               or (job.config or {}).get("agent_transform") or (job.config or {}).get("agent_plan")
               or (job.config or {}).get("agent_plan_preview"))
    if preview:
        from app.models import AgentRun
        run = AgentRun.query.filter_by(run_id=preview.get("run_id"), owner_id=owner_id).first()
        if not run or (job.config or {}).get("skill", {}).get("budget_scope") != run.run_id:
            raise AppError("ARTIFACT_NOT_FOUND", "Preview not found", 404)
    if job.strategy == "agent_upload" and (job.config or {}).get("agent_upload_owner") != owner_id:
        raise AppError("ATTACHMENT_NOT_FOUND", "Attachment not found", 404)


def validate_job_attachment_sources(data: dict, owner_id: str) -> None:
    """Prevent classic Job imports from republishing another user's upload."""
    for value in (data.get("initial_artifacts") or {}).values():
        for artifact in JobService._iter_existing_artifacts(value):
            require_upload_job_owner(artifact.job, owner_id)
            if artifact.artifact_type in {"agent_reference_image", "agent_reference_document"}:
                raise AppError("ATTACHMENT_NOT_FOUND", "Reference image requires its owning Agent run", 404)
    if data.get("source_video_path"):
        target = StorageService.resolve(data["source_video_path"]).resolve()
        # Download receipts also contain private bytes before artifact registration.
        if any(target.is_relative_to(StorageService.root() / "agent" / child) for child in ("references", "frames", "delivery", "plans")):
            raise AppError("ATTACHMENT_NOT_FOUND", "Reference image requires its owning Agent run", 404)
        candidates = Artifact.query.join(Job).filter(or_(Job.strategy == "agent_upload",
            Job.config["agent_story_preview"]["run_id"].as_string().is_not(None),
            Job.config["agent_story_production"]["run_id"].as_string().is_not(None),
            Job.config["agent_transform"]["run_id"].as_string().is_not(None),
            Job.config["agent_plan"].as_string().is_not(None),
            Job.config["agent_plan_preview"].as_string().is_not(None)),
            func.lower(Artifact.file_path).endswith(target.name.lower(), autoescape=True)).all()
        for artifact in candidates:
            if StorageService.resolve(artifact.file_path).resolve() == target:
                require_upload_job_owner(artifact.job, owner_id)
                if artifact.artifact_type in {"agent_reference_image", "agent_reference_document"}:
                    raise AppError("ATTACHMENT_NOT_FOUND", "Reference image requires its owning Agent run", 404)


def describe_attachment(artifact: Artifact) -> dict:
    media = artifact.meta["media"]
    return {"attachment_id": artifact.artifact_id, "kind": media["kind"],
            "file_name": artifact.file_name, "mime_type": artifact.mime_type, "size": artifact.size,
            "width": media["width"], "height": media["height"], "duration": media["duration"],
            "preview_url": f"/api/artifacts/{artifact.artifact_id}/preview"}


def _inspect_image(path: Path, suffix: str) -> dict:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format != IMAGE_FORMATS[suffix]:
                    raise invalid_attachment("Image format does not match its supported extension")
                image.verify()
            with Image.open(path) as image:
                image.load()
                width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise invalid_attachment("Image cannot be decoded safely") from error
    if min(width, height) < 256:
        raise invalid_attachment("Image width and height must each be at least 256 pixels")
    return {"kind": "image", "width": width, "height": height, "duration": None, "fps": None}


def _inspect_video(path: Path) -> dict:
    try:
        video = VideoMediaService.inspect(path)
    except AppError as error:
        if error.status_code != 422:
            raise
        raise invalid_attachment(str(error)) from error
    if video["duration"] > current_app.config["AGENT_MAX_VIDEO_SEC"]:
        raise invalid_attachment("Video exceeds the configured duration limit")
    return {"kind": "video", "width": video["width"], "height": video["height"],
            "duration": video["duration"], "fps": video.get("fps")}


def upload_attachment(file, owner_id: str) -> dict:
    suffix = Path(file.filename or "").suffix.lower() if file else ""
    if suffix not in set(IMAGE_FORMATS) | VIDEO_SUFFIXES | AUDIO_SUFFIXES | FILE_SUFFIXES:
        raise invalid_attachment("Upload a supported image/video, WAV/MP3 audio or TXT/MD/PDF document")
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    limit = current_app.config["MAX_CONTENT_LENGTH"]
    if suffix in IMAGE_FORMATS:
        limit = min(limit, current_app.config["AGENT_MAX_IMAGE_MB"] * 1024 * 1024)
    if suffix in AUDIO_SUFFIXES | FILE_SUFFIXES:
        limit = min(limit, (15 if suffix in AUDIO_SUFFIXES else 100) * 1024 * 1024)
    if not size or size > limit:
        raise invalid_attachment("Attachment is empty or exceeds the configured size limit")

    saved = StorageService.save_source_video(file, new_id("attachment"))
    path = StorageService.resolve(saved["file_path"])
    try:
        if suffix in AUDIO_SUFFIXES | FILE_SUFFIXES:
            try:
                verified = Wan3MediaService.inspect(path, "audio" if suffix in AUDIO_SUFFIXES else "file")
            except AppError as error:
                if error.status_code != 422:
                    raise
                raise invalid_attachment(error.payload.get("reason", str(error))) from error
            media = {**verified, "duration": verified["duration_sec"], "sha256": saved["source_hash"]}
            media.pop("duration_sec")
        else:
            media = _inspect_image(path, suffix) if suffix in IMAGE_FORMATS else _inspect_video(path)
        template = ensure_agent_template()
        job = JobService.create_job({"template_id": template.template_id, "strategy": "agent_upload",
            **node_selection([]), "job_config": {"agent_upload_owner": owner_id},
            **({"source_video_path": str(path)} if media["kind"] == "video" else {})}, commit=False)
        if media["kind"] == "video":
            artifact = ArtifactService.latest_for_job(job, "source_video")
            # Retain the metadata consumed by existing remix tools and v1 runs.
            artifact.meta = {**artifact.meta, "video": {key: media[key] for key in ("duration", "width", "height")}}
            job.source_file_name = saved["file_name"]
        else:
            artifact_type = {"image": "agent_attachment_image", "audio": "agent_attachment_audio",
                             "file": "agent_attachment_document"}[media["kind"]]
            artifact = ArtifactService.register_artifact(job, saved["file_path"], artifact_type)
        artifact.file_name = saved["file_name"]
        # OS MIME registries can omit supported types such as WebP on Windows.
        artifact.mime_type = MIME_TYPES.get(suffix) or MIMES[suffix]
        artifact.meta = {**artifact.meta, "media": media}
        job.status = "success"
        result = describe_attachment(artifact)
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        path.unlink(missing_ok=True)
        raise
