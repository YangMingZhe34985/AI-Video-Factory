"""Phase C preview production via registered image Skills, never video adapters."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

from app.agent import plan_versions as versions
from app.agent.model_selection import select_for_request, validate_generation_model
from app.agent.recovery import invoke_once, recover_job
from app.agent.production_plan import select_plan_model
from app.agent.plan_check import frame_params
from app.api import AppError
from app.extensions import db
from app.models import AgentPlanVersion, AgentShotTask, Artifact, Job, ToolInvocation
from app.services.storage_service import StorageService
from app.skills.budget import BudgetGuard, estimate_model_cost
from app.skills.spec import ToolContext


def _version(run, version=None):
    if version is None:
        row = versions.current_version(run)
        if row is None:
            raise AppError("PLAN_VERSION_NOT_FOUND", "Plan version not found", 404)
        return row
    return versions.get_version(run, version.version if isinstance(version, AgentPlanVersion) else version)


def targets_for(version, phase="all"):
    result = []
    if phase in {"all", "characters"}:
        result.extend(("character", character["character_id"]) for character in version.story_package.get("characters", [])
                      if character["reference"]["source"] == "generate")
    if phase in {"all", "keyframes"}:
        for shot in version.plan["shots"]:
            for key, kind in (("first_frame", "keyframe"), ("end_frame", "end_frame")):
                if shot.get(key) and shot[key]["method"] != "tail_frame":
                    result.append((kind, shot["shot_id"]))
    return result


def _spec(run):
    spec = (run.snapshot or {}).get("request_spec")
    if not spec:
        raise AppError("INVALID_AGENT_STATE", "Understanding must finish before preview production", 409)
    return spec


def planned_inputs(run, version, target_type, target_id):
    return _planned_inputs(run, _version(run, version), target_type, target_id)


def _planned_inputs(run, version, target_type, target_id, *, allow_pending=False):
    if (target_type, target_id) not in targets_for(version):
        raise AppError("INVALID_REFERENCE", "Preview target is not part of this plan", 422)
    pending_characters = []
    if target_type == "character":
        character = next(item for item in version.story_package["characters"] if item["character_id"] == target_id)
        style = version.story_package["style"]
        prompt = f'{style["prompt_prefix"]}。角色外观固定为：{character["lock_description"]}。{character["reference"]["generate_prompt"]}'
        mode, refs = "t2i", []
        model = select_for_request(_spec(run), mode)
    else:
        shot = next(item for item in version.plan["shots"] if item["shot_id"] == target_id)
        frame = shot["first_frame" if target_type == "keyframe" else "end_frame"]
        refs = list(frame["reference_artifact_ids"])
        if frame["method"] == "user_image":
            if len(refs) != 1:
                raise AppError("INVALID_REFERENCE", "User keyframe requires one image", 422)
            from app.skills.job_backed import resolve_artifact
            resolve_artifact(refs[0], image_only=True, ctx=ToolContext(role="production", budget_scope=run.run_id))
            return {"method": "user_image", "artifact_id": refs[0]}
        characters = {item["character_id"]: item for item in version.story_package.get("characters", [])}
        pending_characters = [key for key in shot["character_ids"] if key in characters
                              and characters[key]["reference"]["source"] == "generate"
                              and not characters[key]["reference"]["artifact_ids"]]
        if pending_characters and not allow_pending:
            raise AppError("PREVIEW_INCOMPLETE", "Confirm generated character references first", 409)
        mode, prompt = frame["image_mode"], frame["prompt"]
        if mode not in {"t2i", "i2i"}:
            raise AppError("INVALID_PRODUCTION_PLAN", "Generated frame requires an image mode", 422)
        model = select_plan_model(_spec(run), mode, frame["model_id"], run=run,
                                  slot=f"{target_id}:{'first_frame' if target_type == 'keyframe' else 'end_frame'}")
    if not prompt:
        raise AppError("INVALID_PRODUCTION_PLAN", "Preview prompt is empty", 422)
    params = validate_generation_model(model, mode, frame_params(model, version.plan["aspect_ratio"]),
                                       reference_count=len(refs) + len(pending_characters))
    params.pop("n", None)
    return {"mode": mode, "model_id": model.model_id, "prompt": prompt,
            "params": params, "reference_artifact_ids": refs, "n": 1}


def _cost(data):
    if data.get("method") == "user_image":
        return 0.0
    from app.services.model_service import ModelService
    return estimate_model_cost(ModelService.get_model(data["model_id"]), {**data["params"], "n": 1})


def _usable(artifact_ids):
    if not artifact_ids:
        return False
    for artifact_id in artifact_ids:
        artifact = Artifact.query.filter_by(artifact_id=artifact_id).first()
        if not artifact or not str(artifact.mime_type).startswith("image/"):
            return False
        path = StorageService.resolve(artifact.file_path)
        if not path.is_file() or not path.stat().st_size:
            return False
    return True


def prepare_previews(run, version, *, targets=None, force_targets=()):
    """Persist target attempts and stale flags, without starting paid work."""
    version = _version(run, version)
    wanted = list(targets) if targets is not None else targets_for(version)
    force_targets = {tuple(item) for item in force_targets}
    result = []
    for target_type, target_id in wanted:
        try:
            data = planned_inputs(run, version, target_type, target_id)
        except AppError as error:
            if error.code == "PREVIEW_INCOMPLETE" and target_type != "character":
                continue
            raise
        previous = versions.latest_task(run, version.version, target_type, target_id)
        if previous:
            # Replaying the graph never allocates another regeneration attempt.
            if previous.inputs_hash != versions.inputs_hash(data) and previous.status != "stale":
                versions.mark_stale(run, version.version, target_type=target_type, target_ids={target_id})
            result.append(previous)
            continue
        prior = AgentShotTask.query.filter_by(run_id=run.run_id, target_type=target_type, target_id=target_id).filter(
            AgentShotTask.plan_version < version.version).order_by(AgentShotTask.id.desc()).first()
        forced = (target_type, target_id) in force_targets
        row = versions.create_task(run, version.version, target_type, target_id, data,
                                   estimated_cost=_cost(data), reuse=not forced)
        if data.get("method") == "user_image":
            if row.status != "success":
                versions.update_task(run, row, status="success", artifact_ids=[data["artifact_id"]])
        elif row.status == "success" and not _usable(row.artifact_ids):
            versions.mark_stale(run, version.version, target_type=target_type, target_ids={target_id})
        elif prior and row.status == "pending" and not forced:
            # Carry the old visible image while asking the user to pay for a redo.
            versions.update_task(run, row, status="stale", artifact_ids=prior.artifact_ids,
                                 job_id=prior.job_id, invocation_id=prior.invocation_id, error=prior.error)
            row.inputs_hash = prior.inputs_hash
            db.session.commit()
        result.append(row)
    return result


def preview_cost(run, version, targets, *, force=False):
    """Price only unfinished selected targets; no generation or ledger mutation."""
    version = _version(run, version)
    total = 0.0
    for kind, target_id in targets:
        data = planned_inputs(run, version, kind, target_id)
        task = versions.latest_task(run, version.version, kind, target_id)
        if not force and task and task.status == "success" and task.inputs_hash == versions.inputs_hash(data) and _usable(task.artifact_ids):
            continue
        total += _cost(data)
    return round(total, 6)


def remaining_preview_cost(run, plan, story):
    """Estimate an editable draft without inserting a version or task rows."""
    version = SimpleNamespace(plan=plan, story_package=story)
    total = 0.0
    for kind, target_id in targets_for(version):
        try:
            data = _planned_inputs(run, version, kind, target_id, allow_pending=True)
            reusable = versions.find_reusable_task(run, kind, target_id, versions.inputs_hash(data))
            if reusable and _usable(reusable.artifact_ids):
                continue
            total += _cost(data)
        except AppError:
            # Plan Check owns blocking issues for an editable business draft.
            # Unknown models/references cannot contribute a trustworthy quote.
            continue
    return round(total, 6)


def invocation_key(task):
    suffix = f"{task.plan_version}:{task.target_type}:{task.target_id}:{task.attempt}"
    return f"{task.run_id}:preview:{sha256(suffix.encode()).hexdigest()[:32]}"


def _context(run, task, *, polling=False):
    return ToolContext(role="production", approved=True, budget_scope=run.run_id,
        budget_limit=run.request["budget_limit"], idempotency_key=invocation_key(task),
        preview_task_id=None if polling else task.id)


def launch_previews(run, version, targets, registry):
    version = _version(run, version)
    rows = []
    for kind, target_id in targets:
        row = versions.latest_task(run, version.version, kind, target_id)
        if row is None:
            rows.extend(prepare_previews(run, version, targets=[(kind, target_id)]))
        else:
            rows.append(row)
    # Check the batch before the first image is charged. Registry also checks
    # each invocation against the same budget scope when it is submitted.
    unpaid = [row for row in rows if row.status == "pending" and not ToolInvocation.query.filter_by(
        idempotency_key=invocation_key(row)).first()]
    BudgetGuard.check(run.run_id, run.request["budget_limit"], sum(row.estimated_cost for row in unpaid))
    for row in rows:
        if row.status not in {"pending", "running"}:
            continue
        data = planned_inputs(run, version, row.target_type, row.target_id)
        if row.inputs_hash != versions.inputs_hash(data):
            versions.mark_stale(run, version.version, target_type=row.target_type, target_ids={row.target_id})
            continue
        ctx = _context(run, row)
        try:
            response = invoke_once(registry, "generate_image", data, ctx)
            versions.update_task(run, row, status="running", invocation_id=response["invocation_id"],
                                 job_id=response["output"]["job_id"])
        except AppError as error:
            previous = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).first()
            if previous and previous.job:
                versions.update_task(run, row, status="running", invocation_id=previous.invocation_id,
                                     job_id=previous.job.job_id)
            else:
                versions.update_task(run, row, status="failed", error={"code": error.code, "summary": error.message})
    return rows


def poll_previews(run, version, registry):
    version = _version(run, version)
    rows = versions.list_tasks(run, version.version)
    for row in rows:
        if row.status not in {"running", "pending"} or not row.job_id:
            continue
        try:
            job = Job.query.filter_by(job_id=row.job_id).one()
            recover_job(job, run.run_id)
            report = registry.invoke("get_task_status", {"job_id": row.job_id}, _context(run, row, polling=True))["output"]
            if not report["terminal"] and not report["overdue"]:
                continue
            artifacts = [item["artifact_id"] for item in report["artifacts"]
                         if item["artifact_type"] == "first_frame_image" and _usable([item["artifact_id"]])]
            success = report["terminal"] and report["status"] == "success" and len(artifacts) == 1
            error = None if success else report.get("error") or {
                "code": "TASK_OVERDUE" if report["overdue"] else "INCOMPLETE_OUTPUT",
                "summary": "Preview is incomplete; retry only this image after inspection"}
            versions.update_task(run, row, status="success" if success else "failed", artifact_ids=artifacts, error=error)
        except AppError as error:
            versions.update_task(run, row, status="failed", error={"code": error.code, "summary": error.message})
    return {"complete": all(row.status not in {"pending", "running"} or not row.job_id for row in rows),
            "failed": any(row.status == "failed" for row in rows)}


def bind_character_references(run, version):
    """Return updated copies; the caller records a new system plan version."""
    version = _version(run, version)
    plan, story = deepcopy(version.plan), deepcopy(version.story_package)
    old_refs = {character["character_id"]: set(character["reference"]["artifact_ids"])
                for character in story.get("characters", [])}
    for character in story.get("characters", []):
        if character["reference"]["source"] != "generate":
            continue
        task = versions.latest_task(run, version.version, "character", character["character_id"])
        if not task or task.status != "success" or not _usable(task.artifact_ids):
            raise AppError("PREVIEW_INCOMPLETE", "Generated character preview is missing or stale", 409)
        data = planned_inputs(run, version, "character", character["character_id"])
        if task.inputs_hash != versions.inputs_hash(data):
            raise AppError("PREVIEW_INCOMPLETE", "Character preview no longer matches this plan", 409)
        character["reference"]["artifact_ids"] = list(task.artifact_ids)
    new_refs = {character["character_id"]: character["reference"]["artifact_ids"] for character in story.get("characters", [])}
    for shot in plan["shots"]:
        for key in ("first_frame", "end_frame"):
            frame = shot.get(key)
            if not frame or frame["method"] != "generate":
                continue
            removed = set().union(*(old_refs.get(key, set()) for key in shot["character_ids"]))
            refs = [ref for ref in frame["reference_artifact_ids"] if ref not in removed]
            refs.extend(ref for key in shot["character_ids"] for ref in new_refs.get(key, []))
            frame["reference_artifact_ids"] = list(dict.fromkeys(refs))
            if frame["reference_artifact_ids"]:
                frame["image_mode"] = "i2i"
                # Director already chose an i2i model for pending characters.
    return plan, story


def preview_view(run, version=None):
    version = _version(run, version)
    view = {"characters": {}, "keyframes": {}, "end_frames": {}}
    maps = {"character": "characters", "keyframe": "keyframes", "end_frame": "end_frames"}
    for character in version.story_package.get("characters", []):
        reference = character["reference"]
        if reference["source"] != "generate":
            refs = reference["artifact_ids"]
            good = _usable(refs)
            view["characters"][character["character_id"]] = {
                "status": "success" if good else "failed", "artifact_id": refs[0] if refs and good else None,
                "preview_url": f"/api/artifacts/{refs[0]}/preview" if refs and good else None,
                "attempt": 0, "stale": False, "error": None if good else {"code": "ARTIFACT_NOT_FOUND"},
                "estimated_cost": 0, "model_id": None}
    for kind, target_id in targets_for(version):
        task = versions.latest_task(run, version.version, kind, target_id)
        error = None
        try:
            data = planned_inputs(run, version, kind, target_id)
            fingerprint, cost = versions.inputs_hash(data), _cost(data)
        except AppError as problem:
            data, fingerprint, cost = {}, None, task.estimated_cost if task else 0
            if problem.code == "PREVIEW_INCOMPLETE":
                try:
                    data = _planned_inputs(run, version, kind, target_id, allow_pending=True)
                    cost = _cost(data)
                except AppError:
                    pass
            error = {"code": problem.code, "summary": problem.message}
        stale = bool(task and (task.status == "stale" or (fingerprint is not None and task.inputs_hash != fingerprint)))
        refs = task.artifact_ids if task else []
        if not task and data.get("method") == "user_image":
            refs = [data["artifact_id"]]
        good = _usable(refs)
        status = "stale" if stale else task.status if task else "success" if good else "pending"
        if status == "success" and not good:
            status, stale = "stale", True
        view[maps[kind]][target_id] = {"status": status, "artifact_id": refs[0] if refs and good else None,
            "preview_url": f"/api/artifacts/{refs[0]}/preview" if refs and good else None,
            "attempt": task.attempt if task else 0, "stale": stale,
            "error": task.error if task and task.error else error,
            "estimated_cost": cost, "model_id": data.get("model_id")}
    return view
