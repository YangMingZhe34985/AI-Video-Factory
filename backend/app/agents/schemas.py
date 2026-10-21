"""Typed workspace decisions. PlanDraft validates shape, never execution authority."""

import json
import math
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_serializer, model_validator

from app.agent.clarify import Question
from app.agent.request_spec import AttachmentUse, Constraints, ResearchNeed, StrictModel, Subject, TransformIntent
from app.agent.research_spec import ResearchDossier
from app.agent.story_spec import StoryPackage
from app.api import AppError

WORKSPACE_KINDS = frozenset({"brief", "clarification", "research_dossier", "story", "plan_draft",
                             "critic_review", "patch", "note"})
MAX_PAYLOAD_BYTES = 256 * 1024
WorkspaceKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,120}$")]
NodeId = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,40}$")]
CharacterId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]


class WorkspaceRef(StrictModel):
    key: WorkspaceKey
    version: int = Field(ge=1, strict=True)


class RequirementBrief(StrictModel):
    """RequestSpec fields independent of the v2 fixed recipe router."""

    deliverable: Literal["image", "video"]
    transform: TransformIntent | None = None
    summary: str = Field(min_length=1, max_length=500)
    target_duration_sec: int | None = Field(default=None, ge=1, le=600, strict=True)
    duration_tolerance_sec: int = Field(default=10, ge=0, le=120, strict=True)
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:3", "3:4"] | None = None
    output_count: int = Field(default=1, ge=1, le=4, strict=True)
    subjects: list[Subject] = Field(default_factory=list, max_length=12)
    attachments: list[AttachmentUse] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    research_needs: list[ResearchNeed] = Field(default_factory=list, max_length=5)
    open_questions: list[Question] = Field(default_factory=list, max_length=3)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    intent_notes: str = Field(default="", max_length=2000)
    production_intent: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def consistent_brief(self):
        if self.deliverable == "image" and (self.target_duration_sec is not None or self.transform is not None):
            raise ValueError("Image requests cannot specify video duration or transform intent")
        if self.deliverable == "video" and self.output_count != 1:
            raise ValueError("Video requests must have output_count=1")
        ids = [item.attachment_id for item in self.attachments]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate attachment use")
        if any(set(subject.attachment_ids) - set(ids) for subject in self.subjects):
            raise ValueError("Subject references an unknown attachment")
        required_types = {"first_frame": "image", "remix_source": "video", "transform_source": "video",
                          "audio_ref": "audio", "document_ref": "file"}
        if any(item.role in required_types and item.kind != required_types[item.role] for item in self.attachments):
            raise ValueError("Attachment role requires a compatible media kind")
        sources = [item for item in self.attachments if item.role == "transform_source"]
        if self.transform:
            source = next((item for item in sources if item.attachment_id == self.transform.source_attachment_id), None)
            if self.transform.operation in {"edit", "extend"} and (source is None or len(sources) != 1):
                raise ValueError("Video editing/extension requires one selected video source")
            if self.transform.operation == "reference" and sources:
                raise ValueError("Reference generation has no primary transform source")
            if not any(item.role != "unused" for item in self.attachments) and not self.transform.reference_urls:
                raise ValueError("Reference generation requires media or an explicit URL")
        elif sources:
            raise ValueError("A transform source requires transform intent")
        if len({q.question_id for q in self.open_questions}) != len(self.open_questions):
            raise ValueError("Duplicate question ID")
        return self


class BlueprintOrigin(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=1, strict=True)


class PlanOrigin(StrictModel):
    agent: Literal["producer", "research", "creative", "director", "prompt_smith", "critic", "repair"]
    skills: list[str] = Field(default_factory=list, max_length=30)
    blueprint: BlueprintOrigin | None = None


class PlanDraftNode(StrictModel):
    id: NodeId
    tool: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    inputs: dict = Field(default_factory=dict)
    model_id: str | None = Field(default=None, min_length=1, max_length=120)
    params: dict = Field(default_factory=dict)
    stage: str | None = Field(default=None, max_length=80)
    depends_on: list[NodeId] = Field(default_factory=list, max_length=200)
    gate: Literal["preview", "choice"] | None = None
    origin: PlanOrigin
    rationale: str = Field(max_length=300)
    characters: list[CharacterId] | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def unique_characters(self):
        if self.characters is not None and len(set(self.characters)) != len(self.characters):
            raise ValueError("Node character IDs must be unique")
        return self

    @model_serializer(mode="wrap")
    def compatible_shape(self, handler):
        value = handler(self)
        if self.characters is None:
            value.pop("characters", None)
        return value


class CharacterArtifactRef(StrictModel):
    artifact: str = Field(min_length=1, max_length=120)


class CharacterNodeRef(StrictModel):
    ref: str = Field(pattern=r"^[a-z0-9_]{1,40}\.image$")


IdentityRef = CharacterArtifactRef | CharacterNodeRef
IdentityReferences = Annotated[list[IdentityRef], Field(min_length=1, max_length=3)]


class PlanDeliverable(StrictModel):
    kind: Literal["image", "video", "package"]
    node_id: NodeId
    output: str = Field(pattern=r"^[A-Za-z0-9_]{1,80}$")


class PlanStage(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    label: str = Field(min_length=1, max_length=120)


class PlanDraft(StrictModel):
    """V.8 authoring shape only; V4 supplies compile/dry-run/approval checks."""

    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=2000)
    deliverables: list[PlanDeliverable] = Field(min_length=1, max_length=200)
    nodes: list[PlanDraftNode] = Field(min_length=1, max_length=200)
    stages: list[PlanStage] = Field(default_factory=list, max_length=200)
    character_references: dict[CharacterId, IdentityReferences] = Field(default_factory=dict, max_length=8)
    story_ref: WorkspaceRef | None = None

    @model_validator(mode="after")
    def unique_ids(self):
        if len({node.id for node in self.nodes}) != len(self.nodes):
            raise ValueError("Duplicate plan node IDs")
        if len({stage.id for stage in self.stages}) != len(self.stages):
            raise ValueError("Duplicate plan stage IDs")
        for refs in self.character_references.values():
            if not 1 <= len(refs) <= 3:
                raise ValueError("Each character needs one to three identity references")
            tokens = [json.dumps(ref.model_dump(), sort_keys=True) for ref in refs]
            if len(set(tokens)) != len(tokens):
                raise ValueError("Character references must be unique")
        return self

    @model_serializer(mode="wrap")
    def compatible_shape(self, handler):
        value = handler(self)
        if not self.character_references:
            value.pop("character_references", None)
        if self.story_ref is None:
            value.pop("story_ref", None)
        return value


class CriticIssue(StrictModel):
    node_id: NodeId | None = None
    severity: Literal["info", "warning", "error"]
    message: str = Field(min_length=1, max_length=1000)


class CriticReview(StrictModel):
    verdict: Literal["pass", "revise"]
    issues: list[CriticIssue] = Field(default_factory=list, max_length=200)


def finite_json(payload):
    """Bound untrusted decisions before validation or persistence."""
    if not isinstance(payload, dict):
        raise AppError("INVALID_WORKSPACE_PAYLOAD", "Workspace payload must be a JSON object", 422)
    def check(value, depth=0):
        if depth > 64:
            raise ValueError("JSON nesting exceeds 64 levels")
        if value is None or type(value) in {str, bool, int}:
            return
        if type(value) is float and math.isfinite(value):
            return
        if type(value) is dict and all(isinstance(key, str) for key in value):
            for child in value.values():
                check(child, depth + 1)
            return
        if type(value) is list:
            for child in value:
                check(child, depth + 1)
            return
        raise ValueError("Only JSON values and string object keys are accepted")
    try:
        check(payload)
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise AppError("WORKSPACE_PAYLOAD_TOO_LARGE", "Workspace entry exceeds 256 KiB", 422)
        # JSON round-trip also detaches the input from caller-owned objects.
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise AppError("INVALID_WORKSPACE_PAYLOAD", "Workspace payload must contain finite JSON values", 422) from error


def validate_payload(kind, payload):
    if kind not in WORKSPACE_KINDS:
        raise AppError("INVALID_WORKSPACE_KIND", "Unknown workspace kind", 422)
    value = finite_json(payload)
    model = {"brief": RequirementBrief, "story": StoryPackage, "research_dossier": ResearchDossier,
             "plan_draft": PlanDraft, "critic_review": CriticReview}.get(kind)
    if kind == "patch":
        from app.plans.patch_schemas import PatchDraft
        model = PatchDraft
    if model:
        try:
            value = model.model_validate(value).model_dump(mode="json")
        except ValidationError as error:
            errors = error.errors(include_url=False, include_context=False, include_input=False)
            details = {"kind": kind, "errors": errors}
            from app.agent.research_guidance import dossier_guidance, research_needs_guidance
            if kind == "brief" and any(item.get("loc", ())[:1] == ("research_needs",) for item in errors):
                details["repair_guidance"] = research_needs_guidance()
            elif kind == "research_dossier":
                details["repair_guidance"] = dossier_guidance()
            raise AppError("INVALID_WORKSPACE_PAYLOAD", "Workspace entry does not match its kind", 422,
                           payload=details) from error
    # Defaults can enlarge the normalized entry; enforce the bound again.
    return finite_json(value)
