from http import HTTPStatus

from flask import Blueprint, request

from app.api import api_success
from app.schemas.model_schema import CreateModelSchema, UpdateModelSchema
from app.services.model_service import ModelService


bp = Blueprint("model_registry", __name__, url_prefix="/api/models")


@bp.get("")
def list_models():
    task_type = request.args.get("task_type")
    models = ModelService.list_models(task_type=task_type)
    return api_success({"models": [model.to_dict() for model in models]})


@bp.get("/by-task/<task_type>")
def get_models_by_task(task_type: str):
    models = ModelService.list_models(task_type=task_type)
    return api_success({"models": [model.to_dict() for model in models]})


@bp.get("/<model_id>")
def get_model(model_id: str):
    model = ModelService.get_model(model_id)
    return api_success(model.to_dict())


@bp.post("")
def create_model():
    payload = CreateModelSchema.model_validate(request.get_json(silent=True) or {})
    model = ModelService.create_model(payload.model_dump())
    return api_success(model.to_dict(), HTTPStatus.CREATED)


@bp.put("/<model_id>")
def update_model(model_id: str):
    payload = UpdateModelSchema.model_validate(request.get_json(silent=True) or {})
    model = ModelService.update_model(model_id, payload.model_dump())
    return api_success(model.to_dict())


@bp.post("/<model_id>/enable")
def enable_model(model_id: str):
    model = ModelService.set_enabled(model_id, True)
    return api_success(model.to_dict())


@bp.post("/<model_id>/disable")
def disable_model(model_id: str):
    model = ModelService.set_enabled(model_id, False)
    return api_success(model.to_dict())


@bp.post("/seed-defaults")
def seed_default_models():
    created = ModelService.seed_defaults()
    return api_success({"created": created})


@bp.post("/deduplicate")
def deduplicate_models():
    changed = ModelService.deduplicate_aliases()
    return api_success({"changed": changed})
