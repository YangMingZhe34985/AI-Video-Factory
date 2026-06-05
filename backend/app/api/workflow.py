from http import HTTPStatus

from flask import Blueprint, request, send_file

from app.api import api_success
from app.schemas.prompt_schema import CreateTemplateSchema
from app.services.model_service import ModelService
from app.services.prompt_service import PromptService
from app.services.series_service import SeriesService
from app.services.template_package_service import TemplatePackageService
from app.services.workflow_service import WorkflowService
from app.services.workflow_validator import WorkflowValidator


bp = Blueprint("workflow", __name__, url_prefix="/api")


@bp.post("/templates")
def create_template():
    payload = CreateTemplateSchema.model_validate(request.get_json(silent=True) or {})
    data = payload.model_dump()
    # If series_id provided, use it as the series string; fall back to default
    if not data.get("series") and data.get("series_id"):
        data["series"] = data["series_id"]
    if not data.get("series"):
        data["series"] = "default"
    template = PromptService.create_template(data)
    return api_success(SeriesService.enrich_template(template), HTTPStatus.CREATED)


@bp.get("/templates")
def list_templates():
    series_id = request.args.get("series_id")
    templates = PromptService.list_templates(series_id=series_id)
    return api_success({"templates": SeriesService.enrich_templates(templates)})


@bp.get("/templates/<template_id>")
def get_template(template_id: str):
    template = PromptService.get_template(template_id)
    return api_success(SeriesService.enrich_template(template))


@bp.post("/templates/<template_id>/package")
def package_template(template_id: str):
    result = TemplatePackageService.create_package(template_id)
    return api_success(result, HTTPStatus.CREATED)


@bp.get("/templates/<template_id>/package/download")
def download_template_package(template_id: str):
    package_path = TemplatePackageService.get_package_path(template_id)
    return send_file(
        package_path,
        as_attachment=True,
        download_name=package_path.name,
        mimetype="application/zip",
    )


@bp.post("/templates/<template_id>/move")
def move_template(template_id: str):
    data = request.get_json(silent=True) or {}
    target_series_id = data.get("target_series_id", "default")
    template = SeriesService.move_template(template_id, target_series_id)
    return api_success(SeriesService.enrich_template(template))


@bp.get("/workflow/nodes")
def list_workflow_nodes():
    nodes = WorkflowService.list_nodes()
    node_dicts = [node.to_dict() for node in nodes]
    defs = WorkflowValidator.NODE_DEFINITIONS
    for nd in node_dicts:
        meta = defs.get(nd.get("node_key"), {})
        nd["can_start"] = meta.get("can_start", False)
        nd["start_priority"] = meta.get("start_priority", 99)
        nd["required_inputs"] = meta.get("required_inputs", [])
        nd["optional_inputs"] = meta.get("optional_inputs", [])
        nd["produces"] = meta.get("produces", [])
        nd["paired_with"] = meta.get("paired_with", [])
        nd.update(WorkflowValidator.NODE_DESCRIPTIONS.get(nd.get("node_key"), {}))
    return api_success({"nodes": node_dicts})


@bp.post("/workflow/nodes/<node_key>/enable")
def enable_workflow_node(node_key: str):
    node = WorkflowService.set_node_enabled(node_key, True)
    return api_success(node.to_dict())


@bp.post("/workflow/nodes/<node_key>/disable")
def disable_workflow_node(node_key: str):
    node = WorkflowService.set_node_enabled(node_key, False)
    return api_success(node.to_dict())


@bp.put("/workflow/nodes/<node_key>/config")
def update_workflow_node_config(node_key: str):
    node = WorkflowService.update_node_config(node_key, request.get_json(silent=True) or {})
    return api_success(node.to_dict())


@bp.get("/models/by-task/<task_type>")
def get_models_by_task(task_type: str):
    models = ModelService.list_models(task_type=task_type)
    return api_success({"models": [model.to_dict() for model in models]})


@bp.post("/workflow/validate-run")
def validate_run():
    body = request.get_json(silent=True) or {}
    enabled_nodes = body.get("enabled_nodes") or []
    disabled_nodes = body.get("disabled_nodes") or []
    initial_prompts = body.get("initial_prompts") or {}
    initial_artifacts = body.get("initial_artifacts") or {}

    result = WorkflowValidator.validate(
        enabled_nodes=enabled_nodes,
        disabled_nodes=disabled_nodes,
        initial_prompts=initial_prompts,
        initial_artifacts=initial_artifacts,
    )
    return api_success(result)
