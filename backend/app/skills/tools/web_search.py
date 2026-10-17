"""Budgeted provider-neutral web lookup; no model-generated URLs are executed."""

from typing import Literal

from flask import current_app
from pydantic import Field

from app.agent.search import get_search_provider
from app.agent.search.base import StrictModel, WebResult
from app.agent.search.scope import require_run, reserve
from app.api import AppError
from app.skills.permissions import EXTERNAL, RESEARCH, SYSTEM
from app.skills.spec import ToolSpec
from app.utils.time_utils import utc_now


class WebSearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=200)
    locale: str = Field(default="zh-CN", min_length=1, max_length=40)
    freshness: Literal["any", "day", "week", "month", "year"] = "any"
    max_results: int = Field(default=5, ge=1, le=10, strict=True)


class WebSearchOutput(StrictModel):
    query: str
    provider: str
    fetched_at: str
    results: list[WebResult] = Field(max_length=10)


def run(data, ctx):
    require_run(ctx)
    reserve(ctx, {"web_search", "image_search"}, "AGENT_RESEARCH_MAX_QUERIES")
    provider = get_search_provider()
    try:
        results = provider.web_search(data.query, locale=data.locale, freshness=data.freshness, max_results=data.max_results)
        output = WebSearchOutput(query=data.query, provider=provider.name, fetched_at=utc_now().isoformat(), results=results)
        if len(output.results) > data.max_results or len({item.result_id for item in output.results}) != len(output.results):
            raise ValueError("Search provider returned duplicate IDs or too many results")
        return output
    except Exception as error:
        raise AppError("SEARCH_PROVIDER_UNAVAILABLE", "Search provider failed to return usable results", 503) from error


SPEC = ToolSpec(name="web_search", description="Search web sources for this Agent run",
    input_model=WebSearchInput, output_model=WebSearchOutput, handler=run, permission=EXTERNAL,
    allowed_roles=frozenset({RESEARCH, SYSTEM}), max_retries=0,
    cost_fn=lambda _data, _ctx: current_app.config["AGENT_SEARCH_COST_PER_CALL"])
