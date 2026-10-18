"""Dependency-driven story production using durable tasks and shared Job/MQ skills."""

from copy import deepcopy

from flask import current_app

from app.agent import plan_versions as versions
from app.agent.production_state import (dependencies, enabled, event, latest_tasks, remaining_video_cost,
    shot_cost, update_production, usable_artifact, video_inputs)
from app.agent.recovery import invoke_once, recover_job
from app.api import AppError
from app.extensions import db
from app.models import AgentShotTask, Job, ToolInvocation
from app.skills.budget import BudgetGuard
from app.skills.spec import ToolContext


def validate_start(run, version, repair_budget_credits=0):
    from app.agent.plan_check import check_plan
    from app.agent.story_actions import missing_prompt_issues, require_previews
    if not enabled():
        raise AppError("PRODUCTION_DISABLED", "视频生产尚未开启。", 409)
    versions.require_current_version(run, version.version)
    require_previews(run, version, "all")
    checked = check_plan(version.plan, version.story_package, run.snapshot["request_spec"], run=run, preview_credits=0)
    issues = [item for item in checked["issues"] if item["code"] != "BUDGET_EXCEEDED"]
    issues.extend(missing_prompt_issues(checked["plan"]))
    if issues:
        raise AppError("INVALID_PRODUCTION_PLAN", "分镜仍有问题，请修改后重新审核。", 422, payload={"plan_issues": issues})
    import math
    if isinstance(repair_budget_credits, bool) or not isinstance(repair_budget_credits, (int, float)) or not math.isfinite(repair_budget_credits) or repair_budget_credits < 0:
        raise AppError("INVALID_INPUT", "修复额度必须是非负有限数值。", 422)
    cost = remaining_video_cost(run, version)
    BudgetGuard.check(run.run_id, run.request["budget_limit"], cost + repair_budget_credits)
    return cost + repair_budget_credits


def begin_production(run, version, repair_budget_credits=0):
    version = versions.get_version(run, version.version if hasattr(version, "version") else version)
    validate_start(run, version, repair_budget_credits)
    metadata = (run.snapshot or {}).get("production", {})
    values = {} if metadata.get("plan_version") == version.version else {
        "retained_sources": {}, "force_shot_ids": []}
    update_production(run, **values, plan_version=version.version, approved_version=version.version,
                      repair_budget_credits=repair_budget_credits, status="producing",
                      approved_shot_costs={shot["shot_id"]: shot_cost(run, shot) for shot in version.plan["shots"]})
    event(run, "production_started")
    return "producing"


def _context(run, task, *, polling=False):
    from app.agent.production_policy import invocation_key
    return ToolContext(role="production", approved=True, budget_scope=run.run_id,
        budget_limit=run.request["budget_limit"], idempotency_key=invocation_key(task),
        shot_task_id=None if polling else task.id)


def _inputs(run, version, shot, task=None):
    data = video_inputs(run, version, shot)
    receipts = (run.snapshot or {}).get("production_repairs", {})
    seen = set()
    while data and task and task.id not in seen:
        seen.add(task.id)
        receipt = next((item for item in receipts.values() if item.get("replacement_task_id") == task.id), None)
        if not receipt:
            break
        if receipt.get("motion_prompt"):
            data["prompt"] = receipt["motion_prompt"]
            break
        task = db.session.get(AgentShotTask, receipt.get("failed_task_id"))
    return data


def _local_failure(error):
    invalid = error.code in {"INVALID_INPUT", "INVALID_REFERENCE", "INVALID_PRODUCTION_PLAN",
        "MODEL_CAPABILITY_MISMATCH", "MODEL_SELECTION_UNSATISFIED", "KEYFRAME_BRIDGE_UNAVAILABLE",
        "MODEL_PRICE_CHANGED", "REPAIR_BUDGET_EXCEEDED"}
    return {"category": "invalid_parameters" if invalid else "submit_unknown",
        "code": error.code, "summary": error.message, "stage": "local" if invalid else "submit",
        "submission_state": "not_submitted" if invalid else "unknown", "provider_task_id": None,
        "recovery_action": "replan" if invalid else "stop"}


def _submit(run, task, data, registry):
    ctx = _context(run, task)
    try:
        previous = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).first()
        if previous is None:
            version = versions.get_version(run, task.plan_version)
            shot = next(item for item in version.plan["shots"] if item["shot_id"] == task.target_id)
            cost = shot_cost(run, shot)
            receipt = next((item for item in (run.snapshot or {}).get("production_repairs", {}).values()
                            if item.get("replacement_task_id") == task.id), None)
            if receipt:
                rewrite = ToolInvocation.query.filter_by(invocation_id=receipt.get("invocation_id")).first() if receipt.get("invocation_id") else None
                used = rewrite.estimated_cost if rewrite and rewrite.status != "rejected" else 0
                if cost + used > receipt.get("reserved_credits", 0) + 1e-6:
                    raise AppError("REPAIR_BUDGET_EXCEEDED", "修复单价已变更，请重新审核费用。", 409)
            else:
                approved = (run.snapshot or {}).get("production", {}).get("approved_shot_costs", {}).get(task.target_id, task.estimated_cost)
                if cost > approved + 1e-6:
                    raise AppError("MODEL_PRICE_CHANGED", "模型单价已上涨，请重新审核费用。", 409)
        response = invoke_once(registry, "animate_shot", data, ctx)
        versions.update_task(run, task, status="running", invocation_id=response["invocation_id"],
                             job_id=response["output"]["job_id"])
        event(run, "shot_submitted", task=task)
    except AppError as error:
        previous = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).first()
        if previous and previous.job:
            versions.update_task(run, task, status="running", invocation_id=previous.invocation_id,
                                 job_id=previous.job.job_id)
        else:
            versions.update_task(run, task, status="failed", error=_local_failure(error))
            event(run, "shot_failed", task=task)
    if task.status == "failed":
        _finish_repairs(run, task)


def _finish_repairs(run, task):
    from app.agent.production_repair import record_repair
    for key, receipt in list((run.snapshot or {}).get("production_repairs", {}).items()):
        if receipt.get("replacement_task_id") == task.id and receipt.get("status") == "running":
            original = db.session.get(AgentShotTask, int(key))
            record_repair(run, original, status="completed" if task.status == "success" else "failed")


def _poll(run, version, registry):
    from app.agent.production_repair import classify_job_failure
    for task in latest_tasks(run, version).values():
        if task.status != "running" or not task.job_id:
            continue
        job = Job.query.filter_by(job_id=task.job_id).one()
        try:
            recover_job(job, run.run_id)
            report = registry.invoke("get_task_status", {"job_id": task.job_id}, _context(run, task, polling=True))["output"]
            if not report["terminal"] and not report["overdue"]:
                continue
            # Query the artifact itself as well; status responses alone are not a
            # success receipt when a download vanished or never completed.
            from types import SimpleNamespace
            candidates = [item["artifact_id"] for item in report["artifacts"] if item["artifact_type"] == "i2v_video"]
            candidate = SimpleNamespace(status="success", artifact_ids=candidates, target_type="video", run_id=run.run_id)
            artifact = usable_artifact(candidate)
            recovered = False
            if artifact and report["status"] == "partial_success":
                from app.models import ApiTask
                api = db.session.get(ApiTask, artifact.api_task_id) if artifact.api_task_id else None
                recovered = bool(api and api.job_id == job.id and api.provider_task_id
                    and (api.response_payload or {}).get("status") == "success" and any(
                        item.get("action") == "recover_read" and item.get("replacement_task_id") == task.id
                        and item.get("status") == "running"
                        for item in (run.snapshot or {}).get("production_repairs", {}).values()))
            good = bool(artifact) and (report["status"] == "success" or recovered)
            failure = None if good else classify_job_failure(job)
            versions.update_task(run, task, status="success" if good else "failed",
                artifact_ids=[artifact.artifact_id] if good else [], error=failure)
        except AppError as error:
            versions.update_task(run, task, status="failed", error=_local_failure(error))
        event(run, "shot_completed" if task.status == "success" else "shot_failed", task=task)
        _finish_repairs(run, task)


def retry_shot(run, task, registry, *, automatic=False):
    from app.agent.production_repair import (claim_repair, recover_read, record_repair,
        repair_decision, rewrite_motion_prompt)
    decision = repair_decision(run, task, automatic=automatic)
    receipt = claim_repair(run, task, decision, automatic=automatic)
    if receipt["action"] not in {"retry_submit", "recover_read", "rewrite_prompt"} or receipt["status"] in {"stopped", "failed", "completed"}:
        return False
    event(run, "repair_reserved", task=task)
    version = versions.require_current_version(run, task.plan_version)
    shot = next(item for item in version.plan["shots"] if item["shot_id"] == task.target_id)
    data = _inputs(run, version, shot, task)
    if not data:
        return False
    if receipt["action"] == "rewrite_prompt":
        data["prompt"] = rewrite_motion_prompt(run, task, shot, registry)
    replacement = db.session.get(AgentShotTask, receipt.get("replacement_task_id")) if receipt.get("replacement_task_id") else None
    if replacement is None:
        latest = versions.latest_task(run, version.version, "video", task.target_id)
        if latest.id != task.id and latest.inputs_hash == versions.inputs_hash(data):
            replacement = latest
        else:
            replacement = versions.create_task(run, version.version, "video", task.target_id, data,
                                               estimated_cost=shot_cost(run, shot), reuse=False, force=True)
        record_repair(run, task, status="running", replacement_task_id=replacement.id)
    if replacement.status != "pending":
        return True
    if receipt["action"] == "recover_read":
        result = recover_read(run, task, registry)
        # Keep the paid original invocation; the separate free recovery tool
        # owns its own immutable ledger receipt.
        versions.update_task(run, replacement, status="running", job_id=result["output"]["job_id"],
                             invocation_id=task.invocation_id)
    else:
        _submit(run, replacement, data, registry)
    return True


def recoverable_tail(run, version, shot_id):
    """Find a local dependency failure without treating it as a paid video failure."""
    tasks = latest_tasks(run, version)
    parents = dependencies(version).get(shot_id, [])
    if shot_id in tasks or not parents:
        return None
    source = tasks.get(parents[0])
    video = usable_artifact(source)
    if not video or (source.error or {}).get("category") == "submit_unknown":
        return None
    tail = versions.latest_task(run, version.version, "tail_frame", parents[0])
    if not tail or tail.status not in {"failed", "stale", "success"} or usable_artifact(tail):
        return None
    from app.skills.tools.extract_frame import ExtractFrameInput
    data = ExtractFrameInput(video_artifact_id=video.artifact_id, position="last").model_dump(mode="json")
    if tail.inputs_hash != versions.inputs_hash(data):
        return None
    return {"shot_id": shot_id, "source_task_id": source.id, "tail_task_id": tail.id,
            "video_artifact_id": video.artifact_id, "restore_existing": tail.status == "success"}


def _run_tail(run, task, data, registry):
    try:
        response = invoke_once(registry, "extract_frame", data, _context(run, task))
        versions.update_task(run, task, status="success", invocation_id=response["invocation_id"],
                             artifact_ids=[response["output"]["artifact_id"]], error=None)
    except AppError as error:
        failure = {"category": "transient", "code": error.code, "summary": error.message,
                   "stage": "local", "submission_state": "not_submitted", "provider_task_id": None,
                   "recovery_action": "recover_tail"}
        if task.status == "success":
            versions.mark_stale(run, task.plan_version, target_type="tail_frame", target_ids={task.target_id})
            event(run, "tail_extraction_failed", task=task, error=failure)
        else:
            versions.update_task(run, task, status="failed", error=failure)
    return bool(usable_artifact(task))


def retry_tail(run, version, recovery, registry):
    """Restore one approved tail from the successful source; never regenerate its video."""
    versions.require_current_version(run, version.version)
    if (run.snapshot or {}).get("production", {}).get("approved_version") != version.version:
        raise AppError("PLAN_VERSION_CONFLICT", "当前版本尚未批准生产。", 409)
    parents = dependencies(version).get(recovery["shot_id"], [])
    source = latest_tasks(run, version).get(parents[0]) if parents else None
    video = usable_artifact(source)
    original = db.session.get(AgentShotTask, recovery["tail_task_id"])
    if (not source or source.id != recovery["source_task_id"] or not video
            or video.artifact_id != recovery["video_artifact_id"]
            or (source.error or {}).get("category") == "submit_unknown"
            or not original or original.run_id != run.run_id or original.plan_version != version.version
            or original.target_type != "tail_frame" or original.target_id != source.target_id):
        raise AppError("UNSAFE_RETRY", "上游视频或提帧任务已变化，请刷新后重试。", 409)
    from app.skills.tools.extract_frame import ExtractFrameInput
    data = ExtractFrameInput(video_artifact_id=video.artifact_id, position="last").model_dump(mode="json")
    task = versions.latest_task(run, version.version, "tail_frame", source.target_id)
    if original.inputs_hash != versions.inputs_hash(data) or task.inputs_hash != original.inputs_hash:
        raise AppError("UNSAFE_RETRY", "尾帧输入已变化，请刷新后重试。", 409)
    if task.id == original.id and task.status in {"failed", "stale"}:
        if recovery.get("restore_existing"):
            return False  # This action already attempted to restore its original successful receipt.
        task = versions.create_task(run, version.version, "tail_frame", source.target_id, data, force=True)
    elif task.id != original.id and task.attempt != original.attempt + 1:
        raise AppError("UNSAFE_RETRY", "已有其他提帧修复，请刷新后重试。", 409)
    if usable_artifact(task):
        return True
    if task.status in {"failed", "stale", "cancelled"}:
        return False  # One new local attempt per explicit action, including crash recovery.
    return _run_tail(run, task, data, registry)


def _extract_tail(run, version, source_id, registry):
    from app.skills.tools.extract_frame import ExtractFrameInput
    source = latest_tasks(run, version).get(source_id)
    video = usable_artifact(source)
    if not video:
        return False
    data = ExtractFrameInput(video_artifact_id=video.artifact_id, position="last").model_dump(mode="json")
    task = versions.latest_task(run, version.version, "tail_frame", source_id)
    if task and task.inputs_hash != versions.inputs_hash(data):
        if task.status != "stale":
            versions.mark_stale(run, version.version, target_type="tail_frame", target_ids={source_id})
        task = versions.create_task(run, version.version, "tail_frame", source_id, data, force=True)
    elif task is None:
        task = versions.create_task(run, version.version, "tail_frame", source_id, data)
    if usable_artifact(task):
        return True
    if task.status in {"failed", "stale", "cancelled"}:
        return False
    return _run_tail(run, task, data, registry)


def tick_production(run, registry):
    version = versions.current_version(run)
    metadata = (run.snapshot or {}).get("production", {})
    if not enabled() or not version or metadata.get("approved_version") != version.version:
        raise AppError("PRODUCTION_DISABLED", "当前版本尚未授权视频生产。", 409)
    _poll(run, version, registry)
    limit = max(1, int(current_app.config.get("AGENT_MAX_PARALLEL_SHOTS", 3)))

    def slot_available():
        return sum(item.status == "running" for item in latest_tasks(run, version).values()) < limit

    # Resume reservations even if a crash happened after allocating a new
    # attempt but before linking it to the repair receipt.
    for key, receipt in list((run.snapshot or {}).get("production_repairs", {}).items()):
        if slot_available() and receipt.get("plan_version") == version.version and receipt.get("status") in {"claimed", "running"}:
            original = db.session.get(AgentShotTask, int(key))
            retry_shot(run, original, registry, automatic=receipt.get("automatic", True))
    tasks = latest_tasks(run, version)
    for task in list(tasks.values()):
        if task.status == "success" and not usable_artifact(task):
            versions.mark_stale(run, version.version, target_type="video", target_ids={task.target_id})
        if slot_available() and task.status in {"failed", "stale"}:
            retry_shot(run, task, registry, automatic=True)
    deps = dependencies(version)
    tasks = latest_tasks(run, version)
    running = sum(task.status == "running" for task in tasks.values())
    for shot in version.plan["shots"]:
        sid = shot["shot_id"]
        task = tasks.get(sid)
        if task and task.status not in {"pending"}:
            continue
        if running >= limit:
            break
        if deps[sid] and not _extract_tail(run, version, deps[sid][0], registry):
            continue
        data = _inputs(run, version, shot, task)
        if not data:
            continue
        if task is None:
            # A reviewed plan change cannot turn an unresolved submission into
            # a fresh paid shot. Preserve the durable failure across versions.
            unknown = next((item for item in AgentShotTask.query.filter_by(
                run_id=run.run_id, target_type="video", target_id=sid).order_by(AgentShotTask.id.desc())
                if (item.error or {}).get("category") == "submit_unknown"), None)
            if unknown:
                task = versions.create_task(run, version.version, "video", sid, data,
                                            estimated_cost=shot_cost(run, shot), reuse=False)
                versions.update_task(run, task, status="failed", job_id=unknown.job_id,
                                     invocation_id=unknown.invocation_id, error=unknown.error)
                continue
            forced = sid in metadata.get("force_shot_ids", [])
            task = versions.create_task(run, version.version, "video", sid, data,
                                        estimated_cost=shot_cost(run, shot), reuse=not forced)
        if task.status == "success":
            continue
        _submit(run, task, data, registry)
        running += task.status == "running"
    tasks = latest_tasks(run, version)
    all_complete = len(tasks) == len(version.plan["shots"]) and all(usable_artifact(task) for task in tasks.values())
    status = "awaiting_video_review" if all_complete else "producing" if any(
        task.status in {"pending", "running"} for task in tasks.values()) else "production_attention"
    update_production(run, status=status)
    return status
