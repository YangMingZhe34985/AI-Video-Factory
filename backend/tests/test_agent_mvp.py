"""Phase 2 acceptance: real LangGraph/checkpointer + classic DAG, mocked providers."""

import time
import zipfile
from copy import deepcopy

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.graph import build_graph
from app.agent.worker import AgentWorker, checkpoint_path, worker_lock
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ApiTask, Artifact, Job, ToolInvocation
from app.services.job_run_service import JobRunService
from app.services.node_runner import NodeRunner
from app.services.workflow_service import WorkflowService
from app.services.storage_service import StorageService
from tests.helpers import legacy_agent_run

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True)


def tick():
    # Rebuild the graph and reconnect each time: nothing depends on in-memory state.
    with worker_lock(), SqliteSaver.from_conn_string(str(checkpoint_path())) as saver:
        AgentWorker(build_graph(saver)).tick()
    db.session.expire_all()


def create(client, **overrides):
    return legacy_agent_run(**overrides).run_id


def detail(client, run_id):
    return client.get(f"/api/agent/runs/{run_id}").json["data"]


def action(client, run_id, name, **kwargs):
    response = client.post(f"/api/agent/runs/{run_id}/actions", json={"action": name, **kwargs})
    assert response.status_code == 202, response.json
    return response


def finish(client, run_id):
    for _ in range(200):
        tick()
        result = detail(client, run_id)
        if result["status"] != "producing":
            return result
        time.sleep(0.05)
    pytest.fail("Agent did not leave producing state")


def test_goal_to_approval_generation_preview_and_package(app_ctx, client):
    run_id = create(client)
    tick()
    planned = detail(client, run_id)
    assert planned["status"] == "awaiting_approval", planned
    assert planned["estimated_spent"] == 2
    assert Job.query.count() == 0  # No paid generation before approval.
    assert len(planned["snapshot"]["plan"]["shots"]) == 3
    plan = deepcopy(planned["snapshot"]["plan"])
    plan["shots"][0]["first_frame_prompt"] = "用户确认的橘猫特写"
    action(client, run_id, "approve", plan=plan)
    assert client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "approve"}).status_code == 409
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert result["summary"] == {"total": 3, "success": 3, "failed": 0, "pending": 0}
    assert result["estimated_spent"] == 38
    assert len(result["snapshot"]["shots"]) == 3
    assert result["snapshot"]["plan"]["shots"][0]["first_frame_prompt"] == "用户确认的橘猫特写"
    count = ApiTask.query.count()
    tick()
    assert ApiTask.query.count() == count
    action(client, run_id, "deliver")
    tick()
    delivered = detail(client, run_id)
    assert delivered["status"] == "success", delivered
    assert len(delivered["snapshot"]["packages"]) == 3
    for package in delivered["snapshot"]["packages"]:
        artifact = Artifact.query.filter_by(artifact_id=package["artifact_id"]).one()
        with zipfile.ZipFile(StorageService.resolve(artifact.file_path)) as archive:
            assert any(name.startswith("final/") and name.endswith(".mp4") for name in archive.namelist())
        assert client.get(package["download_url"]).status_code == 200


def test_partial_failure_keeps_other_shots_and_packages(app_ctx, client, monkeypatch):
    original = NodeRunner._run_submit_first_frame_image

    def fail_second(self, job, node, node_run):
        if job.config.get("shot", {}).get("shot_id") == "shot_2":
            raise AppError("API_TASK_FAILED", "Injected image failure", 502)
        return original(self, job, node, node_run)

    monkeypatch.setattr(NodeRunner, "_run_submit_first_frame_image", fail_second)
    run_id = create(client)
    tick()
    action(client, run_id, "approve")
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert result["summary"]["success"] == 2
    assert result["summary"]["failed"] == 1
    assert result["snapshot"]["shots"]["shot_2"]["error"]
    action(client, run_id, "deliver")
    tick()
    result = detail(client, run_id)
    assert result["status"] == "partial_success"
    assert len(result["snapshot"]["packages"]) == 2


def test_duplicate_create_reject_and_request_validation(app_ctx, client):
    run_id = create(client)
    assert create(client) == run_id
    assert AgentRun.query.count() == 1
    deprecated = client.post("/api/agent/runs", json={"goal": "different", "request_key": "demo"})
    assert deprecated.status_code == 422
    assert deprecated.json["error"]["code"] == "DEPRECATED_FIELD"
    for body, expected in [
        ({"goal": "", "request_key": "a"}, 422),
        ({"goal": "cat", "request_key": "a", "shot_count": 21}, 422),
        ({"text": "cat", "request_key": "a", "budget_limit": 2}, 402),
        ({"text": "cat", "request_key": "a", "approved": True}, 422),
        ({"text": "cat", "request_key": "a", "budget_limit": float("inf")}, 422),
    ]:
        assert client.post("/api/agent/runs", json=body).status_code == expected
    tick()
    plan = detail(client, run_id)["snapshot"]["plan"]
    plan["shots"][0]["video_params"] = {"arbitrary_tool": "execute"}
    assert client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "approve", "plan": plan}).status_code == 422
    action(client, run_id, "reject")
    tick()
    assert detail(client, run_id)["status"] == "cancelled"
    assert Job.query.count() == 0


def test_pending_job_recovery_and_checkpoint_replay_do_not_duplicate(app_ctx, client, monkeypatch):
    run_id = create(client, shot_count=1)
    tick()
    action(client, run_id, "approve")
    original = JobRunService.start
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: {})
    tick()
    assert Job.query.count() == 1
    assert detail(client, run_id)["status"] == "producing"
    monkeypatch.setattr(JobRunService, "start", original)
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert Job.query.count() == 1
    assert ApiTask.query.count() == 2
    assert ToolInvocation.query.filter_by(tool_name="produce_shot").count() == 1


def test_worker_lock_rejects_second_worker(app_ctx):
    with worker_lock():
        with pytest.raises(Exception, match="already owns"):
            with worker_lock():
                pass


def test_restart_resumes_persisted_provider_task_without_new_submission(app_ctx, client, monkeypatch):
    run_id = create(client, shot_count=1)
    tick()
    action(client, run_id, "approve")
    original = JobRunService.start
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: {})
    tick()
    job = Job.query.one()
    WorkflowService.run_node(job.job_id, "submit_first_frame_image")
    task = ApiTask.query.one()
    task_id = task.api_task_id
    # Simulate a crash after the provider task was persisted but before the
    # submitting node's success checkpoint; there is no surviving executor.
    task.node_run.status = "running"
    job.status = "running"
    db.session.commit()
    monkeypatch.setattr(JobRunService, "start", original)
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert ApiTask.query.filter_by(branch_key="first_frame_image").one().api_task_id == task_id
    assert ApiTask.query.count() == 2


def test_unknown_submit_outcome_stops_resubmission(app_ctx, client, monkeypatch):
    from app.models import JobNodeRun
    run_id = create(client, shot_count=1)
    tick()
    action(client, run_id, "approve")
    original = JobRunService.start
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: {})
    tick()
    job = Job.query.one()
    job.status = "running"
    db.session.add(JobNodeRun(job_id=job.id, node_key="submit_first_frame_image", status="running"))
    db.session.commit()
    monkeypatch.setattr(JobRunService, "start", original)
    result = finish(client, run_id)
    assert result["status"] == "failed"
    assert "unknown" in result["snapshot"]["shots"]["shot_1"]["error"]["summary"]
    assert ApiTask.query.count() == 0


def test_all_failed_is_terminal_and_preserves_errors(app_ctx, client, monkeypatch):
    def fail(*_args):
        raise AppError("API_TASK_FAILED", "Image provider unavailable", 502)
    monkeypatch.setattr(NodeRunner, "_run_submit_first_frame_image", fail)
    run_id = create(client, shot_count=2)
    tick()
    action(client, run_id, "approve")
    result = finish(client, run_id)
    assert result["status"] == "failed", result
    assert result["summary"]["failed"] == 2
    assert all(shot["error"] for shot in result["snapshot"]["shots"].values())


def test_stale_approval_after_checkpoint_does_not_approve_delivery(app_ctx, client):
    run_id = create(client, shot_count=1)
    tick()
    action(client, run_id, "approve")
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery"
    row = AgentRun.query.filter_by(run_id=run_id).one()
    row.status = "producing"
    row.command = {"action": "approve", "plan": result["snapshot"]["plan"]}
    db.session.commit()
    tick()
    assert detail(client, run_id)["status"] == "awaiting_delivery"
    assert ToolInvocation.query.filter_by(tool_name="package_project").count() == 0


def test_paid_tool_output_replay_after_graph_checkpoint_loss(app_ctx, client, monkeypatch):
    import app.agent.graph as graph_module
    original = graph_module.invoke_once
    crashed = False
    def crash_after_submission(registry, name, data, ctx):
        nonlocal crashed
        result = original(registry, name, data, ctx)
        if name == "produce_shot" and not crashed:
            crashed = True
            raise RuntimeError("Simulated crash after tool commit")
        return result
    monkeypatch.setattr(graph_module, "invoke_once", crash_after_submission)
    run_id = create(client, shot_count=1)
    tick()
    action(client, run_id, "approve")
    tick()
    assert detail(client, run_id)["status"] == "needs_attention"
    action(client, run_id, "resume")
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert Job.query.count() == 1
    assert ApiTask.query.count() == 2
    assert detail(client, run_id)["estimated_spent"] == 14


def test_real_planning_uses_chat_schema_not_mock(app_ctx, monkeypatch):
    from app.adapters.qwen_chat import QwenChatAdapter
    from app.agent.planning import DirectorInput, director
    from app.skills.spec import ToolContext
    app_ctx.config["MODEL_ADAPTER_MODE"] = "real"
    seen = []
    def submit(_self, payload):
        seen.append(payload)
        return {"json": {"title": "Provider plan", "objective": "cat", "visual_style": "ink", "story_arc": "enter and leave"}}
    monkeypatch.setattr(QwenChatAdapter, "submit", submit)
    brief = director(DirectorInput(goal="cat", shot_count=1), ToolContext(role="director"))
    assert brief.title == "Provider plan"
    assert seen[0]["response_format"] == {"type": "json_object"}


def test_worker_transport_does_not_retry_paid_posts(app_ctx):
    from app.adapters.base import BaseModelAdapter
    app_ctx.config["AGENT_WORKER_ACTIVE"] = True
    retry = BaseModelAdapter.http_session().get_adapter("https://").max_retries
    assert "POST" not in retry.allowed_methods
    app_ctx.config["AGENT_WORKER_ACTIVE"] = False
    assert "POST" in BaseModelAdapter.http_session().get_adapter("https://").max_retries.allowed_methods


def test_interrupted_free_packaging_can_resume_without_duplicate_artifacts(app_ctx, client, monkeypatch):
    from app.services.job_package_service import JobPackageService
    run_id = create(client, shot_count=1)
    tick()
    action(client, run_id, "approve")
    assert finish(client, run_id)["status"] == "awaiting_delivery"
    original = JobPackageService.create_or_refresh
    interrupted = False
    def crash(job):
        nonlocal interrupted
        result = original(job)
        if not interrupted:
            interrupted = True
            raise RuntimeError("Simulated packaging interruption")
        return result
    monkeypatch.setattr(JobPackageService, "create_or_refresh", crash)
    action(client, run_id, "deliver")
    tick()
    assert detail(client, run_id)["status"] == "needs_attention"
    count = Artifact.query.count()
    action(client, run_id, "resume")
    tick()
    assert detail(client, run_id)["status"] == "success"
    assert Artifact.query.count() == count
    assert detail(client, run_id)["estimated_spent"] == 14


def test_overdue_shot_does_not_block_other_deliverables(app_ctx, client, monkeypatch):
    from app.skills.tools import get_task_status
    original = JobRunService.start
    def hold_second(job_id, *args, **kwargs):
        job = Job.query.filter_by(job_id=job_id).one()
        if job.config.get("shot", {}).get("shot_id") != "shot_2":
            return original(job_id, *args, **kwargs)
        return {}
    monkeypatch.setattr(JobRunService, "start", hold_second)
    monkeypatch.setattr(get_task_status, "_overdue", lambda invocation, terminal: (
        not terminal and invocation.input_payload.get("shot_id") == "shot_2"
    ))
    run_id = create(client)
    tick()
    action(client, run_id, "approve")
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert result["summary"]["success"] == 2
    assert result["snapshot"]["shots"]["shot_2"]["error"]["code"] == "TASK_OVERDUE"
    action(client, run_id, "deliver")
    tick()
    assert detail(client, run_id)["status"] == "partial_success"
    assert len(detail(client, run_id)["snapshot"]["packages"]) == 2


@pytest.mark.config(AGENT_MODE_ENABLED=False)
def test_agent_disabled_routes_and_classic_health(client):
    assert client.get("/api/agent/runs").status_code == 404
    assert client.get("/api/health").json["data"]["agent_mode"] is False


@pytest.mark.config(AGENT_MODE_ENABLED=True, API_AUTH_REQUIRED=True, JWT_SECRET_KEY="test-agent-jwt-key-longer-than-32-bytes")
def test_agent_auth_and_session_ownership(app_ctx, client):
    from flask_jwt_extended import create_access_token
    assert client.get("/api/agent/runs").status_code == 401
    first = {"Authorization": f"Bearer {create_access_token(identity='first')}"}
    second = {"Authorization": f"Bearer {create_access_token(identity='second')}"}
    response = client.post("/api/agent/runs", headers=first, json={"text": "cat", "request_key": "same"})
    run_id = response.json["data"]["run_id"]
    assert client.get(f"/api/agent/runs/{run_id}", headers=second).status_code == 404
    assert client.post(f"/api/agent/runs/{run_id}/actions", headers=second, json={"action": "approve"}).status_code == 404
    assert client.get("/api/agent/runs", headers=second).json["data"]["items"] == []
