"""Durable approval boundaries with Mock generation and local media."""
from copy import deepcopy
import time

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.graph import build_graph as build_legacy_graph
from app.agent.graph_v2 import build_graph
from app.agent.worker import AgentWorker, checkpoint_path
from app.extensions import db
from app.models import AgentRun, ApiTask, ToolInvocation
from app.services.model_service import ModelService
from app.skills.budget import BudgetGuard
from app.utils.ids import new_id
from tests.test_transform_planning import video

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_AUTO_APPROVE_CREDITS=10000,
                               AGENT_VISION_MODEL="qwen3.7-plus")


def create(video):
    run = AgentRun(owner_id="local", request_key=new_id("graph"), request={"schema_version": 2,
        "text": "把这个视频再延长2秒，使用wan3.0系列", "budget_limit": 100, "attachment_ids": [video]})
    db.session.add(run); db.session.commit()
    return run


def advance(run):
    with SqliteSaver.from_conn_string(str(checkpoint_path())) as saver:
        AgentWorker(build_legacy_graph(saver), build_graph(saver)).advance(run.run_id)
    db.session.refresh(run)


def until(run, statuses):
    for _ in range(200):
        advance(run)
        if run.status in statuses:
            return run
        if run.status in {"needs_attention", "failed", "cancelled"}:
            pytest.fail(f"Unexpected {run.status}: {run.error} {run.snapshot}")
        time.sleep(.03)
    pytest.fail("Agent graph did not reach expected state")


def approve(client, run):
    plan = run.snapshot["plan"]
    response = client.post(f"/api/agent/runs/{run.run_id}/actions", json={"action": "approve", "plan": plan})
    assert response.status_code == 202, response.json
    return plan


def test_explicit_approval_then_one_output(app_ctx, video, client):
    run = until(create(video), {"awaiting_approval"})
    assert run.snapshot["plan"]["params"]["duration"] == 8
    assert not run.snapshot["approved"]
    assert ApiTask.query.filter_by(model_id="wan3.0-video").count() == 0
    approve(client, run)
    until(run, {"success"})
    assert len(run.snapshot["results"]) == 1 and run.snapshot["transform"]["approved"]
    assert ApiTask.query.filter_by(model_id="wan3.0-video").count() == 1
    cost = BudgetGuard.spent(run.run_id)
    advance(run)
    assert BudgetGuard.spent(run.run_id) == cost
    assert ApiTask.query.filter_by(model_id="wan3.0-video").count() == 1


def test_price_drift_after_api_admission_returns_to_approval(app_ctx, video, client):
    run = until(create(video), {"awaiting_approval"})
    old = approve(client, run)
    model = ModelService.get_model("wan3.0-video")
    caps = deepcopy(model.capabilities)
    caps["pricing"]["resolution_rates"]["720P"] *= 2
    model.capabilities = caps; db.session.commit()
    advance(run)
    assert run.status == "awaiting_approval"
    assert run.snapshot["plan_issues"][0]["code"] == "TRANSFORM_QUOTE_EXPIRED"
    assert run.command is None and ApiTask.query.filter_by(model_id="wan3.0-video").count() == 0
    response = client.post(f"/api/agent/runs/{run.run_id}/transform-quote", json={"plan": old})
    assert response.status_code == 200, response.json
    response = client.post(f"/api/agent/runs/{run.run_id}/actions", json={"action": "approve", "plan": response.json["data"]})
    assert response.status_code == 202, response.json
    until(run, {"success"})
    assert ApiTask.query.filter_by(model_id="wan3.0-video").count() == 1


def test_approval_receipt_survives_checkpoint_gap(app_ctx, video, client, monkeypatch):
    from app.agent import transform_policy
    run = until(create(video), {"awaiting_approval"})
    approve(client, run)
    original = transform_policy.approve
    def commit_then_crash(*args):
        original(*args)
        raise RuntimeError("Injected crash after relational approval")
    monkeypatch.setattr(transform_policy, "approve", commit_then_crash)
    advance(run)
    assert run.status == "needs_attention" and run.snapshot["transform"]["approved"]
    frozen = deepcopy(run.snapshot["transform"])
    monkeypatch.setattr(transform_policy, "approve", original)
    response = client.post(f"/api/agent/runs/{run.run_id}/actions", json={"action": "resume"})
    assert response.status_code == 202, response.json
    until(run, {"success"})
    assert run.snapshot["transform"] == frozen
    assert ToolInvocation.query.filter_by(tool_name="transform_video", budget_scope=run.run_id).count() == 1
    assert ApiTask.query.filter_by(model_id="wan3.0-video").count() == 1
