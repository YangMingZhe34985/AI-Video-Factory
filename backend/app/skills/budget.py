"""Static cost estimates and per-scope budget enforcement.

Costs are abstract credits used to stop runaway or duplicated generation;
they are estimates, not provider billing. Submission is treated as billable
even if the provider task later fails, so the estimate errs high.
"""

from decimal import Decimal
from math import isfinite

from flask import current_app
from sqlalchemy import func

from app.api import AppError
from app.extensions import db
from app.models import ToolInvocation

LLM_CALL = 1.0
IMAGE_GENERATION = 2.0
VIDEO_GENERATION = 10.0

NODE_COSTS = {
    "reverse_prompts": LLM_CALL,
    "rewrite_prompts": LLM_CALL,
    "reverse_prompts4r2v": LLM_CALL,
    "rewrite_t2i_to_i2i": LLM_CALL,
    "failure_agent": LLM_CALL,
    "submit_first_frame_image": IMAGE_GENERATION,
    "submit_t2v": VIDEO_GENERATION,
    "submit_i2v": VIDEO_GENERATION,
    "submit_r2v_flash": VIDEO_GENERATION,
}
# I2I test nodes submit one task per sample.
PER_SAMPLE_NODE_COSTS = {
    "submit_i2i_test_image": IMAGE_GENERATION,
    "submit_i2i_test_i2v": VIDEO_GENERATION,
}


NODE_MODELS = {
    "reverse_prompts": ("video_understanding", "DEFAULT_VIDEO_UNDERSTANDING_MODEL"),
    "rewrite_prompts": ("prompt_rewrite", "DEFAULT_PROMPT_REWRITE_MODEL"),
    "reverse_prompts4r2v": ("prompt_rewrite", "DEFAULT_PROMPT_REWRITE_MODEL"),
    "rewrite_t2i_to_i2i": ("prompt_rewrite", "DEFAULT_PROMPT_REWRITE_MODEL"),
    "failure_agent": ("failure_agent", "DEFAULT_PROMPT_REWRITE_MODEL"),
    "submit_first_frame_image": ("image", "DEFAULT_IMAGE_MODEL"),
    "submit_t2v": ("t2v", "DEFAULT_T2V_MODEL"),
    "submit_i2v": ("i2v", "DEFAULT_I2V_MODEL"),
    "submit_r2v_flash": ("r2v_flash", "DEFAULT_R2V_FLASH_MODEL"),
    "submit_i2i_test_image": ("i2i_test_image", "DEFAULT_I2I_TEST_IMAGE_MODEL"),
    "poll_i2i_test_image": ("i2i_test_i2v", "DEFAULT_I2I_TEST_I2V_MODEL"),
    "submit_i2i_test_i2v": ("i2i_test_i2v", "DEFAULT_I2I_TEST_I2V_MODEL"),
}


def _number(value, name, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise AppError("INVALID_INPUT", f"{name} must be a finite number", 422)
    if value < 0 or (value == 0 and not allow_zero):
        raise AppError("INVALID_INPUT", f"{name} must be positive", 422)
    return Decimal(str(value))


def estimate_model_cost(model, params: dict, *, input_video_seconds: float = 0.0) -> float:
    """Estimate final model usage; absent pricing keeps the legacy fixed cost."""
    from app.services.model_service import ModelService

    incoming = _number(input_video_seconds, "input_video_seconds", allow_zero=True)
    catalog = model.capabilities or {}
    pricing = catalog.get("pricing")
    if not pricing:
        current_app.logger.warning("Missing pricing for model %s; using legacy credit estimate", model.model_id)
        if any(ModelService.supports_task_type(model, task) for task in ("text_to_video", "image_to_video", "reference_to_video")):
            return VIDEO_GENERATION
        return IMAGE_GENERATION if model.task_type == "text_to_image" else LLM_CALL
    unit = pricing.get("unit")
    effective = ModelService.effective_params(model, params)
    rates = pricing.get("resolution_rates")
    if rates is not None:
        resolution = effective.get("resolution")
        if unit != "second" or not isinstance(rates, dict) or not isinstance(resolution, str) or resolution not in rates:
            raise AppError("INVALID_INPUT", "No configured estimate for this model resolution", 422)
        rate = _number(rates[resolution], "pricing.resolution_rates", allow_zero=True)
    else:
        rate = _number(pricing.get("credits_per_unit", 1 if unit == "call" else None),
                       "pricing.credits_per_unit", allow_zero=True)
    if unit == "second":
        basis = pricing.get("billing_basis", "output_seconds")
        if basis not in {"output_seconds", "input_plus_output_seconds"}:
            raise AppError("INVALID_INPUT", "Unsupported video billing basis", 422)
        seconds = _number(effective.get("duration"), "duration") * _number(effective.get("n_outputs", 1), "n_outputs")
        return float(rate * (seconds + (incoming if basis == "input_plus_output_seconds" else 0)))
    if incoming:
        raise AppError("INVALID_INPUT", "Input video duration requires a video pricing model", 422)
    if unit == "image":
        return float(rate * _number(effective.get("n", 1), "n"))
    if unit == "call":
        return float(rate)
    raise AppError("INVALID_INPUT", f"Unsupported pricing unit for {model.model_id}: {unit}", 422)


def estimate_nodes_cost(node_keys, sample_count: int = 1, *, node_models=None, node_params=None,
                        job_config=None, ctx=None) -> float:
    """Resolve the same saved model/parameter overrides used by workflow nodes."""
    from app.services.model_service import ModelService
    from app.services.workflow_service import WorkflowService

    config = job_config or {}
    if ctx and ctx.previous and ctx.previous.job:
        # launch() resumes this saved job. New workflow settings and input
        # overrides cannot change the parameters that its nodes will execute.
        config = ctx.previous.job.config or {}
        node_models, node_params = None, None
    total = 0.0
    i2i_video_cost = 0.0
    for key in node_keys:
        if key not in NODE_MODELS:
            continue
        param_key, default_key = NODE_MODELS[key]
        saved_node = (config.get("workflow_node_configs") or {}).get(key)
        node_config = saved_node if isinstance(saved_node, dict) else (WorkflowService.get_node(key).config or {})
        configured = (config.get("models") or {}).get(param_key)
        if key == "submit_i2v":
            configured = (config.get("models") or {}).get("main_i2v") or configured
        batch_default = None
        per_sample = key in PER_SAMPLE_NODE_COSTS or key == "poll_i2i_test_image"
        if per_sample:
            field = "image_model" if key == "submit_i2i_test_image" else "i2v_model"
            configured = (config.get("i2i_test") or {}).get(field) or configured
            batch_default = (config.get("i2i_test_batch") or {}).get(field)
        model_id = ((node_models or {}).get(key) or (config.get("node_models") or {}).get(key)
                    or configured or node_config.get("model_id") or batch_default or current_app.config[default_key])
        if ctx and key in {"submit_t2v", "submit_i2v", "submit_r2v_flash"}:
            from app.agent.model_policy import scope_policy, select_video_model
            policy = scope_policy(ctx.budget_scope)
            selected = (node_models or {}).get(key) or (config.get("node_models") or {}).get(key)
            mode = {"submit_t2v": "t2v", "submit_i2v": "i2v", "submit_r2v_flash": "r2v"}[key]
            if ctx.shot_task_id is not None and mode == "i2v":
                from app.agent.production_policy import model_for_context
                model_id = model_for_context(ctx, selected).model_id
            else:
                model_id = select_video_model(policy, mode, selected).model_id if policy else model_id
        model = ModelService.get_model(model_id, require_enabled=True)
        param_node_key = "submit_i2i_test_i2v" if key == "poll_i2i_test_image" else key
        params = {**(node_config.get("model_params") or {}),
                  **((config.get("model_params") or {}).get(param_key) or {}),
                  **((config.get("node_model_params") or {}).get(param_node_key) or {}),
                  **((node_params or {}).get(key) or {})}
        cost = estimate_model_cost(model, params) * (max(sample_count, 1) if per_sample else 1)
        if key in {"poll_i2i_test_image", "submit_i2i_test_i2v"}:
            # Image polling submits videos inline; the submit node only catches
            # up missing samples. Reserve one batch at the higher possible rate.
            i2i_video_cost = max(i2i_video_cost, cost)
        else:
            total += cost
    return total + i2i_video_cost


def planner_cost() -> float:
    from app.services.model_service import ModelService
    model = ModelService.get_model(current_app.config.get("AGENT_PLANNER_MODEL")
                                   or current_app.config["DEFAULT_PROMPT_REWRITE_MODEL"], require_enabled=True)
    return estimate_model_cost(model, {})


class BudgetGuard:
    @staticmethod
    def limit_for(budget_limit: float | None) -> float:
        if budget_limit is not None:
            return float(budget_limit)
        return float(current_app.config.get("SKILL_DEFAULT_BUDGET", 100))

    @staticmethod
    def spent(budget_scope: str) -> float:
        value = (
            db.session.query(func.coalesce(func.sum(ToolInvocation.estimated_cost), 0.0))
            .filter(
                ToolInvocation.budget_scope == budget_scope,
                ToolInvocation.status != "rejected",
            )
            .scalar()
        )
        return float(value or 0.0)

    @classmethod
    def check(cls, budget_scope: str, budget_limit: float | None, cost: float) -> None:
        if cost <= 0:
            return
        limit = cls.limit_for(budget_limit)
        spent = cls.spent(budget_scope)
        if spent + cost > limit:
            raise AppError(
                "BUDGET_EXCEEDED",
                f"Budget exceeded for scope '{budget_scope}': "
                f"spent {spent:g} + requested {cost:g} > limit {limit:g}",
                402,
                payload={
                    "budget_scope": budget_scope,
                    "spent": spent,
                    "requested": cost,
                    "limit": limit,
                },
            )
