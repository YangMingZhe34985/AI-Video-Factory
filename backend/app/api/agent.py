from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import RequestEntityTooLarge

from app.agent.clarify import resolve_answers
from app.agent.attachments import attachment_for_owner, describe_attachment, invalid_attachment, upload_attachment
from app.agent.protocol import CreateRun, RunAction, validate_plan, validate_request, validate_shot
from app.agent.plan_spec import shot_cost
from app.agent.release import ensure_admission
from app.agent.monitoring import run_metrics
from app.agent.model_policy import scope_policy
from app.agent.sources import source_for_run, upload_source
from app.api import AppError, api_success
from app.extensions import db
from app.models import AgentRun, Artifact, Job
from app.skills.budget import BudgetGuard
from app.utils.ids import new_id

bp = Blueprint("agent", __name__, url_prefix="/api/agent")


def owner():
    return get_jwt_identity() if current_app.config.get("API_AUTH_REQUIRED", True) else "local"


def parse(schema):
    try:
        return schema.model_validate(request.get_json(silent=True) or {})
    except ValidationError as error:
        raise AppError("INVALID_INPUT", "Invalid Agent request", 422,
                       payload={"errors": error.errors(include_url=False, include_context=False)}) from error


def get_run(run_id):
    row = AgentRun.query.filter_by(run_id=run_id, owner_id=owner()).first()
    if not row:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent run not found", 404)
    return row


@bp.post("/sources")
def create_source():
    ensure_admission()
    return api_success(upload_source(request.files.get("file"), owner()), 201)


@bp.post("/attachments")
def create_attachment():
    ensure_admission()
    try:
        files = list(request.files.items(multi=True))
    except RequestEntityTooLarge as error:
        raise invalid_attachment("Attachment exceeds the configured size limit") from error
    if len(files) != 1 or files[0][0] != "file":
        raise invalid_attachment("Upload exactly one file using the file field")
    return api_success(upload_attachment(files[0][1], owner()), 201)


def attachment_metadata(row):
    """History reads metadata; execution separately verifies live attachment files."""
    ids = row.request.get("attachment_ids", [])
    artifacts = Artifact.query.join(Job).filter(
        Artifact.artifact_id.in_(ids),
        Artifact.artifact_type.in_(["agent_attachment_image", "source_video"]),
        Job.strategy == "agent_upload",
    ).all()
    owned = {artifact.artifact_id: artifact for artifact in artifacts
             if (artifact.job.config or {}).get("agent_upload_owner") == row.owner_id}
    return [describe_attachment(owned[value]) for value in ids if value in owned]


def serialize(row):
    result = row.to_dict()
    result.pop("id", None)
    result.pop("owner_id", None)
    result.pop("request_key", None)
    result["estimated_spent"] = BudgetGuard.spent(row.run_id)
    snapshot = row.snapshot or {}
    shots = list(snapshot.get("shots", {}).values())
    version = row.request.get("schema_version", 1)
    result.update(schema_version=version, text=None, attachments=None, request_spec=None,
                  pending_card=None, plan=None, results=None)
    if version == 2:
        plan = snapshot.get("plan") or {}
        total = len(plan["shots"]) if "shots" in plan else sum(plan.get(key) is not None for key in ("image", "video"))
        result.update(text=row.request["text"],
                      attachments=attachment_metadata(row),
                      request_spec=snapshot.get("request_spec"), plan=snapshot.get("plan"),
                      pending_card=snapshot.get("pending_card") if row.status == "awaiting_input" else None,
                      results=snapshot.get("results", []))
        result["summary"] = {"steps_total": total,
                             "steps_success": sum(shot.get("status") == "success" for shot in shots),
                             "steps_failed": sum(shot.get("terminal", False) and shot.get("status") != "success" for shot in shots)}
        return result
    result["summary"] = {
        "total": row.request["shot_count"],
        "success": sum(shot.get("status") == "success" for shot in shots),
        "failed": sum(shot.get("terminal", False) and shot.get("status") != "success" for shot in shots),
    }
    result["summary"]["pending"] = result["summary"]["total"] - result["summary"]["success"] - result["summary"]["failed"]
    return result


@bp.get("/runs")
def list_runs():
    rows = AgentRun.query.filter_by(owner_id=owner()).order_by(AgentRun.id.desc()).limit(100).all()
    return api_success({"items": [serialize(row) for row in rows]})


@bp.post("/runs")
def create_run():
    data = parse(CreateRun)
    payload = data.model_dump(mode="json", exclude={"request_key"}, exclude_none=True)
    payload["schema_version"] = 2
    row = AgentRun.query.filter_by(owner_id=owner(), request_key=data.request_key).first()
    if not row:
        ensure_admission()
        validate_request(data)
        for attachment_id in data.attachment_ids:
            attachment_for_owner(attachment_id, owner())
        row = AgentRun(owner_id=owner(), request_key=data.request_key, request=payload)
        db.session.add(row)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            row = AgentRun.query.filter_by(owner_id=owner(), request_key=data.request_key).one()
    if row.request != payload:
        raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Request key belongs to different request content", 409)
    return api_success(serialize(row), 202)


@bp.get("/runs/<run_id>")
def detail(run_id):
    return api_success(serialize(get_run(run_id)))


@bp.get("/runs/<run_id>/metrics")
def metrics(run_id):
    return api_success(run_metrics(get_run(run_id)))


def approved_plan(row, edited):
    snapshot = row.snapshot or {}
    raw = edited if edited is not None else snapshot["plan"]
    if row.request.get("schema_version", 1) == 1:
        return validate_plan(raw, row.request["shot_count"], row.request["budget_limit"], scope_policy(row.run_id),
                             mode=row.request.get("mode", "from_scratch"),
                             source_duration=source_for_run(row).meta["video"]["duration"]
                             if row.request.get("mode") == "remix" else None)
    spec = snapshot.get("request_spec")
    if not spec:
        raise AppError("INVALID_PLAN", "Request understanding must finish before approval", 422)
    if spec["recipe_hint"] in {"image_edit", "image_create", "single_clip"}:
        from app.agent.simple_plan import approval_request_spec, validate_simple_plan
        approved_spec = approval_request_spec(spec, snapshot["plan"], raw)
        return validate_simple_plan(raw, approved_spec, owner_id=row.owner_id,
                                    budget_scope=row.run_id, budget_limit=row.request["budget_limit"])
    from app.agent.recipes import validate_transition_plan
    return validate_transition_plan(raw, snapshot, enforce_duration=edited is None)


@bp.post("/runs/<run_id>/actions")
def action(run_id):
    data = parse(RunAction)
    row = get_run(run_id)
    command_id = f"revision:{data.request_key}" if data.action == "revise" else new_id("command")
    if data.action == "revise":
        receipts = [item for history in (row.snapshot or {}).get("shot_history", {}).values() for item in history]
        for receipt in [row.command or {}, *receipts]:
            if receipt.get("command_id") == command_id:
                if receipt.get("request_shot") != data.shot.model_dump(mode="json"):
                    raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Revision key belongs to a different edit", 409)
                return api_success(serialize(row), 202)
    expected = {"approve": "awaiting_approval", "reject": "awaiting_approval", "deliver": "awaiting_delivery",
                "revise": "awaiting_delivery", "resume": "needs_attention", "answer": "awaiting_input"}[data.action]
    if row.command is not None or row.status != expected:
        raise AppError("INVALID_AGENT_STATE", f"Action requires {expected} with no pending action", 409)
    command = {"action": data.action, "command_id": command_id}
    if data.plan is not None and data.action != "approve":
        raise AppError("INVALID_INPUT", "Plans may only be edited when approving", 422)
    if data.action == "approve":
        try:
            validated = approved_plan(row, data.plan)
            if row.request.get("schema_version", 1) == 1 or data.plan is not None:
                command["plan"] = validated
        except ValidationError as error:
            raise AppError("INVALID_PLAN", str(error), 422) from error
    if data.action == "revise":
        source = source_for_run(row)
        if data.shot.shot_id not in {shot["shot_id"] for shot in row.snapshot["plan"]["shots"]}:
            raise AppError("INVALID_PLAN", "Revision must target an existing shot", 422)
        command["request_shot"] = data.shot.model_dump(mode="json")
        shot = validate_shot(data.shot, scope_policy(row.run_id), source_duration=source.meta["video"]["duration"])
        BudgetGuard.check(row.run_id, row.request["budget_limit"], shot_cost(shot))
        command["shot"] = shot.model_dump(mode="json")
    if data.action == "answer":
        card = (row.snapshot or {}).get("pending_card")
        if not card:
            raise AppError("INVALID_AGENT_STATE", "This run has no pending question", 409)
        submission = {"card_id": data.card_id, "answers": [item.model_dump(exclude_none=True) for item in data.answers],
                      "use_defaults": data.use_defaults}
        resolve_answers(card, submission)  # reject before queueing; the graph re-validates on resume
        command.update(submission)
    if data.action == "resume" and row.resume_count >= 2:
        raise AppError("RETRY_LIMIT_EXCEEDED", "At most two recovery requests are allowed", 409)
    values = {"command": command}
    if data.action == "resume":
        values["resume_count"] = AgentRun.resume_count + 1
    changed = AgentRun.query.filter_by(id=row.id, status=expected).filter(AgentRun.command.is_(None)).update(values)
    if not changed:
        db.session.rollback()
        raise AppError("INVALID_AGENT_STATE", "Another request already changed this run", 409)
    db.session.commit()
    return api_success(serialize(row), 202)
