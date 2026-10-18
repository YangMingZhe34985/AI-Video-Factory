from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity

from app.agent.attachments import require_upload_job_owner
from app.api import AppError, api_success
from app.extensions import db
from app.models import AgentRun, Artifact, Job, ToolInvocation
from app.schemas.skill_schema import InvokeSkillSchema
from app.skills import get_registry
from app.skills.spec import ToolContext
from app.skills.registry import idempotency_key_for

# Registered only when AGENT_MODE_ENABLED is true (see register_blueprints).
bp = Blueprint("skills", __name__, url_prefix="/api/skills")


def _owner():
    return get_jwt_identity() if current_app.config.get("API_AUTH_REQUIRED", True) else "local"


def _check_scope(scope, owner_id):
    run = AgentRun.query.filter_by(run_id=scope).first()
    if run is not None and run.owner_id != owner_id:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent run not found", 404)


def _check_references(name, data, owner_id, budget_scope=None):
    # Inspect declared top-level references, never text or arbitrary model params.
    registry = get_registry()
    if name not in registry.names():
        # Graph-local tools have no public schema; their AgentRun scope owns the call.
        return
    fields = registry.get(name).input_model.model_fields
    for field in fields:
        value = data.get(field)
        if value is None:
            continue
        if field.endswith("_artifact_id") or field == "attachment_id":
            references, model, column = [value], Artifact, Artifact.artifact_id
        elif field.endswith("_artifact_ids") or field == "attachment_ids":
            references, model, column = value, Artifact, Artifact.artifact_id
        elif field in {"job_id", "job_ids"}:
            references, model, column = [value] if field == "job_id" else value, Job, Job.job_id
        elif field == "invocation_id":
            invocation = ToolInvocation.query.filter_by(invocation_id=value).first()
            if invocation is not None:
                _check_invocation(invocation, owner_id)
            continue
        else:
            continue
        for reference in references:
            row = model.query.filter(column == str(reference)).first()
            if row is None and str(reference).isdigit():
                row = db.session.get(model, int(reference))
            if row is not None:
                job = row.job if model is Artifact else row
                require_upload_job_owner(job, owner_id)
                reference_run = ((job.config or {}).get("agent_reference_run")
                                 or (job.config or {}).get("agent_story_preview", {}).get("run_id")
                                 or (job.config or {}).get("agent_story_production", {}).get("run_id")
                                 or (job.config or {}).get("agent_transform", {}).get("run_id"))
                if model is Artifact and row.artifact_type in {"agent_reference_image", "agent_reference_document"}:
                    reference_run = (row.meta or {}).get("reference", {}).get("run_id")
                if reference_run and reference_run != budget_scope:
                    raise AppError("ATTACHMENT_NOT_FOUND", "Reference image is not part of this run", 404)


def _check_invocation(invocation, owner_id):
    _check_scope(invocation.budget_scope, owner_id)
    _check_references(invocation.tool_name, invocation.input_payload or {}, owner_id, invocation.budget_scope)
    if invocation.job is not None:
        require_upload_job_owner(invocation.job, owner_id)


@bp.get("")
def list_skills():
    return api_success({"skills": get_registry().describe_all()})


@bp.post("/<name>/invoke")
def invoke_skill(name: str):
    from app.agent.release import ensure_admission
    ensure_admission()
    payload = InvokeSkillSchema.model_validate(request.get_json(silent=True) or {})
    registry = get_registry()
    spec = registry.get(name)
    data = registry._validate_input(spec, payload.input)
    owner_id = _owner()
    _check_scope(payload.budget_scope, owner_id)
    _check_references(name, data.model_dump(mode="json"), owner_id, payload.budget_scope)
    key = payload.idempotency_key or (idempotency_key_for(name, data) if spec.dedupe else None)
    if spec.uses_ledger and key:
        previous = ToolInvocation.query.filter_by(idempotency_key=key).first()
        if previous is not None:
            _check_invocation(previous, owner_id)
    ctx = ToolContext(
        role=payload.role,
        approved=payload.approved,
        idempotency_key=payload.idempotency_key,
        budget_scope=payload.budget_scope,
        budget_limit=payload.budget_limit,
    )
    return api_success(registry.invoke(name, payload.input, ctx))


@bp.get("/invocations/<invocation_id>")
def get_invocation(invocation_id: str):
    invocation = ToolInvocation.query.filter_by(invocation_id=invocation_id).first()
    if invocation is None:
        raise AppError("INVOCATION_NOT_FOUND", "Tool invocation not found", 404)
    _check_invocation(invocation, _owner())
    data = invocation.to_dict()
    data.pop("caller_agent", None)
    data.pop("delegation_id", None)
    data["job_public_id"] = invocation.job.job_id if invocation.job else None
    return api_success(data)
