"""Owner-scoped Patch quotes and durable revision commands, without model calls."""
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.worker import AgentWorker
from app.extensions import db
from app.models import AgentDelegation, AgentPlanVersion, ModelRegistry, PlanNodeTask, ToolInvocation
from app.agents.workspace import write_workspace
from app.plans import runtime
from app.plans.patches import normalize_patch, patch_digest
from app.plans.patch_intent import save_assessment
from tests.patch_provenance_fixtures import add_proposal_evidence
from app.tools.spec import ToolContext
from app.services.job_run_service import JobRunService
from tests.test_v4_execution import setup
from tests.test_v4_plan_api import act, reviewable

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)


def reviewed_patch():
    run, version, registry = setup()
    run.owner_id = "local"
    runtime.begin(run, version, repair_budget_credits=5, registry=registry)
    task = runtime.latest_tasks(run)["image"]
    task.status = "failed"
    task.error = {"category": "content_policy", "submission_state": "not_submitted", "code": "CONTENT_POLICY"}
    run.status = "attention"
    director = AgentDelegation(run_id=run.run_id, agent="director", task="Review the minimal repair",
        request_key="review", credits_limit=10)
    db.session.add(director)
    db.session.commit()
    draft = normalize_patch({"base_version": 1, "reason": "Use a harmless prompt", "evidence_refs": [{"task_id": task.id}],
        "ops": [{"op": "update_inputs", "node_id": "image", "inputs": {"prompt": "A cat plays with yarn"}}]})
    ctx = ToolContext(role="director", caller_agent="director", delegation_id=director.id,
        budget_scope=run.run_id, budget_limit=100, idempotency_key="director-review")
    ref = write_workspace("reviewed_patch", "patch", draft, ctx)["workspace_ref"]
    record = {"patch_id": "patch-test", "draft": draft, "proposed_by": "repair", "status": "awaiting_approval",
        "review_delegation_id": director.id, "trigger": {"kind": "failure", "node_ids": ["image"], "task_ids": [task.id]},
        "director_review": {"delegation_id": director.id, "verdict": "approve", "base_version": 1,
            "reason": "Harmless wording only", "intent_preserved": True, "changed_elements": [], "draft_hash": patch_digest(draft), "request_key": "director-review", "review_ref": ref}}
    review = record["director_review"]
    review["assessment_ref"] = save_assessment(run, director, record["patch_id"], review)
    db.session.commit()
    add_proposal_evidence(run, record, author="repair")
    run.snapshot = {**run.snapshot, "v3_patches": {record["patch_id"]: record}}
    db.session.commit()
    return run, record


def quote(client, run, **body):
    return client.post(f"/api/agent/runs/{run.run_id}/patch-quote", json={"patch_id": "patch-test", **body})


def test_quote_is_read_only_exact_scope_and_public(app_ctx, client):
    run, _record = reviewed_patch()
    before = deepcopy(run.snapshot)
    counts = (AgentPlanVersion.query.count(), PlanNodeTask.query.count(), ToolInvocation.query.count())
    only = quote(client, run, scope="only")
    assert only.status_code == 200, only.json
    cascade = quote(client, run, scope="cascade")
    assert cascade.status_code == 200, cascade.json
    data = only.json["data"]
    assert data["quote_id"] != cascade.json["data"]["quote_id"]
    assert data["estimated_credits"]["total"] > 0 and data["automatic"]["eligible"]
    assert run.snapshot == before
    assert counts == (AgentPlanVersion.query.count(), PlanNodeTask.query.count(), ToolInvocation.query.count())
    assert not ({"decisions", "source_task_signatures", "compiled", "review_hash", "draft_hash"} & data.keys())
    view = client.get(f"/api/agent/runs/{run.run_id}").json["data"]
    assert view["patches"][0]["diff_summary"] == [{"op": "update_inputs", "node_id": "image", "fields": ["prompt"]}]
    change = view["patches"][0]["diff_preview"][0]
    assert change["before"] == {"prompt": "A happy orange cat"}
    assert change["after"] == {"prompt": "A cat plays with yarn"}
    assert view["repair_budget"] == {"limit": 5, "committed": 0, "remaining": 5}


def test_quote_and_action_reject_forged_scope_stale_or_foreign(app_ctx, client):
    run, _record = reviewed_patch()
    data = quote(client, run).json["data"]
    assert quote(client, run, decisions={}).status_code == 422
    assert quote(client, run, scope="all").status_code == 422
    response = act(client, run, "approve_patch", "bad-scope", patch_id="patch-test", quote_id=data["quote_id"], scope="cascade")
    assert response.status_code == 409
    assert run.command is None
    assert act(client, run, "approve_patch", "forged", patch_id="patch-test", quote_id=data["quote_id"], scope="only", automatic=True).status_code == 422
    run.owner_id = "foreign"
    db.session.commit()
    assert quote(client, run).status_code == 404
    assert act(client, run, "approve_patch", "foreign", patch_id="patch-test", quote_id=data["quote_id"], scope="only").status_code == 404


def test_patch_approval_admission_is_durable_and_idempotent(app_ctx, client):
    run, _record = reviewed_patch()
    data = quote(client, run).json["data"]
    body = {"patch_id": "patch-test", "quote_id": data["quote_id"], "scope": "only"}
    response = act(client, run, "approve_patch", "once", **body)
    assert response.status_code == 202, response.json
    assert response.json["data"]["action_pending"]
    assert run.status == "understanding" and run.command["admitted_from_status"] == "attention"
    before = deepcopy(run.command)
    assert act(client, run, "approve_patch", "once", **body).status_code == 202
    assert run.command == before
    assert act(client, run, "reject_patch", "once", **body).status_code == 409
    assert AgentPlanVersion.query.count() == 1


@pytest.mark.parametrize("message", ["", "   "])
def test_revision_needs_meaningful_text(app_ctx, client, message):
    run, _root, _ref = reviewable()
    assert act(client, run, "revise_plan", "blank", plan_version=1, message=message).status_code == 422
    assert run.command is None


def test_revision_requires_exact_version_and_does_not_reset_limits(app_ctx, client):
    run, root, _ref = reviewable()
    root.steps, root.llm_calls = 7, 3
    db.session.commit()
    started = root.started_at
    assert act(client, run, "revise_plan", "stale", plan_version=2, message="请改为蓝色背景").status_code == 409
    assert act(client, run, "revise_plan", "gate", plan_version=1, message="请改", gate_node_id="image").status_code == 409
    response = act(client, run, "revise_plan", "edit", plan_version=1, message="请改为蓝色背景")
    assert response.status_code == 202, response.json
    assert (root.steps, root.llm_calls, root.started_at) == (7, 3, started)
    assert ToolInvocation.query.filter_by(tool_name="agent_chat").count() == 0


def test_unknown_submission_blocks_revision_and_approval(app_ctx, client):
    run, _record = reviewed_patch()
    task = runtime.latest_tasks(run)["image"]
    task.error = {"category": "submit_unknown", "submission_state": "unknown"}
    db.session.commit()
    assert act(client, run, "revise_plan", "unknown", plan_version=1, message="重新生成").status_code == 409
    assert run.command is None


def test_worker_patch_approval_replay_keeps_one_version_and_job(app_ctx, client, monkeypatch):
    run, _record = reviewed_patch()
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    data = quote(client, run).json["data"]
    body = {"patch_id": "patch-test", "quote_id": data["quote_id"], "scope": "only"}
    assert act(client, run, "approve_patch", "approve", **body).status_code == 202
    worker = AgentWorker(None, None, v3_saver=InMemorySaver())
    worker.advance(run.run_id)
    assert run.status == "awaiting_result_review", run.error
    assert AgentPlanVersion.query.count() == 2
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 1
    assert act(client, run, "approve_patch", "replay-new-key", **body).status_code == 202
    worker.advance(run.run_id)
    assert AgentPlanVersion.query.count() == 2
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 1


def test_reject_patch_preserves_failed_plan_and_is_replayable(app_ctx, client):
    run, _record = reviewed_patch()
    data = quote(client, run).json["data"]
    body = {"patch_id": "patch-test", "quote_id": data["quote_id"], "scope": "only"}
    assert act(client, run, "reject_patch", "reject-patch", **body).status_code == 202
    worker = AgentWorker(None, None, v3_saver=InMemorySaver())
    worker.advance(run.run_id)
    assert run.status == "attention", run.error
    assert runtime.latest_tasks(run)["image"].status == "failed"
    assert AgentPlanVersion.query.count() == 1
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 0
    assert act(client, run, "reject_patch", "replay-rejection", **body).status_code == 202
    worker.advance(run.run_id)
    assert run.status == "attention"
    assert act(client, run, "approve_patch", "cannot-revive", **body).status_code == 409


def test_quote_drift_after_admission_can_be_requoted_without_cancelling_run(app_ctx, client):
    run, _record = reviewed_patch()
    old = quote(client, run).json["data"]
    assert act(client, run, "approve_patch", "old", patch_id="patch-test", quote_id=old["quote_id"], scope="only").status_code == 202
    model = ModelRegistry.query.filter_by(model_id="wan2.6-image").one()
    model.capabilities = {**model.capabilities, "pricing": {"unit": "image", "credits_per_unit": 3}}
    db.session.commit()
    AgentWorker(None, None, v3_saver=InMemorySaver()).advance(run.run_id)
    assert run.status == "attention" and run.error["code"] == "PATCH_QUOTE_CHANGED"
    assert run.command is None
    assert AgentPlanVersion.query.count() == 1
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 0
    fresh = quote(client, run).json["data"]
    assert fresh["quote_id"] != old["quote_id"]
    response = act(client, run, "approve_patch", "fresh", patch_id="patch-test", quote_id=fresh["quote_id"], scope="only")
    assert response.status_code == 202, response.json


def test_patch_reason_projection_hides_local_paths(app_ctx, client):
    run, record = reviewed_patch()
    record["draft"]["reason"] = "参考 C:\\private\\source.mp4 修订"
    record["director_review"]["reason"] = "Reviewed C:\\private\\source.mp4"
    run.snapshot = {**run.snapshot, "v3_patches": {"patch-test": record}}
    db.session.commit()
    view = client.get(f"/api/agent/runs/{run.run_id}")
    assert view.status_code == 200
    assert "private" not in view.get_data(as_text=True)


def test_invalid_initial_approval_never_occupies_inbox(app_ctx, client, monkeypatch):
    run, _root, _ref = reviewable(gate="preview")
    assert act(client, run, "approve_plan", "over-budget", plan_version=1, repair_budget_credits=1000).status_code == 402
    assert run.command is None and run.status == "awaiting_plan_review"
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    assert act(client, run, "approve_plan", "valid", plan_version=1).status_code == 202
    worker = AgentWorker(None, None, v3_saver=InMemorySaver())
    worker.advance(run.run_id)
    assert run.status == "awaiting_gate"
    assert act(client, run, "approve_gate", "unknown-gate", plan_version=1, gate_node_id="missing").status_code == 409
    assert run.command is None
    assert act(client, run, "approve_gate", "valid-gate", plan_version=1, gate_node_id="image").status_code == 202
