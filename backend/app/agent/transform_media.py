"""Resolve owned, Run-bound media and freeze complete decoded input metadata."""
from collections import Counter
from typing import Literal

from pydantic import Field, ValidationError

from app.agent.attachments import attachment_for_owner
from app.agent.search.base import StrictModel
from app.api import AppError
from app.services.file_fingerprint import cached_digest
from app.services.wan3_media_service import Wan3MediaService, invalid


class MediaReference(StrictModel):
    type: Literal["reference_image", "reference_video", "reference_audio", "file"]
    artifact_id: str = Field(min_length=1, max_length=100)


KINDS = {"reference_image": ("image", {"agent_attachment_image"}),
         "reference_video": ("video", {"source_video"}),
         "reference_audio": ("audio", {"agent_attachment_audio"}),
         "file": ("file", {"agent_attachment_document", "agent_reference_document"})}
LIMITS = {"reference_image": 10, "reference_video": 5, "reference_audio": 5, "file": 1}


def _references(refs):
    if not isinstance(refs, list) or not 1 <= len(refs) <= 20:
        raise invalid("Use 1 to 20 ordered media references")
    try:
        refs = [item if isinstance(item, MediaReference) else MediaReference.model_validate(item) for item in refs]
    except ValidationError as error:
        raise invalid("Malformed media references") from error
    counts = Counter(item.type for item in refs)
    if len({item.artifact_id for item in refs}) != len(refs) or any(counts[key] > value for key, value in LIMITS.items()):
        raise invalid("Media references repeat or exceed per-type limits")
    return refs


def _resolve(ref, run):
    artifact = attachment_for_owner(ref.artifact_id, run.owner_id, run_id=run.run_id)
    kind, types = KINDS[ref.type]
    if artifact.artifact_type not in types:
        raise invalid("Reference type does not match the uploaded artifact")
    uploaded = (run.request or {}).get("attachment_ids", [])
    if artifact.artifact_type != "agent_reference_document" and artifact.artifact_id not in uploaded:
        raise AppError("ATTACHMENT_NOT_FOUND", "Attachment is not an input of this Run", 404)
    return artifact, Wan3MediaService.path(artifact.file_path, kind), kind


def _manifest(refs, run):
    result = []
    for ref in refs:
        artifact, path, kind = _resolve(ref, run)
        before = cached_digest(path)
        metadata = Wan3MediaService.inspect(path, kind)
        after = cached_digest(path)
        if before != after:
            raise AppError("TRANSFORM_INPUT_CHANGED", "Input changed during verification", 409)
        item = {"artifact_id": artifact.artifact_id, "type": ref.type, "sha256": after,
                "size": path.stat().st_size, "mime_type": metadata["mime_type"], "file_name": artifact.file_name,
                **{key: metadata[key] for key in ("duration_sec", "width", "height", "fps", "page_count")}}
        if artifact.artifact_type == "agent_reference_document":
            reference = (artifact.meta or {}).get("reference", {})
            if after != reference.get("sha256"):
                raise AppError("TRANSFORM_INPUT_CHANGED", "Captured page snapshot changed", 409)
            item["source_url"] = reference.get("source_url")
        result.append(item)
    return result


def inspect_transform_media(refs, *, run, operation, source_artifact_id=None):
    refs = _references(refs)
    if operation not in {"reference", "edit", "extend"}:
        raise invalid("Unsupported video operation")
    videos = [ref.artifact_id for ref in refs if ref.type == "reference_video"]
    if operation in {"edit", "extend"}:
        if not source_artifact_id or not videos or videos[0] != source_artifact_id:
            raise invalid("Edit/extend requires the original uploaded video as the first video reference")
    elif source_artifact_id is not None:
        raise invalid("Reference generation does not select an edit/extend source")
    manifest = _manifest(refs, run)
    seconds = sum(item["duration_sec"] for item in manifest if item["type"] == "reference_video")
    audio = sum(item["duration_sec"] for item in manifest if item["type"] == "reference_audio")
    if seconds > 15 or audio > 15:
        raise invalid("Total reference video and audio must each be at most 15 seconds; inputs are never clipped")
    source_seconds = next((item["duration_sec"] for item in manifest if item["artifact_id"] == source_artifact_id), None)
    return {"manifest": manifest, "input_video_seconds": round(seconds, 6), "source_video_seconds": source_seconds}


def assert_manifest(refs, *, run, expected_manifest):
    """Approved identities and bytes must still match; never replace the frozen list."""
    refs = _references(refs)
    if not isinstance(expected_manifest, list) or len(expected_manifest) != len(refs):
        raise AppError("TRANSFORM_INPUT_CHANGED", "Approved input manifest is missing or changed", 409)
    # Digest first: malformed replacements must report drift, not silently re-plan.
    for ref, approved in zip(refs, expected_manifest):
        artifact, path, _ = _resolve(ref, run)
        if (not isinstance(approved, dict) or approved.get("artifact_id") != artifact.artifact_id
                or approved.get("type") != ref.type or approved.get("sha256") != cached_digest(path)):
            raise AppError("TRANSFORM_INPUT_CHANGED", "Approved input bytes or order changed", 409)
    actual = _manifest(refs, run)
    if actual != expected_manifest:
        raise AppError("TRANSFORM_INPUT_CHANGED", "Approved input metadata changed", 409)
    return actual


def resolved_media(refs, *, run, expected_manifest):
    refs = _references(refs)
    assert_manifest(refs, run=run, expected_manifest=expected_manifest)
    return [{"type": ref.type, "url": str(_resolve(ref, run)[1])} for ref in refs]
