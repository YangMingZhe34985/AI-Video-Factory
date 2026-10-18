"""Durable production metadata and deterministic dependency/input projection."""

from copy import deepcopy

from flask import current_app
from pydantic import ValidationError

from app.agent import plan_versions as versions
from app.agent.production_plan import select_plan_model
from app.api import AppError
from app.extensions import db
from app.models import Artifact
from app.services.storage_service import StorageService
from app.skills.budget import estimate_model_cost


def enabled():
    return bool(current_app.config.get("AGENT_STORY_V2_ENABLED")
                and current_app.config.get("AGENT_STORY_PRODUCTION_ENABLED"))


def update_production(run, **changes):
    locked = versions._lock_run(run)
    snapshot = deepcopy(locked.snapshot or {})
    value = snapshot.setdefault("production", {})
    value.update(deepcopy(changes))
    locked.snapshot = snapshot
    db.session.commit()
    return value


def event(run, name, *, task=None, **details):
    locked = versions._lock_run(run)
    snapshot = deepcopy(locked.snapshot or {})
    production = snapshot.setdefault("production", {})
    key = f"{name}:{task.id if task else production.get('plan_version')}:{details.get('key', '')}"
    events = production.setdefault("events", {})
    events.setdefault(key, {"event": name, "task_id": task.id if task else None, **details})
    locked.snapshot = snapshot
    db.session.commit()


def latest_tasks(run, version, target_type="video"):
    number = version.version if hasattr(version, "version") else version
    return {row.target_id: row for row in versions.list_tasks(run, number)
            if row.target_type == target_type}


def usable_artifact(task):
    if task is None or task.status != "success":
        return None
    for artifact_id in task.artifact_ids or []:
        artifact = Artifact.query.filter_by(artifact_id=artifact_id).first()
        if not artifact or not artifact.job:
            continue
        if (artifact.job.config or {}).get("skill", {}).get("budget_scope") != task.run_id:
            # User-image keyframes are independently scoped attachments.
            if task.target_type != "keyframe":
                continue
            from app.models import AgentRun
            from app.agent.attachments import attachment_for_owner
            run = AgentRun.query.filter_by(run_id=task.run_id).one()
            try:
                attachment_for_owner(artifact_id, run.owner_id, run_id=run.run_id)
            except AppError:
                continue
        try:
            path = StorageService.resolve(artifact.file_path).resolve()
            expected = "video/" if task.target_type == "video" else "image/"
            if path.is_relative_to(StorageService.root()) and path.is_file() and path.stat().st_size > 0 and str(artifact.mime_type or "").startswith(expected):
                if task.target_type == "tail_frame":
                    from app.skills.tools.extract_frame import cached_frame_is_valid
                    if not cached_frame_is_valid(artifact):
                        continue
                return artifact
        except (OSError, ValueError):
            continue
    return None


def dependencies(version):
    shots = version.plan["shots"]
    return {shot["shot_id"]: [shots[index - 1]["shot_id"]]
            if index and shot["transition_in"] == "tail_frame" else []
            for index, shot in enumerate(shots)}


def video_inputs(run, version, shot):
    from app.skills.tools.animate_shot import AnimateShotInput
    source = dependencies(version)[shot["shot_id"]]
    first = versions.latest_task(run, version.version, "tail_frame" if source else "keyframe",
                                 source[0] if source else shot["shot_id"])
    first_artifact = usable_artifact(first)
    if not first_artifact:
        return None
    last_id = None
    if shot.get("end_frame"):
        last = usable_artifact(versions.latest_task(run, version.version, "end_frame", shot["shot_id"]))
        if not last:
            return None
        last_id = last.artifact_id
    try:
        return AnimateShotInput(first_frame_artifact_id=first_artifact.artifact_id,
            last_frame_artifact_id=last_id, prompt=shot["motion"]["prompt"],
            model_id=shot["motion"]["model_id"], params=deepcopy(shot["motion"]["params"])).model_dump(mode="json")
    except ValidationError:
        # Editable drafts may intentionally be incomplete. Review remains readable;
        # validate_start still rejects them before any production side effect.
        return None


def shot_cost(run, shot):
    model = select_plan_model(run.snapshot["request_spec"], "i2v", shot["motion"]["model_id"],
                              run=run, slot=f"{shot['shot_id']}:motion")
    return estimate_model_cost(model, {**shot["motion"]["params"], "duration": shot["duration_sec"], "n_outputs": 1})


def remaining_video_cost(run, version):
    tasks = latest_tasks(run, version)
    production = (run.snapshot or {}).get("production", {})
    forced = set(production.get("force_shot_ids", [])) if production.get("plan_version") == version.version else set()
    total = 0.0
    for shot in version.plan["shots"]:
        task = tasks.get(shot["shot_id"])
        if task and (usable_artifact(task) or task.status in {"running", "failed", "stale", "cancelled"}):
            continue
        data = video_inputs(run, version, shot)
        if data and shot["shot_id"] not in forced:
            previous = versions.find_reusable_task(run, "video", shot["shot_id"], versions.inputs_hash(data))
            if usable_artifact(previous):
                continue
        total += shot_cost(run, shot)
    return round(total, 6)
