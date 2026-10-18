"""Safe, database-only projections for task center list and paged details."""
import re

from flask import current_app
from sqlalchemy import func, literal, select, union_all

from app.api import AppError
from app.extensions import db
from app.models import AgentRun, AgentShotTask, ApiTask, Job, JobDispatch, JobNodeRun, ToolInvocation
from app.services.task_center_query import (
    STATES, current_agent_job, current_api_query, current_version, latest_nodes, latest_shots, linked_to_run,
    parent_query, shared_workflow, visible_job,
)
from app.utils.time_utils import as_utc, utc_now

QUEUE_KEYS = ("submit_waiting", "submitting", "provider_running", "download_waiting", "downloading", "unknown")
PHASES = {
    "submit": ("queued", "submit_waiting", "submission_queue"),
    "submit_active": ("running", "submitting", None),
    "poll": ("running", "provider_running", "provider"),
    "poll_active": ("running", "provider_running", "provider"),
    "download": ("queued", "download_waiting", "download_queue"),
    "download_active": ("running", "downloading", None),
    "submit_unknown": ("attention", "unknown", "submission_unknown"),
}
SAFE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,119}$")


def code(value):
    return value if isinstance(value, str) and SAFE_CODE.fullmatch(value) else None


def stamp(value):
    return as_utc(value).isoformat() if value else None


def pagination(args, default=20):
    values = []
    for key, fallback, ceiling in (("page", 1, 1000000), ("per_page", default, 100)):
        raw = args.get(key, str(fallback))
        if not isinstance(raw, (str, int)) or not str(raw).isdigit() or not 1 <= int(raw) <= ceiling:
            raise AppError("INVALID_INPUT", "Invalid pagination", 422)
        values.append(int(raw))
    return values


def metadata():
    return {"observed_at": stamp(utc_now()), "scope": "own_agent_and_shared_workflow",
            "data_source": "database", "mq_admission_enabled": bool(current_app.config.get("MQ_ENABLED")),
            "worker_health": "unknown"}


def task_list(owner, args):
    page, per_page = pagination(args)
    source, state = args.get("source", "all"), args.get("state", "all")
    search = args.get("search", "").strip()
    if source not in {"all", "agent", "workflow"} or state not in {"all", *STATES} or len(search) > 200:
        raise AppError("INVALID_INPUT", "Invalid task filters", 422)
    base = parent_query(owner)
    filters = []
    if source != "all":
        filters.append(base.c.source == source)
    if search:
        filters.append(base.c.title.contains(search, autoescape=True) | base.c.task_id.contains(search, autoescape=True))
    with db.session.no_autoflush:
        summary = dict.fromkeys(STATES, 0)
        summary.update(dict(db.session.execute(select(base.c.state, func.count()).where(*filters).group_by(base.c.state)).all()))
        if state != "all":
            filters.append(base.c.state == state)
        total = db.session.scalar(select(func.count()).select_from(base).where(*filters))
        rows = db.session.execute(select(base).where(*filters).order_by(
            base.c.created_at.desc(), base.c.source.asc(), base.c.task_id.desc()
        ).offset((page - 1) * per_page).limit(per_page)).mappings().all()
        items = [project_parent(row, owner)[0] for row in rows]
    return {**metadata(), "items": items, "total": total, "page": page, "per_page": per_page, "summary": summary}


def _parent(owner, source, task_id):
    if source not in {"agent", "workflow"}:
        raise AppError("INVALID_INPUT", "Invalid task source", 422)
    base = parent_query(owner)
    row = db.session.execute(select(base).where(base.c.source == source, base.c.task_id == task_id)).mappings().first()
    if row is None:
        raise AppError("TASK_NOT_FOUND", "Task not found", 404)
    return row


def _jobs_for_run(run, version):
    query = Job.query.filter(linked_to_run(run.run_id), visible_job(run.owner_id))
    query = query.filter(current_agent_job(run.run_id))
    return query.all()


def queue_tasks(jobs):
    return current_api_query([job.id for job in jobs]).all() if jobs else []


def queue_counts(tasks):
    counts = dict.fromkeys(QUEUE_KEYS, 0)
    for task in tasks:
        phase = PHASES.get(task.queue_phase)
        if phase:
            counts[phase[1]] += 1
        elif not task.operation_key and task.status in {"submitted", "running", "pending"}:
            counts["provider_running"] += 1
    return counts


def _task_phase(task):
    if not task:
        return None
    result = PHASES.get(task.queue_phase)
    if result:
        state, stage, reason = result
        if task.queue_phase in {"submit", "download"} and task.queue_attempts and task.next_poll_at and as_utc(task.next_poll_at) > utc_now():
            reason = "retry_backoff"
        return state, stage, reason
    if task.status in {"submitted", "running", "pending"} and not task.operation_key:
        return "running", "provider_running", "provider"
    return None


def _phase_for(tasks):
    # Uncertain submission must remain visible even while independent work runs.
    priority = {"unknown": 0, "submitting": 1, "downloading": 2, "provider_running": 3,
                "submit_waiting": 4, "download_waiting": 5}
    relevant = [(task, _task_phase(task)) for task in tasks]
    relevant = [(task, phase) for task, phase in relevant if phase]
    return min(relevant, key=lambda pair: priority[pair[1][1]]) if relevant else (None, None)


def _node_keys(job):
    config = job.config or {}
    current = config.get("current_run") or {}
    keys = current.get("enabled_nodes") or (job.node_overrides or {}).get("enabled_nodes") or []
    return list(dict.fromkeys(key for key in keys if code(key)))


def _progress(statuses, total, unit):
    return {"unit": unit, "completed": sum(value in {"success", "skipped", "completed"} for value in statuses),
            "failed": sum(value in {"failed", "stale", "blocked", "path_failed"} for value in statuses), "total": total}


def project_parent(row, owner):
    item = {"source": row["source"], "id": row["task_id"], "title": str(row["title"])[:160],
            "state": row["state"], "created_at": stamp(row["created_at"]), "updated_at": stamp(row["updated_at"]),
            "wait_reason": None}
    if row["source"] == "agent":
        obj = db.session.get(AgentRun, row["pk"])
        version = current_version(obj)
        jobs = _jobs_for_run(obj, version)
        shots = latest_shots(obj.run_id, version.version).all() if version else []
        videos = [shot for shot in shots if shot.target_type == "video"]
        planned = (version.plan or {}).get("shots", []) if version else []
        if version:
            item["progress"] = _progress([task.status for task in videos], len(planned), "video_shots")
        else:
            nodes = latest_nodes([job.id for job in jobs]).all() if jobs else []
            item["progress"] = _progress([node.status for node in nodes],
                max(len(nodes), sum(len(_node_keys(job)) for job in jobs)), "workflow_nodes")
        item["stage"] = code(obj.status) or "unknown"
        if obj.status == "editing":
            stage = (obj.snapshot or {}).get("delivery", {}).get("stage")
            item["stage"] = "delivery_" + stage if stage in {"pending", "composing", "checking", "packaging", "complete", "failed"} else "editing"
        if obj.status.startswith("awaiting_") or obj.status in {"storyboard_approved", "characters_approved", "videos_approved"}:
            item["wait_reason"] = "user_authorization" if obj.status == "storyboard_approved" else "user_review"
        context = {"object": obj, "version": version, "shots": shots, "jobs": jobs, "planned": planned}
    else:
        obj = db.session.get(Job, row["pk"])
        jobs = [obj]
        nodes = latest_nodes([obj.id]).all()
        keys = _node_keys(obj)
        item["progress"] = _progress([node.status for node in nodes], max(len(nodes), len(keys)), "workflow_nodes")
        item["stage"] = code(obj.current_node) or code(obj.status) or "unknown"
        if obj.status == "queued":
            dispatch = JobDispatch.query.filter_by(job_id=obj.id).first()
            item["stage"] = "dispatch_waiting" if not dispatch or dispatch.status == "ready" else "dispatching"
            item["wait_reason"] = "scheduler"
        elif obj.status in {"paused", "pending"}:
            item["wait_reason"] = "paused" if obj.status == "paused" else "not_started"
        context = {"object": obj, "jobs": jobs, "nodes": nodes, "keys": keys}
    tasks = queue_tasks(jobs)
    item["queue_counts"] = queue_counts(tasks)
    task, phase = _phase_for(tasks)
    # Preserve the business-level approval/editing stage over old queue records.
    if phase and item["state"] not in {"waiting", "completed", "cancelled"} and obj.status != "editing":
        item["stage"], item["wait_reason"] = phase[1:]
    context["api_tasks"] = tasks
    return item, context


def _child(key, status, *, shot_id=None, node_key=None, model_id=None, depends_on=None,
           attempt=0, updated_at=None, error=None, task=None):
    state = ("completed" if status in {"success", "skipped", "completed"} else
             "attention" if status in {"failed", "stale", "blocked", "path_failed"} else
             "cancelled" if status == "cancelled" else "running" if status == "running" else "waiting")
    stage, reason = code(status) or "unknown", None
    phase = _task_phase(task)
    if phase and status not in {"success", "skipped", "cancelled"}:
        state, stage, reason = phase
    return {"id": key, "shot_id": code(shot_id), "node_key": code(node_key), "model_id": code(model_id),
            "state": state, "stage": stage, "wait_reason": reason, "depends_on": depends_on or [],
            "attempt": attempt, "next_check_at": stamp(task.next_poll_at) if task else None,
            "updated_at": stamp(updated_at), "error_code": code((error or {}).get("code"))}


def _paged_keys(query, synthetic, page, per_page):
    statements = [query] + [select(literal(key).label("key")) for key in synthetic]
    base = (union_all(*statements) if len(statements) > 1 else statements[0]).subquery()
    total = db.session.scalar(select(func.count()).select_from(base))
    keys = db.session.scalars(select(base.c.key).order_by(base.c.key).offset((page - 1) * per_page).limit(per_page)).all()
    return keys, total


def story_children(context, page, per_page):
    run, version = context["object"], context["version"]
    tasks = {f"{task.target_type}:{task.target_id}": task for task in context["shots"]}
    planned = context["planned"]
    shots = {shot["shot_id"]: shot for shot in planned}
    dependencies = {shot["shot_id"]: [planned[index - 1]["shot_id"]]
                    if index and shot.get("transition_in") == "tail_frame" else []
                    for index, shot in enumerate(planned)}
    query = latest_shots(run.run_id, version.version).with_entities(
        (AgentShotTask.target_type + ":" + AgentShotTask.target_id).label("key")).statement
    missing = [f"video:{sid}" for sid in shots if f"video:{sid}" not in tasks]
    keys, total = _paged_keys(query, missing, page, per_page)
    job_ids = {job.job_id: job.id for job in context["jobs"]}
    children = []
    for key in keys:
        kind, sid = key.split(":", 1)
        task, shot = tasks.get(key), shots.get(sid, {})
        dep = dependencies.get(sid, []) if kind == "video" else []
        status = task.status if task else "pending"
        apis = [api for api in context["api_tasks"] if task and api.job_id == job_ids.get(task.job_id)]
        api, _ = _phase_for(apis)
        child = _child(key, status, shot_id=sid, node_key=kind,
            model_id=(shot.get("motion") or {}).get("model_id") if kind == "video" else (api.model_id if api else None),
            depends_on=dep, attempt=task.attempt if task else 0,
            updated_at=task.updated_at if task else run.updated_at, error=task.error if task else None, task=api)
        if kind == "video" and status == "pending":
            if run.status not in {"producing", "production_attention", "awaiting_video_review", "videos_approved", "editing", "delivery_attention", "success", "partial_success", "cancelled"}:
                child.update(stage="awaiting_authorization", wait_reason="user_authorization")
            elif dep and any(not tasks.get(f"video:{parent}") or tasks[f"video:{parent}"].status != "success" for parent in dep):
                child.update(stage="waiting_dependency", wait_reason="dependency")
            else:
                child.update(state="queued", stage="pending", wait_reason="scheduler")
        children.append(child)
    return children, total


def workflow_children(context, page, per_page):
    jobs = context["jobs"]
    job_map = {job.id: job for job in jobs}
    nodes = latest_nodes(list(job_map)).all() if jobs else []
    by_key = {f"{node.job_id}:{node.node_key}": node for node in nodes}
    synthetic = [f"{job.id}:{node}" for job in jobs for node in _node_keys(job) if f"{job.id}:{node}" not in by_key]
    query = latest_nodes(list(job_map)).with_entities(
        (func.cast(JobNodeRun.job_id, db.String) + ":" + JobNodeRun.node_key).label("key")).statement
    keys, total = _paged_keys(query, synthetic, page, per_page)
    children = []
    for key in keys:
        node = by_key.get(key)
        job_id, node_key = key.split(":", 1)
        job = job_map[int(job_id)]
        apis = [api for api in context["api_tasks"] if node and api.node_run_id == node.id]
        api, _ = _phase_for(apis)
        child = _child(key, node.status if node else "pending", node_key=node_key,
            model_id=api.model_id if api else None, attempt=node.attempt if node else 0,
            updated_at=node.updated_at if node else job.updated_at, task=api)
        if not node:
            child["wait_reason"] = "not_started" if job.status == "pending" else "dependency"
        children.append(child)
    return children, total


def task_detail(owner, source, task_id, args):
    page, per_page = pagination(args, 50)
    with db.session.no_autoflush:
        row = _parent(owner, source, task_id)
        item, context = project_parent(row, owner)
        children, total = (story_children(context, page, per_page)
            if source == "agent" and context["version"] else workflow_children(context, page, per_page))
    return {**metadata(), "item": item, "children": children, "total": total, "page": page, "per_page": per_page}


def legacy_queue_status(owner):
    """Keep the legacy shape without exposing commands or other owners' IDs."""
    with db.session.no_autoflush:
        active = Job.query.filter(visible_job(owner), Job.status.in_(["queued", "running", "pending"])).all()
        dispatches = {row.job_id: row for row in JobDispatch.query.filter(
            JobDispatch.job_id.in_([job.id for job in active]), JobDispatch.status.in_(["ready", "running"])).all()}
        redis = bool(current_app.config.get("MQ_ENABLED") or dispatches)
        enabled = redis or bool(current_app.config.get("JOB_QUEUE_ENABLED", True))
        if not enabled:
            return {"enabled": False}
        queued = [{"job_id": job.job_id} for job in active if job.status == "queued"]
        running = [job.job_id for job in active if job.status == "running"
                   or (job.status == "pending" and job.id in dispatches)]
    return {"enabled": True, "mode": "redis" if redis else "memory", "data_source": "database",
            "worker_health": "unknown", "max_concurrent_runs": None, "queued_count": len(queued),
            "queued": queued, "running_count": len(running), "running": running}
