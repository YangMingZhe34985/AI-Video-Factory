from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from flask import current_app

from app.api import AppError
from app.extensions import db
from app.models import Job
from app.services.error_detail_service import ErrorDetailService
from app.services.event_service import EventService
from app.services.job_run_state_service import JobRunStateService
from app.services.workflow_service import WorkflowService


@dataclass
class QueuedJobTask:
    job_id: str
    run_type: str
    node_key: str | None = None
    force: bool = False
    restart: bool = False
    submitted_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "run_type": self.run_type,
            "node_key": self.node_key,
            "force": self.force,
            "restart": self.restart,
            "submitted_at": self.submitted_at,
        }


class JobQueueService:
    _lock = threading.RLock()
    _queue: deque[QueuedJobTask] = deque()
    _running: dict[str, threading.Thread] = {}
    _app = None

    @classmethod
    def enqueue(
        cls,
        job_id: str,
        run_type: str,
        force: bool = False,
        node_key: str | None = None,
        restart: bool = False,
    ) -> dict:
        app = current_app._get_current_object()
        with cls._lock:
            cls._app = app
            job = Job.query.filter_by(job_id=job_id).first()
            if not job:
                raise AppError("JOB_NOT_FOUND", "Job not found", 404)
            if job.status == "running" or cls._is_known(job_id):
                return cls._response_for_existing(job)

            if restart and run_type == "run_full":
                nodes = [
                    node.node_key
                    for node in WorkflowService.list_nodes()
                    if WorkflowService.is_node_enabled(job, node)
                ]
                JobRunStateService.begin_restart(job, nodes)

            task = QueuedJobTask(
                job_id=job_id,
                run_type=run_type,
                node_key=node_key,
                force=force,
                restart=restart,
            )
            cls._queue.append(task)
            job.status = "queued"
            job.current_node = None
            job.error_summary = None
            EventService.record(
                job,
                "JOB_QUEUED",
                message="Job queued",
                payload=task.to_dict(),
            )
            db.session.commit()
            cls._drain_locked()
            return cls._response_for_task(task, job.status)

    @classmethod
    def cancel_queued(cls, job_id: str) -> bool:
        with cls._lock:
            for task in list(cls._queue):
                if task.job_id != job_id:
                    continue
                cls._queue.remove(task)
                job = Job.query.filter_by(job_id=job_id).first()
                if job:
                    job.status = "cancelled"
                    job.current_node = None
                    EventService.record(
                        job,
                        "JOB_CANCELLED",
                        message="Queued job cancelled",
                        payload={"queue": True},
                    )
                    db.session.commit()
                return True
        return False

    @classmethod
    def status(cls) -> dict:
        with cls._lock:
            max_runs = cls._max_concurrent_runs()
            return {
                "enabled": True,
                "max_concurrent_runs": max_runs,
                "running_count": len(cls._running),
                "queued_count": len(cls._queue),
                "running_job_ids": list(cls._running.keys()),
                "queued_jobs": [task.to_dict() for task in cls._queue],
            }

    @classmethod
    def _drain_locked(cls) -> None:
        app = cls._app
        if app is None:
            return
        max_runs = cls._max_concurrent_runs()
        while cls._queue and len(cls._running) < max_runs:
            task = cls._queue.popleft()
            thread = threading.Thread(
                target=cls._run_task,
                args=(app, task),
                daemon=True,
            )
            cls._running[task.job_id] = thread
            thread.start()

    @classmethod
    def _run_task(cls, app, task: QueuedJobTask) -> None:
        with app.app_context():
            try:
                job = Job.query.filter_by(job_id=task.job_id).first()
                if not job:
                    return
                if job.status == "cancelled":
                    return
                EventService.record(
                    job,
                    "JOB_DEQUEUED",
                    message="Job dequeued",
                    payload=task.to_dict(),
                )
                EventService.record(
                    job,
                    "JOB_QUEUE_STARTED",
                    message="Job queue execution started",
                    payload={
                        "running_count": len(cls._running),
                        "max_concurrent_runs": cls._max_concurrent_runs(),
                    },
                )
                db.session.commit()
                cls._execute_task(task)
            except Exception as error:
                app.logger.exception("Queued job execution failed: %s", error)
                job = Job.query.filter_by(job_id=task.job_id).first()
                if job:
                    code = getattr(error, "code", "INTERNAL_ERROR")
                    payload = getattr(error, "payload", None)
                    error_detail = ErrorDetailService.build(
                        job=job,
                        code=code,
                        message=getattr(error, "message", str(error)),
                        error=error,
                        payload=payload,
                        extra={"queue": True, "task": task.to_dict()},
                    )
                    job.status = "failed"
                    job.current_node = None
                    job.error_summary = error_detail["summary"]
                    EventService.record(
                        job,
                        "JOB_FAILED",
                        message=error_detail["summary"],
                        level="error",
                        payload={"queue": True, "error_detail": error_detail},
                    )
                    db.session.commit()
            finally:
                try:
                    cls._release(task.job_id)
                finally:
                    db.session.remove()

    @classmethod
    def _execute_task(cls, task: QueuedJobTask) -> None:
        if task.run_type == "run_full":
            WorkflowService.run_full(task.job_id, force=task.force)
            return
        if task.run_type == "run_from":
            WorkflowService.run_from(task.job_id, task.node_key or "", force=task.force)
            return
        if task.run_type == "run_node":
            WorkflowService.run_node(task.job_id, task.node_key or "", force=task.force)
            return
        raise AppError("INVALID_INPUT", f"Unknown queue task type: {task.run_type}", 400)

    @classmethod
    def _release(cls, job_id: str) -> None:
        with cls._lock:
            cls._running.pop(job_id, None)
            app = cls._app
            if app:
                with app.app_context():
                    job = Job.query.filter_by(job_id=job_id).first()
                    if job:
                        EventService.record(
                            job,
                            "JOB_QUEUE_SLOT_RELEASED",
                            message="Job queue slot released",
                            payload={
                                "running_count": len(cls._running),
                                "queued_count": len(cls._queue),
                            },
                        )
                        db.session.commit()
            cls._drain_locked()

    @classmethod
    def _is_known(cls, job_id: str) -> bool:
        return job_id in cls._running or any(task.job_id == job_id for task in cls._queue)

    @classmethod
    def _response_for_existing(cls, job: Job) -> dict:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "queue": cls.status(),
        }

    @classmethod
    def _response_for_task(cls, task: QueuedJobTask, status: str) -> dict:
        return {
            "job_id": task.job_id,
            "status": status,
            "queue": cls.status(),
        }

    @staticmethod
    def _max_concurrent_runs() -> int:
        return max(1, int(current_app.config.get("JOB_MAX_CONCURRENT_RUNS", 2)))
