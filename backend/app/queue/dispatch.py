"""Durable, shared Job ingress. A dispatch tick yields while providers are busy."""
from contextlib import contextmanager
from datetime import timedelta
import threading

from flask import current_app, g
from sqlalchemy import or_

from app.extensions import db
from app.api import AppError
from app.models import ApiTask, Job, JobDispatch
from app.queue.state import seconds
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


def require_lease(job_id, token):
    from app.queue import DispatchLost
    if not token:
        return
    # Node handlers already write Job/Artifact FK rows. Taking a dispatch + Job
    # FOR UPDATE join here reverses their lock order and deadlocks parallel DAGs.
    # Read from a fresh transaction (not the caller's repeatable-read snapshot).
    # Paid operations remain fenced atomically by ApiTask CAS/operation keys.
    with db.engine.connect() as connection:
        owner = connection.execute(db.select(JobDispatch.id).join(Job, Job.id == JobDispatch.job_id).where(
            Job.job_id == job_id, JobDispatch.lease_token == token)).first()
    if not owner:
        raise DispatchLost("Job dispatch ownership changed")


def enqueue_job(job, run_type, node_key=None, force=False, restart=False):
    # Lock the parent row, which exists even for the first dispatch.
    job = Job.query.filter_by(id=job.id).populate_existing().with_for_update().one()
    dispatch = JobDispatch.query.filter_by(job_id=job.id).populate_existing().first()
    if not dispatch and job.status in {"running", "queued"}:
        raise AppError("LEGACY_RUN_ACTIVE", "Drain the existing workflow execution before moving this job to MQ", 409)
    if dispatch and dispatch.status in {"ready", "running"}:
        if job.status == "paused":
            job.status = "pending"
            dispatch.available_at = utc_now()
        db.session.commit()
        return {"job_id": job.job_id, "status": "queued", "queue": "redis"}
    if ApiTask.query.filter_by(job_id=job.id, queue_phase="submit_unknown").first():
        raise AppError("MQ_RECONCILIATION_REQUIRED", "Reconcile the unknown provider submission before starting a new run", 409)
    if restart and run_type == "run_full":
        from app.services.job_run_state_service import JobRunStateService
        from app.services.workflow_service import WorkflowService
        JobRunStateService.begin_restart(job, [node.node_key for node in WorkflowService.list_nodes()
                                              if WorkflowService.is_node_enabled(job, node)])
    if not dispatch:
        dispatch = JobDispatch(job_id=job.id)
        db.session.add(dispatch)
    dispatch.version = new_id("dispatch")
    dispatch.command = {"run_type": run_type, "node_key": node_key, "force": force}
    dispatch.status = "ready"
    dispatch.available_at = utc_now()
    dispatch.lease_token = None
    dispatch.lease_until = None
    dispatch.error = None
    job.status = "queued"
    db.session.commit()
    return {"job_id": job.job_id, "status": "queued", "queue": "redis"}


@contextmanager
def heartbeat(dispatch_id, token):
    app = current_app._get_current_object()
    stop = threading.Event()
    lease_seconds = seconds("MQ_LEASE_SEC", 900)
    def renew():
        while not stop.wait(max(1, lease_seconds / 3)):
            with app.app_context():
                try:
                    JobDispatch.query.filter_by(id=dispatch_id, lease_token=token).update(
                        {"lease_until": utc_now() + timedelta(seconds=lease_seconds)}, synchronize_session=False)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    app.logger.exception("MQ dispatch heartbeat failed: %s", dispatch_id)
                finally:
                    db.session.remove()
    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


def dispatch_once():
    now = utc_now()
    eligible = or_(JobDispatch.status == "ready",
                   (JobDispatch.status == "running") & (JobDispatch.lease_until < now))
    candidate = JobDispatch.query.filter(eligible, JobDispatch.available_at <= now).order_by(JobDispatch.available_at).first()
    if not candidate:
        db.session.commit()
        return False
    dispatch_id, token = candidate.id, new_id("joblease")
    won = JobDispatch.query.filter(JobDispatch.id == dispatch_id, eligible).update({
        "status": "running", "lease_token": token,
        "lease_until": now + timedelta(seconds=seconds("MQ_LEASE_SEC", 900)),
    }, synchronize_session=False)
    db.session.commit()
    if not won:
        return False
    # This project disables expire_on_commit. Reload after the CAS update so
    # unchanged-looking cached values cannot suppress lease/status release.
    db.session.expire_all()
    dispatch = db.session.get(JobDispatch, dispatch_id)
    job = db.session.get(Job, dispatch.job_id)
    version, command, job_id = dispatch.version, dispatch.command, job.job_id
    status = job.status
    db.session.commit()
    error = None
    try:
        with heartbeat(dispatch_id, token):
            if status not in {"paused", "cancelled"}:
                from app.services.job_run_service import JobRunService
                g.mq_dispatch = version
                g.mq_dispatch_token = token
                result = JobRunService._dispatch(job_id, command["run_type"], command["node_key"], command["force"])
                status = result["status"]
    except Exception as exc:
        db.session.rollback()
        error = str(exc)
        status = "failed"
        current_app.logger.exception("MQ dispatch failed: %s", job_id)
    finally:
        g.pop("mq_dispatch", None)
        g.pop("mq_dispatch_token", None)
    dispatch = JobDispatch.query.filter_by(id=dispatch_id, lease_token=token).populate_existing().with_for_update().first()
    if dispatch:
        dispatch.status = "ready" if status in {"running", "paused", "queued", "pending"} else "done"
        dispatch.available_at = utc_now() + timedelta(seconds=seconds("MQ_TICK_SEC", 2))
        dispatch.error = error
        dispatch.lease_token = None
        dispatch.lease_until = None
        if error:
            job = db.session.get(Job, dispatch.job_id)
            job.status, job.error_summary = "failed", error
        db.session.commit()
    return True
