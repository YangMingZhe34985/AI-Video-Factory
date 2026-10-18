"""Validated Intake output shared by v2 routing and plan generation."""

from typing import Literal
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.clarify import Question


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Subject(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(max_length=1000)
    source: Literal["user_text", "attachment", "needs_research"]
    attachment_ids: list[str] = Field(default_factory=list)


class AttachmentUse(StrictModel):
    attachment_id: str = Field(min_length=1)
    kind: Literal["image", "video", "audio", "file"]
    role: Literal["identity_ref", "style_ref", "first_frame", "remix_source", "content_ref", "unused", "transform_source", "audio_ref", "document_ref"]
    description: str = Field(max_length=1000)
    reason: str = Field(min_length=1, max_length=300)


class Constraints(StrictModel):
    model_preferences: list[str] = Field(default_factory=list)
    model_exclusions: list[str] = Field(default_factory=list)
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    style: str | None = Field(default=None, max_length=500)
    language: str | None = None
    compress_output: bool = False


class ResearchNeed(StrictModel):
    query: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=300)


class TransformIntent(StrictModel):
    operation: Literal["reference", "edit", "extend"]
    source_attachment_id: str | None = None
    additional_duration_sec: float | None = Field(default=None, gt=0, le=29, allow_inf_nan=False, strict=True)
    reference_urls: list[str] = Field(default_factory=list, max_length=1)

    @model_validator(mode="after")
    def valid_intent(self):
        if self.operation != "extend" and self.additional_duration_sec is not None:
            raise ValueError("Only extension may specify an additional duration")
        if self.operation == "reference" and self.source_attachment_id is not None:
            raise ValueError("Reference generation does not select a primary source")
        for value in self.reference_urls:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Reference URLs must be complete public HTTP(S) URLs")
        return self


class RequestSpec(StrictModel):
    deliverable: Literal["image", "video"]
    recipe_hint: Literal["image_edit", "image_create", "single_clip", "story_video", "remix", "video_transform"]
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

    @model_validator(mode="after")
    def consistent_request(self):
        image_recipe = self.recipe_hint in {"image_edit", "image_create"}
        if image_recipe != (self.deliverable == "image"):
            raise ValueError("deliverable and recipe_hint disagree")
        if self.deliverable == "image" and self.target_duration_sec is not None:
            raise ValueError("Image requests cannot have a target duration")
        if self.deliverable == "video" and self.output_count != 1:
            raise ValueError("Video requests must have output_count=1")
        ids = [item.attachment_id for item in self.attachments]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate attachment use")
        if any(set(subject.attachment_ids) - set(ids) for subject in self.subjects):
            raise ValueError("Subject references an unknown attachment")
        if any(item.role == "first_frame" and item.kind != "image" for item in self.attachments):
            raise ValueError("First-frame references must be images")
        sources = [item for item in self.attachments if item.role == "remix_source"]
        if any(item.kind != "video" for item in sources):
            raise ValueError("Remix sources must be videos")
        if self.recipe_hint == "remix" and len(sources) != 1:
            raise ValueError("Remix requires exactly one source video")
        if self.recipe_hint != "remix" and sources:
            raise ValueError("Only remix may select a remix source")
        if self.recipe_hint == "image_edit" and not any(
            item.kind == "image" and item.role in {"identity_ref", "content_ref"} for item in self.attachments
        ):
            raise ValueError("Image editing requires an identity or content image reference")
        if (self.recipe_hint == "video_transform") != (self.transform is not None):
            raise ValueError("Only video_transform requires transform intent")
        transform_sources = [item for item in self.attachments if item.role == "transform_source"]
        if self.transform:
            source = next((item for item in self.attachments
                           if item.attachment_id == self.transform.source_attachment_id), None)
            if self.transform.operation in {"edit", "extend"}:
                if not source or source.kind != "video" or source.role != "transform_source":
                    raise ValueError("Video editing/extension requires an uploaded video transform source")
            if len(transform_sources) != (1 if source else 0):
                raise ValueError("Transform intent must identify its unique primary source")
            if not any(item.role != "unused" for item in self.attachments) and not self.transform.reference_urls:
                raise ValueError("Reference generation requires media or an explicit reference URL")
        elif transform_sources:
            raise ValueError("Only video_transform may select transform_source")
        if any(item.role == "audio_ref" and item.kind != "audio" for item in self.attachments):
            raise ValueError("Audio references must be audio attachments")
        if any(item.role == "document_ref" and item.kind != "file" for item in self.attachments):
            raise ValueError("Document references must be files")
        question_ids = [item.question_id for item in self.open_questions]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("Duplicate question_id")
        return self


def validate_request_spec(raw: dict | RequestSpec, attachments: list[dict], *, source_text: str | None = None, url_source_text: str | None = None) -> RequestSpec:
    """Check LLM references against the server-owned attachment inventory."""
    spec = RequestSpec.model_validate(raw)
    expected = {item["attachment_id"]: item["kind"] for item in attachments}
    actual = {item.attachment_id: item.kind for item in spec.attachments}
    if len(expected) != len(attachments) or expected != actual:
        raise ValueError("attachments must cover the uploaded IDs exactly, with their original kinds")
    if source_text is not None and any(not value or value not in source_text for value in (
        spec.constraints.model_preferences + spec.constraints.model_exclusions
    )):
        raise ValueError("Model preferences and exclusions must preserve the user's original wording")
    if spec.transform and spec.transform.reference_urls:
        text = source_text if url_source_text is None else url_source_text
        literal_urls = {value.rstrip(".,;!?") for value in re.findall(r'https?://[^\s<>"，。！？；）)]+', text or "")}
        if text is None or any(url not in literal_urls for url in spec.transform.reference_urls):
            raise ValueError("Reference URLs must occur in the original user text")
    return spec
