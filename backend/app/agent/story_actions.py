"""Command validation and public projections for the story-board review gates."""

from copy import deepcopy

from flask import current_app
from pydantic import ValidationError

from app.agent.plan_versions import current_version, inputs_hash, require_current_version
from app.agent.production_plan import normalized_plan, promptless_shot
from app.api import AppError
from app.models import ToolInvocation
from app.skills.budget import BudgetGuard

STORY_ACTIONS = {"approve_characters", "regenerate", "regenerate_stale", "edit_plan", "approve_storyboard"}
REVIEW_STATUSES = {"awaiting_characters", "awaiting_storyboard"}


def is_story_run(run):
    return run.request.get("schema_version") == 2 and current_version(run) is not None


def rules():
    return {"duration_tolerance_ratio": current_app.config.get("AGENT_STORY_DURATION_TOLERANCE_RATIO", 0.1),
            "max_shots": current_app.config.get("AGENT_MAX_STORY_SHOTS", 30),
            "keyframe_bridge_enabled": current_app.config.get("AGENT_ENABLE_KEYFRAME_BRIDGE", False)}


def public_view(run):
    from app.agent.preview_production import preview_view
    version = current_version(run)
    if not version:
        return {}
    estimates = dict(version.check.get("estimates") or version.plan.get("estimates") or {})
    estimates.update(spent_credits=BudgetGuard.spent(run.run_id), preview_spent_credits=sum(
        row.estimated_cost for row in ToolInvocation.query.filter_by(budget_scope=run.run_id, tool_name="generate_image")
        if row.status != "rejected"))
    return {"story": version.story_package, "plan": version.plan, "plan_version": version.version,
            "plan_issues": version.check.get("issues", []), "estimates": estimates,
            "previews": preview_view(run, version), "story_rules": rules()}


def missing_prompt_issues(plan):
    return [{"code": "MISSING_PROMPT", "shot_id": shot["shot_id"], "message": "生成提示词不能为空，请编辑或重新规划该镜头。"}
            for shot in plan["shots"] if not shot["motion"]["prompt"].strip() or any(
                frame and frame["method"] == "generate" and not frame["prompt"].strip()
                for frame in (shot["first_frame"], shot.get("end_frame")))]


def parse_plan(raw):
    try:
        return normalized_plan(raw)
    except ValidationError as error:
        raise AppError("INVALID_PRODUCTION_PLAN", "分镜结构无效，请检查必填字段。", 422,
                       payload={"errors": error.errors(include_url=False, include_context=False, include_input=False)}) from error


def changed_shots(previous, plan):
    old = {shot["shot_id"]: shot for shot in previous["shots"]}
    return [shot["shot_id"] for shot in plan["shots"]
            if shot["shot_id"] not in old or promptless_shot(shot) != promptless_shot(old[shot["shot_id"]])]


def selected_targets(version, command):
    from app.agent.preview_production import targets_for
    action = command["action"]
    if action == "regenerate":
        target = (command["target_type"], command["target_id"])
        if target not in [tuple(value) for value in targets_for(version, phase="all")]:
            raise AppError("INVALID_REFERENCE", "该目标不需要生成预览。", 422)
        if target[0] == "character":
            character = next(item for item in version.story_package["characters"] if item["character_id"] == target[1])
            if character["reference"]["source"] != "generate":
                raise AppError("INVALID_REFERENCE", "检索和附件参考图不能被隐式替换。", 422)
        else:
            shot = next(item for item in version.plan["shots"] if item["shot_id"] == target[1])
            frame = shot["end_frame"] if target[0] == "end_frame" else shot["first_frame"]
            if frame["method"] != "generate":
                raise AppError("INVALID_REFERENCE", "该镜头使用已有图片或视频尾帧。", 422)
        return [target]
    return []


def stale_targets(run, version):
    from app.agent.preview_production import preview_view
    view = preview_view(run, version)
    return [(kind, target_id) for key, kind in (("keyframes", "keyframe"), ("end_frames", "end_frame"))
            for target_id, item in view[key].items() if item.get("stale") or item.get("status") == "stale"]


def require_previews(run, version, phase):
    from app.agent.preview_production import preview_view, targets_for
    view = preview_view(run, version)
    missing = []
    for kind, target_id in targets_for(version, phase=phase):
        key = {"character": "characters", "keyframe": "keyframes", "end_frame": "end_frames"}[kind]
        preview = view[key].get(target_id, {})
        if preview.get("status") != "success" or preview.get("stale") or not preview.get("artifact_id"):
            missing.append({"target_type": kind, "target_id": target_id})
    if missing:
        raise AppError("PREVIEW_INCOMPLETE", "仍有缺失、失败或过期的预览，请先处理。", 409,
                       payload={"targets": missing})


def validate_command(run, command, *, review_status=None):
    """Pure admission checks; the graph repeats them immediately before effects."""
    from app.agent.plan_check import check_plan
    from app.agent.preview_production import preview_cost
    version = current_version(run)
    if not version:
        raise AppError("INVALID_AGENT_STATE", "当前任务没有新版分镜计划。", 409)
    action = command["action"]
    expected = {"approve_characters": {"awaiting_characters"}, "edit_plan": {"awaiting_storyboard"},
                "approve_storyboard": {"awaiting_storyboard"}, "regenerate_stale": {"awaiting_storyboard"},
                "regenerate": REVIEW_STATUSES, "reject": REVIEW_STATUSES}[action]
    status = review_status if review_status is not None else run.status
    if status not in expected:
        raise AppError("INVALID_AGENT_STATE", "当前状态不接受此审核动作。", 409)
    estimate = 0.0
    if action == "edit_plan":
        require_current_version(run, command["base_version"])
        parse_plan(command["plan"])
    elif action == "approve_storyboard":
        require_current_version(run, command["plan_version"])
        require_previews(run, version, "all")
        checked = check_plan(version.plan, version.story_package, run.snapshot["request_spec"], run=run, preview_credits=0)
        checked["issues"].extend(missing_prompt_issues(checked["plan"]))
        if checked["issues"]:
            raise AppError("INVALID_PRODUCTION_PLAN", "分镜仍有问题，请修改后再确认。", 422,
                           payload={"plan_issues": checked["issues"]})
        BudgetGuard.check(run.run_id, run.request["budget_limit"], checked["estimates"]["video_credits"])
    elif action == "approve_characters":
        require_previews(run, version, "characters")
        characters = {item["character_id"]: item for item in version.story_package["characters"]}
        ids = [edit["character_id"] for edit in command.get("edits", [])]
        if len(ids) != len(set(ids)) or any(cid not in characters for cid in ids):
            raise AppError("INVALID_REFERENCE", "角色编辑必须指向当前计划中的不同角色。", 422)
        for edit in command.get("edits", []):
            if edit.get("generate_prompt") and characters[edit["character_id"]]["reference"]["source"] != "generate":
                raise AppError("INVALID_INPUT", "只有生成定妆角色可以修改生成提示词。", 422)
    elif action in {"regenerate", "regenerate_stale"}:
        targets = stale_targets(run, version) if action == "regenerate_stale" else selected_targets(version, command)
        if action == "regenerate" and status == "awaiting_characters" and command["target_type"] != "character":
            raise AppError("INVALID_AGENT_STATE", "请先确认角色定妆。", 409)
        if command.get("prompt") and command.get("target_type") == "character" and len(command["prompt"]) > 2000:
            raise AppError("INVALID_INPUT", "角色定妆提示词不能超过 2000 字符。", 422)
        estimate = preview_cost(run, version, targets, force=True)
        BudgetGuard.check(run.run_id, run.request["budget_limit"], estimate)
    return estimate


def receipt_payload(data):
    payload = data.model_dump(mode="json", exclude_none=True)
    payload.pop("request_key", None)
    return inputs_hash(payload)
