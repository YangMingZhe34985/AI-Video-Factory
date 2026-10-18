"""Delegation quotas and concurrent admission use durable, scoped accounting."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Barrier, Event

from pydantic import BaseModel, ConfigDict
import pytest

from app.agents import runtime
from app.agents.budget import own_spent, remaining, subtree_spent
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentRun, AgentWorkspaceItem, ToolInvocation
from app.tools import build_v3_registry
from app.tools.budget import BudgetGuard
from app.tools.registry import ToolRegistry
from app.tools.spec import ToolContext, ToolSpec
from app.utils.ids import new_id


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = "stub"


def make_run(limit=20):
    run = AgentRun(owner_id="local", request_key=new_id("budget"), request={
        "schema_version": 3, "text": "Mock budget test", "attachment_ids": [], "budget_limit": limit})
    db.session.add(run)
    db.session.commit()
    root = runtime.initialize(run)
    return run, root


def child(parent, role="research", quota=4, status="running"):
    row = AgentDelegation(run_id=parent.run_id, parent_id=parent.id, agent=role, credits_limit=quota,
        status=status, task="Bounded stub", request_key=new_id("child"), depth=parent.depth + 1)
    db.session.add(row)
    db.session.commit()
    return row


def charge(delegation, cost, status="success"):
    row = ToolInvocation(tool_name="analyze_images", caller_role=delegation.agent, caller_agent=delegation.agent,
        delegation_id=delegation.id, budget_scope=delegation.run_id, idempotency_key=new_id("spent"),
        estimated_cost=cost, status=status)
    db.session.add(row)
    db.session.commit()
    return row


def context(delegation, key=None):
    return ToolContext(role=delegation.agent, caller_agent=delegation.agent, delegation_id=delegation.id,
        budget_scope=delegation.run_id, agent_step=0, idempotency_key=key or new_id("admit"))


def stub_registry(cost, handler=None):
    registry = ToolRegistry()
    # Reuse a card-permitted identity; no provider/model handler is called.
    registry.register(ToolSpec(name="analyze_images", description="Offline budget probe", input_model=Payload,
        output_model=Payload, permission="llm", allowed_roles=frozenset({"producer", "director", "research", "creative"}),
        agent_visible=True, max_retries=0, cost_fn=lambda _data, _ctx: cost,
        handler=handler or (lambda data, _ctx: data)))
    return registry


def test_active_children_reserve_unused_quota_and_terminal_children_release_it(app_ctx):
    run, root = make_run()
    director = child(root, "director", 8)
    research = child(director, "research", 4)
    sibling = child(root, "creative", 6)
    charge(root, 2)
    charge(director, 3)
    charge(research, 2)
    charge(sibling, 1)
    assert subtree_spent(root) == BudgetGuard.spent(run.run_id) == 8
    assert remaining(root) == 4
    assert remaining(director) == 1
    research.status = "completed"
    db.session.commit()
    assert remaining(director) == 3
    assert remaining(root) == 4  # Director is still active and owns its allocation.
    director.status = "completed"
    db.session.commit()
    assert remaining(root) == 7
    sibling.status = "returned"
    db.session.commit()
    assert remaining(root) == 12


@pytest.mark.parametrize("status", ["pending", "running", "success", "partial_success", "failed", "rejected"])
def test_only_rejected_receipts_are_excluded_from_delegation_cost(app_ctx, status):
    _run, root = make_run()
    charge(root, 3, status)
    assert own_spent(root) == (0 if status == "rejected" else 3)
    assert remaining(root) == (20 if status == "rejected" else 17)


def test_parent_cannot_spend_active_child_allocation_but_can_use_released_balance(app_ctx):
    run, root = make_run(limit=10)
    delegated = child(root, quota=8)
    charge(delegated, 3)
    executions = []
    registry = stub_registry(4, lambda data, ctx: executions.append(ctx.delegation_id) or data)
    with pytest.raises(AppError) as error:
        registry.invoke("analyze_images", {}, context(root))
    assert error.value.code == "AGENT_DELEGATION_BUDGET_EXCEEDED" and executions == []
    delegated.status = "completed"
    db.session.commit()
    assert registry.invoke("analyze_images", {}, context(root))["status"] == "success"
    assert BudgetGuard.spent(run.run_id) == 7 and remaining(root) == 3


def test_grandchild_spending_counts_at_every_ancestor_and_stays_within_its_quota(app_ctx):
    run, root = make_run(limit=12)
    director = child(root, "director", 8)
    research = child(director, "research", 4)
    charge(root, 2)
    charge(director, 2)
    charge(research, 1)
    registry = stub_registry(3)
    assert registry.invoke("analyze_images", {}, context(research))["status"] == "success"
    assert own_spent(research) == 4
    assert subtree_spent(director) == 6 and subtree_spent(root) == 8
    with pytest.raises(AppError) as error:
        stub_registry(1).invoke("analyze_images", {}, context(research))
    assert error.value.code == "AGENT_DELEGATION_BUDGET_EXCEEDED"
    assert BudgetGuard.spent(run.run_id) == 8


@pytest.mark.parametrize("status", ["completed", "returned", "failed", "limit", "cancelled"])
def test_terminal_delegation_cannot_create_new_paid_or_free_side_effects(app_ctx, status):
    _run, root = make_run()
    root.status = status
    db.session.commit()
    executions = []
    with pytest.raises(AppError) as error:
        stub_registry(1, lambda data, ctx: executions.append(ctx.delegation_id) or data).invoke(
            "analyze_images", {}, context(root))
    assert error.value.code == "AGENT_NOT_ACTIVE" and executions == []
    for tool, args in (("write_workspace", {"key": "late", "kind": "note", "payload": {}}),
                       ("delegate", {"agent": "research", "task": "late", "expected": "Dossier"})):
        with pytest.raises(AppError) as error:
            build_v3_registry().invoke(tool, args, context(root))
        assert error.value.code == "AGENT_NOT_ACTIVE"
    assert AgentDelegation.query.count() == 1 and AgentWorkspaceItem.query.count() == 0


def test_admission_refreshes_preloaded_delegation_after_another_session_finishes_it(app_ctx):
    run, root = make_run()
    delegated = child(root, "research", 4)
    delegation_id = delegated.id
    assert delegated.status == "running"
    with app_ctx.app_context():
        changed = db.session.get(AgentDelegation, delegation_id)
        changed.status = "completed"
        db.session.commit()
    # The outer identity map still holds the old status. Admission must refresh
    # under the Run lock instead of trusting this earlier planning observation.
    assert delegated.status == "running"
    executions = []
    with pytest.raises(AppError) as error:
        stub_registry(1, lambda data, ctx: executions.append(ctx.delegation_id) or data).invoke(
            "analyze_images", {}, context(delegated))
    assert error.value.code == "AGENT_NOT_ACTIVE"
    assert executions == [] and BudgetGuard.spent(run.run_id) == 0


def test_concurrent_delegate_calls_cannot_allocate_the_same_parent_balance_twice(app):
    with app.app_context():
        run, root = make_run(limit=10)
        root_id, run_id = root.id, run.run_id
    start = Barrier(2)
    def allocate(index):
        with app.app_context():
            parent = db.session.get(AgentDelegation, root_id)
            ctx = context(parent, key=f"concurrent-allocation-{index}")
            start.wait(timeout=15)
            try:
                return build_v3_registry().invoke("delegate", {
                    "agent": "research", "task": f"Stub {index}", "expected": "Dossier", "planning_credits": 6}, ctx)["status"]
            except AppError as error:
                return error.code
            finally:
                db.session.remove()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(allocate, (1, 2)))
    assert sorted(results) == ["AGENT_DELEGATION_BUDGET_EXCEEDED", "success"]
    with app.app_context():
        assert AgentDelegation.query.filter_by(parent_id=root_id).count() == 1
        assert remaining(db.session.get(AgentDelegation, root_id)) == 4
        assert BudgetGuard.spent(run_id) == 0


def test_concurrent_delegations_respect_lowered_run_ceiling_before_handler_execution(app):
    with app.app_context():
        run, root = make_run(limit=10)
        delegates = [child(root, quota=4), child(root, "director", quota=4)]
        ids, run_id = [item.id for item in delegates], run.run_id
        # A server-owned overall ceiling may be reduced after allocation; old
        # child allocations cannot bypass the tighter admission fence.
        run.request = {**run.request, "budget_limit": 5}
        db.session.commit()
    start, entered, release = Barrier(2), Event(), Event()
    executions = []
    def handler(data, ctx):
        executions.append(ctx.delegation_id)
        entered.set()
        assert release.wait(15)
        return data
    registry = stub_registry(4, handler)
    def invoke(identity):
        with app.app_context():
            delegated = db.session.get(AgentDelegation, identity)
            ctx = context(delegated)
            start.wait(timeout=15)
            try:
                return registry.invoke("analyze_images", {}, ctx)["status"]
            except AppError as error:
                return error.code
            finally:
                db.session.remove()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke, identity) for identity in ids]
        try:
            assert entered.wait(15)
            completed, _pending = wait(futures, timeout=15, return_when=FIRST_COMPLETED)
            assert len(completed) == 1 and next(iter(completed)).result() == "BUDGET_EXCEEDED"
        finally:
            release.set()
        assert sorted(future.result(timeout=15) for future in futures) == ["BUDGET_EXCEEDED", "success"]
    with app.app_context():
        assert len(executions) == 1 and BudgetGuard.spent(run_id) == 4
        assert sorted(row.status for row in ToolInvocation.query.all()) == ["rejected", "success"]
