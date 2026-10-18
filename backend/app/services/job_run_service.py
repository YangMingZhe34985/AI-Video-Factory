import threading
from collections.abc import Callable

from flask import current_app

from app.api import AppError
from app.extensions import db
from app.models import Job
from app.services.error_detail_service import ErrorDetailService
from app.services.event_service import EventService
from app.services.job_queue_service import JobQueueService
from app.services.job_run_state_service import JobRunStateService
from app.services.job_service import JobService
from app.services.workflow_service import WorkflowService


RUN_TYPES = ("run_full", "run_from", "run_node")


class JobRunService:
    """Starts workflow runs for a job.

    Shared by the REST API and the skill layer: dispatches to the global job
    queue when it is enabled, otherwise to a per-job background thread.
    """

    _threads: dict[str, threading.Thread] = {}
    _threads_lock = threading.RLock()

    @classmethod
    def start(
        cls,
        job_id: str,
        run_type: str,
        node_key: str | None = None,
        force: bool = False,
        restart: bool = False,
    ) -> dict:
        job = cls._prepare(job_id, run_type, node_key, force=force, restart=restart)
        from app.models import JobDispatch
        # Queue ownership survives admission being switched off during drain.
        if current_app.config.get("MQ_ENABLED", False) or JobDispatch.query.filter_by(job_id=job.id).first():
            from app.queue.dispatch import enqueue_job
            return enqueue_job(job, run_type, node_key, force, restart)
        if current_app.config.get("JOB_QUEUE_ENABLED", True):
            return JobQueueService.enqueue(
                job_id,
                run_type,
                force=force,
                node_key=node_key,
                restart=restart,
            )
        if restart and run_type == "run_full":
            cls._begin_restart(job)
        cls._start_thread(job_id, lambda: cls._dispatch(job_id, run_type, node_key, force))
        return {"job_id": job_id, "status": "running"}

    @classmethod
    def run_inline(
        cls,
        job_id: str,
        run_type: str = "run_full",
        node_key: str | None = None,
        force: bool = False,
        restart: bool = False,
    ) -> dict:
        """Run synchronously in the caller's thread (tests and scripts)."""
        job = cls._prepare(job_id, run_type, node_key, force=force, restart=restart)
        if restart and run_type == "run_full":
            cls._begin_restart(job)
        return cls._dispatch(job_id, run_type, node_key, force)

    @staticmethod
    def validate_start_node(job: Job, node_key: str, check_dependencies: bool = False) -> None:
        node = WorkflowService.get_node(node_key)
        if not WorkflowService.is_node_enabled(job, node):
            raise AppError("NODE_DISABLED", "Workflow node is disabled", 400)
        if check_dependencies:
            missing = WorkflowService._missing_dependencies(job, node)
            if missing:
                raise AppError(
                    "DEPENDENCY_MISSING",
                    f"Dependencies not satisfied: {', '.join(missing)}",
                    400,
                    payload={"missing": missing},
                )

    @classmethod
    def is_running_in_thread(cls, job_id: str) -> bool:
        thread = cls._threads.get(job_id)
        return bool(thread and thread.is_alive())

    @classmethod
    def _prepare(cls, job_id: str, run_type: str, node_key: str | None, *, force=False, restart=False) -> Job:
        if run_type not in RUN_TYPES:
            raise AppError("INVALID_INPUT", f"Unknown run type: {run_type}", 400)
        job = JobService.get_job(job_id)
        from app.agent.production_policy import validate_dispatch
        validate_dispatch(job, run_type, node_key, force, restart)
        from app.agent.transform_policy import validate_dispatch as validate_transform_dispatch
        validate_transform_dispatch(job, run_type, node_key, force, restart)
        if run_type == "run_from":
            cls.validate_start_node(job, node_key or "")
        elif run_type == "run_node":
            cls.validate_start_node(job, node_key or "", check_dependencies=True)
        return job

    @staticmethod
    def _begin_restart(job: Job) -> None:
        nodes = [
            node.node_key
            for node in WorkflowService.list_nodes()
            if WorkflowService.is_node_enabled(job, node)
        ]
        JobRunStateService.begin_restart(job, nodes)
        db.session.commit()

    @staticmethod
    def _dispatch(job_id: str, run_type: str, node_key: str | None, force: bool) -> dict:
        if run_type == "run_full":
            return WorkflowService.run_full(job_id, force=force)
        if run_type == "run_from":
            return WorkflowService.run_from(job_id, node_key or "", force=force)
        return WorkflowService.run_node(job_id, node_key or "", force=force)

    @classmethod
    def _start_thread(cls, job_id: str, target: Callable[[], object]) -> None:
        with cls._threads_lock:
            if cls.is_running_in_thread(job_id):
                return
            app = current_app._get_current_object()
            thread = threading.Thread(
                target=cls._run_in_app_context, args=(app, job_id, target), daemon=True
            )
            cls._threads[job_id] = thread
            thread.start()

    @staticmethod
    def _run_in_app_context(app, job_id: str, target: Callable[[], object]) -> None:
        with app.app_context():
            try:
                target()
            except Exception as error:
                app.logger.exception("Async job execution failed: %s", error)
                job = Job.query.filter_by(job_id=job_id).first()
                if not job:
                    return
                code = getattr(error, "code", "INTERNAL_ERROR")
                payload = getattr(error, "payload", None)
                error_detail = ErrorDetailService.build(
                    job=job,
                    code=code,
                    message=getattr(error, "message", str(error)),
                    error=error,
                    payload=payload,
                    extra={"async_runner": True},
                )
                job.status = "failed"
                job.current_node = None
                job.error_summary = error_detail["summary"]
                EventService.record(
                    job,
                    "JOB_FAILED",
                    message=error_detail["summary"],
                    payload={"code": code, "error_detail": error_detail},
                    level="error",
                )
                db.session.commit()
            finally:
                db.session.remove()
