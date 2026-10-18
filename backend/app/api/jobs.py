import json
import time
from http import HTTPStatus

from flask import Blueprint, Response, current_app, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app.agent.attachments import is_private_agent_job, require_upload_job_owner, validate_job_attachment_sources
from app.api import api_success
from app.models import JobEvent
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
from app.services.job_run_service import JobRunService
from app.services.job_service import JobService


bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")


@bp.before_app_request
def _protect_agent_upload_job():
    job_id = (request.view_args or {}).get("job_id")
    if request.method == "OPTIONS" or not job_id or not request.path.startswith("/api/jobs/"):
        return
    job = JobService.get_job(job_id)
    if is_private_agent_job(job):
        if current_app.config.get("API_AUTH_REQUIRED", True):
            verify_jwt_in_request()
            owner_id = get_jwt_identity()
        else:
            owner_id = "local"
        require_upload_job_owner(job, owner_id)


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
    validate_job_attachment_sources(payload.model_dump(),
        get_jwt_identity() if current_app.config.get("API_AUTH_REQUIRED", True) else "local")
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
    return api_success(
        JobRunService.start(job_id, "run_full", force=payload.force, restart=payload.restart)
    )


@bp.post("/<job_id>/run-from")
def run_from(job_id: str):
    payload = RunFromSchema.model_validate(request.get_json(silent=True) or {})
    return api_success(
        JobRunService.start(job_id, "run_from", node_key=payload.node_key, force=payload.force)
    )


@bp.post("/<job_id>/run-node")
def run_node(job_id: str):
    payload = RunNodeSchema.model_validate(request.get_json(silent=True) or {})
    return api_success(
        JobRunService.start(job_id, "run_node", node_key=payload.node_key, force=payload.force)
    )


@bp.get("/queue/status")
def queue_status():
    from app.models import JobDispatch
    if current_app.config.get("MQ_ENABLED") or JobDispatch.query.filter(JobDispatch.status.in_(["ready", "running"])).first():
        from app.queue.operations import ingress_status
        return api_success(ingress_status())
    if not current_app.config.get("JOB_QUEUE_ENABLED", True):
        return api_success({"enabled": False})
    return api_success(JobQueueService.status())


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
