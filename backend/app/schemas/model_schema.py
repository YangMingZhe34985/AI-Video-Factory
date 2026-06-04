from pydantic import BaseModel, ConfigDict, Field


class CreateModelSchema(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    display_name: str
    provider: str
    task_type: str
    adapter_name: str
    enabled: bool = True
    input_schema: dict = Field(default_factory=dict)
    parameter_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    default_params: dict = Field(default_factory=dict)


class UpdateModelSchema(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    display_name: str | None = None
    provider: str | None = None
    task_type: str | None = None
    adapter_name: str | None = None
    enabled: bool | None = None
    input_schema: dict | None = None
    parameter_schema: dict | None = None
    output_schema: dict | None = None
    default_params: dict | None = None
