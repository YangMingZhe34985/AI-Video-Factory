from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.skills.permissions import LEDGER_PERMISSIONS

if TYPE_CHECKING:
    from app.models import ToolInvocation


@dataclass
class ToolContext:
    """Who is calling a tool and under which constraints.

    The caller supplies role/approval/budget fields; the registry fills in
    tool_name, invocation_id and previous before running the handler.
    """

    role: str
    approved: bool = False
    idempotency_key: str | None = None
    budget_scope: str = "default"
    budget_limit: float | None = None
    tool_name: str = ""
    invocation_id: str | None = None
    # Set when the call retries a previously failed invocation.
    previous: "ToolInvocation | None" = None
    # Server-only linkage; public Skill schemas never accept this field.
    preview_task_id: int | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[BaseModel, ToolContext], BaseModel | dict]
    permission: str
    allowed_roles: frozenset[str]
    requires_approval: bool = False
    # Soft limit for the synchronous handler; exceeding it is logged, not aborted.
    timeout_sec: int = 30
    # How long the async result (the launched job) may take before it is
    # reported as overdue by get_task_status. None for synchronous tools.
    max_wait_sec: int | None = None
    # Extra executions allowed after a failed attempt (hard capped at 2).
    max_retries: int = 1
    # False for tools whose repeated calls must re-execute (e.g. packaging).
    dedupe: bool = True
    # Context carries the server-owned model policy used for the actual call.
    cost_fn: Callable[[BaseModel, ToolContext], float] = field(default=lambda _data, _ctx: 0.0)

    def __post_init__(self):
        if not 0 <= self.max_retries <= 2:
            raise ValueError(f"{self.name}: max_retries must be between 0 and 2")

    @property
    def uses_ledger(self) -> bool:
        return self.permission in LEDGER_PERMISSIONS

    def describe(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission,
            "allowed_roles": sorted(self.allowed_roles),
            "requires_approval": self.requires_approval,
            "timeout_sec": self.timeout_sec,
            "max_wait_sec": self.max_wait_sec,
            "max_retries": self.max_retries,
            "dedupe": self.dedupe,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
        }
