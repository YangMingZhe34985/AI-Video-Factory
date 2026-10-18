"""Story contracts and server-owned reference validation for Creative v2."""

from typing import Literal

from flask import current_app
from pydantic import Field, model_validator

from app.agent.attachments import attachment_for_owner
from app.agent.clarify import Question
from app.agent.request_spec import RequestSpec, StrictModel
from app.agent.search.references import reference_for_run
from app.api import AppError


class Act(StrictModel):
    act_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    title: str = Field(min_length=1, max_length=60)
    summary: str = Field(min_length=1, max_length=600)


class Beat(StrictModel):
    beat_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    act_id: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1, max_length=400)
    duration_sec: int = Field(ge=1, strict=True)
    character_ids: list[str] = Field(default_factory=list, max_length=8)
    location: str = Field(min_length=1, max_length=120)
    emotion: str = Field(min_length=1, max_length=60)


class Story(StrictModel):
    logline: str = Field(min_length=1, max_length=200)
    synopsis: str = Field(min_length=1, max_length=2000)
    acts: list[Act] = Field(min_length=1, max_length=6)
    beats: list[Beat] = Field(min_length=1, max_length=40)


class CharacterReference(StrictModel):
    source: Literal["research", "attachment", "generate"]
    artifact_ids: list[str] = Field(default_factory=list, max_length=3)
    research_entity_id: str | None = Field(default=None, max_length=40)
    generate_prompt: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def consistent_source(self):
        if len(set(self.artifact_ids)) != len(self.artifact_ids) or any(not item.strip() for item in self.artifact_ids):
            raise ValueError("Reference IDs must be non-empty and unique")
        if self.source == "generate":
            if not self.generate_prompt or self.research_entity_id:
                raise ValueError("Generated references need a prompt and no research entity")
        elif not self.artifact_ids or self.generate_prompt:
            raise ValueError("Existing references need artifact IDs and no generation prompt")
        if (self.source == "research") != bool(self.research_entity_id):
            raise ValueError("Only research references need a research entity")
        return self


class Character(StrictModel):
    character_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=120)
    lock_description: str = Field(min_length=1, max_length=600)
    personality: str = Field(min_length=1, max_length=300)
    reference: CharacterReference


class StyleGuide(StrictModel):
    visual_style: str = Field(min_length=1, max_length=300)
    palette: str = Field(min_length=1, max_length=200)
    lighting: str = Field(min_length=1, max_length=200)
    camera_language: str = Field(min_length=1, max_length=300)
    prompt_prefix: str = Field(min_length=1, max_length=400)
    negative_prompt: str | None = Field(default=None, max_length=500)


class StoryPackage(StrictModel):
    story: Story
    characters: list[Character] = Field(default_factory=list, max_length=8)
    style: StyleGuide
    open_questions: list[Question] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def consistent_story(self):
        for label, ids in (("character", [item.character_id for item in self.characters]),
                           ("act", [item.act_id for item in self.story.acts]),
                           ("beat", [item.beat_id for item in self.story.beats]),
                           ("question", [item.question_id for item in self.open_questions])):
            if len(set(ids)) != len(ids):
                raise ValueError(f"Duplicate {label} ID")
        acts = {item.act_id for item in self.story.acts}
        characters = {item.character_id for item in self.characters}
        for beat in self.story.beats:
            if beat.act_id not in acts or not set(beat.character_ids) <= characters:
                raise ValueError("Beat references an unknown act or character")
            if len(set(beat.character_ids)) != len(beat.character_ids):
                raise ValueError("Beat character IDs must be unique")
        return self


def duration_tolerance(spec):
    spec = RequestSpec.model_validate(spec)
    return max(spec.duration_tolerance_sec,
               (spec.target_duration_sec or 0) * current_app.config.get("AGENT_STORY_DURATION_TOLERANCE_RATIO", 0.1))


def validate_story_package(raw, request_spec, *, run, research_dossier=None):
    """Validate new Creative output, before any generated character art exists."""
    package = StoryPackage.model_validate(raw)
    spec = RequestSpec.model_validate(request_spec)
    if spec.recipe_hint != "story_video":
        raise ValueError("Creative v2 requires the story_video recipe")
    if spec.target_duration_sec is not None and abs(
        sum(beat.duration_sec for beat in package.story.beats) - spec.target_duration_sec
    ) > duration_tolerance(spec):
        raise ValueError("Story beat duration differs from the requested target beyond tolerance")
    uploads = set((run.request or {}).get("attachment_ids", []))
    references = {item.attachment_id for item in spec.attachments
                  if item.kind == "image" and item.role in {"identity_ref", "style_ref"}}
    entities = {item["entity_id"]: item for item in (research_dossier or {}).get("entities", [])}
    available_images = set()
    try:
        for character in package.characters:
            reference = character.reference
            if reference.source == "generate":
                if reference.artifact_ids:
                    raise ValueError("Creative cannot claim generated reference artifacts before production")
            elif reference.source == "attachment":
                if not set(reference.artifact_ids) <= references & uploads:
                    raise ValueError("Character attachments must be this Run's identity_ref or style_ref images")
                for artifact_id in reference.artifact_ids:
                    artifact = attachment_for_owner(artifact_id, run.owner_id, run_id=run.run_id)
                    if (artifact.meta or {}).get("media", {}).get("kind") != "image":
                        raise ValueError("Character references must be images")
                    available_images.add(artifact_id)
            else:
                entity = entities.get(reference.research_entity_id, {})
                selected = [candidate["reference_id"] for candidate in entity.get("candidates", [])
                            if candidate["candidate_id"] == entity.get("selected_candidate_id")]
                if not selected or not set(reference.artifact_ids) <= set(selected):
                    raise ValueError("Research references must match this entity's selected candidate")
                for artifact_id in reference.artifact_ids:
                    reference_for_run(artifact_id, run)
                    available_images.add(artifact_id)
        # Question images cannot smuggle an unrelated artifact into the review UI.
        for question in package.open_questions:
            for option in question.options:
                if option.image_artifact_id and option.image_artifact_id not in available_images:
                    raise ValueError("Clarification image must be an admitted character reference")
    except AppError as error:
        raise ValueError("Character reference is unavailable or does not belong to this Run") from error
    return package.model_dump(mode="json")
