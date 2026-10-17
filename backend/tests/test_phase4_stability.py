"""Offline release, cost and failure-injection acceptance; outbound HTTP is blocked."""
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from flask_jwt_extended import create_access_token

from app import create_app
from app.adapters.mock import MockAdapter
from app.agent.worker import AgentWorker, worker_lock, checkpoint_path
from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Job, ToolInvocation
from app.services.job_queue_service import JobQueueService
from app.services.node_runner import NodeRunner
from tests.test_agent_mvp import action, create, detail, finish, tick

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True)


def test_provider_accepts_then_response_is_lost_no_resubmission(app_ctx, client, monkeypatch):
    submissions = []
    def lost_reply(self, payload):
        submissions.append(self.model_id)  # Fake upstream accepted this request.
        raise AppError("API_TASK_FAILED", "Connection lost after provider acceptance", 502)
    monkeypatch.setattr(MockAdapter, "submit", lost_reply)
    run_id = create(client, shot_count=1)
    tick()  # Mock planning bypasses generation adapters.
    action(client, run_id, "approve")
    assert finish(client, run_id)["status"] == "failed"
    for _ in range(3):
        tick()
    assert len(submissions) == 1
    assert ApiTask.query.count() == 0  # No provider ID reached the application.
    metrics = client.get(f"/api/agent/runs/{run_id}/metrics").json["data"]
    assert metrics["estimated_spent"] == 14  # Unknown submission is not refunded.
    assert metrics["provider_task_count"] == 0  # Persisted tasks are not an HTTP count.


@pytest.mark.config(AGENT_MODE_ENABLED=True, API_AUTH_REQUIRED=True,
                    JWT_SECRET_KEY="phase4-test-key-longer-than-thirty-two", AGENT_ALLOWED_USERS="pilot")
def test_canary_admission_and_metrics_ownership(app_ctx, client):
    pilot = {"Authorization": "Bearer " + create_access_token(identity="pilot")}
    other = {"Authorization": "Bearer " + create_access_token(identity="other")}
    body = {"text": "生成一张猫的图片", "budget_limit": 14, "request_key": "pilot"}
    assert client.post("/api/agent/runs", json=body, headers=other).status_code == 403
    assert client.post("/api/agent/sources", headers=other).status_code == 403
    assert client.post("/api/skills/produce_shot/invoke", json={}, headers=other).status_code == 403
    response = client.post("/api/agent/runs", json=body, headers=pilot)
    assert response.status_code == 202
    run_id = response.json["data"]["run_id"]
    assert client.get(f"/api/agent/runs/{run_id}/metrics", headers=other).status_code == 404
    assert client.get(f"/api/agent/runs/{run_id}/metrics", headers=pilot).status_code == 200
    app_ctx.config["AGENT_ALLOWED_USERS"] = "other"
    # Existing admitted work and creation replay are not stranded by cohort changes.
    assert client.post("/api/agent/runs", json=body, headers=pilot).json["data"]["run_id"] == run_id
    from app.agent.graph_v2 import build_graph as build_graph_v2
    from langgraph.checkpoint.sqlite import SqliteSaver
    with worker_lock(), SqliteSaver.from_conn_string(str(checkpoint_path())) as saver:
        AgentWorker(None, build_graph_v2(saver)).tick()
    assert client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "reject"}, headers=pilot).status_code == 202
    with worker_lock(), SqliteSaver.from_conn_string(str(checkpoint_path())) as saver:
        AgentWorker(None, build_graph_v2(saver)).tick()


def test_drain_finish_disable_reenable_preserves_history_and_classic(app_ctx, client, h, source_video):
    run_id = create(client, shot_count=1)
    tick()
    app_ctx.config["AGENT_ACCEPT_NEW_RUNS"] = False
    assert create(client, shot_count=1) == run_id
    assert client.post("/api/agent/runs", json={"text": "cat", "request_key": "new"}).status_code == 503
    assert client.post("/api/agent/sources").status_code == 503
    action(client, run_id, "approve")
    assert finish(client, run_id)["status"] == "awaiting_delivery"
    action(client, run_id, "deliver")
    tick()
    assert detail(client, run_id)["status"] == "success"
    task_count = ApiTask.query.count()
    config = dict(app_ctx.config)
    config.update(AGENT_MODE_ENABLED=False, AUTO_REPAIR_SCHEMA=False)
    disabled = create_app("testing", config_overrides=config)
    with disabled.app_context():
        off = disabled.test_client()
        assert off.get("/api/agent/runs").status_code == 404
        assert off.get("/api/skills").status_code == 404
        assert off.get("/api/health").json["data"]["agent_mode"] is False
        assert h.run_full(h.make_job(source_video=source_video).job_id).status == "success"
        db.session.remove()
        db.engine.dispose()
    # Reopening the same DB/checkpoint with feature on replays no generation.
    tick()
    assert detail(client, run_id)["status"] == "success"
    assert ApiTask.query.count() == task_count + 2  # Only the classic job added tasks.


def test_cost_monitoring_counts_failed_reservations_excludes_rejections(app_ctx, client, monkeypatch):
    def fail(*args):
        raise AppError("API_TASK_FAILED", "Injected provider failure", 502)
    monkeypatch.setattr(NodeRunner, "_run_submit_first_frame_image", fail)
    run_id = create(client, shot_count=1, budget_limit=14)
    tick()
    action(client, run_id, "approve")
    assert finish(client, run_id)["status"] == "failed"
    db.session.add(ToolInvocation(tool_name="produce_shot", idempotency_key="rejected-over-budget",
                                  caller_role="production", budget_scope=run_id, estimated_cost=12,
                                  status="rejected"))
    db.session.commit()
    metrics = client.get(f"/api/agent/runs/{run_id}/metrics").json["data"]
    assert metrics["estimated_spent"] == 14
    assert metrics["remaining"] == 0
    assert metrics["by_tool"]["produce_shot"]["estimated_credits"] == 12
    assert metrics["invocation_statuses"]["rejected"] == 1
    assert "BUDGET_NEAR_LIMIT" in metrics["alerts"] and "SHOT_FAILED" in metrics["alerts"]
    assert metrics["provider_task_count"] == 0
    assert "not_provider_bill" in metrics["cost_basis"]


def test_failure_after_graph_commit_before_index_save_replays_no_paid_work(app_ctx, client, monkeypatch):
    run_id = create(client, shot_count=1)
    tick()
    action(client, run_id, "approve")
    original = AgentWorker._save
    def crash(row, values, error):
        raise RuntimeError("Injected crash after graph checkpoint before business index")
    monkeypatch.setattr(AgentWorker, "_save", staticmethod(crash))
    tick()
    assert detail(client, run_id)["status"] == "needs_attention"
    monkeypatch.setattr(AgentWorker, "_save", staticmethod(original))
    action(client, run_id, "resume")
    assert finish(client, run_id)["status"] == "awaiting_delivery"
    assert Job.query.count() == 1 and ApiTask.query.count() == 2
    assert detail(client, run_id)["estimated_spent"] == 14


def test_download_failure_can_rerun_poll_without_regenerating(app_ctx, h, source_video, monkeypatch):
    original = MockAdapter.download_outputs
    failed = False
    def fail_once(self, response, directory):
        nonlocal failed
        if self.output_kind == "video" and not failed:
            failed = True
            raise AppError("DOWNLOAD_FAILED", "Injected storage/download interruption", 502)
        return original(self, response, directory)
    monkeypatch.setattr(MockAdapter, "download_outputs", fail_once)
    job = h.run_full(h.make_job(source_video=source_video).job_id)
    assert job.status == "failed"
    task_ids = [task.provider_task_id for task in ApiTask.query.order_by(ApiTask.id)]
    assert len(task_ids) == 2
    h.run_node(job.job_id, "poll_i2v", force=True)
    assert [task.provider_task_id for task in ApiTask.query.order_by(ApiTask.id)] == task_ids
    assert "i2v_video" in h.artifact_types(h.reload_job(job.job_id))


def test_process_death_releases_single_worker_lock(app_ctx, tmp_path):
    lock = str(checkpoint_path()) + ".worker-lock"
    ready = tmp_path / "ready"
    code = "import sqlite3,sys,time,pathlib; c=sqlite3.connect(sys.argv[1]); c.execute('BEGIN IMMEDIATE'); pathlib.Path(sys.argv[2]).write_text('ready'); time.sleep(30)"
    process = subprocess.Popen([sys.executable, "-c", code, lock, str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        with pytest.raises(Exception, match="already owns"):
            with worker_lock():
                pass
        process.kill()
        process.wait(timeout=10)
        with worker_lock():
            pass
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_concurrent_duplicate_approval_only_one_command(app_ctx, client):
    run_id = create(client, shot_count=1)
    tick()
    barrier = threading.Barrier(4)
    def approve():
        barrier.wait(timeout=10)
        with app_ctx.test_client() as browser:
            return browser.post(f"/api/agent/runs/{run_id}/actions", json={"action": "approve"}).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(lambda _: approve(), range(4)))
    assert sorted(codes) == [202, 409, 409, 409]
    assert finish(client, run_id)["status"] == "awaiting_delivery"
    assert ApiTask.query.count() == 2
    assert detail(client, run_id)["estimated_spent"] == 14


@pytest.mark.config(AGENT_MODE_ENABLED=True, JOB_QUEUE_ENABLED=True, JOB_MAX_CONCURRENT_RUNS=2)
def test_burst_queue_respects_concurrency_and_delivers_every_job(app_ctx, h, source_video, monkeypatch, record_property):
    original = JobQueueService._execute_task
    lock = threading.Lock()
    active, peak = 0, 0
    def measured(task):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.02)
            return original(task)
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(JobQueueService, "_execute_task", staticmethod(measured))
    jobs = [h.make_job(source_video=source_video).job_id for _ in range(12)]
    started = time.monotonic()
    for job_id in jobs:
        JobQueueService.enqueue(job_id, "run_full")
    for job_id in jobs:
        assert h.wait_for_terminal(job_id).status == "success"
    assert 1 <= peak <= 2
    assert ApiTask.query.count() == 24
    record_property("evaluation", {"case": "12_job_burst", "jobs": 12, "success": 12,
                                    "peak_active_jobs": peak, "elapsed_seconds": time.monotonic() - started})
