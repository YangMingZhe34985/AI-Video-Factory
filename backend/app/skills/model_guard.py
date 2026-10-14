"""Model and parameter validation for tool inputs.

The classic UI only uses parameter_schema to render forms; nothing on the
server checks values. Tools are driven by LLMs, so every model choice and
parameter is validated here before it reaches a provider payload.
"""

from flask import current_app

from app.api import AppError
from app.models import ModelRegistry
from app.services.model_service import ModelService
from app.services.workflow_service import WorkflowService

TASK_TYPES = {
    "video_understanding": {"video_understanding"},
    "prompt_rewrite": {"prompt_rewrite", "text_to_text"},
    "image": {"text_to_image"},
    "t2v": {"text_to_video"},
    "i2v": {"image_to_video"},
    "r2v": {"reference_to_video"},
}

# Same fallback order as NodeRunner._model_for below the job-level overrides.
DEFAULT_MODEL_CONFIG_KEYS = {
    "video_understanding": "DEFAULT_VIDEO_UNDERSTANDING_MODEL",
    "prompt_rewrite": "DEFAULT_PROMPT_REWRITE_MODEL",
    "image": "DEFAULT_IMAGE_MODEL",
    "t2v": "DEFAULT_T2V_MODEL",
    "i2v": "DEFAULT_I2V_MODEL",
    "r2v": "DEFAULT_R2V_FLASH_MODEL",
}

_TYPE_CHECKS = {
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "string": lambda value: isinstance(value, str),
    "boolean": lambda value: isinstance(value, bool),
}


def resolve_model(model_id: str, capability: str) -> ModelRegistry:
    model = ModelService.get_model(model_id, require_enabled=True)
    allowed = TASK_TYPES[capability]
    if model.task_type not in allowed:
        raise AppError(
            "INVALID_INPUT",
            f"Model {model.model_id} has task_type {model.task_type}; expected one of {sorted(allowed)}",
            422,
        )
    return model


def effective_model(capability: str, node_key: str, model_id: str | None) -> ModelRegistry:
    """Resolve the model a node will actually run with.

    Tools pin the result into job_config.node_models so the validated model
    is the one used at runtime, regardless of later global config changes.
    """
    if not model_id:
        node = WorkflowService.get_node(node_key)
        model_id = (node.config or {}).get("model_id") or current_app.config[
            DEFAULT_MODEL_CONFIG_KEYS[capability]
        ]
    return resolve_model(model_id, capability)


def validate_params(model: ModelRegistry, params: dict) -> dict:
    if not params:
        return {}
    schema = model.parameter_schema or {}
    errors = []
    for name, value in params.items():
        rule = schema.get(name)
        if not isinstance(rule, dict):
            errors.append(f"{name}: unknown parameter")
            continue
        check = _TYPE_CHECKS.get(rule.get("type"))
        if check and not check(value):
            errors.append(f"{name}: expected {rule.get('type')}")
            continue
        if "enum" in rule and value not in rule["enum"]:
            errors.append(f"{name}: must be one of {rule['enum']}")
        if "min" in rule and isinstance(value, (int, float)) and value < rule["min"]:
            errors.append(f"{name}: must be >= {rule['min']}")
        if "max" in rule and isinstance(value, (int, float)) and value > rule["max"]:
            errors.append(f"{name}: must be <= {rule['max']}")
    if errors:
        raise AppError(
            "INVALID_INPUT",
            f"Invalid parameters for model {model.model_id}",
            422,
            payload={"errors": errors},
        )
    return dict(params)
