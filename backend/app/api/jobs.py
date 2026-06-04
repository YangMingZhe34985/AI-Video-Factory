import json
import threading
import time
from http import HTTPStatus

from flask import Blueprint, Response, current_app, request

from app.api import AppError, api_success
from app.extensions import db
from app.models import Job, JobEvent
from app.services.error_detail_service import ErrorDetailService
from app.schemas.job_schema import (
    CreateJobSchema,
    DeleteJobSchema,
    RunFromSchema,
    RunFullSchema,
    RunNodeSchema,
    UpdateJobSchema,
)
from app.services.job_package_service import JobPackageService
from app.services.job_queue_service import JobQueueService
from app.services.job_service import JobService
from app.services.workflow_service import WorkflowService


bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")

_job_threads: dict[str, threading.Thread] = {}
_job_event_cursors: dict[str, int] = {}
_job_threads_lock = threading.RLock()


def _maybe_json(value, fallback):
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _request_payload() -> dict:
    if request.is_json:
        return request.get_json(silent=True) or {}
    data = request.form.to_dict()
    data["enabled_nodes"] = _maybe_json(data.get("enabled_nodes"), [])
    data["disabled_nodes"] = _maybe_json(data.get("disabled_nodes"), [])
    data["job_config"] = _maybe_json(data.get("job_config"), {})
    data["initial_prompts"] = _maybe_json(data.get("initial_prompts"), {})
    data["initial_artifacts"] = _maybe_json(data.get("initial_artifacts"), {})
    return data


@bp.post("")
def create_job():
    payload = CreateJobSchema.model_validate(_request_payload())
    source_video = request.files.get("source_video")
    initial_files = {
        "first_frame_image": request.files.get("first_frame_image")
        or request.files.get("artifact:first_frame_image"),
        "reference_images": (
            request.files.getlist("reference_images")
            + request.files.getlist("reference_images[]")
        ),
    }
    job = JobService.create_job(
        payload.model_dump(),
        source_video=source_video,
        initial_files=initial_files,
    )
    return api_success(
        {"job_id": job.job_id, "job_name": job.job_name, "status": job.status},
        HTTPStatus.CREATED,
    )


@bp.get("")
def list_jobs():
    return api_success(JobService.list_jobs(request.args.to_dict()))


@bp.get("/<job_id>")
def get_job(job_id: str):
    return api_success(JobService.get_detail(job_id))


@bp.patch("/<job_id>")
def update_job(job_id: str):
    payload = UpdateJobSchema.model_validate(request.get_json(silent=True) or {})
    job = JobService.update_job(job_id, payload.model_dump(exclude_unset=True))
    return api_success(job.to_dict())


@bp.delete("/<job_id>")
def delete_job(job_id: str):
    payload = DeleteJobSchema.model_validate(request.get_json(silent=True) or {})
    return api_success(JobService.delete_job(job_id, payload.confirm_job_id))


@bp.post("/<job_id>/package")
def package_job(job_id: str):
    job = JobService.get_job(job_id)
    return api_success(JobPackageService.create_or_refresh(job), HTTPStatus.CREATED)


@bp.post("/<job_id>/run-full")
def run_full(job_id: str):
    payload = RunFullSchema.model_validate(request.get_json(silent=True) or {})
    JobService.get_job(job_id)
    if current_app.config.get("JOB_QUEUE_ENABLED", True):
        return api_success(JobQueueService.enqueue(job_id, "run_full", force=payload.force))
    _start_async_run(job_id, lambda: WorkflowService.run_full(job_id, force=payload.force))
    return api_success({"job_id": job_id, "status": "running"})


@bp.post("/<job_id>/run-from")
def run_from(job_id: str):
    payload = RunFromSchema.model_validate(request.get_json(silent=True) or {})
    job = JobService.get_job(job_id)
    _validate_start_node(job, payload.node_key)
    if current_app.config.get("JOB_QUEUE_ENABLED", True):
        return api_success(
            JobQueueService.enqueue(
                job_id,
                "run_from",
                node_key=payload.node_key,
                force=payload.force,
            )
        )
    _start_async_run(job_id, lambda: WorkflowService.run_from(job_id, payload.node_key, force=payload.force))
    return api_success({"job_id": job_id, "status": "running"})


@bp.post("/<job_id>/run-node")
def run_node(job_id: str):
    payload = RunNodeSchema.model_validate(request.get_json(silent=True) or {})
    job = JobService.get_job(job_id)
    _validate_start_node(job, payload.node_key, check_dependencies=True)
    if current_app.config.get("JOB_QUEUE_ENABLED", True):
        return api_success(
            JobQueueService.enqueue(
                job_id,
                "run_node",
                node_key=payload.node_key,
                force=payload.force,
            )
        )
    _start_async_run(job_id, lambda: WorkflowService.run_node(job_id, payload.node_key, force=payload.force))
    return api_success({"job_id": job_id, "status": "running"})


@bp.get("/queue/status")
def queue_status():
    if not current_app.config.get("JOB_QUEUE_ENABLED", True):
        return api_success({"enabled": False})
    return api_success(JobQueueService.status())


def _start_async_run(job_id: str, target):
    with _job_threads_lock:
        if job_id in _job_threads and _job_threads[job_id].is_alive():
            return
        app = current_app._get_current_object()
        thread = threading.Thread(target=_run_in_app_context, args=(app, job_id, target), daemon=True)
        _job_threads[job_id] = thread
        thread.start()


def _run_in_app_context(app, job_id: str, target):
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
            from app.services.event_service import EventService

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


def _validate_start_node(job: Job, node_key: str, check_dependencies: bool = False) -> None:
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


@bp.get("/<job_id>/stream")
def stream_events(job_id: str):
    job = JobService.get_job(job_id)
    app = current_app._get_current_object()
    job_pk = job.id
    try:
        initial_last_id = max(int(request.args.get("after_id") or 0), 0)
    except (TypeError, ValueError):
        initial_last_id = 0

    def generate():
        last_id = initial_last_id
        empty_rounds = 0
        max_empty = 60
        while empty_rounds < max_empty:
            with app.app_context():
                events = (
                    JobEvent.query
                    .filter_by(job_id=job_pk)
                    .filter(JobEvent.id > last_id)
                    .order_by(JobEvent.id.asc())
                    .all()
                )
                for event in events:
                    data = json.dumps(event.to_dict(), ensure_ascii=False)
                    yield f"id: {event.id}\ndata: {data}\n\n"
                    last_id = event.id
                    empty_rounds = 0
                if not events:
                    empty_rounds += 1
            time.sleep(2)
        yield "data: {\"type\": \"stream_closed\"}\n\n"

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@bp.post("/<job_id>/pause")
def pause_job(job_id: str):
    job = JobService.pause(job_id)
    return api_success(job.to_dict())


@bp.post("/<job_id>/cancel")
def cancel_job(job_id: str):
    if current_app.config.get("JOB_QUEUE_ENABLED", True) and JobQueueService.cancel_queued(job_id):
        return api_success(JobService.get_job(job_id).to_dict())
    job = JobService.cancel(job_id)
    return api_success(job.to_dict())


@bp.get("/<job_id>/events")
def job_events(job_id: str):
    job = JobService.get_job(job_id)
    try:
        limit = int(request.args.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    limit = min(max(limit, 1), 500)
    events = (
        JobEvent.query.filter_by(job_id=job.id)
        .order_by(JobEvent.id.desc())
        .limit(limit)
        .all()
    )
    events = list(reversed(events))
    return api_success({"events": [event.to_dict() for event in events]})
