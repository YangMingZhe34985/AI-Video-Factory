"""Convert an authored story board into image gates and typed video dependencies."""
from pydantic import Field

from app.agent.plan_check import frame_params
from app.plans.model_selection import select_generation_model
from app.agent.request_spec import StrictModel
from app.agent.story_spec import StoryPackage
from app.plans.blueprints.common import StoryDraft, artifact, delivery_nodes, node, ref, result


class Params(StrictModel):
    plan: StoryDraft
    story: StoryPackage
    goal: str | None = Field(default=None, min_length=1, max_length=2000)
    compress_output: bool = Field(default=False, strict=True)


def build(params, *, run, caller_agent="director"):
    from app.plans.compiler import request_spec_for_run

    data = Params.model_validate(params)
    plan, story = data.plan, data.story
    spec = request_spec_for_run(run)
    nodes, identities, videos = [], {}, []
    stages = [{"id": "characters", "label": "角色定妆"}]
    scene_ids = [scene.scene_id for scene in plan.scenes]
    shot_ids = [shot.shot_id for shot in plan.shots]
    if len(scene_ids) != len(set(scene_ids)) or len(shot_ids) != len(set(shot_ids)):
        raise ValueError("Story scenes and shots must have unique IDs")
    scene_stages = {scene.scene_id: f"scene_{index:03d}" for index, scene in enumerate(plan.scenes, 1)}
    stages.extend({"id": scene_stages[scene.scene_id], "label": scene.location or scene.scene_id} for scene in plan.scenes)
    beats = {beat.beat_id for beat in story.story.beats}
    for index, character in enumerate(story.characters, 1):
        references = [artifact(value) for value in character.reference.artifact_ids]
        if character.reference.source == "generate" and not references:
            model, image_params = select_generation_model(spec, "t2i", None, run=run,
                params_factory=lambda candidate: frame_params(candidate, plan.aspect_ratio))
            cid = f"character_{index:03d}"
            prompt = (f"{story.style.prompt_prefix}。角色外观固定为：{character.lock_description}。"
                      f"{character.reference.generate_prompt}")
            nodes.append(node(cid, "generate_image", {"mode": "t2i", "prompt": prompt},
                "story-video", caller_agent, model_id=model.model_id,
                params=image_params, stage="characters", gate="preview",
                rationale=f"确认角色 {character.name} 的外观，再生成依赖此身份的画面。"))
            references = [ref(cid, "image")]
        identities[character.character_id] = references
    previous = None
    for index, shot in enumerate(plan.shots):
        if (shot.order != index + 1 or (index == 0) != (shot.transition_in == "start")
                or shot.scene_id not in scene_stages or not set(shot.beat_ids) <= beats
                or not set(shot.character_ids) <= identities.keys()
                or len(shot.character_ids) != len(set(shot.character_ids))
                or len(shot.beat_ids) != len(set(shot.beat_ids))):
            raise ValueError("Story shot order, scene, beat or character reference is invalid")
        tail = shot.transition_in == "tail_frame"
        bridge = shot.transition_in == "keyframe_bridge"
        if ((shot.first_frame.method == "tail_frame") != tail
                or tail and (previous is None or previous.scene_id != shot.scene_id)):
            raise ValueError("Tail-frame continuity requires the preceding shot in the same scene")
        if bridge != (shot.motion.mode == "first_last_frame") or bridge != (shot.end_frame is not None):
            raise ValueError("First/last-frame mode requires a paired end frame and bridge transition")
        stage = scene_stages[shot.scene_id]
        frames = {}
        for field in ("first_frame", "end_frame"):
            frame = getattr(shot, field)
            if frame is None:
                continue
            fid = shot.shot_id + ("_first" if field == "first_frame" else "_last")
            if frame.method == "tail_frame":
                if field != "first_frame" or frame.reference_artifact_ids or frame.model_id or frame.image_mode:
                    raise ValueError("Inherited tail frames cannot specify image generation or references")
                nodes.append(node(fid, "extract_frame", {"video_artifact_id": ref(previous.shot_id, "video"),
                    "position": "last"}, "story-video", caller_agent, stage=stage,
                    rationale="继承上一镜头的末帧，串行保证动作衔接。"))
                frames[field] = ref(fid, "artifact_id")
            elif frame.method == "user_image":
                if len(frame.reference_artifact_ids) != 1 or frame.model_id or frame.image_mode:
                    raise ValueError("User keyframes require exactly one image and no generation settings")
                frames[field] = artifact(frame.reference_artifact_ids[0])
            else:
                references = [artifact(value) for value in frame.reference_artifact_ids]
                for character_id in shot.character_ids:
                    for value in identities[character_id]:
                        if value not in references:
                            references.append(value)
                if frame.image_mode not in {"t2i", "i2i"} or not frame.prompt:
                    raise ValueError("Generated keyframes require an image mode and prompt")
                if (frame.image_mode == "i2i") != bool(references):
                    raise ValueError("Character keyframes require i2i with every selected identity reference")
                model, image_params = select_generation_model(spec, frame.image_mode, frame.model_id,
                    reference_count=len(references), run=run, slot=f"{shot.shot_id}:{field}",
                    params_factory=lambda candidate: frame_params(candidate, plan.aspect_ratio))
                nodes.append(node(fid, "generate_image", {"mode": frame.image_mode, "prompt": frame.prompt,
                    "reference_artifact_ids": references}, "story-video", caller_agent,
                    model_id=model.model_id, params=image_params,
                    stage=stage, gate="preview", rationale=shot.rationale))
                frames[field] = ref(fid, "image")
        inputs = {"prompt": shot.motion.prompt, "first_frame_artifact_id": frames["first_frame"]}
        if "end_frame" in frames:
            inputs["last_frame_artifact_id"] = frames["end_frame"]
        duration = shot.duration_sec
        motion_params = {**shot.motion.params, "duration": int(duration) if duration.is_integer() else duration}
        nodes.append(node(shot.shot_id, "animate_shot", inputs, "story-video", caller_agent,
                          model_id=shot.motion.model_id, params=motion_params, stage=stage, rationale=shot.rationale))
        videos.append(ref(shot.shot_id, "video"))
        previous = shot
    delivery, deliverables = delivery_nodes(videos, "story-video", caller_agent, compress_output=data.compress_output)
    stages.append({"id": "delivery", "label": "成片交付"})
    return result(plan.title, data.goal, run, nodes + delivery, deliverables, stages,
                  ["角色定妆及生成关键帧需通过预览门；尾帧继承串行，独立场景可并行。",
                   "首尾帧为受能力和开关约束的候选方式，尚未验证与首帧生视频的画质对等。"])
