"""One finite network operation per claimed event; no per-task polling loop."""
from app.adapters import get_adapter
from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Job, ModelRegistry, TaskOutbox
from app.queue.state import claim, enqueue, fail, finish_event, inactive_reason, owned, seconds
from app.utils.time_utils import utc_now


def process_event(event_id, expected_phase=None):
    db.session.expire_all()
    event = db.session.get(TaskOutbox, event_id)
    if not event or event.consumed_at:
        return
    if event.available_at.replace(tzinfo=None) > utc_now().replace(tzinfo=None):
        return
    if expected_phase and event.phase != expected_phase:
        raise ValueError("Outbox event routed to wrong stream")
    task = db.session.get(ApiTask, event.task_id)
    phase, generation, task_id = event.phase, event.generation, event.task_id
    if task.queue_generation != generation or task.queue_phase not in {phase, phase + "_active"}:
        finish_event(event_id)
        db.session.commit()
        return
    job = db.session.get(Job, task.job_id)
    reason = inactive_reason(task)
    if reason:
        fail(task, reason)
        task.status = "cancelled"
        finish_event(event_id)
        db.session.commit()
        return
    if job.status == "paused":
        return  # SQL event remains unconsumed and will be republished after resume.
    token = claim(task_id, phase, generation)
    if not token:
        return
    task = db.session.get(ApiTask, task_id)
    model = ModelRegistry.query.filter_by(model_id=task.model_id).first()
    adapter = get_adapter(task.adapter_name, model=model)
    payload = (task.queue_data or {}).get("wire_payload")
    logical_inputs = (task.queue_data or {}).get("inputs")
    params = (task.queue_data or {}).get("params")
    provider_id = task.provider_task_id
    db.session.commit()
    try:
        if phase == "submit":
            if not model or not model.enabled:
                raise AppError("MODEL_DISABLED", "Model was removed or disabled before submission", 400)
            if (job.config or {}).get("agent_transform"):
                from app.agent.transform_policy import validate_before_submit
                validate_before_submit(job, model, logical_inputs, params, adapter_name=task.adapter_name)
                if task.branch_key not in {"submit_r2v_flash", "r2v_flash"}:
                    raise AppError("TRANSFORM_APPROVAL_MISMATCH", "Queued transform operation differs from approval", 409)
            if logical_inputs is not None:
                payload = adapter.build_payload(logical_inputs, params or {})
                task = owned(task_id, token)
                if not task:
                    db.session.rollback()
                    return
                task.queue_data = {**task.queue_data, "wire_payload": payload}
                db.session.commit()
            if (job.config or {}).get("agent_transform"):
                validate_before_submit(job, model, logical_inputs, params, adapter_name=task.adapter_name)
            response = adapter.submit(payload)
        elif phase == "poll":
            response = adapter.poll(provider_id)
        else:
            from app.queue.download import download
            download(task_id, token, adapter)
            finish_event(event_id)
            db.session.commit()
            return
    except Exception as error:
        db.session.rollback()
        task = owned(task_id, token)
        if task:
            task.queue_attempts += 1
            code = getattr(error, "status_code", None)
            if (job.config or {}).get("agent_story_production"):
                from app.agent.production_repair import failure_evidence
                task.queue_data = {**(task.queue_data or {}), "failure_detail": failure_evidence(error, phase)}
            # A transport failure or server error after POST may have billed already.
            if phase == "submit" and code != 429:
                fail(task, str(error), unknown=not (isinstance(code, int) and 400 <= code < 500))
            elif task.queue_attempts >= seconds("MQ_MAX_ATTEMPTS", 3):
                fail(task, str(error))
            else:
                task.error_message = str(error)
                retry_after = (getattr(error, "payload", None) or {}).get("retry_after", 0)
                try:
                    retry_after = min(3600, max(0, int(retry_after)))
                except (TypeError, ValueError):
                    retry_after = 0
                enqueue(task, phase, max(retry_after, min(300, 2 ** task.queue_attempts)))
            finish_event(event_id)
            db.session.commit()
        return
    task = owned(task_id, token)
    if not task:
        db.session.rollback()
        return
    task.response_payload = response
    task.error_message = None
    if (job.config or {}).get("agent_story_production") and task.queue_data:
        task.queue_data = {key: value for key, value in task.queue_data.items() if key != "failure_detail"}
    reason = inactive_reason(task)
    if reason:
        if phase == "submit":
            task.provider_task_id = None if response.get("synchronous") else response.get("provider_task_id")
        fail(task, reason)
        task.status = "cancelled"
        finish_event(event_id)
        db.session.commit()
        return
    if phase == "submit":
        task.provider_task_id = None if response.get("synchronous") else response.get("provider_task_id")
        task.submitted_at = utc_now()
        task.status = response.get("status") or "submitted"
        if response.get("status") in {"failed", "cancelled"}:
            fail(task, response.get("error_message") or "Provider rejected submission")
        elif not task.queue_data["generation"]:
            task.queue_phase = "done"
            task.status = "success"
            task.completed_at = utc_now()
            task.lease_token = None
            task.lease_until = None
        elif response.get("status") == "success":
            generated(task)
        elif task.provider_task_id:
            task.queue_attempts = 0
            enqueue(task, "poll")
        else:
            fail(task, "Submission returned no usable provider ID", unknown=True)
    else:
        task.poll_count += 1
        if response.get("status") == "success":
            generated(task)
        elif response.get("status") in {"failed", "cancelled"}:
            fail(task, response.get("error_message") or "Provider task failed")
        elif task.poll_count >= seconds("MAX_POLL_ROUNDS", 90):
            fail(task, "Maximum poll rounds reached; provider ID retained for reconciliation")
        else:
            enqueue(task, "poll", seconds("POLL_INTERVAL_SEC", 10))
    finish_event(event_id)
    db.session.commit()


def generated(task):
    task.status = "generated"
    task.queue_attempts = 0
    task.lease_token = None
    task.lease_until = None
    if task.queue_data.get("download"):
        enqueue(task, "download")
    else:
        task.queue_phase = "generated"


def recover_expired():
    now = utc_now()
    ids = [row.id for row in ApiTask.query.filter(
        ApiTask.lease_until < now,
        ApiTask.queue_phase.in_(["submit_active", "poll_active", "download_active"])
    ).limit(100).all()]
    db.session.commit()
    for task_id in ids:
        task = ApiTask.query.filter(ApiTask.id == task_id, ApiTask.lease_until < now).populate_existing().with_for_update().first()
        if not task:
            continue
        phase = task.queue_phase.removesuffix("_active")
        if phase == "submit":
            fail(task, "Submit worker lease expired; reconcile provider outcome before proceeding", unknown=True)
        else:
            task.queue_attempts += 1
            if task.queue_attempts >= seconds("MQ_MAX_ATTEMPTS", 3):
                fail(task, f"{phase} worker repeatedly lost its lease")
            else:
                enqueue(task, phase)
        db.session.commit()
    return len(ids)
