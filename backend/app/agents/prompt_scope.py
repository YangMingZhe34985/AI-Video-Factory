"""Server-frozen Prompt Smith scope; returned edits never authorize execution."""

from copy import deepcopy

from pydantic import Field, ValidationError, model_validator

from app.agent.plan_spec import PROMPT_MAX_LENGTH
from app.agent.plan_versions import inputs_hash
from app.agent.request_spec import StrictModel
from app.agents.schemas import NodeId, PlanDraft, WorkspaceRef
from app.api import AppError


PROMPT_TOOLS = frozenset({"generate_image", "animate_shot", "generate_video", "transform_video"})


class PromptScope(StrictModel):
    plan_ref: WorkspaceRef
    node_ids: list[NodeId] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_nodes(self):
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("Prompt scope requires unique node IDs")
        return self


class PromptFields(StrictModel):
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX_LENGTH, strict=True)


class PromptUpdate(StrictModel):
    node_id: NodeId
    inputs_patch: PromptFields


def freeze_scope(scope, context_refs, ctx):
    """Validate the immutable draft and copy only explicitly assigned nodes."""
    from app.agents.workspace import resolve_workspace_ref
    checked = PromptScope.model_validate(scope)
    ref = checked.plan_ref.model_dump(mode="json")
    if ref not in context_refs:
        raise AppError("INVALID_PROMPT_SCOPE", "Prompt Plan reference must be in the delegation context", 422)
    item = resolve_workspace_ref(ref, ctx, expected_kind="plan_draft")
    plan = PlanDraft.model_validate(item["payload"])
    nodes = {node.id: node for node in plan.nodes}
    if any(node_id not in nodes or nodes[node_id].tool not in PROMPT_TOOLS for node_id in checked.node_ids):
        raise AppError("INVALID_PROMPT_SCOPE", "Prompt scope requires existing generation nodes", 422)
    return {**checked.model_dump(mode="json"), "plan_hash": inputs_hash(item["payload"])}


def checked_scope(delegation, ctx):
    """Old unscoped delegations fail closed instead of inferring new authority."""
    raw = (delegation.state or {}).get("prompt_scope")
    if not isinstance(raw, dict) or not raw.get("plan_hash"):
        raise AppError("PROMPT_SCOPE_REQUIRED", "Prompt Smith requires a server-frozen delegation scope", 409)
    try:
        scope = PromptScope.model_validate({name: value for name, value in raw.items() if name != "plan_hash"})
        frozen = freeze_scope(scope, delegation.context_refs or [], ctx)
    except (ValidationError, KeyError) as error:
        raise AppError("INVALID_PROMPT_SCOPE", "Stored Prompt Smith scope is invalid", 409) from error
    if frozen != raw:
        raise AppError("PROMPT_SCOPE_CHANGED", "The frozen Prompt Smith draft no longer matches", 409)
    return deepcopy(frozen)


def validate_updates(updates, delegation, ctx):
    from app.agents.workspace import resolve_workspace_ref
    from app.tools import build_v3_registry
    frozen = checked_scope(delegation, ctx)
    values = [PromptUpdate.model_validate(item) for item in updates]
    node_ids = [item.node_id for item in values]
    if len(set(node_ids)) != len(node_ids) or set(node_ids) - set(frozen["node_ids"]):
        raise AppError("INVALID_PROMPT_UPDATE", "Prompt updates require unique assigned node IDs", 422)
    plan = resolve_workspace_ref(frozen["plan_ref"], ctx, expected_kind="plan_draft")["payload"]
    tools = {node["id"]: node["tool"] for node in plan["nodes"]}
    registry = build_v3_registry()
    for item in values:
        # Future references remain unresolved. Only validate the prompt field's
        # tighter tool-specific limit; full Plan compilation remains mandatory.
        field = registry.get(tools[item.node_id]).input_model.model_fields["prompt"]
        limits = [meta.max_length for meta in field.metadata if getattr(meta, "max_length", None) is not None]
        if limits and len(item.inputs_patch.prompt) > min(limits):
            raise AppError("INVALID_PROMPT_UPDATE", "Prompt exceeds the assigned tool's text limit", 422)
    return [item.model_dump(mode="json") for item in values]


def validate_delegate_receipt(data, parent, child, ctx):
    """A local-commit recovery must match the exact child and frozen scope."""
    if (child.run_id != parent.run_id or child.parent_id != parent.id or child.agent != data.agent
            or child.task != data.task or child.expected != data.expected
            or child.context_refs != [ref.model_dump(mode="json") for ref in data.context_refs]):
        raise AppError("IDEMPOTENCY_CONFLICT", "Delegation receipt belongs to different input", 409)
    previous_hash = (child.state or {}).get("delegate_input_hash")
    if previous_hash and previous_hash != inputs_hash(data.model_dump(mode="json")):
        raise AppError("IDEMPOTENCY_CONFLICT", "Delegation receipt belongs to different input", 409)
    if child.agent == "prompt_smith":
        frozen = checked_scope(child, ctx)
        expected = freeze_scope(data.prompt_scope, child.context_refs, ctx)
        if frozen != expected:
            raise AppError("IDEMPOTENCY_CONFLICT", "Delegation receipt has a different Prompt Smith scope", 409)
