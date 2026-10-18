from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError


class InvokeSkillSchema(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    role: Literal["director", "creative", "production", "system", "intake", "research"]
    approved: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    budget_scope: str = Field(default="default", min_length=1, max_length=128)
    budget_limit: float | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def reject_agent_context(cls, value):
        # Preserve legacy extra-field behavior, but never accept v3 identities
        # from the public API. Only the server constructs these fields.
        if isinstance(value, dict) and {"caller_agent", "delegation_id", "agent_step"}.intersection(value):
            raise PydanticCustomError("server_owned_context", "Agent identity and step context are server-owned")
        return value
