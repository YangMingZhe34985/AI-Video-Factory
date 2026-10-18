"""Owner-scoped story package with approved originals and a safe manifest."""
from copy import deepcopy
from hashlib import sha256
import json
import re
import zipfile
from pydantic import BaseModel, ConfigDict, Field
from app.api import AppError
from app.agent.delivery_policy import approved_sources, require_delivery_authorization, resolve_delivery_artifact, resolve_source
from app.extensions import db
from app.models import Artifact, ToolInvocation
from app.services.artifact_service import ArtifactService
from app.services.file_fingerprint import cached_digest, memoized
from app.services.job_service import JobService
from app.services.storage_service import StorageService
from app.tools import job_backed
from app.tools.budget import BudgetGuard
from app.tools.permissions import PRODUCTION, SYSTEM, WRITE
from app.tools.spec import ToolSpec
from app.utils.time_utils import utc_now

class PackageStoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_version: int = Field(ge=1, strict=True)
    artifact_id: str = Field(min_length=1, max_length=80)
    compressed_artifact_id: str | None = Field(default=None, min_length=1, max_length=80)

class PackageStoryOutput(BaseModel):
    artifact_id: str
    download_url: str
    file_name: str


def validate_sources(data, ctx):
    owner, version = require_delivery_authorization(ctx, data.plan_version)
    sources = approved_sources(owner, version)
    master = resolve_delivery_artifact(owner, version, data.artifact_id)
    compressed = resolve_delivery_artifact(owner, version, data.compressed_artifact_id, kind="compressed") if data.compressed_artifact_id else None
    delivery = owner.snapshot["delivery"]
    if data.compressed_artifact_id != (delivery.get("composition") or {}).get("compressed_artifact_id"):
        raise AppError("INVALID_REFERENCE", "Package compression output differs from approval", 422)
    if not (delivery.get("qc") or {}).get("passed"):
        raise AppError("DELIVERY_QC_FAILED", "The delivery must pass structural checks before packaging", 409)
    for artifact in [master, *([compressed] if compressed else []), *(item for _s, _t, item in sources)]:
        resolve_source(artifact)
    return owner, version, sources, master, compressed


def _digest(path):
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_is_complete(path):
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None and {"manifest.json", "plan.json", "story.json", "qc.json", "final/master.mp4"}.issubset(archive.namelist())
    except (OSError, ValueError, zipfile.BadZipFile):
        return False


def cached_output_is_valid(invocation):
    output = invocation.output_payload or {}
    artifact = Artifact.query.filter_by(artifact_id=output.get("artifact_id")).first()
    if not artifact or artifact.artifact_type != "story_package":
        return False
    metadata = (artifact.meta or {}).get("story_package", {})
    try:
        path = StorageService.resolve(artifact.file_path)
        if (not path.resolve().is_relative_to(StorageService.root()) or not path.is_file()
                or metadata.get("invocation_id") != invocation.invocation_id or cached_digest(path) != metadata.get("sha256")):
            return False
        return memoized(path, "story_package_zip", _archive_is_complete)
    except (OSError, ValueError, zipfile.BadZipFile):
        return False


def _safe(value):
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()
                if not any(part in key.lower() for part in ("secret", "api_key", "token", "password"))
                and not key.lower().endswith(("_path", "_url")) and key.lower() not in {"path", "url"}}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"https?://[^\s<>]+", "[external URL omitted]", value)
        value = re.sub(r"[A-Za-z]:[\\/][^\s<>]+", "[local path omitted]", value)
        return "[local path omitted]" if value.startswith(("/", "\\\\")) else value
    return value


def _source_name(index, artifact):
    suffix = resolve_source(artifact).suffix.lower()
    if suffix not in {".mp4", ".mov", ".webm", ".mkv"}:
        suffix = ".bin"
    return f"sources/{index + 1:02d}{suffix}"


def run(data, ctx):
    owner, version, sources, master, compressed = validate_sources(data, ctx)
    invocation = ToolInvocation.query.filter_by(invocation_id=ctx.invocation_id, budget_scope=owner.run_id).one()
    if cached_output_is_valid(invocation):
        return invocation.output_payload
    existing = Artifact.query.filter(Artifact.meta["story_package"]["invocation_id"].as_string() == ctx.invocation_id).first()
    directory = StorageService.root() / "agent" / "delivery" / sha256(owner.run_id.encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (ctx.invocation_id + ".zip")
    temporary = target.with_suffix(".partial.zip")
    manifest = {"schema_version": 1, "run_id": owner.run_id, "plan_version": version.version,
        "source_artifact_ids": [artifact.artifact_id for _shot, _task, artifact in sources],
        "master_artifact_id": master.artifact_id, "compressed_artifact_id": compressed.artifact_id if compressed else None,
        "composition": deepcopy(owner.snapshot["delivery"]["composition"]["composition"]),
        "costs": {"delivery_credits": 0, "run_estimated_spent_credits": BudgetGuard.spent(owner.run_id)},
        "files": [_source_name(index, artifact) for index, (_shot, _task, artifact) in enumerate(sources)]}
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for index, (shot, _task, artifact) in enumerate(sources):
                archive.write(resolve_source(artifact), _source_name(index, artifact))
            archive.write(resolve_source(master), "final/master.mp4")
            if compressed:
                archive.write(resolve_source(compressed), "final/compressed.mp4")
            for name, payload in (("manifest", manifest), ("plan", version.plan), ("story", version.story_package), ("qc", owner.snapshot["delivery"]["qc"])):
                archive.writestr(name + ".json", json.dumps(_safe(payload), ensure_ascii=False, indent=2, allow_nan=False))
        validate_sources(data, ctx)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    if existing:
        artifact, job = existing, existing.job
        artifact.size = target.stat().st_size
    else:
        template = job_backed.ensure_agent_template()
        job = JobService.create_job({"template_id": template.template_id, "strategy": "skill:package_story",
            **job_backed.node_selection([]), "job_config": {"agent_story_production": {"run_id": owner.run_id,
                "plan_version": version.version, "target_type": "delivery"}, "skill": {"tool_name": "package_story",
                "budget_scope": owner.run_id, "invocation_id": ctx.invocation_id, "caller_role": ctx.role}}}, commit=False)
        artifact = ArtifactService.register_artifact(job, StorageService.relative_path(target), "story_package")
    artifact.meta = {**(artifact.meta or {}), "story_package": {"invocation_id": ctx.invocation_id,
        "plan_version": version.version, "sha256": _digest(target)}}
    job.status = "success"
    output = {"artifact_id": artifact.artifact_id, "download_url": f"/api/artifacts/{artifact.artifact_id}/download", "file_name": "cinecrew-story.zip"}
    invocation.job, invocation.output_payload, invocation.status, invocation.finished_at = job, output, "success", utc_now()
    db.session.commit()
    return output

SPEC = ToolSpec(name="package_story", description="Package approved story originals, master and safe manifests locally.",
    input_model=PackageStoryInput, output_model=PackageStoryOutput, handler=run, permission=WRITE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}), requires_approval=True, timeout_sec=300, max_retries=0)
