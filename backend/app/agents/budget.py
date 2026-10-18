"""Planning quotas, including outstanding allocations to child delegations."""

from flask import current_app

from app.api import AppError
from app.models import AgentDelegation, AgentRun, ToolInvocation
from app.tools.budget import BudgetGuard

TERMINAL = frozenset({"completed", "returned", "failed", "limit", "cancelled"})


def submitted_producer(run, delegation):
    return (delegation.agent == "producer" and delegation.status == "completed"
            and run.status == "awaiting_plan_review"
            and (delegation.output or {}).get("outcome") == "plan_submitted"
            and (run.snapshot or {}).get("v3_plan_submission", {}).get("plan_ref")
            == (delegation.output or {}).get("plan_ref"))


def validate_context(ctx, tool_name=None):
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
    if run is None or not (run.request or {}).get("_v3_runtime"):
        return None
    from app.agents.workspace import require_context
    run, delegation = require_context(ctx)
    from app.agents.cards import get_catalog
    card = get_catalog().cards[delegation.agent]
    if (tool_name or ctx.tool_name) not in set(card.tools) | {"agent_llm_turn"}:
        raise AppError("TOOL_FORBIDDEN", "Tool is not in this Agent's server-owned card", 403)
    return run, delegation


def own_spent(delegation):
    return sum(float(row.estimated_cost or 0) for row in ToolInvocation.query.filter_by(
        budget_scope=delegation.run_id, delegation_id=delegation.id).all()
        if row.status != "rejected")


def planning_spent(run_id):
    return sum(float(row.estimated_cost or 0) for row in ToolInvocation.query.filter_by(budget_scope=run_id).filter(
        ToolInvocation.caller_agent.is_not(None), ToolInvocation.status != "rejected").all())


def subtree_spent(delegation):
    return own_spent(delegation) + sum(subtree_spent(child) for child in
        AgentDelegation.query.filter_by(run_id=delegation.run_id, parent_id=delegation.id).all())


def remaining(delegation):
    used = own_spent(delegation)
    for child in AgentDelegation.query.filter_by(run_id=delegation.run_id, parent_id=delegation.id).all():
        spent = subtree_spent(child)
        used += spent if child.status in TERMINAL else max(float(child.credits_limit), spent)
    return max(0.0, float(delegation.credits_limit) - used)


def check_admission(ctx, cost):
    found = validate_context(ctx)
    if found is None:
        return
    run, delegation = found
    if not cost and ctx.tool_name == "finish" and submitted_producer(run, delegation):
        return
    if delegation.status in TERMINAL or run.status in {"cancelled", "failed", "success"}:
        raise AppError("AGENT_NOT_ACTIVE", "This delegation is no longer active", 409)
    # Free bookkeeping remains available when an Agent has spent its quota.
    if not cost:
        return
    root = AgentDelegation.query.filter_by(run_id=run.run_id, parent_id=None).one()
    run_limit = float(root.credits_limit)
    if planning_spent(run.run_id) + cost > run_limit + 1e-9:
        raise AppError("AGENT_PLANNING_BUDGET_EXCEEDED", "Run planning quota is exhausted", 422)
    if cost > remaining(delegation) + 1e-9:
        raise AppError("AGENT_DELEGATION_BUDGET_EXCEEDED", "Delegation quota is exhausted or allocated", 422)
    parent = delegation
    while parent.parent_id is not None:
        parent = AgentDelegation.query.filter_by(id=parent.parent_id, run_id=run.run_id).one()
        if subtree_spent(parent) + cost > float(parent.credits_limit) + 1e-9:
            raise AppError("AGENT_DELEGATION_BUDGET_EXCEEDED", "Ancestor delegation quota is exhausted", 422)


def allocate(parent, requested, card):
    available = remaining(parent)
    quota = available / 2 if requested is None else float(requested)
    if quota <= 0 or quota > available + 1e-9:
        raise AppError("AGENT_DELEGATION_BUDGET_EXCEEDED", "Child quota exceeds unallocated parent quota", 422)
    return min(quota, float(card.limits.planning_credits))
