"""Adapt existing node handlers to resumable provider operations."""
import hashlib
import json
from sqlalchemy.exc import IntegrityError

from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Artifact
from app.queue import TaskPending
from app.queue.state import enqueue
from app.services.job_run_state_service import JobRunStateService


def submit(node_run, job, model, adapter_name, payload, identity, *, generation):
    # A resumed node owns the original operation even if defaults/prompts change
    # while it waits. Input hashes would accidentally submit a second paid call.
    slot = {"dispatch": node_run.input_snapshot["mq_dispatch"], "operation": identity["operation"],
            "sample": identity["inputs"].get("test_index", 0)}
    digest = hashlib.sha256(json.dumps(slot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    key = f"mq:{digest}"
    task = ApiTask.query.filter_by(operation_key=key).first()
    if not task:
        task = ApiTask(job_id=job.id, node_run_id=node_run.id, branch_key=node_run.node_key,
                       model_id=model.model_id, adapter_name=adapter_name, operation_key=key,
                       status="queued", queue_generation=0,
                       request_payload=JobRunStateService.task_payload_for_job(job, payload),
                       queue_data={"inputs": identity["inputs"], "params": identity["params"], "generation": generation,
                                   "dispatch": node_run.input_snapshot["mq_dispatch"], "operation": identity["operation"]})
        try:
            with db.session.begin_nested():
                db.session.add(task)
                db.session.flush()
                enqueue(task, "submit")
                db.session.flush()
            db.session.commit()
        except IntegrityError:
            # Another owner may have recovered this same logical node while the
            # previous process was losing its lease. Reuse its committed operation.
            db.session.rollback()
            task = ApiTask.query.filter_by(operation_key=key).first()
            if not task:
                raise
    if generation:
        # Media submit nodes only declare work. Poll/download own completion.
        return {**(task.response_payload or {}), "_mq_task_id": task.id,
                "provider_task_id": task.provider_task_id, "status": task.status}
    if task.queue_phase in {"failed", "submit_unknown"}:
        raise AppError("MQ_TASK_FAILED", task.error_message, 502)
    if task.queue_phase != "done":
        raise TaskPending()
    return task.response_payload


def adopt(job, task_id, branch_key, request_payload, expected_path):
    task = db.session.get(ApiTask, task_id)
    task.branch_key = branch_key
    task.request_payload = JobRunStateService.task_payload_for_job(job, {**request_payload, **task.request_payload})
    # Explicit reruns never overwrite an older valid result or its receipt.
    from pathlib import PurePosixPath
    original = PurePosixPath(expected_path)
    task.expected_artifact_path = str(original.parent / task.api_task_id / original.name)
    db.session.flush()
    return task


def complete(task, node_run, artifact_type, prompt_version, metadata, artifact_branch_key):
    if task.queue_phase in {"failed", "submit_unknown"}:
        raise AppError("MQ_TASK_FAILED", task.error_message or task.queue_phase, 502)
    if task.queue_phase == "done":
        artifact = Artifact.query.filter_by(api_task_id=task.id, artifact_type=artifact_type).first()
        if not artifact:
            raise AppError("MQ_ARTIFACT_MISSING", "Completed task has no registered artifact", 500)
        return artifact
    if not (task.queue_data or {}).get("download"):
        task.queue_data = {**task.queue_data, "download": {
            "node_run_id": node_run.id, "artifact_type": artifact_type,
            "prompt_version": prompt_version, "metadata": metadata,
            "artifact_branch_key": artifact_branch_key,
        }}
        if task.queue_phase == "generated":
            enqueue(task, "download")
        db.session.commit()
    raise TaskPending()
