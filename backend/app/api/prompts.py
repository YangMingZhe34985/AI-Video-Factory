from http import HTTPStatus

from flask import Blueprint, request

from app.api import api_success
from app.schemas.prompt_schema import CreatePromptVersionSchema, EditPromptVersionSchema, RollbackPromptSchema
from app.services.prompt_service import PromptService


bp = Blueprint("prompts", __name__, url_prefix="/api/templates")
global_bp = Blueprint("global_prompts", __name__, url_prefix="/api")


@global_bp.get("/prompts")
def list_global_prompts():
    """List Prompt Manager assets across templates and jobs."""
    limit = request.args.get("limit", "500")
    try:
        parsed_limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        parsed_limit = 500
    assets = PromptService.list_global_visible_assets(
        series_id=request.args.get("series_id"),
        template_id=request.args.get("template_id"),
        job_id=request.args.get("job_id"),
        prompt_type=request.args.get("prompt_type"),
        prompt_key=request.args.get("prompt_key"),
        scope=request.args.get("scope"),
        limit=parsed_limit,
    )
    return api_success({"prompts": assets, "total": len(assets)})


# ---------------------------------------------------------------------------
# Legacy / template-level prompt routes (preserved for backward compat)
# ---------------------------------------------------------------------------

@bp.post("/<template_id>/prompts")
def create_prompt(template_id: str):
    payload = CreatePromptVersionSchema.model_validate(request.get_json(silent=True) or {})
    prompt = PromptService.create_version(template_id, payload.model_dump())
    return api_success(prompt.to_dict(), HTTPStatus.CREATED)


@bp.post("/<template_id>/prompts/seed-factory")
def seed_factory_prompts(template_id: str):
    skip_existing = (request.get_json(silent=True) or {}).get("skip_existing", True)
    prompts = PromptService.seed_factory_prompts(template_id, skip_existing=bool(skip_existing))
    return api_success(
        {"created": len(prompts), "prompts": [prompt.to_dict() for prompt in prompts]},
        HTTPStatus.CREATED,
    )


@bp.get("/<template_id>/prompts/<prompt_type>/versions")
def list_prompt_versions(template_id: str, prompt_type: str):
    job_id = request.args.get("job_id")
    prompt_key = request.args.get("prompt_key")
    prompts = PromptService.list_versions(template_id, prompt_type, job_id=job_id, prompt_key=prompt_key)
    return api_success({"versions": [p.to_dict() for p in prompts]})


@bp.get("/<template_id>/prompts/<prompt_type>/active")
def get_active_prompt(template_id: str, prompt_type: str):
    job_id = request.args.get("job_id")
    prompt_key = request.args.get("prompt_key", "default")
    prompt = PromptService.get_active(template_id, prompt_type, job_id=job_id, prompt_key=prompt_key)
    return api_success(prompt.to_dict())


@bp.post("/<template_id>/prompts/<prompt_type>/versions/<version>/activate")
def activate_prompt(template_id: str, prompt_type: str, version: str):
    body = request.get_json(silent=True) or {}
    prompt = PromptService.activate(
        template_id, prompt_type, version,
        job_id=body.get("job_id"),
        prompt_key=body.get("prompt_key", "default"),
    )
    return api_success(prompt.to_dict())


@bp.post("/<template_id>/prompts/<prompt_type>/activate")
def activate_prompt_compat(template_id: str, prompt_type: str):
    body = request.get_json(silent=True) or {}
    version = body.get("version")
    prompt = PromptService.activate(
        template_id, prompt_type, version,
        job_id=body.get("job_id"),
        prompt_key=body.get("prompt_key", "default"),
    )
    return api_success(prompt.to_dict())


@bp.post("/<template_id>/prompts/<prompt_type>/versions/<version>/rollback")
def rollback_prompt(template_id: str, prompt_type: str, version: str):
    raw = request.get_json(silent=True) or {}
    payload = RollbackPromptSchema.model_validate(raw)
    prompt = PromptService.rollback(
        template_id, prompt_type, version, payload.model_dump(),
        job_id=raw.get("job_id"),
        prompt_key=raw.get("prompt_key", "default"),
    )
    return api_success(prompt.to_dict(), HTTPStatus.CREATED)


@bp.post("/<template_id>/prompts/<prompt_type>/versions/<version>/edit")
def edit_prompt(template_id: str, prompt_type: str, version: str):
    raw = request.get_json(silent=True) or {}
    payload = EditPromptVersionSchema.model_validate(raw)
    prompt = PromptService.edit_version(
        template_id,
        prompt_type,
        version,
        payload.model_dump(),
        job_id=raw.get("job_id"),
        prompt_key=raw.get("prompt_key", "default"),
    )
    return api_success(prompt.to_dict(), HTTPStatus.CREATED)


@bp.post("/<template_id>/prompts/<prompt_type>/rollback")
def rollback_prompt_compat(template_id: str, prompt_type: str):
    raw = request.get_json(silent=True) or {}
    version = raw.get("version")
    payload = RollbackPromptSchema.model_validate(raw)
    prompt = PromptService.rollback(
        template_id, prompt_type, version, payload.model_dump(),
        job_id=raw.get("job_id"),
        prompt_key=raw.get("prompt_key", "default"),
    )
    return api_success(prompt.to_dict(), HTTPStatus.CREATED)


# ---------------------------------------------------------------------------
# New job-level prompt hierarchy routes
# ---------------------------------------------------------------------------

@bp.get("/<template_id>/prompts")
def list_prompts_with_filter(template_id: str):
    """List prompts filtered by job_id and/or prompt_type."""
    job_id = request.args.get("job_id")
    prompt_type = request.args.get("prompt_type")
    prompt_key = request.args.get("prompt_key")
    assets = PromptService.list_visible_assets(
        template_id, job_id=job_id, prompt_type=prompt_type, prompt_key=prompt_key
    )
    return api_success({"prompts": assets, "total": len(assets)})


@bp.get("/<template_id>/jobs/<job_id>/prompts")
def list_job_prompts(template_id: str, job_id: str):
    """List all prompt assets for a job."""
    assets = PromptService.list_by_job(template_id, job_id)
    return api_success({"prompts": assets})


@bp.get("/<template_id>/jobs/<job_id>/prompts/<prompt_type>")
def list_job_prompts_by_type(template_id: str, job_id: str, prompt_type: str):
    """List all prompt assets of a type for a job."""
    assets = PromptService.list_assets_by_type(template_id, job_id, prompt_type)
    return api_success({"prompts": assets})


@bp.get("/<template_id>/jobs/<job_id>/prompts/<prompt_type>/<prompt_key>/versions")
def list_job_prompt_versions(template_id: str, job_id: str, prompt_type: str, prompt_key: str):
    versions = PromptService.list_versions_for_asset(template_id, job_id, prompt_type, prompt_key)
    return api_success({"versions": [v.to_dict() for v in versions]})


@bp.get("/<template_id>/jobs/<job_id>/prompts/<prompt_type>/<prompt_key>/active")
def get_job_prompt_active(template_id: str, job_id: str, prompt_type: str, prompt_key: str):
    prompt = PromptService.get_active_for_asset(template_id, job_id, prompt_type, prompt_key)
    return api_success(prompt.to_dict())
