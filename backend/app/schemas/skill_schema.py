from typing import Any, Literal

from pydantic import BaseModel, Field


class InvokeSkillSchema(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    role: Literal["director", "creative", "production", "system"]
    approved: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    budget_scope: str = Field(default="default", min_length=1, max_length=128)
    budget_limit: float | None = Field(default=None, ge=0)
