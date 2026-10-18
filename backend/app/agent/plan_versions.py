"""Immutable plan snapshots and durable, Run-scoped preview attempts."""

from copy import deepcopy
from hashlib import sha256
import json
import math

from sqlalchemy import update

from app.api import AppError
from app.extensions import db
from app.models import AgentPlanVersion, AgentRun, AgentShotTask, Artifact, Job, ToolInvocation

TARGET_TYPES = {"character", "keyframe", "end_frame"}
TASK_STATUSES = {"pending", "running", "success", "failed", "stale", "cancelled"}
TRANSITIONS = {
    "pending": {"running", "success", "failed", "stale", "cancelled"},
    "running": {"success", "failed", "stale", "cancelled"},
    "success": {"stale"}, "failed": {"stale"}, "stale": set(), "cancelled": set(),
}


def inputs_hash(inputs: dict) -> str:
    """Canonical hash; callers include prompts, models, params and reference IDs."""
    try:
        encoded = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AppError("INVALID_INPUT", "Preview inputs must be finite JSON values", 422) from error
    return sha256(encoded).hexdigest()


def _require_run(run):
    row = AgentRun.query.filter_by(run_id=run.run_id, owner_id=run.owner_id).first()
    if not row:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent run not found", 404)
    return row


def _lock_run(run):
    # A no-op UPDATE serializes writers on SQLite as well as MySQL. SELECT FOR
    # UPDATE alone is ignored by SQLite. Keep unrelated Run fields unchanged.
    with db.session.no_autoflush:
        result = db.session.execute(update(AgentRun).where(
            AgentRun.run_id == run.run_id, AgentRun.owner_id == run.owner_id
        ).values(updated_at=AgentRun.updated_at).execution_options(synchronize_session=False))
        if not result.rowcount:
            raise AppError("AGENT_RUN_NOT_FOUND", "Agent run not found", 404)
        return AgentRun.query.populate_existing().with_for_update().filter_by(run_id=run.run_id).one()


def current_version(run, *, _lock=False):
    _require_run(run)
    query = AgentPlanVersion.query.filter_by(run_id=run.run_id).order_by(AgentPlanVersion.version.desc())
    return (query.with_for_update() if _lock else query).first()


def get_version(run, version, *, _lock=False):
    _require_run(run)
    query = AgentPlanVersion.query.filter_by(run_id=run.run_id, version=version)
    row = (query.with_for_update() if _lock else query).first()
    if not row:
        raise AppError("PLAN_VERSION_NOT_FOUND", "Plan version not found", 404)
    return row


def require_current_version(run, version):
    current = current_version(run)
    if not current or current.version != version:
        raise AppError("PLAN_VERSION_CONFLICT", "The plan changed; refresh before editing", 409,
                       payload={"current_version": current.version if current else None})
    return current


def create_version(run, plan, story_package, check, *, author="director", base_version=None,
                   operation_key=None):
    """Commit an immutable version and current pointer atomically.

    The graph worker must preserve snapshot.plan_operations when saving state.
    A replay resolves its original version even after later edits have landed.
    """
    if author not in {"director", "user", "system"}:
        raise AppError("INVALID_INPUT", "Unknown plan author", 422)
    if operation_key is not None and (not isinstance(operation_key, str) or not operation_key
                                      or len(operation_key) > 128):
        raise AppError("INVALID_INPUT", "Invalid plan operation key", 422)
    payload = {"plan": deepcopy(plan), "story_package": deepcopy(story_package),
               "check": deepcopy(check), "author": author, "base_version": base_version}
    payload["plan"].pop("plan_version", None)
    fingerprint = inputs_hash(payload)
    try:
        locked = _lock_run(run)
        snapshot = deepcopy(locked.snapshot or {})
        operations = snapshot.setdefault("plan_operations", {})
        if operation_key in operations:
            receipt = operations[operation_key]
            if receipt["inputs_hash"] != fingerprint:
                raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Plan operation key belongs to different input", 409)
            row = get_version(locked, receipt["version"], _lock=True)
            db.session.commit()
            return row
        previous = current_version(locked, _lock=True)
        current = previous.version if previous else 0
        if base_version is not None and base_version != current:
            raise AppError("PLAN_VERSION_CONFLICT", "The plan changed; refresh before editing", 409,
                           payload={"current_version": current})
        version = current + 1
        row = AgentPlanVersion(run_id=locked.run_id, version=version, author=author,
                               parent_version=current or None,
                               plan={**payload["plan"], "plan_version": version},
                               story_package=payload["story_package"], check=payload["check"])
        db.session.add(row)
        snapshot["plan_version"] = version
        if operation_key:
            operations[operation_key] = {"version": version, "inputs_hash": fingerprint}
        locked.snapshot = snapshot
        db.session.commit()
        return row
    except Exception:
        db.session.rollback()
        raise


def list_tasks(run, plan_version, *, latest_only=True):
    get_version(run, plan_version)
    rows = AgentShotTask.query.filter_by(run_id=run.run_id, plan_version=plan_version).order_by(
        AgentShotTask.id).all()
    if not latest_only:
        return rows
    latest = {(row.target_type, row.target_id): row for row in rows}
    return list(latest.values())


def latest_task(run, plan_version, target_type, target_id, *, _lock=False):
    get_version(run, plan_version, _lock=_lock)
    query = AgentShotTask.query.filter_by(run_id=run.run_id, plan_version=plan_version,
        target_type=target_type, target_id=target_id).order_by(AgentShotTask.attempt.desc())
    return (query.with_for_update() if _lock else query).first()


def find_reusable_task(run, target_type, target_id, fingerprint, *, _lock=False):
    _require_run(run)
    query = AgentShotTask.query.filter_by(run_id=run.run_id, target_type=target_type,
        target_id=target_id, inputs_hash=fingerprint, status="success").order_by(AgentShotTask.id.desc())
    return (query.with_for_update() if _lock else query).first()


def _validate_target(version, target_type, target_id):
    if target_type not in TARGET_TYPES:
        raise AppError("INVALID_INPUT", "Unknown preview target type", 422)
    items = version.story_package.get("characters", []) if target_type == "character" else version.plan.get("shots", [])
    key = "character_id" if target_type == "character" else "shot_id"
    selected = next((item for item in items if item.get(key) == target_id), None)
    if not selected or (target_type == "end_frame" and not selected.get("end_frame")):
        raise AppError("INVALID_REFERENCE", "Preview target is not part of this plan", 422)


def create_task(run, plan_version, target_type, target_id, inputs, *, estimated_cost=0.0,
                reuse=True, force=False):
    """Reuse unchanged success; failure retries always require an explicit force."""
    if isinstance(estimated_cost, bool) or not isinstance(estimated_cost, (int, float)) or not math.isfinite(estimated_cost) or estimated_cost < 0:
        raise AppError("INVALID_INPUT", "Preview cost must be finite and nonnegative", 422)
    fingerprint = inputs_hash(inputs)
    try:
        locked = _lock_run(run)
        version = get_version(locked, plan_version, _lock=True)
        _validate_target(version, target_type, target_id)
        previous = latest_task(locked, plan_version, target_type, target_id, _lock=True)
        if previous and not force:
            if previous.inputs_hash != fingerprint:
                raise AppError("PLAN_VERSION_CONFLICT", "Changed preview inputs need a new plan version", 409)
            db.session.commit()
            return previous
        source = find_reusable_task(locked, target_type, target_id, fingerprint, _lock=True) if reuse and not force else None
        row = AgentShotTask(run_id=run.run_id, plan_version=plan_version,
            target_type=target_type, target_id=target_id, attempt=(previous.attempt + 1) if previous else 1,
            inputs_hash=fingerprint, estimated_cost=estimated_cost,
            status="success" if source else "pending", artifact_ids=deepcopy(source.artifact_ids) if source else [],
            job_id=source.job_id if source else None, invocation_id=source.invocation_id if source else None)
        db.session.add(row)
        db.session.commit()
        return row
    except Exception:
        db.session.rollback()
        raise


def _validate_links(run, values):
    invocation = None
    if values.get("invocation_id"):
        invocation = ToolInvocation.query.filter_by(invocation_id=values["invocation_id"], budget_scope=run.run_id).first()
        if not invocation:
            raise AppError("INVALID_REFERENCE", "Invocation is not part of this run", 422)
    if values.get("job_id"):
        job = Job.query.filter_by(job_id=values["job_id"]).first()
        if not job or (job.config or {}).get("skill", {}).get("budget_scope") != run.run_id:
            raise AppError("INVALID_REFERENCE", "Job is not part of this run", 422)
        if invocation and invocation.job_id != job.id:
            raise AppError("INVALID_REFERENCE", "Invocation and job do not match", 422)
    for artifact_id in values.get("artifact_ids", []):
        artifact = Artifact.query.filter_by(artifact_id=artifact_id).first()
        if not artifact:
            raise AppError("INVALID_REFERENCE", "Preview artifact not found", 422)
        if (artifact.job.config or {}).get("skill", {}).get("budget_scope") == run.run_id:
            continue
        if artifact.artifact_type == "agent_reference_image":
            from app.agent.search.references import reference_for_run
            reference_for_run(artifact_id, run)
        elif artifact_id in run.request.get("attachment_ids", []):
            from app.agent.attachments import attachment_for_owner
            attachment_for_owner(artifact_id, run.owner_id, run_id=run.run_id)
        else:
            raise AppError("INVALID_REFERENCE", "Preview artifact is not part of this run", 422)


def update_task(run, task, **values):
    allowed = {"status", "invocation_id", "job_id", "artifact_ids", "error"}
    if not values.keys() <= allowed or values.get("status", task.status) not in TASK_STATUSES:
        raise AppError("INVALID_INPUT", "Invalid preview task update", 422)
    try:
        locked = _lock_run(run)
        row = AgentShotTask.query.populate_existing().filter_by(id=task.id, run_id=locked.run_id).first()
        if not row:
            raise AppError("INVALID_REFERENCE", "Preview task is not part of this run", 422)
        status = values.get("status", row.status)
        if status != row.status and status not in TRANSITIONS[row.status]:
            raise AppError("INVALID_INPUT", "Preview attempt is terminal; create a new attempt", 409)
        merged = {**row.to_dict(), **values}
        if status == "success" and not merged["artifact_ids"]:
            raise AppError("INVALID_REFERENCE", "Successful preview requires an artifact", 422)
        _validate_links(locked, merged)
        for key, value in values.items():
            setattr(row, key, deepcopy(value))
        db.session.commit()
        return row
    except Exception:
        db.session.rollback()
        raise


def mark_stale(run, plan_version, *, target_type=None, target_ids=None, expected_hashes=None):
    """Invalidate current attempts only; never submit replacement work implicitly."""
    try:
        locked = _lock_run(run)
        rows = list_tasks(locked, plan_version)
        changed = []
        for row in rows:
            if target_type is not None and row.target_type != target_type:
                continue
            if target_ids is not None and row.target_id not in target_ids:
                continue
            if expected_hashes is not None and row.inputs_hash == expected_hashes.get((row.target_type, row.target_id)):
                continue
            if row.status not in {"stale", "cancelled"}:
                row.status = "stale"
                changed.append(row)
        db.session.commit()
        return changed
    except Exception:
        db.session.rollback()
        raise


def invalidate_character_keyframes(run, plan_version, character_id):
    version = get_version(run, plan_version)
    shot_ids = {shot["shot_id"] for shot in version.plan.get("shots", [])
                if character_id in shot.get("character_ids", [])}
    changed = []
    for target_type in ("keyframe", "end_frame"):
        changed.extend(mark_stale(run, plan_version, target_type=target_type, target_ids=shot_ids))
    return changed
