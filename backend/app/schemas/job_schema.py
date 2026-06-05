from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class CreateJobSchema(BaseModel):
    template_id: str = "default"
    job_name: str | None = None
    strategy: str = "default"
    enabled_nodes: list[str] | dict[str, bool] = Field(default_factory=list)
    disabled_nodes: list[str] | dict[str, bool] = Field(default_factory=list)
    job_config: dict[str, Any] = Field(default_factory=dict)
    budget_limit: Decimal | None = None
    source_video_path: str | None = None
    start_node: str | None = None
    initial_prompts: dict[str, Any] = Field(default_factory=dict)
    initial_artifacts: dict[str, Any] = Field(default_factory=dict)


class RunFullSchema(BaseModel):
    force: bool = False
    restart: bool = False


class RunFromSchema(BaseModel):
    node_key: str
    force: bool = False


class RunNodeSchema(BaseModel):
    node_key: str
    force: bool = False


class UpdateJobSchema(BaseModel):
    job_name: str | None = None


class DeleteJobSchema(BaseModel):
    confirm_job_id: str
