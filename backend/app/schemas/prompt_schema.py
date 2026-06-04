from pydantic import BaseModel, Field


class CreateTemplateSchema(BaseModel):
    template_id: str | None = None
    name: str
    series: str | None = None
    series_id: str | None = None  # alias for series (new field name)
    description: str | None = None
    config: dict = Field(default_factory=dict)


class CreatePromptVersionSchema(BaseModel):
    prompt_type: str
    prompt_key: str = "default"
    job_id: str | None = None
    title: str
    content: str
    content_format: str = "markdown"
    parent_version: str | None = None
    note: str | None = None
    source: str = "manual"
    created_by: str | None = None
    activate: bool = True


class RollbackPromptSchema(BaseModel):
    title: str | None = None
    note: str | None = None
    created_by: str | None = None


class EditPromptVersionSchema(BaseModel):
    prompt_key: str = "default"
    job_id: str | None = None
    title: str | None = None
    content: str
    content_format: str = "markdown"
    note: str | None = None
    created_by: str | None = None
    activate: bool = True
