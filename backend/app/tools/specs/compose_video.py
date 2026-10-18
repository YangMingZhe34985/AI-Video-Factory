"""Approved, Run-scoped, zero-model-cost movie composition."""
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent import plan_versions as versions
from app.agent.delivery_policy import approved_sources, require_delivery_authorization, resolve_source, source_hashes
from app.api import AppError
from app.extensions import db
from app.models import Artifact, Job, ToolInvocation
from app.services.artifact_service import ArtifactService
from app.services.generation_outputs import digest
from app.services.job_service import JobService
from app.services.storage_service import StorageService
from app.services.video_composition_service import VideoCompositionService
from app.tools import job_backed
from app.tools.permissions import PRODUCTION, SYSTEM, WRITE
from app.tools.spec import ToolContext, ToolSpec
from app.utils.time_utils import utc_now


class ComposeVideoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    plan_version: int = Field(ge=1, strict=True)
    video_artifact_ids: list[str] = Field(min_length=1, max_length=120)
    compress_output: bool = Field(default=False, strict=True)


class Composition(BaseModel):
    mode: Literal["stream_copy", "normalized"]
    source_artifact_ids: list[str]
    duration_sec: float
    width: int
    height: int
    fps: float
    mock_materialized: bool
    warnings: list[str]


class ComposeVideoOutput(BaseModel):
    job_id: str
    artifact_id: str
    compressed_artifact_id: str | None = None
    preview_url: str
    download_url: str
    composition: Composition


def validate_sources(data, ctx):
    run, version = require_delivery_authorization(ctx, data.plan_version)
    delivery = run.snapshot["delivery"]
    if (data.video_artifact_ids != delivery["source_artifact_ids"]
            or data.compress_output is not delivery["compress_output"]
            or versions.inputs_hash(data.model_dump(mode="json")) != delivery["inputs_hash"]):
        raise AppError("INVALID_REFERENCE", "Composition must use the complete approved source order and settings", 422)
    return run, version, approved_sources(run, version)


def _existing(invocation):
    return Artifact.query.filter(Artifact.meta["composition"]["invocation_id"].as_string() == invocation.invocation_id,
        Artifact.meta["rendition"].as_string() == "master").first()


def cached_output_is_valid(invocation):
    output = invocation.output_payload or {}
    master = _existing(invocation)
    if not master or master.artifact_id != output.get("artifact_id"):
        return False
    metadata = (master.meta or {}).get("composition") or {}
    try:
        if digest(resolve_source(master)) != metadata.get("master_sha256"):
            return False
        compressed_id = output.get("compressed_artifact_id")
        if bool(compressed_id) != bool((invocation.input_payload or {}).get("compress_output")):
            return False
        if compressed_id:
            compressed = Artifact.query.filter_by(artifact_id=compressed_id, job_id=master.job_id).first()
            if not compressed or digest(resolve_source(compressed)) != metadata.get("compressed_sha256"):
                return False
        return True
    except (AppError, OSError, ValueError):
        return False


def run(data: ComposeVideoInput, ctx: ToolContext):
    owner, version, sources = validate_sources(data, ctx)
    invocation = ToolInvocation.query.filter_by(invocation_id=ctx.invocation_id, budget_scope=owner.run_id).one()
    existing = _existing(invocation)
    hashes = source_hashes(sources)
    if existing and (existing.meta or {}).get("composition", {}).get("source_sha256") != hashes:
        raise AppError("INVALID_REFERENCE", "Approved source bytes changed after composition", 422)
    if existing and cached_output_is_valid(invocation):
        return _finish(existing, invocation)
    directory = StorageService.root() / "agent" / "delivery" / sha256(owner.run_id.encode()).hexdigest()
    target = directory / (ctx.invocation_id + ".mp4")
    result = VideoCompositionService.compose([resolve_source(item[2]) for item in sources], target,
        durations=[item[0]["duration_sec"] for item in sources], shot_ids=[item[0]["shot_id"] for item in sources],
        compress_output=data.compress_output)
    compressed_path = result.pop("compressed_path")
    public = {**result, "source_artifact_ids": data.video_artifact_ids}
    metadata = {**public, "invocation_id": invocation.invocation_id, "plan_version": version.version,
        "input_hash": versions.inputs_hash(data.model_dump(mode="json")), "source_sha256": hashes,
        "master_sha256": digest(target), "compressed_sha256": digest(StorageService.resolve(compressed_path)) if compressed_path else None}
    job = existing.job if existing else Job.query.filter(
        Job.config["skill"]["invocation_id"].as_string() == ctx.invocation_id).first()
    if not job:
        template = job_backed.ensure_agent_template()
        job = JobService.create_job({"template_id": template.template_id, "strategy": "skill:compose_video",
            **job_backed.node_selection([]), "job_config": {
                "agent_story_production": {"run_id": owner.run_id, "plan_version": version.version, "target_type": "delivery"},
                "agent_output_policy": {"compress_output": False},
                "skill": {"tool_name": "compose_video", "budget_scope": owner.run_id,
                          "invocation_id": ctx.invocation_id, "caller_role": ctx.role}}}, commit=False)
    master = _save_artifact(job, existing, target, "composed_video", "master", metadata)
    if compressed_path:
        compressed = Artifact.query.filter_by(job_id=job.id, artifact_type="composed_video_compressed").first()
        _save_artifact(job, compressed, StorageService.resolve(compressed_path), "composed_video_compressed", "compressed", metadata)
    job.status = "success"
    return _finish(master, invocation)


def _save_artifact(job, existing, path, kind, rendition, metadata):
    value = {"composition": metadata, "rendition": rendition}
    if existing:
        existing.file_path = StorageService.relative_path(path)
        existing.size = path.stat().st_size
        existing.meta = {**(existing.meta or {}), **value}
        return existing
    return ArtifactService.register_artifact(job, StorageService.relative_path(path), kind, metadata=value)


def _finish(master, invocation):
    compressed = Artifact.query.filter_by(job_id=master.job_id, artifact_type="composed_video_compressed").first()
    result = ComposeVideoOutput(job_id=master.job.job_id, artifact_id=master.artifact_id,
        compressed_artifact_id=compressed.artifact_id if compressed else None,
        preview_url=f"/api/artifacts/{master.artifact_id}/preview",
        download_url=f"/api/artifacts/{master.artifact_id}/download",
        composition=Composition.model_validate(master.meta["composition"])).model_dump(mode="json")
    invocation.job = master.job
    invocation.output_payload, invocation.status, invocation.finished_at = result, "success", utc_now()
    db.session.commit()
    return result


SPEC = ToolSpec(name="compose_video", description="Assemble approved story clips locally, preserving a master and optional explicit compressed copy.",
    input_model=ComposeVideoInput, output_model=ComposeVideoOutput, handler=run, permission=WRITE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}), requires_approval=True, timeout_sec=1800, max_retries=1)
