"""Review actions, worker execution and public Plan projections on isolated Mock."""
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.worker import AgentWorker
from app.agents.workspace import write_workspace
from app.extensions import db
from app.models import AgentRun, ToolInvocation
from app.plans.runtime import latest_tasks
from app.services.job_run_service import JobRunService
from app.services.task_center_service import task_detail
from app.tools import build_v3_registry
from app.tools.scripted_llm import ScriptedLLM
from tests.test_v3_workspace import brief, make_context, next_context
from tests.test_v4_execution import image_node

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)


def reviewable(*, gate=None):
    run, root, ctx = make_context(owner="local", text="生成一张猫的图片")
    write_workspace("brief", "brief", brief(), ctx)
    draft = {"title": "猫", "goal": "生成猫的图片", "nodes": [image_node(gate=gate)],
        "deliverables": [{"kind": "image", "node_id": "image", "output": "image"}]}
    ref = write_workspace("plan", "plan_draft", draft, next_context(ctx))["workspace_ref"]
    registry = build_v3_registry()
    output = registry.invoke("submit_plan", {"plan_ref": ref}, next_context(ctx))["output"]
    assert output["submitted"]
    return run, root, ref


def act(client, run, action, key, **data):
    return client.post(f"/api/agent/runs/{run.run_id}/actions", json={"action": action, "request_key": key, **data})


def test_plan_review_worker_and_acceptance_without_llm(app_ctx, client, monkeypatch):
    run, root, ref = reviewable()
    scripted = ScriptedLLM({})
    app_ctx.extensions["agent_v3_scripted_llm"] = scripted
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    result = client.get(f"/api/agent/runs/{run.run_id}").json["data"]
    assert result["status"] == "awaiting_plan_review"
    assert result["plan"]["plan_version"] == 1 and result["estimates"]["total_credits"] > 0
    assert result["summary"] == {"steps_total": 1, "steps_success": 0, "steps_failed": 0}
    assert "output_metadata" not in result["plan"]
    assert act(client, run, "approve_plan", "bad", plan_version=2).status_code == 409
    assert act(client, run, "approve_plan", "approve", plan_version=1).status_code == 202
    before = deepcopy(run.command)
    assert act(client, run, "approve_plan", "approve", plan_version=1).status_code == 202
    assert run.command == before
    worker = AgentWorker(None, None, v3_saver=InMemorySaver())
    worker.advance(run.run_id)
    assert run.status == "awaiting_result_review", run.error
    view = client.get(f"/api/agent/runs/{run.run_id}").json["data"]
    assert len(view["results"]) == 1
    assert view["planning_budget"]["spent"] == 0 < view["estimated_spent"]
    assert act(client, run, "approve_results", "accept", plan_version=1).status_code == 202
    worker.advance(run.run_id)
    assert run.status == "success" and scripted.calls == []
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 1
    center = task_detail("local", "agent", run.run_id, {})
    assert center["item"]["progress"] == {"unit": "plan_nodes", "completed": 1, "failed": 0, "total": 1}
    assert center["children"][0]["node_key"] == "generate_image"


def test_plan_gate_api_and_cancellation_stop_descendants(app_ctx, client, monkeypatch):
    run, _root, _ref = reviewable(gate="preview")
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    assert act(client, run, "approve_plan", "go", plan_version=1).status_code == 202
    worker = AgentWorker(None, None, v3_saver=InMemorySaver())
    worker.advance(run.run_id)
    assert run.status == "awaiting_gate"
    assert act(client, run, "approve_results", "early", plan_version=1).status_code == 409
    assert act(client, run, "approve_gate", "gate", plan_version=1, gate_node_id="image").status_code == 202
    worker.advance(run.run_id)
    assert run.status == "awaiting_result_review"
    assert act(client, run, "reject", "cancel").status_code == 202
    worker.advance(run.run_id)
    assert run.status == "cancelled"
    assert latest_tasks(run)["image"].status == "success"


def test_review_is_owner_scoped_and_context_is_not_client_authority(app_ctx, client):
    run, _root, _ref = reviewable()
    assert act(client, run, "approve_plan", "ctx", plan_version=1, plan_node_task_id=1).status_code == 422
    run.owner_id = "foreign"
    db.session.commit()
    assert client.get(f"/api/agent/runs/{run.run_id}").status_code == 404
    assert act(client, run, "approve_plan", "foreign", plan_version=1).status_code == 404


def test_producer_finish_needs_server_submission_receipt(app_ctx):
    run, root, ref = reviewable()
    from app.agents.runtime import _context
    ctx = _context(run, root, suffix="finish")
    result = build_v3_registry().invoke("finish", {"kind": "completed", "outcome": "plan_submitted",
        "message": "请审核计划", "plan_ref": ref}, ctx)
    assert result["output"]["status"] == "completed"
    assert run.status == "awaiting_plan_review"


def test_workspace_allows_future_refs_but_rejects_forged_artifact(app_ctx):
    run, _root, ctx = make_context(owner="local", text="猫")
    draft = {"title": "猫", "goal": "猫", "nodes": [image_node(), {**image_node("next"),
        "inputs": {"prompt": "cat", "reference_artifact_ids": [{"ref": "image.image"}]}}],
        "deliverables": [{"kind": "image", "node_id": "next", "output": "image"}]}
    value = write_workspace("plan", "plan_draft", draft, ctx)
    assert value["artifact_ids"] == []
    draft["nodes"][1]["inputs"]["reference_artifact_ids"] = [{"artifact": "foreign"}]
    from app.api import AppError
    with pytest.raises(AppError):
        write_workspace("plan", "plan_draft", draft, next_context(ctx))
