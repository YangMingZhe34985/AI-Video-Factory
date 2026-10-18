"""Task center permissions, SQL pagination and side-effect-free queue projection."""
from copy import deepcopy
from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import event

from app.extensions import db
from app.models import (AgentPlanVersion, AgentRun, AgentShotTask, ApiTask, Job, JobDispatch,
                        JobNodeRun, TaskOutbox, Template, ToolInvocation)
from app.utils.time_utils import utc_now

pytestmark = pytest.mark.config(API_AUTH_REQUIRED=True, JWT_SECRET_KEY="task-center-test-secret-long-enough-for-hmac-256")


def token(owner):
    return {"Authorization": "Bearer " + create_access_token(identity=owner)}


def run(owner, key, status="producing", **snapshot):
    row = AgentRun(run_id="agent_" + key, owner_id=owner, request_key=key, status=status,
                   request={"text": "PRIVATE PROMPT must not be serialized"}, snapshot=snapshot)
    db.session.add(row)
    db.session.flush()
    return row


def job(key, status="running", config=None, **kwargs):
    row = Job(job_id="job_" + key, job_name=key, status=status, config=config or {},
              template_id=Template.query.filter_by(template_id="default").one().id, **kwargs)
    db.session.add(row)
    db.session.flush()
    return row


def link(row, agent):
    value = ToolInvocation(tool_name="animate_shot", idempotency_key="key_" + row.job_id,
        caller_role="production", budget_scope=agent.run_id, job_id=row.id, status="running",
        input_payload={"secret": "PRIVATE PROMPT"})
    db.session.add(value)
    db.session.flush()
    return value


def api(row, phase, *, branch="i2v", node=None, run_id=None, **kwargs):
    value = ApiTask(job_id=row.id, node_run_id=node.id if node else None,
        branch_key=branch, model_id="wan2.7-i2v", adapter_name="mock", status="running",
        queue_phase=phase, queue_generation=3, operation_key="op_" + row.job_id + "_" + branch + "_" + str(node.id if node else 0),
        request_payload={"_run_id": run_id} if run_id else {},
        provider_task_id="PRIVATE_PROVIDER_ID", queue_data={"token": "SECRET"},
        error_message="C:/private/path?api_key=SECRET", **kwargs)
    db.session.add(value)
    db.session.flush()
    return value


def version(agent, number=1, shots=None):
    value = AgentPlanVersion(run_id=agent.run_id, version=number, author="director",
        plan={"shots": shots or [{"shot_id": "s01", "transition_in": "cut", "motion": {"model_id": "wan2.7-i2v"}},
                                 {"shot_id": "s02", "transition_in": "tail_frame", "motion": {"model_id": "wan2.7-i2v"}}]},
        story_package={"title": "Safe title"}, check={})
    db.session.add(value)
    db.session.flush()
    return value


def shot(agent, ver, sid, row=None, attempt=1, status="running"):
    value = AgentShotTask(run_id=agent.run_id, plan_version=ver.version, target_type="video",
        target_id=sid, status=status, inputs_hash="a" * 64, attempt=attempt, job_id=row.job_id if row else None,
        error={"code": "SUBMISSION_UNKNOWN", "summary": "SECRET C:/path"} if status == "failed" else None)
    db.session.add(value)
    db.session.flush()
    return value


def data(response):
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def test_owner_isolation_shared_classic_and_no_child_duplicates(app_ctx, client):
    alice, bob = run("alice", "alice", plan={"title": "Alice film"}), run("bob", "bob", plan={"title": "Bob secret"})
    classic = job("shared")
    for agent in (alice, bob):
        row = job(agent.owner_id, config={"skill": {"budget_scope": agent.run_id},
            "agent_story_production": {"run_id": agent.run_id}})
        link(row, agent)
    job("upload", strategy="agent_upload")
    job("orphan", config={"agent_story_production": {}})
    job("bad_skill", config={"skill": {"budget_scope": "missing"}})
    job("orphan_marker", config={"agent_story_preview": {"run_id": "missing"}})
    db.session.commit()
    result = data(client.get("/api/task-center", headers=token("alice")))
    assert {(row["source"], row["id"]) for row in result["items"]} == {("agent", alice.run_id), ("workflow", classic.job_id)}
    assert result["total"] == sum(result["summary"].values()) == 2
    assert client.get("/api/task-center/agent/" + bob.run_id, headers=token("alice")).status_code == 404
    assert client.get("/api/task-center/workflow/job_bob", headers=token("alice")).status_code == 404
    assert data(client.get("/api/task-center?search=Bob", headers=token("alice")))["total"] == 0
    for forbidden in ("PRIVATE PROMPT", "SECRET", "Bob secret", "request_payload", "queue_data"):
        assert forbidden not in str(result)


def test_anonymous_requires_auth_even_with_agent_disabled(app_ctx, client):
    assert client.get("/api/task-center").status_code == 401


@pytest.mark.parametrize("query", ["page=0", "page=-1", "page=1.5", "per_page=101", "per_page=x", "source=admin", "state=failed", "search=" + "a" * 201])
def test_invalid_filters_return_422(app_ctx, client, query):
    assert client.get("/api/task-center?" + query, headers=token("alice")).status_code == 422


def test_pagination_stable_and_summary_ignores_state_filter(app_ctx, client):
    when = utc_now()
    for index in range(35):
        row = job("shared_" + str(index).zfill(3), status="success" if index < 5 else "queued")
        row.created_at = when
    other = run("bob", "hidden", status="queued")
    db.session.commit()
    first = data(client.get("/api/task-center?source=workflow&search=shared_&state=queued&per_page=7", headers=token("alice")))
    second = data(client.get("/api/task-center?source=workflow&search=shared_&state=queued&per_page=7&page=2", headers=token("alice")))
    assert first["total"] == 30 and first["summary"]["completed"] == 5
    assert len(first["items"]) == len(second["items"]) == 7
    assert not ({row["id"] for row in first["items"]} & {row["id"] for row in second["items"]})
    assert first["items"] == data(client.get("/api/task-center?source=workflow&search=shared_&state=queued&per_page=7", headers=token("alice")))["items"]
    assert data(client.get("/api/task-center?search=%", headers=token("alice")))["total"] == 0
    assert other.run_id not in str(first)


def test_approval_and_dependency_are_not_queued(app_ctx, client):
    agent = run("alice", "story", status="storyboard_approved")
    ver = version(agent)
    db.session.commit()
    result = data(client.get("/api/task-center/agent/" + agent.run_id, headers=token("alice")))
    assert result["item"]["state"] == "waiting"
    assert result["item"]["wait_reason"] == "user_authorization"
    assert all(row["stage"] == "awaiting_authorization" for row in result["children"])
    agent.status = "producing"
    db.session.commit()
    result = data(client.get("/api/task-center/agent/" + agent.run_id, headers=token("alice")))
    assert result["children"][1]["stage"] == "waiting_dependency"
    assert result["children"][1]["depends_on"] == ["s01"]
    assert not any(result["item"]["queue_counts"].values())


def test_latest_version_attempt_and_queue_generation_only(app_ctx, client):
    agent = run("alice", "versions")
    old = version(agent)
    old_job = job("old")
    link(old_job, agent)
    shot(agent, old, "s01", old_job, status="failed")
    api(old_job, "submit_unknown")
    current = version(agent, 2)
    retry_old = job("retry_old")
    link(retry_old, agent)
    shot(agent, current, "s01", retry_old, status="failed")
    api(retry_old, "submit_unknown")
    new_job = job("new")
    link(new_job, agent)
    shot(agent, current, "s01", new_job, attempt=2)
    active = api(new_job, "poll")
    db.session.add(TaskOutbox(event_key="stale", task_id=active.id, phase="submit", generation=1))
    db.session.commit()
    result = data(client.get("/api/task-center/agent/" + agent.run_id + "?per_page=1", headers=token("alice")))
    assert result["total"] == 2 and len(result["children"]) == 1
    assert result["children"][0]["attempt"] == 2
    assert result["item"]["queue_counts"]["unknown"] == 0
    assert result["item"]["queue_counts"]["provider_running"] == 1
    assert result["item"]["progress"] == {"unit": "video_shots", "completed": 0, "failed": 0, "total": 2}
    assert "PRIVATE_PROVIDER_ID" not in str(result)


def test_current_workflow_round_and_latest_node_attempt(app_ctx, client):
    row = job("rounds", config={"current_run": {"run_id": "jr_new", "enabled_nodes": ["submit_i2v", "poll_i2v"]}})
    for name, batch in (("old", "jr_old"), ("retry", "jr_new"), ("new", "jr_new")):
        node = JobNodeRun(job_id=row.id, node_key="submit_i2v", input_snapshot={"run_id": batch}, status="running")
        db.session.add(node)
        db.session.flush()
        api(row, "poll" if name == "new" else "submit_unknown", branch=name, node=node, run_id=batch)
    db.session.commit()
    result = data(client.get("/api/task-center/workflow/" + row.job_id, headers=token("alice")))
    assert result["total"] == 2
    assert result["item"]["queue_counts"]["provider_running"] == 1
    assert result["item"]["queue_counts"]["unknown"] == 0


@pytest.mark.parametrize("phase,stage,reason", [
    ("submit", "submit_waiting", "retry_backoff"), ("submit_active", "submitting", None),
    ("poll", "provider_running", "provider"), ("poll_active", "provider_running", "provider"),
    ("download", "download_waiting", "retry_backoff"), ("download_active", "downloading", None),
    ("submit_unknown", "unknown", "submission_unknown"),
])
def test_queue_phases_backoff_and_redaction(app_ctx, client, phase, stage, reason):
    row = job("phase")
    node = JobNodeRun(job_id=row.id, node_key="poll_i2v", status="running")
    db.session.add(node)
    db.session.flush()
    api(row, phase, node=node, queue_attempts=1, next_poll_at=utc_now() + timedelta(seconds=30))
    db.session.commit()
    result = data(client.get("/api/task-center/workflow/" + row.job_id, headers=token("alice")))
    assert result["item"]["stage"] == stage
    child = result["children"][0]
    assert child["stage"] == stage and child["wait_reason"] == reason
    assert child["next_check_at"]
    assert "eta" not in str(result).lower()
    assert all(word not in str(result) for word in ("SECRET", "PRIVATE_PROVIDER_ID", "C:/private", "lease_token", "request_payload"))


def test_local_delivery_and_unknown_worker_health(app_ctx, client):
    agent = run("alice", "delivery", status="editing", delivery={"stage": "checking"})
    db.session.commit()
    result = data(client.get("/api/task-center", headers=token("alice")))
    assert result["items"][0]["stage"] == "delivery_checking"
    assert result["worker_health"] == "unknown" and result["mq_admission_enabled"] is False


def test_gets_never_write_or_touch_redis_media_or_serialization(app_ctx, client, monkeypatch):
    from app.agent import production_view
    from app.api import agent as agent_api
    from app.queue import transport
    from app.services.storage_service import StorageService
    agent = run("alice", "readonly")
    version(agent)
    db.session.commit()
    def forbidden(*args, **kwargs):
        raise AssertionError("Task center must only read SQL")
    monkeypatch.setattr(production_view, "public_production", forbidden)
    monkeypatch.setattr(agent_api, "serialize", forbidden)
    monkeypatch.setattr(transport.Streams, "__init__", forbidden)
    monkeypatch.setattr(StorageService, "resolve", forbidden)
    statements = []
    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(db.engine, "before_cursor_execute", record)
    try:
        headers = token("alice")
        for path in ("/api/task-center", "/api/task-center/agent/" + agent.run_id, "/api/jobs/queue/status"):
            data(client.get(path, headers=headers))
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    assert not any(sql.lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE ")) for sql in statements)
    assert any("LIMIT" in sql.upper() and "UNION ALL" in sql.upper() for sql in statements)


def test_legacy_queue_status_owner_filtered_and_drain_visible(app_ctx, client):
    alice, bob = run("alice", "queue_a"), run("bob", "queue_b")
    rows = [job("shared_queue", status="queued"), job("own_queue", status="queued"), job("secret_queue", status="queued")]
    link(rows[1], alice)
    link(rows[2], bob)
    for row in rows:
        db.session.add(JobDispatch(job_id=row.id, version="v1", status="ready",
            command={"run_type": "run_full", "SECRET": "C:/private"}))
    db.session.commit()
    result = data(client.get("/api/jobs/queue/status", headers=token("alice")))
    assert result["mode"] == "redis" and result["queued_count"] == 2
    assert {row["job_id"] for row in result["queued"]} == {"job_shared_queue", "job_own_queue"}
    assert "job_secret_queue" not in str(result) and "SECRET" not in str(result)
    assert result["worker_health"] == "unknown"



def test_existing_pending_shot_uses_dependency_and_authorization(app_ctx, client):
    agent = run("alice", "pending")
    ver = version(agent)
    shot(agent, ver, "s01", status="pending")
    shot(agent, ver, "s02", status="pending")
    db.session.commit()
    result = data(client.get("/api/task-center/agent/" + agent.run_id, headers=token("alice")))
    assert result["children"][0]["state"] == "queued"
    assert result["children"][1]["stage"] == "waiting_dependency"
    assert result["children"][1]["state"] == "waiting"
    agent.status = "storyboard_approved"
    db.session.commit()
    result = data(client.get("/api/task-center/agent/" + agent.run_id, headers=token("alice")))
    assert all(child["stage"] == "awaiting_authorization" for child in result["children"])


def test_null_node_latest_api_hides_old_unknown_and_summary_matches(app_ctx, client):
    row = job("no_node")
    old = api(row, "submit_unknown")
    # Failed old generation is retained; new operation has no node linkage.
    db.session.add(ApiTask(job_id=row.id, branch_key="i2v", model_id="wan2.7-i2v",
        adapter_name="mock", status="running", queue_phase="poll", operation_key="new_op"))
    db.session.commit()
    result = data(client.get("/api/task-center", headers=token("alice")))
    assert result["items"][0]["state"] == "running"
    assert result["summary"]["attention"] == 0
    assert result["items"][0]["queue_counts"]["unknown"] == 0
    assert result["items"][0]["queue_counts"]["provider_running"] == 1


def test_current_unknown_overrides_parent_summary_without_cross_run_effect(app_ctx, client):
    agent = run("alice", "unknown_parent")
    healthy = run("alice", "healthy_parent")
    foreign = run("bob", "foreign_parent")
    ver = version(agent)
    child = job("unknown_child")
    link(child, agent)
    shot(agent, ver, "s01", child)
    api(child, "submit_unknown")
    shared = job("shared_unknown")
    api(shared, "submit_unknown")
    db.session.commit()
    result = data(client.get("/api/task-center?state=attention", headers=token("alice")))
    assert {row["id"] for row in result["items"]} == {agent.run_id, shared.job_id}
    assert result["summary"]["attention"] == 2 and result["summary"]["running"] == 1
    healthy_detail = data(client.get("/api/task-center/agent/" + healthy.run_id, headers=token("alice")))
    assert healthy_detail["item"]["state"] == "running"
    bob = data(client.get("/api/task-center", headers=token("bob")))
    assert next(item for item in bob["items"] if item["id"] == foreign.run_id)["state"] == "running"


def test_legacy_retry_snapshot_excludes_old_jobs(app_ctx, client):
    agent = run("alice", "legacy")
    old = job("legacy_old", config={"skill": {"tool_name": "remix_shot"}, "shot": {"shot_id": "s1"}})
    new = job("legacy_new", config={"skill": {"tool_name": "remix_shot"}, "shot": {"shot_id": "s1"}})
    link(old, agent)
    link(new, agent)
    api(old, "poll")
    api(new, "download")
    agent.snapshot = {"shots": {"s1": {"job_id": new.job_id}}}
    db.session.commit()
    result = data(client.get("/api/task-center/agent/" + agent.run_id, headers=token("alice")))
    assert result["item"]["queue_counts"]["provider_running"] == 0
    assert result["item"]["queue_counts"]["download_waiting"] == 1



def test_i2i_batch_members_are_distinct_and_unknown_is_not_hidden(app_ctx, client):
    row = job("batch")
    node = JobNodeRun(job_id=row.id, node_key="submit_i2i_test_image", status="running")
    db.session.add(node)
    db.session.flush()
    for index, phase in [(1, "submit_unknown"), (2, "poll")]:
        db.session.add(ApiTask(job_id=row.id, node_run_id=node.id, branch_key="i2i_test_image",
            model_id="wan2.7-image", adapter_name="mock", status="running", queue_phase=phase,
            request_payload={"test_index": index}, operation_key=f"batch-{index}"))
    db.session.commit()
    result = data(client.get("/api/task-center?state=attention", headers=token("alice")))
    assert result["total"] == result["summary"]["attention"] == 1
    assert result["items"][0]["queue_counts"]["unknown"] == 1
    assert result["items"][0]["queue_counts"]["provider_running"] == 1
    ApiTask.query.filter_by(operation_key="batch-1").one().queue_phase = "poll"
    db.session.commit()
    result = data(client.get("/api/task-center", headers=token("alice")))
    assert result["items"][0]["queue_counts"]["provider_running"] == 2


def test_legacy_unknown_revision_excluded_from_summary_and_detail(app_ctx, client):
    agent = run("alice", "legacy_unknown")
    old = job("old_unknown", config={"skill": {"tool_name": "produce_shot"}, "shot": {"shot_id": "s1"}})
    new = job("new_known", config={"skill": {"tool_name": "produce_shot"}, "shot": {"shot_id": "s1"}})
    link(old, agent)
    link(new, agent)
    api(old, "submit_unknown")
    api(new, "poll")
    agent.snapshot = {"shots": {"s1": {"job_id": new.job_id}}}
    db.session.commit()
    result = data(client.get("/api/task-center", headers=token("alice")))
    assert result["summary"]["attention"] == 0
    assert result["items"][0]["state"] == "running"
    assert result["items"][0]["queue_counts"]["unknown"] == 0
    assert result["items"][0]["queue_counts"]["provider_running"] == 1


def test_parent_query_compiles_for_mysql():
    from sqlalchemy.dialects import mysql
    from app.services.task_center_query import parent_query
    sql = str(parent_query("alice").select().compile(dialect=mysql.dialect()))
    assert "JSON_EXTRACT" in sql and "JSON_UNQUOTE" in sql and "UNION ALL" in sql



def test_classic_failed_dependency_path_is_terminal_attention(app_ctx, client):
    row = job("path_failure", status="partial_success")
    db.session.add(JobNodeRun(job_id=row.id, node_key="poll_i2v", status="path_failed"))
    db.session.commit()
    result = data(client.get("/api/task-center/workflow/" + row.job_id, headers=token("alice")))
    assert result["item"]["progress"]["failed"] == 1
    assert result["children"][0]["state"] == "attention"
    assert result["children"][0]["stage"] == "path_failed"


def test_agent_helper_job_progress_ignores_skipped_dag_nodes(app_ctx, client):
    agent = run("alice", "helper", status="awaiting_input")
    row = job("helper", status="success", config={"current_run": {"run_id": "jr_h", "enabled_nodes": ["reverse_prompts"]}})
    link(row, agent)
    for key, status in (("reverse_prompts", "success"), ("submit_i2v", "skipped"), ("submit_t2v", "skipped")):
        db.session.add(JobNodeRun(job_id=row.id, node_key=key, input_snapshot={"run_id": "jr_h"}, status=status))
    db.session.commit()
    item = next(item for item in data(client.get("/api/task-center?source=agent", headers=token("alice")))["items"]
                if item["id"] == agent.run_id)
    assert item["progress"] == {"unit": "workflow_nodes", "completed": 1, "failed": 0, "total": 1}
