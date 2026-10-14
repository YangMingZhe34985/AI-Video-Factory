from flask import Blueprint, request

from app.api import AppError, api_success
from app.models import ToolInvocation
from app.schemas.skill_schema import InvokeSkillSchema
from app.skills import get_registry
from app.skills.spec import ToolContext

# Registered only when AGENT_MODE_ENABLED is true (see register_blueprints).
bp = Blueprint("skills", __name__, url_prefix="/api/skills")


@bp.get("")
def list_skills():
    return api_success({"skills": get_registry().describe_all()})


@bp.post("/<name>/invoke")
def invoke_skill(name: str):
    payload = InvokeSkillSchema.model_validate(request.get_json(silent=True) or {})
    ctx = ToolContext(
        role=payload.role,
        approved=payload.approved,
        idempotency_key=payload.idempotency_key,
        budget_scope=payload.budget_scope,
        budget_limit=payload.budget_limit,
    )
    return api_success(get_registry().invoke(name, payload.input, ctx))


@bp.get("/invocations/<invocation_id>")
def get_invocation(invocation_id: str):
    invocation = ToolInvocation.query.filter_by(invocation_id=invocation_id).first()
    if invocation is None:
        raise AppError("INVOCATION_NOT_FOUND", "Tool invocation not found", 404)
    data = invocation.to_dict()
    data["job_public_id"] = invocation.job.job_id if invocation.job else None
    return api_success(data)
