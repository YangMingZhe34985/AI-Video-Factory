from datetime import timedelta

from flask import current_app
from sqlalchemy import or_

from app.extensions import db
from app.models import ApiTask, Job, TaskOutbox
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


def seconds(name, default):
    return max(1, int(current_app.config.get(name, default)))


def inactive_reason(task):
    from app.services.job_run_state_service import JobRunStateService
    job = db.session.get(Job, task.job_id)
    if not job or job.status == "cancelled":
        return "Job cancelled"
    current_run = JobRunStateService.current_run_id(job)
    if current_run and task.request_payload.get("_run_id") != current_run:
        return "Superseded full run; stale result ignored"
    return None


def enqueue(task, phase, delay=0):
    """Caller commits the state transition and event in the SAME transaction."""
    task.queue_phase = phase
    task.queue_generation += 1
    task.lease_token = None
    task.lease_until = None
    task.next_poll_at = utc_now() + timedelta(seconds=delay)
    db.session.add(TaskOutbox(
        event_key=f"{task.api_task_id}:{phase}:{task.queue_generation}",
        task_id=task.id, phase=phase, generation=task.queue_generation,
        available_at=task.next_poll_at,
    ))


def claim(task_id, phase, generation):
    token = new_id("lease")
    now = utc_now()
    changed = ApiTask.query.filter(
        ApiTask.id == task_id, ApiTask.queue_phase == phase,
        ApiTask.queue_generation == generation,
        or_(ApiTask.lease_token.is_(None), ApiTask.lease_until < now),
    ).update({"lease_token": token, "lease_until": now + timedelta(seconds=seconds("MQ_LEASE_SEC", 900)),
              "queue_phase": phase + "_active"}, synchronize_session=False)
    db.session.commit()
    return token if changed else None


def owned(task_id, token):
    """A row lock fences completion against recovery; never held during network IO."""
    db.session.expire_all()
    return ApiTask.query.filter_by(id=task_id, lease_token=token).with_for_update().first()


def finish_event(event_id):
    TaskOutbox.query.filter_by(id=event_id).update({"consumed_at": utc_now()}, synchronize_session=False)


def fail(task, message, *, unknown=False):
    task.queue_phase = "submit_unknown" if unknown else "failed"
    task.status = task.queue_phase
    task.error_message = message
    task.lease_token = None
    task.lease_until = None
    task.completed_at = utc_now()
