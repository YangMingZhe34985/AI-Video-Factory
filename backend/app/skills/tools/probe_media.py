"""Inspect an approved delivery artifact without exposing storage paths."""
from pydantic import BaseModel, ConfigDict, Field
from app.api import AppError
from app.agent.delivery_policy import approved_sources, require_delivery_authorization, resolve_delivery_artifact, resolve_source
from app.services.media_probe_service import MediaProbeService
from app.skills.permissions import PRODUCTION, SYSTEM, WRITE
from app.skills.spec import ToolSpec

class ProbeMediaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str = Field(min_length=1, max_length=80)

class ProbeMediaOutput(BaseModel):
    artifact_id: str
    media: dict


def validate_sources(data, ctx):
    owner, version = require_delivery_authorization(ctx)
    for shot, _task, artifact in approved_sources(owner, version):
        if artifact.artifact_id == data.artifact_id:
            resolve_source(artifact)
            return artifact, shot["duration_sec"]
    artifact = resolve_delivery_artifact(owner, version, data.artifact_id)
    resolve_source(artifact)
    return artifact, None


def run(data, ctx):
    artifact, duration = validate_sources(data, ctx)
    return {"artifact_id": artifact.artifact_id, "media": MediaProbeService.probe(
        resolve_source(artifact), decode=True, mock_duration_sec=duration)}

SPEC = ToolSpec(name="probe_media", description="Decode and inspect an approved local delivery video.",
    input_model=ProbeMediaInput, output_model=ProbeMediaOutput, handler=run, permission=WRITE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}), requires_approval=True, timeout_sec=600, max_retries=0)
