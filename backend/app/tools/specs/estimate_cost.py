"""Read-only estimates for explicit model nodes, without compiling a Plan IR."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.adapters import ADAPTERS
from app.agent.attachments import attachment_for_owner
from app.agent.model_selection import TRANSFORM_MODES, validate_generation_model
from app.agent.production_plan import select_plan_model
from app.agent.transform_media import MediaReference, inspect_transform_media
from app.api import AppError
from app.models import AgentRun
from app.services.model_service import ModelService
from app.tools.budget import estimate_model_cost
from app.tools.permissions import READ
from app.tools.spec import ToolContext, ToolSpec
from app.tools.specs.list_models import CatalogModel, V3_ROLES, public_pricing


ArtifactId = Annotated[str, Field(min_length=1, max_length=100)]
GenerationMode = Literal["t2i", "i2i", "t2v", "i2v", "first_last_frame", "r2v",
                         "omni_reference", "video_edit", "video_extend"]


class CostNode(CatalogModel):
    node_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,40}$")
    model_id: str = Field(min_length=1, max_length=120)
    mode: GenerationMode
    params: dict = Field(default_factory=dict)
    reference_artifact_ids: list[ArtifactId] = Field(default_factory=list, max_length=20)
    media: list[MediaReference] = Field(default_factory=list, max_length=20)
    source_artifact_id: ArtifactId | None = None

    @model_validator(mode="after")
    def reference_shape(self):
        ids = self.reference_artifact_ids + [item.artifact_id for item in self.media]
        if len(ids) != len(set(ids)):
            raise ValueError("Reference artifact IDs must be unique")
        if self.mode in TRANSFORM_MODES:
            if not self.media or self.reference_artifact_ids:
                raise ValueError("Transform estimates require media, not image reference_artifact_ids")
            if self.mode == "omni_reference" and self.source_artifact_id is not None:
                raise ValueError("Reference generation does not select a primary video source")
            if self.mode in {"video_edit", "video_extend"} and not self.source_artifact_id:
                raise ValueError("Editing/extension requires an owned source video")
        elif self.media or self.source_artifact_id:
            raise ValueError("Media and source_artifact_id are only supported for video transformation")
        return self


class EstimateCostInput(CatalogModel):
    nodes: list[CostNode] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_nodes(self):
        ids = [item.node_id for item in self.nodes if item.node_id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("Named nodes must be unique")
        return self


class CostEstimate(CatalogModel):
    node_id: str | None
    model_id: str
    mode: GenerationMode
    params: dict
    estimated_cost: float = Field(ge=0)
    input_video_seconds: float = Field(ge=0)
    output_video_seconds: float = Field(ge=0)
    pricing: dict


class EstimateCostOutput(CatalogModel):
    nodes: list[CostEstimate]
    total_credits: float = Field(ge=0)
    demo: Literal[True] = True


def _image_count(ids, owner):
    if ids and owner is None:
        raise AppError("ATTACHMENT_NOT_FOUND", "Image references require an owning Agent run", 404)
    for artifact_id in ids:
        artifact = attachment_for_owner(artifact_id, owner.owner_id, run_id=owner.run_id)
        if (artifact.artifact_type != "agent_reference_image"
                and artifact_id not in (owner.request or {}).get("attachment_ids", [])):
            raise AppError("ATTACHMENT_NOT_FOUND", "Image is not attached to this run", 404)
        if (artifact.meta or {}).get("media", {}).get("kind") != "image":
            raise AppError("INVALID_ATTACHMENT", "Image references must contain images", 422)
    return len(ids)


def _estimate(node, owner):
    mode = "i2v" if node.mode == "first_last_frame" else node.mode
    # Reuse the existing request policy when an understood request exists.
    # A catalog listing never overrides a user's model family or exclusions.
    request_spec = (owner.snapshot or {}).get("request_spec") if owner is not None else None
    requested_id = ModelService.canonical_model_id(node.model_id) or node.model_id
    # Resolve aliases before lookup so the legacy lookup's alias-upgrade branch
    # cannot seed catalog rows or commit from this read-only tool.
    model = (select_plan_model(request_spec, mode, requested_id, run=owner) if request_spec
             else ModelService.get_model(requested_id, require_enabled=True))
    if model.adapter_name not in ADAPTERS:
        raise AppError("MODEL_CAPABILITY_MISMATCH", "Model adapter is not integrated", 422)
    count = (_image_count(node.reference_artifact_ids, owner) if mode not in TRANSFORM_MODES
             else sum(item.type == "reference_image" for item in node.media))
    if node.mode == "first_last_frame" and (not ModelService.supports_mode(model, "first_last_frame") or count != 2):
        raise AppError("MODEL_CAPABILITY_MISMATCH", "First/last-frame estimates require an integrated model and two images", 422)
    if node.mode == "i2v" and count != 1:
        raise AppError("MODEL_CAPABILITY_MISMATCH", "Image-to-video estimates require exactly one first-frame image", 422)
    params = validate_generation_model(model, mode, node.params, reference_count=count)
    incoming = 0.0
    if mode in TRANSFORM_MODES:
        if owner is None:
            raise AppError("ATTACHMENT_NOT_FOUND", "Transform estimates require an owning Agent run", 404)
        from app.adapters.dashscope_wan3 import MODEL_IDS
        if model.provider != "dashscope" or model.adapter_name != "dashscope_wan3" or model.model_id not in MODEL_IDS:
            raise AppError("MODEL_CAPABILITY_MISMATCH", "Transform estimates require the integrated Wan 3 protocol", 422)
        if params.get("n_outputs", 1) != 1:
            raise AppError("INVALID_INPUT", "Transform estimates require exactly one output", 422)
        if any(item.type == "file" for item in node.media) and params.get("prompt_extend") is not True:
            raise AppError("INVALID_INPUT", "Document references require prompt_extend=true", 422)
        operation = {"omni_reference": "reference", "video_edit": "edit", "video_extend": "extend"}[mode]
        inspected = inspect_transform_media(node.media, run=owner, operation=operation,
                                             source_artifact_id=node.source_artifact_id)
        incoming = inspected["input_video_seconds"]
        output = params["duration"]
        if incoming + output > 30:
            raise AppError("INVALID_INPUT", "Input videos plus complete output must fit within 30 seconds", 422)
        if mode == "video_extend" and output <= inspected["source_video_seconds"]:
            raise AppError("INVALID_INPUT", "Extended output must be longer than its source", 422)
        pricing = (model.capabilities or {}).get("pricing") or {}
        if pricing.get("unit") != "second" or pricing.get("billing_basis") != "input_plus_output_seconds":
            raise AppError("INVALID_INPUT", "Transform pricing requires verified input-plus-output seconds", 422)
    cost = estimate_model_cost(model, params, input_video_seconds=incoming)
    return CostEstimate(node_id=node.node_id, model_id=model.model_id, mode=node.mode, params=params,
                        estimated_cost=cost, input_video_seconds=incoming,
                        output_video_seconds=params.get("duration", 0) * params.get("n_outputs", 1),
                        pricing=public_pricing(model))


def run(data: EstimateCostInput, ctx: ToolContext):
    owner = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
    nodes = [_estimate(node, owner) for node in data.nodes]
    return EstimateCostOutput(nodes=nodes, total_credits=float(sum(Decimal(str(node.estimated_cost)) for node in nodes)))


SPEC = ToolSpec(
    name="estimate_cost", description="Estimate one explicit generation node or a node fragment using validated effective parameters and demonstration prices. Video input seconds are measured from owned media; this does not compile or approve a plan.",
    input_model=EstimateCostInput, output_model=EstimateCostOutput, handler=run,
    permission=READ, allowed_roles=V3_ROLES, agent_visible=True,
    io_types={"inputs": {"nodes": "json"}, "outputs": {"nodes": "json", "total_credits": "json", "demo": "json"}},
)
