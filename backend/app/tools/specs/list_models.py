"""Read-only, public capability catalog for v3 planning."""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.adapters import ADAPTERS
from app.models import ModelRegistry
from app.services.model_service import ModelService
from app.tools.permissions import READ
from app.tools.spec import ToolContext, ToolSpec


V3_ROLES = frozenset({"producer", "research", "creative", "director", "prompt_smith", "critic", "repair", "system"})
PUBLIC_CAPABILITIES = {"modes", "duration", "resolutions", "aspect_ratios", "reference_images",
                       "quality_tier", "agent_selectable", "notes"}
PUBLIC_PARAMETER_RULES = {"type", "label", "min", "max", "step", "enum", "default", "format", "presets",
                          "min_pixels", "max_pixels", "min_aspect_ratio", "max_aspect_ratio"}
PUBLIC_PRICING = {"unit", "credits_per_unit", "credits_per_1k_tokens", "resolution_rates", "billing_basis"}


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class ListModelsInput(CatalogModel):
    mode: str | None = Field(default=None, min_length=1, max_length=80)
    family: str | None = Field(default=None, min_length=1, max_length=120)


class ModelEntry(CatalogModel):
    model_id: str
    display_name: str
    provider: str
    family: str
    modes: list[str]
    capabilities: dict
    parameter_schema: dict
    default_params: dict
    pricing: dict
    integration_status: Literal["integrated"] = "integrated"
    verification_status: Literal["untested"] = "untested"


class ListModelsOutput(CatalogModel):
    models: list[ModelEntry]
    demo: Literal[True] = True


def public_pricing(model):
    return {key: deepcopy(value) for key, value in ((model.capabilities or {}).get("pricing") or {}).items()
            if key in PUBLIC_PRICING}


def _public_parameter(name):
    normalized = name.lower().replace("-", "_")
    return not any(part in normalized for part in ("api_key", "secret", "password", "credential", "token", "url"))


def run(data: ListModelsInput, _ctx: ToolContext):
    entries = []
    for model in ModelRegistry.query.filter_by(enabled=True).order_by(ModelRegistry.model_id).all():
        capabilities = model.capabilities or {}
        # Provider claims are descriptive only; only integrated modes grant use.
        modes = capabilities.get("modes") or []
        family = ModelService.model_family(model)
        if (model.adapter_name not in ADAPTERS or not capabilities.get("agent_selectable") or not modes
                or (data.mode is not None and data.mode not in modes)
                or (data.family is not None and data.family.casefold() != family.casefold())):
            continue
        parameters = {name: {key: deepcopy(value) for key, value in rule.items() if key in PUBLIC_PARAMETER_RULES}
                      for name, rule in (model.parameter_schema or {}).items()
                      if _public_parameter(name) and isinstance(rule, dict)}
        defaults = {key: deepcopy(value) for key, value in ModelService.effective_params(model).items()
                    if key in parameters}
        entries.append(ModelEntry(
            model_id=model.model_id, display_name=model.display_name, provider=model.provider, family=family,
            modes=modes, capabilities={key: deepcopy(value) for key, value in capabilities.items()
                                       if key in PUBLIC_CAPABILITIES},
            parameter_schema=parameters, default_params=defaults, pricing=public_pricing(model),
        ))
    return ListModelsOutput(models=entries)


SPEC = ToolSpec(
    name="list_models", description="List integrated model modes, validated parameters and demonstration credit prices; quality is untested.",
    input_model=ListModelsInput, output_model=ListModelsOutput, handler=run,
    permission=READ, allowed_roles=V3_ROLES, agent_visible=True,
    io_types={"inputs": {"mode": "text", "family": "text"}, "outputs": {"models": "json", "demo": "json"}},
)
