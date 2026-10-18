"""Pure-code production-plan checks. Invalid business drafts stay editable."""

from math import isfinite

from flask import current_app
from pydantic import ValidationError

from app.agent.attachments import attachment_for_owner
from app.agent.director_lite import _aspect_params
from app.agent.model_selection import select_for_request, validate_generation_model
from app.agent.production_plan import normalized_plan, select_plan_model
from app.agent.request_spec import RequestSpec
from app.agent.search.references import reference_for_run
from app.agent.story_spec import StoryPackage, duration_tolerance
from app.api import AppError
from app.models import Artifact
from app.services.storage_service import StorageService
from app.skills.budget import BudgetGuard, estimate_model_cost


def frame_params(model, aspect_ratio):
    """Preview validation and production must use the same aspect/count inputs."""
    return {**_aspect_params({"parameters": model.parameter_schema}, aspect_ratio), "n": 1}


def _character_reference(character, spec, run):
    reference = character["reference"]
    ids = reference["artifact_ids"]
    if reference["source"] == "generate":
        if not ids:
            return
        from app.models import AgentShotTask
        tasks = AgentShotTask.query.filter_by(run_id=run.run_id, target_type="character",
                    target_id=character["character_id"], status="success").all()
        admitted = {artifact_id for task in tasks for artifact_id in task.artifact_ids}
        if not set(ids) <= admitted:
            raise AppError("INVALID_REFERENCE", "Generated character reference has no successful preview task", 422)
        for artifact_id in ids:
            artifact = Artifact.query.filter_by(artifact_id=artifact_id).first()
            if (not artifact or (artifact.job.config or {}).get("skill", {}).get("budget_scope") != run.run_id
                    or not str(artifact.mime_type or "").startswith("image/")):
                raise AppError("INVALID_REFERENCE", "Generated character image is not owned by this Run", 422)
            path = StorageService.resolve(artifact.file_path)
            if not path.resolve().is_relative_to(StorageService.root()) or not path.is_file():
                raise AppError("INVALID_REFERENCE", "Generated character image is unavailable", 422)
    elif reference["source"] == "research":
        for artifact_id in ids:
            reference_for_run(artifact_id, run)
    else:
        admitted = {item.attachment_id for item in spec.attachments
                    if item.kind == "image" and item.role in {"identity_ref", "style_ref"}}
        if not set(ids) <= admitted & set(run.request.get("attachment_ids", [])):
            raise AppError("INVALID_REFERENCE", "Character reference is not an admitted identity/style attachment", 422)
        for artifact_id in ids:
            attachment_for_owner(artifact_id, run.owner_id, run_id=run.run_id)


def check_plan(raw, story, request_spec, *, run, preview_credits=None):
    try:
        plan = normalized_plan(raw)
        story = StoryPackage.model_validate(story).model_dump(mode="json")
        spec = RequestSpec.model_validate(request_spec)
    except (ValidationError, ValueError) as error:
        raise AppError("INVALID_PRODUCTION_PLAN", "Production plan does not match its schema", 422) from error
    issues = []

    def issue(code, message, shot_id=None):
        item = {"code": code, "message": message, "shot_id": shot_id}
        if item not in issues:
            issues.append(item)

    target = spec.target_duration_sec or plan["target_duration_sec"]
    if (abs(sum(shot["duration_sec"] for shot in plan["shots"]) - target) > duration_tolerance(spec)
            or plan["target_duration_sec"] != target):
        issue("DURATION_MISMATCH", "镜头总时长必须在用户目标时长的容差内，不能改写目标时长。")
    if spec.aspect_ratio and plan["aspect_ratio"] != spec.aspect_ratio:
        issue("MODEL_CAPABILITY_MISMATCH", "分镜画幅与用户明确要求不一致。")
    if len(plan["shots"]) > current_app.config.get("AGENT_MAX_STORY_SHOTS", 30):
        issue("INVALID_PRODUCTION_PLAN", "镜头数超过当前计划上限。")
    scenes = {item["scene_id"] for item in plan["scenes"]}
    characters = {item["character_id"]: item for item in story["characters"]}
    beats = {item["beat_id"] for item in story["story"]["beats"]}
    if len(scenes) != len(plan["scenes"]):
        issue("INVALID_REFERENCE", "场景 ID 必须唯一。")
    if len({shot["shot_id"] for shot in plan["shots"]}) != len(plan["shots"]):
        issue("INVALID_TRANSITION", "镜头 ID 必须唯一。")
    valid_character_refs = set()
    for character in characters.values():
        try:
            _character_reference(character, spec, run)
            valid_character_refs.update(character["reference"]["artifact_ids"])
        except AppError:
            issue("INVALID_REFERENCE", f"角色 {character['name']} 的参考图不属于本任务或已失效。")
    attachments = {item.attachment_id: item for item in spec.attachments
                   if item.kind == "image" and item.role != "unused"}
    preview, video = 0.0, 0.0
    for character in characters.values():
        if character["reference"]["source"] == "generate" and not character["reference"]["artifact_ids"]:
            try:
                model = select_for_request(spec, "t2i")
                validate_generation_model(model, "t2i", frame_params(model, plan["aspect_ratio"]))
                preview += estimate_model_cost(model, {"n": 1})
            except AppError:
                issue("MODEL_CAPABILITY_MISMATCH", "角色定妆图没有符合要求的图片模型。")
    for index, shot in enumerate(plan["shots"]):
        sid = shot["shot_id"]
        if shot["order"] != index + 1 or (index == 0) != (shot["transition_in"] == "start"):
            issue("INVALID_TRANSITION", "镜头顺序必须从 1 连续排列，只有首镜头可以使用 start。", sid)
        tail = shot["transition_in"] == "tail_frame"
        if (shot["first_frame"]["method"] == "tail_frame") != tail or (tail and not index):
            issue("INVALID_TRANSITION", "尾帧衔接必须使用上一镜头尾帧，首镜头不可使用尾帧。", sid)
        if tail and index and shot["scene_id"] != plan["shots"][index - 1]["scene_id"]:
            issue("INVALID_TRANSITION", "换场景必须独立生成或硬切，不能借用上一场景尾帧。", sid)
        if (shot["scene_id"] not in scenes or not set(shot["character_ids"]) <= characters.keys()
                or not set(shot["beat_ids"]) <= beats):
            issue("INVALID_REFERENCE", "镜头引用了不存在的场景、角色或剧情节拍。", sid)
        if len(set(shot["character_ids"])) != len(shot["character_ids"]) or len(set(shot["beat_ids"])) != len(shot["beat_ids"]):
            issue("INVALID_REFERENCE", "角色与剧情节拍引用不能重复。", sid)
        bridge = shot["transition_in"] == "keyframe_bridge"
        if bridge != (shot["motion"]["mode"] == "first_last_frame") or bridge != bool(shot["end_frame"]):
            issue("KEYFRAME_BRIDGE_UNAVAILABLE", "首尾帧衔接必须配套首尾帧模式和尾帧。", sid)
        try:
            video_model = select_plan_model(spec, "i2v", shot["motion"]["model_id"], run=run, slot=f"{sid}:motion")
            if bridge and (not current_app.config.get("AGENT_ENABLE_KEYFRAME_BRIDGE", False)
                           or "first_last_frame" not in video_model.capabilities.get("modes", [])):
                issue("KEYFRAME_BRIDGE_UNAVAILABLE", "首尾帧候选方式尚未启用或所选模型不支持。", sid)
            shot["motion"]["params"] = validate_generation_model(video_model, "i2v", shot["motion"]["params"], reference_count=2 if bridge else 1)
            if shot["motion"]["params"].get("n_outputs", 1) != 1:
                issue("MODEL_CAPABILITY_MISMATCH", "每个镜头只能生成一个视频输出。", sid)
            video += estimate_model_cost(video_model, {**shot["motion"]["params"], "n_outputs": 1})
        except AppError:
            issue("MODEL_CAPABILITY_MISMATCH", "视频模型不满足型号要求、时长范围、步长或参数能力。", sid)
        required = {ref for cid in shot["character_ids"] if cid in characters
                    for ref in characters[cid]["reference"]["artifact_ids"]}
        pending = sum(1 for cid in shot["character_ids"] if cid in characters
                      and characters[cid]["reference"]["source"] == "generate"
                      and not characters[cid]["reference"]["artifact_ids"])
        for key in ("first_frame", "end_frame"):
            frame = shot.get(key)
            if frame is None:
                continue
            refs = frame["reference_artifact_ids"]
            if len(refs) != len(set(refs)):
                issue("INVALID_REFERENCE", "图片引用不能重复。", sid)
            for ref in refs:
                if ref in valid_character_refs:
                    continue
                if ref not in attachments or ref not in run.request.get("attachment_ids", []):
                    issue("INVALID_REFERENCE", "图片引用不属于本任务的附件或角色参考图。", sid)
                    continue
                try:
                    attachment_for_owner(ref, run.owner_id, run_id=run.run_id)
                except AppError:
                    issue("INVALID_REFERENCE", "图片附件已失效或无权访问。", sid)
            if frame["method"] == "tail_frame":
                if key == "end_frame" or refs or frame["model_id"] or frame["image_mode"]:
                    issue("INVALID_TRANSITION", "尾帧继承不应包含图片生成模型、模式或引用。", sid)
                continue
            if frame["method"] == "user_image":
                if (len(refs) != 1 or refs[0] not in attachments or attachments[refs[0]].role != "first_frame"
                        or frame["model_id"] or frame["image_mode"]):
                    issue("INVALID_REFERENCE", "用户首帧必须指定一张本任务的 first_frame 图片。", sid)
                continue
            if not frame["image_mode"] or not frame["model_id"]:
                issue("MODEL_CAPABILITY_MISMATCH", "生成关键帧需要明确图片模式与模型。", sid)
                continue
            if (required or pending) and (frame["image_mode"] != "i2i" or not required <= set(refs)):
                issue("CHARACTER_REFERENCE_MISSING", "含角色的关键帧必须以 i2i 引用该角色的全部定妆参考图。", sid)
            try:
                image_model = select_plan_model(spec, frame["image_mode"], frame["model_id"], run=run, slot=f"{sid}:{key}")
                # Missing generated IDs are allowed only as typed pre-preview placeholders.
                validate_generation_model(image_model, frame["image_mode"], frame_params(image_model, plan["aspect_ratio"]),
                                          reference_count=len(refs) + pending)
                preview += estimate_model_cost(image_model, {"n": 1})
            except AppError:
                issue("MODEL_CAPABILITY_MISMATCH", "关键帧模型不满足图片模式、画幅或参考图数量限制。", sid)
    if preview_credits is not None:
        if isinstance(preview_credits, bool) or not isinstance(preview_credits, (int, float)) or not isfinite(preview_credits) or preview_credits < 0:
            raise ValueError("Remaining preview credits must be a finite nonnegative number")
        preview = preview_credits
    estimates = {"preview_credits": round(preview, 6), "video_credits": round(video, 6), "total_credits": round(preview + video, 6)}
    plan["estimates"] = estimates
    if estimates["total_credits"] + BudgetGuard.spent(run.run_id) > run.request["budget_limit"] + 1e-8:
        issue("BUDGET_EXCEEDED", "剩余预算不足以支付所需预览图与预计视频费用。")
    return {"plan": plan, "issues": issues, "estimates": estimates}
