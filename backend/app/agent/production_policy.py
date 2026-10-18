"""Server-owned approval and artifact bindings for story production Skills."""
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar

from app.api import AppError
from app.models import AgentPlanVersion, AgentRun, AgentShotTask, ToolInvocation
from app.agent import plan_versions as versions
from app.agent.production_plan import select_plan_model


_dispatch_permit = ContextVar("story_production_dispatch", default=None)


def require_task_authorization(tool_name, ctx):
    """Public callers cannot replace a frozen story task with a fresh tool key."""
    if ctx.shot_task_id is not None or tool_name not in {"animate_shot", "generate_video", "produce_shot", "remix_shot"}:
        return
    version = AgentPlanVersion.query.filter_by(run_id=ctx.budget_scope).order_by(AgentPlanVersion.version.desc()).first()
    if version and (version.plan or {}).get("recipe") == "story_video":
        raise AppError("UNSAFE_RETRY", "Story videos require an approved production task and quoted action", 409)


def reject_manual_dispatch(job):
    if (job.config or {}).get("agent_story_production") or (job.config or {}).get("agent_transform"):
        raise AppError("UNSAFE_RETRY", "Production Jobs must use the story retry/redo approval flow", 409)


@contextmanager
def authorized_job_dispatch(job, run_type, node_key=None, *, force=False, restart=False):
    """Server-only admission permit, never populated from HTTP or tool input.

    Callers already validated the frozen task or durable recovery receipt. The
    permission exists only while admitting that exact Job operation, not in the
    asynchronous executor thread or another HTTP request.
    """
    allowed = ((run_type == "run_full" and node_key is None and not force and not restart)
               or (run_type == "run_node" and node_key == "poll_i2v" and force and not restart))
    if not allowed:
        raise AppError("UNSAFE_RETRY", "Production permits cannot force a paid submit or restart", 409)
    token = _dispatch_permit.set((job.job_id, run_type, node_key, force, restart))
    try:
        yield
    finally:
        _dispatch_permit.reset(token)


def validate_dispatch(job, run_type, node_key, force, restart):
    if ((job.config or {}).get("agent_story_production")
            and _dispatch_permit.get() != (job.job_id, run_type, node_key, force, restart)):
        reject_manual_dispatch(job)


def invocation_key(task):
    return (f"{task.run_id}:production:{task.plan_version}:{task.target_type}:"
            f"{task.target_id}:{task.attempt}:{task.inputs_hash[:12]}")


def task_context(ctx, *, current=True):
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
    task = AgentShotTask.query.filter_by(id=ctx.shot_task_id, run_id=ctx.budget_scope).first()
    if not run or not task or task.target_type not in {"video", "tail_frame"}:
        raise AppError("INVALID_REFERENCE", "Invalid production task linkage", 422)
    if ctx.idempotency_key != invocation_key(task):
        raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Production key does not match its task", 409)
    production = (run.snapshot or {}).get("production") or {}
    if current and (production.get("approved_version") != task.plan_version
                    or versions.current_version(run).version != task.plan_version):
        raise AppError("PLAN_VERSION_CONFLICT", "Production requires the current approved plan version", 409)
    version = versions.get_version(run, task.plan_version)
    shot = next((item for item in version.plan["shots"] if item["shot_id"] == task.target_id), None)
    if not shot:
        raise AppError("INVALID_REFERENCE", "Shot is not part of this production plan", 422)
    return run, task, version, shot


def _artifact(run, version, kind, target):
    task = versions.latest_task(run, version.version, kind, target)
    if not task or task.status != "success" or not task.artifact_ids:
        raise AppError("PREVIEW_INCOMPLETE", "Production reference is missing or stale", 409)
    return task.artifact_ids[0]


def _motion_prompt(run, task, shot, _seen=()):
    if task.id in _seen or len(_seen) > 2:
        raise AppError("MODEL_PREFERENCE_VIOLATION", "Repair approval lineage is invalid", 422)
    for key, receipt in ((run.snapshot or {}).get("production_repairs") or {}).items():
        if receipt.get("replacement_task_id") != task.id:
            continue
        failed = AgentShotTask.query.filter_by(id=receipt.get("failed_task_id"), run_id=run.run_id,
            plan_version=task.plan_version, target_type="video", target_id=task.target_id, status="failed").first()
        bound = (failed and str(failed.id) == key and receipt.get("shot_id") == task.target_id
                 and receipt.get("plan_version") == task.plan_version
                 and receipt.get("status") in {"running", "completed", "failed"})
        if receipt.get("action") in {"retry_submit", "recover_read"}:
            if bound:
                return _motion_prompt(run, failed, shot, (*_seen, task.id))
            return shot["motion"]["prompt"]
        reserved = receipt.get("reserved_credits")
        if (bound and receipt.get("action") == "rewrite_prompt" and receipt.get("category") == "content_policy"
                and isinstance(reserved, (int, float)) and not isinstance(reserved, bool) and reserved > 0
                and isinstance(receipt.get("motion_prompt"), str) and receipt["motion_prompt"].strip()):
            return receipt["motion_prompt"]
        raise AppError("MODEL_PREFERENCE_VIOLATION", "Motion revision has no authorized repair receipt", 422)
    return shot["motion"]["prompt"]


def validate_submission(data, ctx):
    """Validate full canonical Skill input before budgets, replays or side effects."""
    run, task, version, shot = task_context(ctx)
    payload = data.model_dump(mode="json")
    if versions.inputs_hash(payload) != task.inputs_hash:
        raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Production inputs do not match the frozen task", 409)
    if task.target_type == "tail_frame":
        if (ctx.tool_name != "extract_frame" or payload["position"] != "last" or payload["timestamp_sec"] is not None
                or payload["video_artifact_id"] != _artifact(run, version, "video", task.target_id)):
            raise AppError("INVALID_REFERENCE", "Tail extraction requires this shot's completed video", 422)
        return
    if ctx.tool_name != "animate_shot":
        raise AppError("INVALID_REFERENCE", "Video task requires animate_shot", 422)
    first = (_artifact(run, version, "tail_frame", shot["depends_on"][0])
             if shot["transition_in"] == "tail_frame" else _artifact(run, version, "keyframe", shot["shot_id"]))
    last = _artifact(run, version, "end_frame", shot["shot_id"]) if shot["motion"]["mode"] == "first_last_frame" else None
    expected = {"first_frame_artifact_id": first, "last_frame_artifact_id": last,
                "prompt": _motion_prompt(run, task, shot), "model_id": shot["motion"]["model_id"],
                "params": deepcopy(shot["motion"]["params"])}
    if expected != payload:
        raise AppError("MODEL_PREFERENCE_VIOLATION", "Video inputs differ from the approved storyboard", 422)
    model_for_context(ctx, payload["model_id"])


def model_for_context(ctx, requested):
    run, task, _version, shot = task_context(ctx)
    if task.target_type != "video" or requested != shot["motion"]["model_id"]:
        raise AppError("MODEL_PREFERENCE_VIOLATION", "Video model differs from the approved shot", 422)
    return select_plan_model((run.snapshot or {})["request_spec"], "i2v", requested,
                             run=run, slot=f"{task.target_id}:motion")


def job_marker(ctx):
    run, task, _version, shot = task_context(ctx)
    return {"run_id": run.run_id, "plan_version": task.plan_version,
            "target_type": task.target_type, "target_id": task.target_id, "shot_id": task.target_id, "task_id": task.id,
            "inputs_hash": task.inputs_hash, "motion_prompt": _motion_prompt(run, task, shot) if task.target_type == "video" else None}


def validate_job(job):
    """Recover a frozen approved Job without reverting review-selected models."""
    config = job.config or {}
    marker, skill = config.get("agent_story_production") or {}, config.get("skill") or {}
    task = AgentShotTask.query.filter_by(id=marker.get("task_id"), run_id=marker.get("run_id"),
        plan_version=marker.get("plan_version"), target_type="video", target_id=marker.get("target_id")).first()
    invocation = ToolInvocation.query.filter_by(invocation_id=skill.get("invocation_id"),
        budget_scope=marker.get("run_id"), tool_name="animate_shot").first()
    if (not task or not invocation or marker.get("inputs_hash") != task.inputs_hash
            or versions.inputs_hash(invocation.input_payload) != task.inputs_hash
            or invocation.idempotency_key != invocation_key(task)
            or invocation.job_id != job.id or skill.get("budget_scope") != task.run_id):
        raise AppError("MODEL_PREFERENCE_VIOLATION", "Production Job has no matching approval receipt", 422)
    from app.services.model_service import ModelService
    from app.agent.model_selection import candidates_for_request, validate_generation_model
    run = AgentRun.query.filter_by(run_id=task.run_id).one()
    data = invocation.input_payload
    version = versions.get_version(run, task.plan_version)
    shot = next(item for item in version.plan["shots"] if item["shot_id"] == task.target_id)
    if data["prompt"] != _motion_prompt(run, task, shot) or marker.get("motion_prompt") != data["prompt"]:
        raise AppError("MODEL_PREFERENCE_VIOLATION", "Production motion has no matching approval", 422)
    model_id = (config.get("node_models") or {}).get("submit_i2v")
    if model_id != data["model_id"] or model_id not in {item.model_id for item in candidates_for_request(
            (run.snapshot or {})["request_spec"], "i2v", use_default=False)}:
        raise AppError("MODEL_PREFERENCE_VIOLATION", "Production Job model violates the approved constraints", 422)
    model = ModelService.get_model(model_id, require_enabled=True)
    params = (config.get("node_model_params") or {}).get("submit_i2v", {})
    if any(params.get(key) != value for key, value in data["params"].items()):
        raise AppError("MODEL_PREFERENCE_VIOLATION", "Production Job parameters differ from approval", 422)
    from app.services.artifact_service import ArtifactService
    from app.services.prompt_service import PromptService
    from app.services.job_run_state_service import JobRunStateService
    prompt = PromptService.get_active_for_template(job.template, "i2v", job_id=job.id)
    if not prompt or prompt.content != data["prompt"] or JobRunStateService.prompt_policy(job) == "template_first":
        raise AppError("MODEL_PREFERENCE_VIOLATION", "Production prompt differs from approval", 422)
    for kind, field in (("first_frame_image", "first_frame_artifact_id"), ("last_frame_image", "last_frame_artifact_id")):
        artifact = ArtifactService.latest_for_job(job, kind)
        expected = data.get(field)
        if bool(artifact) != bool(expected) or (artifact and (artifact.meta or {}).get("source_artifact_id") != expected):
            raise AppError("MODEL_PREFERENCE_VIOLATION", "Production frame differs from approval", 422)
    validate_generation_model(model, "i2v", params, reference_count=2 if data.get("last_frame_artifact_id") else 1)
    from app.skills.tools.animate_shot import AnimateShotInput, validate_bridge
    validate_bridge(AnimateShotInput.model_validate(data), model)
