from pydantic import BaseModel, Field


class RegisterUploadArtifactSchema(BaseModel):
    artifact_type: str = "reference_image"
    branch_key: str = "reference"
    metadata: dict = Field(default_factory=dict)
