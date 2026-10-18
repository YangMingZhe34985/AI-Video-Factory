"""Production graph resumes admitted work after an interrupted action receipt."""

from copy import deepcopy

import pytest

from app.agent import production_actions as actions, production_engine as engine, production_graph
from app.agent.production_state import latest_tasks, usable_artifact
from app.extensions import db
from app.models import ToolInvocation
from app.skills.budget import BudgetGuard
from tests.test_production_actions import fixture, drive, priced
from tests.test_production_actions_safety import attention, price, retry_command, start
from tests.test_production_recovery import fail_submit_once, inline_jobs

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_MAX_SHOT_AUTO_REPAIRS=0)


def interrupted_retry(monkeypatch):
    calls = fail_submit_once(monkeypatch)
    run, version, registry = fixture(complete=False)
    start(run, version, registry)
    assert drive(run, registry) == "production_attention"
    attention(run)
    price(.5)
    quoted = priced(run, version, "s01", "retry")
    assert quoted["estimated_credits"]["only"] == 5
    command = {**retry_command(quoted), "command_id": "resume-interrupted-retry"}
    state = {"run_id": run.run_id, "status": "production_attention", "plan_version": version.version,
             "production_command": command}
    tick = production_graph.nodes(registry)["production_v2_tick"]
    original = actions._save_receipt
    def crash(row, key, **changes):
        if key == command["request_key"] and changes.get("status") == "completed":
            raise RuntimeError("crash after replacement start, before action completion receipt")
        return original(row, key, **changes)
    monkeypatch.setattr(actions, "_save_receipt", crash)
    with pytest.raises(RuntimeError, match="after replacement start"):
        tick(state)
    monkeypatch.setattr(actions, "_save_receipt", original)
    assert latest_tasks(run, version)["s01"].status == "running"
    assert run.snapshot["production_action_receipts"]["retry"]["status"] == "applying"
    assert run.snapshot["production"]["approved_shot_costs"]["s02"] == 2.5
    price(.75)
    return run, version, tick, state, calls


def test_expired_replayed_action_keeps_admitted_replacement_polling(app_ctx, inline_jobs, monkeypatch):
    run, version, tick, state, calls = interrupted_retry(monkeypatch)
    before = (len(calls), ToolInvocation.query.filter_by(tool_name="animate_shot").count(), BudgetGuard.spent(run.run_id))
    previous = deepcopy(latest_tasks(run, version)["s03"].artifact_ids)
    poll = engine._poll
    polls = []
    # Model an accepted external task whose completion becomes visible next tick.
    monkeypatch.setattr(engine, "_poll", lambda *args: polls.append(True))
    result = tick(state)
    assert result["production_error"]["code"] == "PRODUCTION_QUOTE_EXPIRED"
    assert result["status"] == "producing"
    assert polls == [True]
    assert result["production_command"] is None and result["last_command_id"] == state["production_command"]["command_id"]
    assert run.snapshot["production_action_receipts"]["retry"]["status"] == "completed"
    assert (len(calls), ToolInvocation.query.filter_by(tool_name="animate_shot").count(), BudgetGuard.spent(run.run_id)) == before
    monkeypatch.setattr(engine, "_poll", poll)
    final = tick({**state, **result})
    assert final["status"] == "production_attention"
    tasks = latest_tasks(run, version)
    assert usable_artifact(tasks["s01"])
    assert tasks["s02"].status == "failed" and tasks["s02"].error["code"] == "MODEL_PRICE_CHANGED"
    assert tasks["s03"].artifact_ids == previous
    assert not any(task.status in {"pending", "running"} for task in tasks.values())
    assert (len(calls), ToolInvocation.query.filter_by(tool_name="animate_shot").count(), BudgetGuard.spent(run.run_id)) == before
    actions._idle(run, version)  # The user can now review the blocked continuation.


@pytest.mark.parametrize("admitted", [False, True], ids=["approval-revoked", "production-disabled"])
def test_error_replay_does_not_resume_without_current_production_authorization(app_ctx, inline_jobs, monkeypatch, admitted):
    run, version, tick, state, calls = interrupted_retry(monkeypatch)
    if admitted:
        app_ctx.config["AGENT_STORY_PRODUCTION_ENABLED"] = False
    else:
        run.snapshot = {**run.snapshot, "production": {**run.snapshot["production"], "approved_version": None}}
        db.session.commit()
    monkeypatch.setattr(production_graph, "tick_production", lambda *_args: pytest.fail("Unapproved work resumed"))
    before = len(calls), BudgetGuard.spent(run.run_id)
    result = tick(state)
    assert result["status"] == "production_attention"
    assert result["production_error"]["code"] in {"PRODUCTION_DISABLED", "PRODUCTION_QUOTE_EXPIRED"}
    assert (len(calls), BudgetGuard.spent(run.run_id)) == before
