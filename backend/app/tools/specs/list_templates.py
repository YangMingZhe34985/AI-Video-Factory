"""Read-only classic series/template catalog for classic-path plans (V.25.1)."""

from pydantic import Field

from app.tools.permissions import READ
from app.tools.spec import ToolContext, ToolSpec
from app.tools.specs.list_models import CatalogModel, V3_ROLES


class ListTemplatesInput(CatalogModel):
    series_id: str | None = Field(default=None, min_length=1, max_length=128)
    query: str | None = Field(default=None, min_length=1, max_length=80)


class PromptPreview(CatalogModel):
    version: str
    preview: str


class TemplateEntry(CatalogModel):
    template_id: str
    name: str
    description: str
    prompt_types: dict[str, PromptPreview]


class SeriesEntry(CatalogModel):
    series_id: str
    name: str
    description: str
    templates: list[TemplateEntry]


class ListTemplatesOutput(CatalogModel):
    series: list[SeriesEntry]


def run(data: ListTemplatesInput, _ctx: ToolContext):
    from app.plans.workflow import catalog
    return ListTemplatesOutput(series=catalog(data.series_id, data.query))


SPEC = ToolSpec(
    name="list_templates",
    description="List classic series and templates (with current prompt previews) as targets for classic-workflow plans.",
    input_model=ListTemplatesInput, output_model=ListTemplatesOutput, handler=run,
    permission=READ, allowed_roles=V3_ROLES, agent_visible=True,
    io_types={"inputs": {"series_id": "text", "query": "text"}, "outputs": {"series": "json"}},
)
