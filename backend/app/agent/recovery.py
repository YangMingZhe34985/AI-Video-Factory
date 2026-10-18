"""Conservative recovery for jobs owned by the single Agent worker only."""

from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Job, ToolInvocation
from app.services.event_service import EventService
from app.services.job_queue_service import JobQueueService
from app.services.job_run_service import JobRunService
from app.services.job_run_state_service import JobRunStateService
from app.skills.budget import NODE_COSTS, PER_SAMPLE_NODE_COSTS
from app.utils.time_utils import utc_now


def recover_job(job: Job, scope: str) -> None:
    from app.agent.model_policy import validate_job_policy
    if (job.config or {}).get("skill", {}).get("budget_scope") != scope:
        raise AppError("TOOL_FORBIDDEN", "Cannot recover another run's job", 403)
    if job.status not in {"created", "pending", "queued", "running"}:
        return
    from app.models import JobDispatch
    if JobDispatch.query.filter_by(job_id=job.id).first():
        return  # Shared MQ recovery owns these tasks, including submit_unknown.
    if JobRunService.is_running_in_thread(job.job_id) or JobQueueService._is_known(job.job_id):
        return
    # Completion can commit after our original read and before the worker
    # exits. A locking current read also bypasses MySQL repeatable-read snapshots
    # and the identity map; a stale running Job must never restart paid nodes.
    job = Job.query.filter_by(id=job.id).populate_existing().with_for_update().one()
    if job.status not in {"created", "pending", "queued", "running"}:
        db.session.commit()  # Release the row lock on this read-only exit.
        return
    # A disabled model must block new submissions, but completed/in-flight
    # work still owns valid results that must remain visible and deliverable.
    validate_job_policy(job)
    # Only this worker starts Agent jobs. After a worker restart, successful
    # submit nodes are reused; interrupted polls resume their persisted task IDs.
    latest = {}
    for node in JobRunStateService.query_current_node_runs(job).order_by("id").all():
        latest[node.node_key] = node
    for node in latest.values():
        if not (NODE_COSTS.get(node.node_key) or PER_SAMPLE_NODE_COSTS.get(node.node_key)) or node.status in {"success", "skipped"}:
            continue
        task = ApiTask.query.filter_by(node_run_id=node.id).order_by(ApiTask.id.desc()).first()
        if not task or not task.provider_task_id:
            job.status = "failed"
            job.error_summary = f"Submission outcome unknown at {node.node_key}; automatic resubmission stopped"
            EventService.record(job, "AGENT_RECOVERY_BLOCKED", message=job.error_summary, level="error")
            db.session.commit()
            return
        node.status = "success"
        node.output_snapshot = {"api_task_id": task.api_task_id, "provider_task_id": task.provider_task_id}
        node.ended_at = utc_now()
    job.status = "pending"
    db.session.commit()
    JobRunService.start(job.job_id, "run_full")


def invoke_once(registry, name, data, ctx):
    """Replay completed side effects, never use Registry's paid failure retry implicitly."""
    if name == "extract_frame":
        # Free local extraction owns a durable artifact + output receipt; an
        # interrupted handler may safely reconstruct that receipt.
        return registry.invoke(name, data, ctx)
    if ctx.shot_task_id is not None:
        from app.agent.production_policy import validate_submission
        spec = registry.get(name)
        parsed = registry._validate_input(spec, data)
        registry._authorize(spec, ctx)
        ctx.tool_name = name
        validate_submission(parsed, ctx)
    previous = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).first()
    if previous:
        spec = registry.get(name)
        if spec.permission == "external" or name == "analyze_image":
            from app.agent.search.scope import require_run
            parsed = registry._validate_input(spec, data)
            registry._authorize(spec, ctx)
            require_run(ctx, getattr(parsed, "run_id", None))
            registry._check_scoped_replay(spec, previous, parsed, ctx)
            if previous.status not in {"failed", "rejected"}:
                return registry.invoke(name, data, ctx)
        if name == "package_project" and not previous.output_payload:
            # Packaging is free and refreshes an existing archive. An explicit,
            # bounded recovery can safely repeat an interrupted packaging call.
            previous.status = "rejected"
            db.session.commit()
            return registry.invoke(name, data, ctx)
        if previous.status in {"failed", "rejected"}:
            raise AppError(previous.error_code or "TOOL_FAILED", previous.error_message or "Previous call failed", 409)
        job_backed = name in {"produce_shot", "remix_shot", "analyze_video", "generate_image", "generate_video", "animate_shot"}
        if job_backed and not previous.job:
            # A crash can occur between JobService's commit and ledger linking.
            job = Job.query.filter(
                Job.config["skill"]["invocation_id"].as_string() == previous.invocation_id
            ).first()
            if job:
                previous.job = job
                db.session.commit()
        if job_backed and previous.job:
            recover_job(previous.job, ctx.budget_scope)
            return {"invocation_id": previous.invocation_id, "output": {"job_id": previous.job.job_id}}
        if previous.output_payload and previous.status in {"success", "partial_success"}:
            return {"invocation_id": previous.invocation_id, "output": previous.output_payload}
        raise AppError("RECOVERY_REQUIRED", "Call outcome is unknown; automatic retry stopped to prevent duplicate charges", 409)
    return registry.invoke(name, data, ctx)
