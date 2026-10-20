"""Pure deterministic authoring helpers; compilation grants no execution rights."""
from typing import Literal

from pydantic import Field, model_validator

from app.agent.production_plan import Scene, ShotPlan
from app.agent.request_spec import StrictModel
from app.agent.simple_plan import ImageStep, SimplePlan, VideoStep
from app.agent.transform_media import MediaReference
from app.agents.schemas import PlanDraft

VERSION = 2


class SimpleDraft(StrictModel):
    recipe: Literal["image_edit", "image_create", "single_clip"]
    title: str = Field(min_length=1, max_length=200)
    image: ImageStep | None = None
    video: VideoStep | None = None
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    rationale: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_steps(self):
        SimplePlan.model_validate(self.model_dump(mode="json"))
        return self


class StoryDraft(StrictModel):
    recipe: Literal["story_video"] = "story_video"
    title: str = Field(min_length=1, max_length=200)
    target_duration_sec: float = Field(gt=0, le=600, strict=True, allow_inf_nan=False)
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:3", "3:4"] = "16:9"
    scenes: list[Scene] = Field(min_length=1, max_length=12)
    shots: list[ShotPlan] = Field(min_length=1, max_length=120)
    rationale: str = Field(default="", max_length=1500)


class TransformDraft(StrictModel):
    recipe: Literal["video_transform"] = "video_transform"
    operation: Literal["reference", "edit", "extend"]
    title: str = Field(min_length=1, max_length=200)
    model_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=8000)
    params: dict = Field(default_factory=dict)
    media: list[MediaReference] = Field(min_length=1, max_length=20)
    source_artifact_id: str | None = None
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    rationale: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_media(self):
        from app.agent.transform_plan import TransformPlan
        TransformPlan.model_validate(self.model_dump(mode="json"))
        return self


def artifact(value):
    return {"artifact": value}


def ref(node_id, output):
    return {"ref": f"{node_id}.{output}"}


def node(name, tool, inputs, blueprint, agent, *, model_id=None, params=None,
         stage=None, gate=None, depends_on=None, rationale="", characters=None):
    value = {"id": name, "tool": tool, "inputs": inputs, "model_id": model_id,
            "params": params or {}, "stage": stage, "gate": gate,
            "depends_on": depends_on or [], "origin": {"agent": agent, "skills": [blueprint],
                "blueprint": {"name": blueprint, "version": VERSION}}, "rationale": rationale[:300]}
    if characters is not None:
        value["characters"] = list(characters)
    return value


def result(title, goal, run, nodes, deliverables, stages, notes=None, *, character_references=None):
    draft = {"title": title, "goal": goal or str((run.request or {}).get("text") or title)[:2000],
             "nodes": nodes, "deliverables": deliverables, "stages": stages}
    if character_references:
        draft["character_references"] = character_references
    return {"plan": PlanDraft.model_validate(draft).model_dump(mode="json"), "notes": notes or []}


def build_simple(data, name, run, agent):
    plan, nodes = data.plan, []
    if plan.image:
        image = plan.image
        nodes.append(node("image", "generate_image", {"mode": image.mode, "prompt": image.prompt,
            "reference_artifact_ids": [artifact(value) for value in image.reference_attachment_ids]},
            name, agent, model_id=image.model_id, params={**image.params, "n": image.n}, stage="creation",
            rationale=plan.rationale))
    if plan.video:
        video = plan.video
        first = ref("image", "image") if video.first_frame == "generated_image" else artifact(video.first_frame_attachment_id)
        nodes.append(node("video", "animate_shot", {"first_frame_artifact_id": first, "prompt": video.prompt},
            name, agent, model_id=video.model_id, params=video.params, stage="creation", rationale=plan.rationale))
    deliverables = [{"kind": "video", "node_id": "video", "output": "video"}] if plan.video else [
        {"kind": "image", "node_id": "image", "output": "images"}]
    return result(plan.title, data.goal, run, nodes, deliverables, [{"id": "creation", "label": "创作"}])


def delivery_nodes(videos, blueprint, agent, *, compress_output=False):
    """QC is an explicit control predecessor, not an artifact placeholder."""
    nodes = [
        node("compose", "compose_video", {"video_artifact_ids": videos, "compress_output": compress_output},
             blueprint, agent, stage="delivery", rationale="按审核顺序拼接原始片段。"),
        node("probe", "probe_media", {"artifact_id": ref("compose", "artifact_id")},
             blueprint, agent, stage="delivery", rationale="验证成片媒体结构。"),
        node("qc", "qc_video", {"artifact_id": ref("compose", "artifact_id"), "video_artifact_ids": videos},
             blueprint, agent, stage="delivery", depends_on=["probe"], rationale="验证成片与批准片段的完整性。"),
    ]
    package_inputs = {"artifact_id": ref("compose", "artifact_id")}
    if compress_output:
        package_inputs["compressed_artifact_id"] = ref("compose", "compressed_artifact_id")
    nodes.append(node("package", "package_story", package_inputs, blueprint, agent, stage="delivery",
                      depends_on=["qc"], rationale="质检通过后打包主片与批准素材。"))
    deliverables = [{"kind": "video", "node_id": "compose", "output": "artifact_id"},
                    {"kind": "package", "node_id": "package", "output": "artifact_id"}]
    if compress_output:
        deliverables.append({"kind": "video", "node_id": "compose", "output": "compressed_artifact_id"})
    return nodes, deliverables
