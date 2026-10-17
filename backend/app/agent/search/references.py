"""Validated reference images with Run-scoped receipts and content deduplication."""

from hashlib import sha256
from io import BytesIO
import json
import warnings

from flask import current_app
from PIL import Image, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError

from app.agent.attachments import attachment_for_owner
from app.agent.search.fetch import fetch_resource
from app.agent.search.scope import require_allowed_url
from app.api import AppError
from app.extensions import db
from app.models import Artifact, ToolInvocation
from app.services.artifact_service import ArtifactService
from app.services.job_service import JobService
from app.services.storage_service import StorageService
from app.skills.job_backed import ensure_agent_template, node_selection
from app.utils.ids import new_id
from app.utils.time_utils import utc_now

IMAGE_TYPES = {"image/jpeg": ("JPEG", ".jpg"), "image/png": ("PNG", ".png"), "image/webp": ("WEBP", ".webp")}


def reference_for_run(reference_id, run):
    artifact = attachment_for_owner(reference_id, run.owner_id, run_id=run.run_id)
    if artifact.artifact_type != "agent_reference_image":
        raise AppError("ATTACHMENT_NOT_FOUND", "Reference image not found", 404)
    return artifact


def _invalid(reason):
    return AppError("INVALID_REFERENCE_IMAGE", "Invalid reference image", 422, payload={"reason": reason})


def _limit():
    return int(current_app.config["AGENT_REFERENCE_MAX_MB"] * 1024 * 1024)


def inspect_reference(body, content_type):
    if not body or len(body) > _limit():
        raise _invalid("Image is empty or exceeds the configured size limit")
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime not in IMAGE_TYPES:
        raise AppError("CONTENT_TYPE_NOT_ALLOWED", "Reference must be JPEG, PNG or WebP", 422)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(body)) as image:
                if image.format != IMAGE_TYPES[mime][0]:
                    raise _invalid("Image format does not match its content type")
                width, height = image.size
                if min(width, height) < 256 or max(width, height) > 8192:
                    raise _invalid("Image dimensions must each be between 256 and 8192 pixels")
                image.verify()
            with Image.open(BytesIO(body)) as image:
                image.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise _invalid("Image cannot be decoded safely") from error
    return {"kind": "image", "width": width, "height": height, "duration": None, "fps": None}, mime


def _directory(run_id):
    path = StorageService.root() / "agent" / "references" / sha256(run_id.encode()).hexdigest()[:32]
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write(path, body):
    temporary = path.with_name(new_id("reference_tmp"))
    try:
        temporary.write_bytes(body)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _download(data, ctx):
    directory = _directory(data.run_id)
    key = sha256(data.image_url.encode()).hexdigest()
    cached, receipt = directory / (key + ".bin"), directory / (key + ".json")
    if cached.is_file() and receipt.is_file():
        try:
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            if cached.stat().st_size > _limit():
                raise _invalid("Cached image exceeds the configured size limit")
            body = cached.read_bytes()
            if saved["source_url"] == data.image_url and sha256(body).hexdigest() == saved["sha256"]:
                return body, saved["content_type"]
        except (ValueError, KeyError, OSError):
            pass
    try:
        fetched = fetch_resource(data.image_url, ctx, run_id=data.run_id,
                                 max_bytes=_limit(), allowed_types=set(IMAGE_TYPES))
    except AppError as error:
        if error.code == "FETCH_FAILED" and error.payload.get("reason") == "size_limit":
            raise _invalid("Image exceeds the configured size limit") from error
        raise
    _, mime = inspect_reference(fetched.body, fetched.content_type)
    _atomic_write(cached, fetched.body)
    _atomic_write(receipt, json.dumps({"source_url": data.image_url, "sha256": sha256(fetched.body).hexdigest(),
                                      "content_type": mime}).encode())
    return fetched.body, mime


def _references(run_id):
    return Artifact.query.filter(Artifact.artifact_type == "agent_reference_image",
                                 Artifact.meta["reference"]["run_id"].as_string() == run_id)


def _output(artifact, duplicate=False):
    media, reference = artifact.meta["media"], artifact.meta["reference"]
    return {"reference_id": artifact.artifact_id, "preview_url": f"/api/artifacts/{artifact.artifact_id}/preview",
            "width": media["width"], "height": media["height"], "sha256": reference["sha256"],
            "duplicate_of": artifact.artifact_id if duplicate else None}


def _finish(ctx, output):
    # Commit the reference and its ledger receipt together, closing the restart gap.
    if ctx.invocation_id:
        invocation = ToolInvocation.query.filter_by(invocation_id=ctx.invocation_id,
                                                    budget_scope=ctx.budget_scope).one()
        invocation.output_payload, invocation.status, invocation.finished_at = output, "success", utc_now()
    db.session.commit()
    return output


def _provider(run_id, url):
    for invocation in ToolInvocation.query.filter_by(budget_scope=run_id, tool_name="image_search", status="success"):
        output = invocation.output_payload or {}
        if any(url in {item.get("image_url"), item.get("thumbnail_url")} for item in output.get("results", [])):
            return output.get("provider", "unknown")
    return "user"


def download_reference(data, ctx, run):
    require_allowed_url(data.image_url, ctx, run_id=data.run_id)
    existing = _references(run.run_id).filter(Artifact.meta["reference"]["source_url"].as_string() == data.image_url).first()
    if existing and StorageService.resolve(existing.file_path).is_file():
        return _finish(ctx, _output(reference_for_run(existing.artifact_id, run), duplicate=True))
    body, mime = _download(data, ctx)
    media, mime = inspect_reference(body, mime)
    digest = sha256(body).hexdigest()
    existing = _references(run.run_id).filter(Artifact.meta["reference"]["sha256"].as_string() == digest).first()
    if existing:
        path = StorageService.resolve(existing.file_path)
        if not path.resolve().is_relative_to(StorageService.root()):
            raise _invalid("Reference path is outside managed storage")
        if not path.is_file():
            _atomic_write(path, body)
        return _finish(ctx, _output(reference_for_run(existing.artifact_id, run), duplicate=True))

    artifact_id = "art_ref_" + sha256((run.run_id + ":" + digest).encode()).hexdigest()
    path = _directory(run.run_id) / (digest + IMAGE_TYPES[mime][1])
    _atomic_write(path, body)
    template = ensure_agent_template()
    try:
        job = JobService.create_job({"template_id": template.template_id, "strategy": "agent_upload",
            "job_name": f"reference:{run.run_id}:{digest}", **node_selection([]),
            "job_config": {"agent_upload_owner": run.owner_id, "agent_reference_run": run.run_id}}, commit=False)
        artifact = ArtifactService.register_artifact(job, str(path), "agent_reference_image", metadata={
            "media": media, "reference": {"source_url": data.image_url, "source_page_url": data.source_page_url,
                "entity": data.entity, "provider": _provider(run.run_id, data.image_url), "sha256": digest,
                "downloaded_at": utc_now().isoformat(), "run_id": run.run_id}})
        artifact.artifact_id, artifact.mime_type, job.status = artifact_id, mime, "success"
        return _finish(ctx, _output(artifact))
    except (IntegrityError, AppError):
        db.session.rollback()
        if Artifact.query.filter_by(artifact_id=artifact_id).first():
            return _finish(ctx, _output(reference_for_run(artifact_id, run), duplicate=True))
        raise
