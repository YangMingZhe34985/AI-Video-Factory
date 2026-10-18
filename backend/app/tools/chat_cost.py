"""Conservative reservations and usage settlement for v3 planning calls."""

import json
from decimal import Decimal
from math import isfinite

from app.api import AppError
from app.tools.budget import estimate_model_cost


def token_rate(model) -> float | None:
    pricing = (model.capabilities or {}).get("pricing") or {}
    rate = pricing.get("credits_per_1k_tokens")
    if rate is None:
        return None
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not isfinite(rate) or rate < 0:
        raise AppError("INVALID_MODEL_PRICING", "Token pricing must be a finite nonnegative number", 422)
    return float(rate)


def prompt_token_reserve(messages: list[dict], tools: list[dict]) -> int:
    """UTF-8 bytes plus message/tool framing; deliberately above text token counts.

    This is a reservation, not a tokenizer or a provider bill. Image/video
    understanding needs its own media allowance; agent_chat only accepts text.
    """
    wire = json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False, separators=(",", ":"))
    return len(wire.encode("utf-8")) + 256 + 32 * (len(messages) + len(tools))


def cost_for_tokens(rate: float, count: int) -> float:
    return float(Decimal(str(rate)) * Decimal(count) / Decimal(1000))


def reserve_chat_cost(model, messages: list[dict], tools: list[dict], max_tokens: int) -> float:
    rate = token_rate(model)
    if rate is None:
        return estimate_model_cost(model, {})
    return cost_for_tokens(rate, prompt_token_reserve(messages, tools) + max_tokens)


def usage_token_count(usage: dict | None) -> int | None:
    """Missing usage retains the reservation; malformed usage is never free."""
    if usage is None or usage == {}:
        return None
    if not isinstance(usage, dict):
        raise AppError("INVALID_LLM_USAGE", "Model usage must be an object", 502,
                       payload={"response_validation": True})
    values = [usage.get(key) for key in ("prompt_tokens", "completion_tokens")]
    if any(value is not None and (type(value) is not int or value < 0) for value in values):
        raise AppError("INVALID_LLM_USAGE", "Model token usage must contain nonnegative integers", 502,
                       payload={"response_validation": True})
    if any(value is None for value in values):
        return None
    return sum(values)


def settle_chat_cost(model, usage: dict | None, reserved_cost: float | None = None) -> float | None:
    """Return actual cost; the Registry records and rejects any excess itself."""
    rate = token_rate(model)
    if rate is None:
        return estimate_model_cost(model, {})
    count = usage_token_count(usage)
    return cost_for_tokens(rate, count) if count is not None else None
