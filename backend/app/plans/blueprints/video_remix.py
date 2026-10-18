"""Preserve source intervals and regenerate only selected independent clips."""
from pydantic import Field, model_validator
from app.agent.plan_spec import PlanSpec
from app.agent.request_spec import StrictModel
from app.agents.workspace import require_artifact
from app.api import AppError
from app.plans.blueprints.common import artifact, delivery_nodes, node, ref, result
from app.services.media_probe_service import MediaProbeService
from app.services.storage_service import StorageService
from app.tools.spec import ToolContext


class Params(StrictModel):
    plan: PlanSpec
    source_artifact_id: str = Field(min_length=1, max_length=80)
    goal: str | None = Field(default=None, min_length=1, max_length=2000)
    compress_output: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def correct_recipe(self):
        if self.plan.mode != "remix":
            raise ValueError("video-remix requires mode=remix")
        return self


def source_duration(run, artifact_id):
    source = require_artifact(artifact_id, ToolContext(role="production", budget_scope=run.run_id), run=run)
    if not str(source.mime_type or "").startswith("video/"):
        raise AppError("INVALID_SOURCE_RANGE", "Remix requires an owned source video", 422)
    return MediaProbeService.probe(StorageService.resolve(source.file_path), decode=True)["duration_sec"]


def build(params, *, run, caller_agent="director"):
    data = Params.model_validate(params)
    duration = source_duration(run, data.source_artifact_id)
    if any(shot.source_end > duration for shot in data.plan.shots):
        raise AppError("INVALID_SOURCE_RANGE", "Retained and replaced ranges must lie inside the source video", 422)
    nodes, videos = [], []
    source = artifact(data.source_artifact_id)
    for index, shot in enumerate(data.plan.shots, 1):
        prefix = f"s{index:03d}"
        if shot.action == "keep":
            nodes.append(node(prefix, "retain_video_segment", {"video_artifact_id": source,
                "source_start_sec": shot.source_start, "source_end_sec": shot.source_end}, "video-remix", caller_agent,
                stage="shots", rationale=shot.edit_reason))
            videos.append(ref(prefix, "artifact_id"))
            continue
        frame = prefix + "_frame"
        if shot.first_frame_mode == "source":
            nodes.append(node(frame, "extract_frame", {"video_artifact_id": source,
                "position": "first", "timestamp_sec": shot.source_start}, "video-remix", caller_agent,
                stage="shots", rationale="从所替换原片区间的起点抽取首帧。"))
            image = ref(frame, "artifact_id")
        else:
            nodes.append(node(frame, "generate_image", {"mode": "t2i", "prompt": shot.first_frame_prompt},
                "video-remix", caller_agent, model_id=shot.image_model_id, params={**shot.image_params, "n": 1},
                stage="shots", rationale=shot.edit_reason))
            image = ref(frame, "image")
        nodes.append(node(prefix, "animate_shot", {"first_frame_artifact_id": image, "prompt": shot.i2v_prompt},
            "video-remix", caller_agent, model_id=shot.video_model_id, params=shot.video_params,
            stage="shots", rationale=shot.edit_reason))
        videos.append(ref(prefix, "video"))
    delivery, deliverables = delivery_nodes(videos, "video-remix", caller_agent, compress_output=data.compress_output)
    return result(data.plan.title, data.goal, run, nodes + delivery, deliverables,
                  [{"id": "shots", "label": "保留与局部重生成"}, {"id": "delivery", "label": "成片交付"}],
                  ["原片区间仅决定保留或替换范围，生成片段时长独立使用视频参数 duration；默认不额外压缩。"])
