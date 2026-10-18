"""Owner-scoped production quotes and durable user decisions; no direct model calls."""

from copy import deepcopy
from hashlib import sha256

from pydantic import ValidationError

from app.agent import plan_versions as versions
from app.agent.production_state import (dependencies, enabled, latest_tasks, remaining_video_cost,
    shot_cost, update_production, usable_artifact, event)
from app.api import AppError
from app.extensions import db
from app.models import AgentShotTask, Job
from app.skills.budget import BudgetGuard

PRODUCTION_ACTIONS = {"start_production", "retry_shot", "redo_shot", "review_plan", "approve_videos"}
FIELDS = {
    "start_production": {"plan_version", "repair_budget_credits"},
    "retry_shot": {"shot_id", "base_version", "quote_id"},
    "redo_shot": {"shot_id", "base_version", "quote_id", "scope", "motion_prompt"},
    "review_plan": {"plan_version"}, "approve_videos": {"plan_version"},
}
STATES = {"start_production": {"storyboard_approved"}, "retry_shot": {"production_attention", "awaiting_video_review"},
          "redo_shot": {"production_attention", "awaiting_video_review"},
          "review_plan": {"production_attention"}, "approve_videos": {"awaiting_video_review"}}


def command_payload(data):
    from app.agent.protocol import RunAction
    if isinstance(data, dict):
        value = {key: val for key, val in data.items() if key != "command_id"}
        try:
            data = RunAction.model_validate(value)
        except ValidationError as error:
            raise AppError("INVALID_INPUT", "生产动作字段无效。", 422) from error
    if data.action not in PRODUCTION_ACTIONS:
        raise AppError("INVALID_INPUT", "不支持的生产动作。", 422)
    return data.model_dump(mode="json", include={"action", "request_key"} | FIELDS[data.action], exclude_none=True)


def receipt_fingerprint(payload):
    value = command_payload(payload)
    value.pop("request_key", None)
    return versions.inputs_hash(value)


def _version(run, number):
    if not enabled():
        raise AppError("PRODUCTION_DISABLED", "视频生产尚未开启。", 409)
    if run.request.get("schema_version") != 2:
        raise AppError("INVALID_AGENT_STATE", "当前任务没有新版故事分镜。", 409)
    return versions.require_current_version(run, number)


def _idle(run, version):
    tasks = versions.list_tasks(run, version.version)
    if any(task.target_type in {"video", "tail_frame"} and task.status in {"pending", "running"} for task in tasks):
        raise AppError("INVALID_AGENT_STATE", "请等待当前在途镜头结束后再修改。", 409)


def _closure(version, shot_id):
    deps = dependencies(version)
    if shot_id not in deps:
        raise AppError("INVALID_REFERENCE", "镜头不属于当前计划。", 422)
    selected = {shot_id}
    while True:
        updated = selected | {sid for sid, parents in deps.items() if selected.intersection(parents)}
        if updated == selected:
            return [shot["shot_id"] for shot in version.plan["shots"] if shot["shot_id"] in selected]
        selected = updated


def _failure(task):
    from app.agent.production_repair import classify_job_failure
    if task is None or task.status not in {"failed", "stale"}:
        return None
    job = Job.query.filter_by(job_id=task.job_id).first() if task.job_id else None
    return classify_job_failure(job) if job else deepcopy(task.error or {
        "category": "submit_unknown", "submission_state": "unknown", "recovery_action": "stop"})


def _unsafe(task):
    failure = _failure(task) or {}
    return failure.get("category") == "submit_unknown" or failure.get("submission_state") == "unknown"


def _task_fingerprint(task):
    return {"id": task.id, "status": task.status, "inputs_hash": task.inputs_hash,
            "job_id": task.job_id, "invocation_id": task.invocation_id,
            "artifact_ids": task.artifact_ids, "usable": bool(usable_artifact(task)), "error": task.error}


def quote(run, payload, *, review_status=None, _allow_command=False):
    from app.agent.protocol import ProductionQuote
    from app.agent.production_repair import repair_decision
    try:
        value = ProductionQuote.model_validate(payload).model_dump(mode="json", exclude_none=True)
    except ValidationError as error:
        raise AppError("INVALID_INPUT", "生产报价字段无效。", 422) from error
    version = _version(run, value["base_version"])
    operation = value["operation"]
    status = review_status or run.status
    if status not in STATES["retry_shot" if operation == "retry" else "redo_shot"]:
        raise AppError("INVALID_AGENT_STATE", "当前状态不接受生产报价。", 409)
    if run.command and not _allow_command:
        raise AppError("INVALID_AGENT_STATE", "已有操作等待处理。", 409)
    _idle(run, version)
    affected = _closure(version, value["shot_id"])
    tasks = latest_tasks(run, version)
    task = tasks.get(value["shot_id"])
    if not task or task.status not in {"success", "failed", "stale"}:
        raise AppError("INVALID_AGENT_STATE", "此镜头尚未完成一次生产，请先处理上游。", 409)
    if _unsafe(task):
        raise AppError("UNSAFE_RETRY", "提交结果尚未核实，不能重新提交付费任务。", 409)
    missing_success = task.status == "success" and not usable_artifact(task)
    if missing_success and operation == "redo":
        raise AppError("UNSAFE_RETRY", "成功视频的本地文件缺失，请先恢复原任务下载。", 409)
    kept = [sid for sid in affected if sid != task.target_id and usable_artifact(tasks.get(sid))]
    continued = [shot["shot_id"] for shot in version.plan["shots"]
                 if shot["shot_id"] != task.target_id and shot["shot_id"] not in tasks]
    warnings = []
    if kept:
        warnings.append("只重做当前镜头会保留旧下游视频，请接受画面衔接可能变化。")
    if continued:
        warnings.append("原计划未生成的镜头仍将继续：" + "、".join(continued) + "；费用已包含在报价中。")
    costs = {shot["shot_id"]: shot_cost(run, shot) for shot in version.plan["shots"]}
    continuation_cost = sum(costs[sid] for sid in continued)
    can_retry = False
    reason = "由当前镜头与已确认的尾帧依赖决定影响范围。"
    if operation == "retry":
        if missing_success:
            from app.agent.production_repair import classify_job_failure
            job = Job.query.filter_by(job_id=task.job_id).first() if task.job_id else None
            failure = classify_job_failure(job) if job else {}
            free_download = failure.get("recovery_action") == "recover_read" and failure.get("stage") == "download"
            decision = {"action": "recover_read" if free_download else "stop", "estimated_cost": 0.0, "failure": failure}
        else:
            decision = repair_decision(run, task, automatic=False)
        if status == "awaiting_video_review" and not (decision["action"] == "recover_read"
                and decision.get("failure", {}).get("stage") == "download"):
            raise AppError("UNSAFE_RETRY", "视频审核阶段只允许免费恢复已完成视频的下载。", 409)
        can_retry = decision["action"] in {"recover_read", "retry_submit", "rewrite_prompt"}
        only = round(decision["estimated_cost"] + continuation_cost, 6) if can_retry else None
        cascade = None
        reason = {"recover_read": "免费恢复原任务查询或下载，不重新提交模型。", "retry_submit": "原提交被明确拒绝，可以确认费用后重新提交。",
                  "rewrite_prompt": "合规修订一次动作提示词，再重新生成；费用包含修订和视频。"}.get(decision["action"], "当前错误不适合重试，请核实或返回分镜修改。")
    else:
        only = round(costs[task.target_id] + continuation_cost, 6)
        cascade = None if any(_unsafe(tasks.get(sid)) for sid in affected) else round(sum(
            costs[sid] for sid in set(affected) | set(continued)), 6)
        if cascade is None:
            warnings.append("依赖链中存在未核实的提交结果，不能连带重做。")
    result = {"base_version": version.version, "shot_id": task.target_id, "affected_shot_ids": affected,
              "kept_shot_ids": kept, "continuation_shot_ids": continued,
              "estimated_credits": {"only": only, "cascade": cascade}, "can_retry": can_retry,
              "reason": reason, "warnings": warnings}
    fingerprint = {"run_id": run.run_id, "input": value, "result": result,
        "tasks": [_task_fingerprint(item) for item in versions.list_tasks(run, version.version)],
        "repairs": (run.snapshot or {}).get("production_repairs", {})}
    result["quote_id"] = versions.inputs_hash(fingerprint)
    return result


def _current_quote(run, command, *, review_status=None):
    request = {"shot_id": command["shot_id"], "base_version": command["base_version"],
               "operation": "retry" if command["action"] == "retry_shot" else "redo"}
    if command.get("motion_prompt") is not None:
        request["motion_prompt"] = command["motion_prompt"]
    result = quote(run, request, review_status=review_status, _allow_command=True)
    if result["quote_id"] != command["quote_id"]:
        raise AppError("PRODUCTION_QUOTE_EXPIRED", "镜头、费用或计划已变化，请重新确认报价。", 409)
    return result


def validate_command(run, payload, *, review_status=None):
    from app.agent.production_engine import validate_start
    command = command_payload(payload)
    action = command["action"]
    version = _version(run, command.get("base_version") or command.get("plan_version"))
    if (review_status or run.status) not in STATES[action]:
        raise AppError("INVALID_AGENT_STATE", "当前状态不接受此生产动作。", 409)
    if action == "start_production":
        return validate_start(run, version, command.get("repair_budget_credits", 0))
    _idle(run, version)
    if action in {"retry_shot", "redo_shot"}:
        result = _current_quote(run, command, review_status=review_status)
        if command.get("scope") == "cancel":
            return 0.0
        cost = result["estimated_credits"][command.get("scope", "only")]
        if cost is None or (action == "retry_shot" and not result["can_retry"]):
            raise AppError("UNSAFE_RETRY", "此操作不能安全执行，请核实失败原因或修改计划。", 409)
        BudgetGuard.check(run.run_id, run.request["budget_limit"], cost)
        return cost
    if action == "approve_videos":
        if any(not usable_artifact(latest_tasks(run, version).get(shot["shot_id"])) for shot in version.plan["shots"]):
            raise AppError("VIDEO_INCOMPLETE", "仍有缺失或未完成的视频，请先处理。", 409)
        validate_start(run, version, 0)
    return 0.0


def _receipt(run, key):
    return (run.snapshot or {}).get("production_action_receipts", {}).get(key)


def _save_receipt(run, key, **changes):
    locked = versions._lock_run(run)
    snapshot = deepcopy(locked.snapshot or {})
    records = snapshot.setdefault("production_action_receipts", {})
    records.setdefault(key, {}).update(deepcopy(changes))
    locked.snapshot = snapshot
    db.session.commit()
    return records[key]


def _retained(tasks, ids):
    return {sid: {"task_id": tasks[sid].id, "source_version": tasks[sid].plan_version,
        "inputs_hash": tasks[sid].inputs_hash, "job_id": tasks[sid].job_id,
        "invocation_id": tasks[sid].invocation_id, "artifact_ids": deepcopy(tasks[sid].artifact_ids)}
        for sid in ids if usable_artifact(tasks.get(sid))}


def _copy_tasks(run, source, target, force_ids):
    """Copy exact terminal receipts, including unknown failures; never invent a resubmission."""
    locked = versions._lock_run(run)
    existing = {(task.target_type, task.target_id) for task in versions.list_tasks(locked, target.version)}
    for task in versions.list_tasks(locked, source.version):
        if (task.target_type, task.target_id) in existing:
            continue
        if task.target_type in {"video", "tail_frame"} and task.target_id in force_ids:
            continue
        if task.status in {"pending", "running"}:
            raise AppError("INVALID_AGENT_STATE", "旧版本仍有执行中的任务。", 409)
        db.session.add(AgentShotTask(run_id=run.run_id, plan_version=target.version,
            target_type=task.target_type, target_id=task.target_id, attempt=1,
            status=task.status, inputs_hash=task.inputs_hash, invocation_id=task.invocation_id,
            job_id=task.job_id, artifact_ids=deepcopy(task.artifact_ids),
            estimated_cost=task.estimated_cost, error=deepcopy(task.error)))
    db.session.commit()


def _make_intent(run, command, estimate, *, review_status=None):
    version = versions.current_version(run)
    intent = {"source_version": version.version, "status_before": run.status, "estimated_cost": estimate}
    if command["action"] == "redo_shot" and command["scope"] != "cancel":
        result = _current_quote(run, command, review_status=review_status)
        force = [command["shot_id"]] if command["scope"] == "only" else result["affected_shot_ids"]
        tasks = latest_tasks(run, version)
        retained = deepcopy((run.snapshot or {}).get("production", {}).get("retained_sources", {}))
        retained = {sid: value for sid, value in retained.items() if sid not in force}
        if command["scope"] == "only":
            retained.update(_retained(tasks, result["kept_shot_ids"]))
        plan = deepcopy(version.plan)
        if command.get("motion_prompt"):
            next(shot for shot in plan["shots"] if shot["shot_id"] == command["shot_id"])["motion"]["prompt"] = command["motion_prompt"]
        intent.update(plan=plan, story_package=version.story_package, check=version.check,
            force_shot_ids=force, retained_sources=retained)
    elif command["action"] == "retry_shot":
        intent["task_id"] = latest_tasks(run, version)[command["shot_id"]].id
    return intent


def _within_quote(cost, authorized):
    if cost > authorized + 1e-6:
        raise AppError("PRODUCTION_QUOTE_EXPIRED", "当前预计费用超过已确认报价，请重新确认。", 409)


def apply_command(run, payload, registry=None, *, review_status=None):
    from app.agent.production_engine import begin_production, retry_shot
    from app.skills import get_registry
    command = command_payload(payload)
    key, fingerprint = command["request_key"], receipt_fingerprint(command)
    receipt = _receipt(run, key)
    if receipt and receipt.get("inputs_hash") != fingerprint:
        raise AppError("IDEMPOTENCY_KEY_CONFLICT", "操作标识已用于其他内容。", 409)
    if receipt and receipt.get("result"):
        return deepcopy(receipt["result"])
    if not receipt or not receipt.get("intent"):
        estimate = validate_command(run, command, review_status=review_status)
        intent = _make_intent(run, command, estimate, review_status=review_status)
        if review_status:
            intent["status_before"] = review_status
        receipt = _save_receipt(run, key, inputs_hash=fingerprint, estimated_cost=estimate,
            status="applying", action=command["action"], scope=command.get("scope"), intent=intent)
    intent = receipt["intent"]
    if not enabled():
        raise AppError("PRODUCTION_DISABLED", "视频生产尚未开启。", 409)
    source = versions.get_version(run, intent["source_version"])
    version = source
    action = command["action"]
    if action == "start_production":
        _within_quote(remaining_video_cost(run, source) + command.get("repair_budget_credits", 0), intent["estimated_cost"])
        status = begin_production(run, source, command.get("repair_budget_credits", 0))
    elif action == "redo_shot" and command["scope"] == "cancel":
        status = intent["status_before"]
    elif action == "redo_shot":
        operation_key = "production-version:" + sha256(key.encode()).hexdigest()
        version = versions.create_version(run, intent["plan"], intent["story_package"], intent["check"],
            author="user", base_version=source.version, operation_key=operation_key)
        _copy_tasks(run, source, version, set(intent["force_shot_ids"]))
        update_production(run, plan_version=version.version, force_shot_ids=intent["force_shot_ids"],
            retained_sources=intent["retained_sources"])
        _within_quote(remaining_video_cost(run, version), intent["estimated_cost"])
        event(run, "cascade_confirmed", key=key, scope=command["scope"], shot_ids=intent["force_shot_ids"])
        status = begin_production(run, version, 0)
    elif action == "retry_shot":
        task = db.session.get(AgentShotTask, intent["task_id"])
        if task.status == "success" and not usable_artifact(task):
            versions.mark_stale(run, task.plan_version, target_type="video", target_ids={task.target_id})
        from app.agent.production_repair import repair_decision
        decision = repair_decision(run, task, automatic=False)
        _within_quote(decision["estimated_cost"], intent["estimated_cost"])
        # retry_shot owns a durable failed-task receipt and may safely be replayed.
        retry_shot(run, task, registry or get_registry(), automatic=False)
        status = "producing"
        update_production(run, status=status)
    elif action == "review_plan":
        status = "awaiting_storyboard"
        update_production(run, approved_version=None, status=status)
    else:
        status = "videos_approved"
        event(run, "videos_approved", key=key)
        update_production(run, status=status)
    result = {"status": status, "plan_version": version.version, "plan": deepcopy(version.plan),
              "story_package": deepcopy(version.story_package)}
    _save_receipt(run, key, status="completed", result=result)
    return result
