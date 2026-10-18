"""Private v3 plan schemas. The legacy registry keeps its original contracts."""

from dataclasses import replace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tools.spec import ToolSpec


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class MediaReference(Strict):
    type: Literal["reference_image", "reference_video", "reference_audio", "file"]
    artifact_id: str = Field(min_length=1, max_length=100)


class TransformInput(Strict):
    operation: Literal["reference", "edit", "extend"]
    prompt: str = Field(min_length=1, max_length=5000)
    media: list[MediaReference] = Field(min_length=1, max_length=20)
    source_artifact_id: str | None = None
    model_id: str = Field(min_length=1, max_length=120)
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def source_matches(self):
        ids = [item.artifact_id for item in self.media]
        videos = [item.artifact_id for item in self.media if item.type == "reference_video"]
        if len(ids) != len(set(ids)):
            raise ValueError("Media references must be unique")
        if self.operation == "reference" and self.source_artifact_id is not None:
            raise ValueError("Reference generation does not select a primary source")
        if self.operation != "reference" and (not videos or videos[0] != self.source_artifact_id):
            raise ValueError("Editing/extension requires its source as the first reference video")
        return self


class ComposeInput(Strict):
    plan_version: int = Field(ge=1, strict=True)
    video_artifact_ids: list[str] = Field(min_length=1, max_length=120)
    compress_output: bool = Field(default=False, strict=True)


class ProbeInput(Strict):
    plan_version: int = Field(ge=1, strict=True)
    artifact_id: str = Field(min_length=1, max_length=100)


class QcInput(ProbeInput):
    video_artifact_ids: list[str] = Field(min_length=1, max_length=120)


class PackageInput(ProbeInput):
    compressed_artifact_id: str | None = None


class RetainInput(Strict):
    video_artifact_id: str = Field(min_length=1, max_length=100)
    source_start_sec: float = Field(ge=0, strict=True)
    source_end_sec: float = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def ordered_range(self):
        if self.source_end_sec <= self.source_start_sec:
            raise ValueError("Source end must be after source start")
        return self


class RetainOutput(Strict):
    artifact_id: str
    source_artifact_id: str
    duration_sec: float
    job_id: str


_INPUTS = {"transform_video": TransformInput, "compose_video": ComposeInput,
           "probe_media": ProbeInput, "qc_video": QcInput, "package_story": PackageInput}


def _handler(name):
    def invoke(data, ctx):
        from app.plans import media
        return getattr(media, name)(data, ctx)
    return invoke


def plan_spec(spec):
    if not spec.plan_executable:
        return spec
    original_cost = spec.cost_fn
    def cost(data, ctx):
        if getattr(ctx, "plan_node_task_id", None) is not None:
            from app.plans.policy import submission_cost
            return submission_cost(ctx)
        return original_cost(data, ctx)
    changes = {"cost_fn": cost}
    if spec.name in _INPUTS:
        changes.update(input_model=_INPUTS[spec.name], handler=_handler(spec.name))
    if spec.name == "transform_video":
        changes["io_types"] = {"inputs": {"prompt": "text", "media": "json", "source_artifact_id": "video"},
                               "outputs": {"video": "video"}}
    return replace(spec, **changes)


def extra_specs():
    return [ToolSpec(name="retain_video_segment", description="Keep an approved source-video range locally without model calls.",
        input_model=RetainInput, output_model=RetainOutput, handler=_handler("retain_video_segment"),
        permission="write", allowed_roles=frozenset({"production", "system"}), requires_approval=True,
        plan_executable=True, max_retries=0, timeout_sec=600,
        io_types={"inputs": {"video_artifact_id": "video"}, "outputs": {"artifact_id": "video"}})]
