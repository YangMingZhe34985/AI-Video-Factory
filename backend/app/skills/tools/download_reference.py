"""Download an allowed reference image into an owned, run-scoped artifact."""
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.search.base import validate_result_url
from app.agent.search.references import download_reference
from app.agent.search.scope import require_run, reserve
from app.skills.permissions import EXTERNAL, RESEARCH, SYSTEM
from app.skills.spec import ToolContext, ToolSpec


class DownloadReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    run_id: str = Field(min_length=1, max_length=80)
    image_url: str = Field(min_length=1, max_length=4096)
    source_page_url: str | None = Field(default=None, max_length=4096)
    entity: str | None = Field(default=None, max_length=80)

    @field_validator("image_url", "source_page_url")
    @classmethod
    def safe_url(cls, value):
        return validate_result_url(value)


class DownloadReferenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: str
    preview_url: str
    width: int
    height: int
    sha256: str
    duplicate_of: str | None = None


def run(data: DownloadReferenceInput, ctx: ToolContext):
    owner = require_run(ctx, data.run_id)
    reserve(ctx, {"download_reference"}, "AGENT_MAX_REFERENCE_DOWNLOADS")
    return download_reference(data, ctx, owner)


SPEC = ToolSpec(
    name="download_reference", description="Download and validate an allowed image as a private Run reference.",
    input_model=DownloadReferenceInput, output_model=DownloadReferenceOutput, handler=run,
    permission=EXTERNAL, allowed_roles=frozenset({RESEARCH, SYSTEM}), max_retries=0,
)
