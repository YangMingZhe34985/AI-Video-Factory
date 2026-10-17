"""Image search records untrusted provider results in the owning Run ledger."""
from flask import current_app
from pydantic import BaseModel, ConfigDict, Field

from app.agent.search import get_search_provider
from app.agent.search.base import ImageResult
from app.agent.search.scope import require_run, reserve
from app.api import AppError
from app.skills.permissions import EXTERNAL, RESEARCH, SYSTEM
from app.skills.spec import ToolContext, ToolSpec
from app.utils.time_utils import utc_now


class ImageSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=200)
    max_results: int = Field(default=6, ge=1, le=12, strict=True)
    safe: bool = True


class ImageSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    provider: str
    fetched_at: str
    results: list[ImageResult]


def run(data: ImageSearchInput, ctx: ToolContext):
    require_run(ctx)
    reserve(ctx, {"web_search", "image_search"}, "AGENT_RESEARCH_MAX_QUERIES")
    provider = get_search_provider()
    try:
        results = provider.image_search(data.query, max_results=data.max_results, safe=data.safe)
        results = [ImageResult.model_validate(item) for item in results[:data.max_results]]
        if len({item.result_id for item in results}) != len(results):
            raise ValueError("Image search result IDs must be unique")
        return ImageSearchOutput(query=data.query, provider=provider.name, fetched_at=utc_now().isoformat(),
                                 results=results)
    except AppError:
        raise
    except Exception as error:
        raise AppError("SEARCH_PROVIDER_UNAVAILABLE", "Image search provider is unavailable", 503) from error


SPEC = ToolSpec(
    name="image_search", description="Search images and retain their source URLs as untrusted references.",
    input_model=ImageSearchInput, output_model=ImageSearchOutput, handler=run,
    permission=EXTERNAL, allowed_roles=frozenset({RESEARCH, SYSTEM}), max_retries=0,
    cost_fn=lambda _data, _ctx: current_app.config["AGENT_SEARCH_COST_PER_CALL"],
)
