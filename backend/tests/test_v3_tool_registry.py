"""V3 tool admission: legacy schemas, durable costs and concurrent reservation."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from flask_migrate import upgrade
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import inspect, text

from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ToolInvocation
from app.schemas.skill_schema import InvokeSkillSchema
from app.services.schema_service import SchemaService
from app.tools.budget import BudgetGuard
from app.tools.registry import ToolRegistry
from app.tools.spec import ToolContext, ToolSpec
from tests.test_migrations import _empty_app, MIGRATIONS_DIR


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = "ok"


def spec(handler, *, reserve=4.0, settle=None):
    return ToolSpec(name="v3_probe", description="Test admission", input_model=Payload,
        output_model=Payload, handler=handler, permission="llm",
        allowed_roles=frozenset({"producer"}), agent_visible=True,
        max_retries=0, cost_fn=lambda data, ctx: reserve, settlement_fn=settle)


def make_run(limit=100):
    run = AgentRun(run_id="agent_v3_registry", owner_id="local", request_key="registry-v3",
        request={"schema_version": 3, "text": "test", "budget_limit": limit})
    db.session.add(run)
    db.session.commit()
    return run.run_id


def context(run_id, **kwargs):
    return ToolContext(**{"role": "producer", "caller_agent": "producer", "delegation_id": 1,
        "agent_step": 0, "budget_scope": run_id, **kwargs})


@pytest.mark.parametrize("name", ["caller_agent", "delegation_id", "agent_step"])
def test_public_schema_does_not_accept_server_agent_context(name):
    with pytest.raises(ValidationError):
        InvokeSkillSchema.model_validate({"role": "system", "input": {}, name: "forged"})


def test_new_nullable_columns_preserve_legacy_ledger_and_repair_is_idempotent(tmp_path):
    app = _empty_app(tmp_path)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR, revision="20261018_002")
        db.session.execute(text("""INSERT INTO tool_invocations
            (invocation_id, tool_name, idempotency_key, caller_role, budget_scope, status,
             attempt, input_payload, output_payload, estimated_cost, created_at, updated_at)
            VALUES ('legacy', 'rewrite_prompt', 'legacy-key', 'creative', 'legacy', 'success',
                    1, '{}', '{}', 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""))
        db.session.commit()
        repaired = SchemaService.ensure_compatible_schema()
        assert {"tool_invocations.caller_agent", "tool_invocations.delegation_id"} <= set(repaired)
        assert not any(item.startswith("tool_invocations") for item in SchemaService.ensure_compatible_schema())
        db.session.commit()  # Release compatibility repair session before Alembic opens its own.
        upgrade(directory=MIGRATIONS_DIR)
        row = ToolInvocation.query.filter_by(invocation_id="legacy").one()
        assert row.estimated_cost == 3 and row.status == "success"
        assert row.caller_agent is None and row.delegation_id is None
        columns = {item["name"]: item for item in inspect(db.engine).get_columns("tool_invocations")}
        assert columns["caller_agent"]["nullable"] and columns["delegation_id"]["nullable"]
        db.session.remove()
        db.engine.dispose()


def test_direct_upgrade_from_previous_revision_adds_agent_columns(tmp_path):
    app = _empty_app(tmp_path)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR, revision="20261018_002")
        upgrade(directory=MIGRATIONS_DIR)
        columns = {item["name"] for item in inspect(db.engine).get_columns("tool_invocations")}
        assert {"caller_agent", "delegation_id"} <= columns
        db.session.remove()
        db.engine.dispose()


@pytest.mark.parametrize("injected", [{"caller_agent": "system"}, {"approved": True}, {"budget_limit": 999}])
def test_model_inputs_cannot_set_context(app_ctx, injected):
    run_id = make_run()
    registry = ToolRegistry()
    registry.register(spec(lambda data, ctx: data))
    with pytest.raises(AppError) as exc:
        registry.invoke("v3_probe", {"value": "x", **injected}, context(run_id))
    assert exc.value.code == "INVALID_INPUT"
    assert ToolInvocation.query.count() == 0


def test_scope_budget_overrides_larger_caller_limit(app_ctx):
    run_id = make_run(limit=3)
    registry = ToolRegistry()
    calls = []
    registry.register(spec(lambda data, ctx: calls.append(data) or data))
    with pytest.raises(AppError) as exc:
        registry.invoke("v3_probe", {}, context(run_id, budget_limit=1000))
    assert exc.value.code == "BUDGET_EXCEEDED" and calls == []
    assert ToolInvocation.query.one().status == "rejected"


@pytest.mark.parametrize("actual", [float("nan"), float("inf"), -1, True])
def test_invalid_settlement_never_refunds_or_marks_success(app_ctx, actual):
    run_id = make_run()
    registry = ToolRegistry()
    registry.register(spec(lambda data, ctx: data, settle=lambda data, output, ctx: actual))
    with pytest.raises(AppError) as exc:
        registry.invoke("v3_probe", {}, context(run_id))
    assert exc.value.code == "INVALID_COST_SETTLEMENT"
    row = ToolInvocation.query.one()
    assert row.status == "failed" and row.estimated_cost == 4
    assert BudgetGuard.spent(run_id) == 4


def test_actual_cost_overrun_is_preserved_and_stops_run_budget(app_ctx):
    run_id = make_run(limit=5)
    registry = ToolRegistry()
    registry.register(spec(lambda data, ctx: data, settle=lambda data, output, ctx: 7.5))
    with pytest.raises(AppError) as exc:
        registry.invoke("v3_probe", {}, context(run_id))
    assert exc.value.code == "BUDGET_SETTLEMENT_EXCEEDED"
    row = ToolInvocation.query.one()
    assert row.status == "failed" and row.estimated_cost == 7.5
    assert row.output_payload == {"value": "ok"}
    assert BudgetGuard.spent(run_id) == 7.5
    with pytest.raises(AppError) as next_error:
        registry.invoke("v3_probe", {"value": "next"}, context(run_id, agent_step=1))
    assert next_error.value.code == "BUDGET_EXCEEDED"


def test_concurrent_delegations_reserve_before_execution(app):
    with app.app_context():
        run_id = make_run(limit=5)
    start = Barrier(2)
    entered = Event()
    release = Event()
    executions = []
    registry = ToolRegistry()

    def handler(data, ctx):
        executions.append(ctx.delegation_id)
        entered.set()
        assert release.wait(15), "Test failed to release the admitted handler"
        return data

    registry.register(spec(handler))

    def invoke(delegation):
        with app.app_context():
            start.wait(timeout=15)
            try:
                return registry.invoke("v3_probe", {}, context(run_id, delegation_id=delegation))["status"]
            except AppError as error:
                return error.code
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(invoke, number) for number in (1, 2)]
        try:
            assert entered.wait(15)
            # Admission is committed before the handler. The other delegation
            # must be rejected even while the first result is still pending.
            from concurrent.futures import wait, FIRST_COMPLETED
            done, _pending = wait(futures, timeout=15, return_when=FIRST_COMPLETED)
            assert len(done) == 1
            assert next(iter(done)).result() == "BUDGET_EXCEEDED"
        finally:
            release.set()
        assert sorted(future.result(timeout=15) for future in futures) == ["BUDGET_EXCEEDED", "success"]
    with app.app_context():
        assert len(executions) == 1
        assert BudgetGuard.spent(run_id) == 4
        assert sorted(row.status for row in ToolInvocation.query.all()) == ["rejected", "success"]


@pytest.mark.config(AGENT_MODE_ENABLED=True)
@pytest.mark.parametrize("field,value", [("caller_agent", "producer"), ("delegation_id", 1), ("agent_step", 0)])
def test_public_api_rejects_agent_context_before_any_invocation(client, app_ctx, field, value):
    response = client.post("/api/skills/get_task_status/invoke", json={
        "role": "system", "input": {"job_id": "missing"}, field: value})
    assert response.status_code == 422
    assert "server-owned" in str(response.get_json())
    assert ToolInvocation.query.count() == 0


def test_public_schema_keeps_legacy_shape_and_non_agent_extras():
    payload = InvokeSkillSchema.model_validate({"role": "system", "input": {}, "legacy_extra": 1})
    assert payload.role == "system"
    assert set(payload.model_dump()) == {"role", "input", "approved", "idempotency_key", "budget_scope", "budget_limit"}
