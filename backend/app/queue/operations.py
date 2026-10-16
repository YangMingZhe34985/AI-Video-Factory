"""Operator-only status/reconciliation. Never creates a new provider submission."""
from collections import Counter

from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Job, JobDispatch, JobNodeRun, TaskOutbox
from app.queue.state import enqueue, fail
from app.services.event_service import EventService
from app.utils.time_utils import as_utc, utc_now


def status():
    tasks = ApiTask.query.filter(ApiTask.operation_key.is_not(None)).all()
    pending = TaskOutbox.query.filter_by(consumed_at=None).all()
    unknown = [task for task in tasks if task.queue_phase == "submit_unknown"]
    return {
        "dispatches": dict(Counter(row.status for row in JobDispatch.query.all())),
        "task_phases": dict(Counter(task.queue_phase for task in tasks)),
        "unconsumed_events": len(pending),
        "oldest_event_seconds": max([max(0, (utc_now() - as_utc(row.created_at)).total_seconds()) for row in pending] or [0]),
        "publish_attempts": sum(row.attempts for row in pending),
        "submit_unknown": [{"api_task_id": task.api_task_id, "job_id": task.job_id,
                            "model_id": task.model_id, "branch": task.branch_key} for task in unknown],
        "cost_note": "Estimated Agent credits are in Agent metrics; these counts are not provider billing.",
    }


def ingress_status():
    rows = db.session.query(JobDispatch, Job).join(Job, JobDispatch.job_id == Job.id).filter(
        JobDispatch.status.in_(["ready", "running"])).all()
    queued = [{"job_id": job.job_id, **dispatch.command} for dispatch, job in rows if job.status == "queued"]
    running = [job.job_id for dispatch, job in rows if job.status in {"running", "pending"}]
    return {"enabled": True, "mode": "redis", "max_concurrent_runs": None,
            "queued_count": len(queued), "queued_jobs": queued,
            "running_count": len(running), "running_job_ids": running}


def reconcile(api_task_id, *, provider_id=None, terminate=False, retry=False, reason):
    if not reason.strip() or sum(bool(value) for value in (provider_id, terminate, retry)) != 1:
        raise AppError("INVALID_INPUT", "Provide a reason and exactly one reconciliation action", 400)
    task = ApiTask.query.filter_by(api_task_id=api_task_id).populate_existing().with_for_update().first()
    if not task or not task.operation_key:
        raise AppError("TASK_NOT_FOUND", "MQ task not found", 404)
    if task.queue_phase not in {"submit_unknown", "failed"}:
        raise AppError("INVALID_STATE", "Only stopped tasks can be reconciled", 409)
    job = db.session.get(Job, task.job_id)
    if terminate:
        fail(task, f"Operator terminated: {reason}")
    else:
        if not task.queue_data.get("generation"):
            raise AppError("INVALID_STATE", "Synchronous analysis outcome requires manual review; cannot bind a media task ID", 409)
        if provider_id:
            if task.queue_phase != "submit_unknown" or len(provider_id) > 255:
                raise AppError("INVALID_STATE", "A confirmed provider ID can only resolve submit_unknown", 409)
            task.provider_task_id = provider_id
            phase = "poll"
        else:
            last = TaskOutbox.query.filter_by(task_id=task.id).order_by(TaskOutbox.id.desc()).first()
            if not last or last.phase not in {"poll", "download"}:
                raise AppError("INVALID_STATE", "Automatic or manual resubmission of a paid POST is not supported", 409)
            phase = last.phase
        task.queue_attempts = 0
        task.poll_count = 0
        task.error_message = None
        task.status = "submitted" if phase == "poll" else "generated"
        enqueue(task, phase)
        dispatch = JobDispatch.query.filter_by(job_id=job.id).first()
        if dispatch:
            if job.status == "cancelled":
                raise AppError("INVALID_STATE", "Cancelled jobs cannot be resumed", 409)
            for node in JobNodeRun.query.filter_by(job_id=job.id).all():
                if ((node.input_snapshot or {}).get("mq_dispatch") == dispatch.version
                        and node.status in {"failed", "path_failed"}):
                    node.status = "waiting"
                    node.error_message = None
            dispatch.status = "ready"
            dispatch.available_at = utc_now()
            job.status = "pending"
            job.error_summary = None
    EventService.record(job, "MQ_RECONCILED", message=reason,
        payload={"api_task_id": task.api_task_id, "action": "terminate" if terminate else "bind_provider" if provider_id else "retry_read"})
    db.session.commit()
    return {"api_task_id": task.api_task_id, "queue_phase": task.queue_phase}
