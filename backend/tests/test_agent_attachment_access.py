"""Private uploads cannot be republished through the classic Skills HTTP API."""

import io

import pytest
from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models import AgentRun, ApiTask, Artifact, ToolInvocation
from app.services.job_run_service import JobRunService
from tests.test_agent_attachments import image_file, video_file

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, API_AUTH_REQUIRED=True,
                               JWT_SECRET_KEY="attachment-skill-access-secret-over-32-bytes")


@pytest.fixture
def headers(app_ctx, monkeypatch):
    # Exercise validation, job creation and the ledger without starting workers.
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: {"status": "queued"})
    return {owner: {"Authorization": f"Bearer {create_access_token(identity=owner)}"}
            for owner in ("alice", "bob")}


def owned_upload(client, headers, stream, filename):
    response = client.post("/api/agent/attachments", headers=headers, data={"file": (stream, filename)})
    assert response.status_code == 201, response.json
    return response.json["data"]["attachment_id"]


@pytest.mark.parametrize("mode", ["analyze", "i2v", "r2v"])
def test_skill_references_require_upload_owner_and_leave_classic_inputs_shared(app_ctx, client, headers, video_file, mode):
    if mode == "analyze":
        artifact_id = owned_upload(client, headers["alice"], io.BytesIO(video_file.read_bytes()), "source.mp4")
        tool, data = "analyze_video", {"source_artifact_id": artifact_id}
    else:
        artifact_id = owned_upload(client, headers["alice"], image_file(), "portrait.png")
        data = {"mode": mode, "prompt": "The person smiles."}
        data["first_frame_artifact_id" if mode == "i2v" else "reference_artifact_ids"] = (
            artifact_id if mode == "i2v" else [artifact_id])
        tool = "generate_video"
    url = f"/api/skills/{tool}/invoke"
    payload = {"role": "system", "approved": True, "input": data}
    assert client.post(url, json=payload).status_code == 401
    denied = client.post(url, headers=headers["bob"], json=payload)
    assert denied.status_code == 404, denied.json
    assert denied.json["error"]["code"] == "ATTACHMENT_NOT_FOUND"
    assert ToolInvocation.query.count() == 0
    allowed = client.post(url, headers=headers["alice"], json=payload)
    assert allowed.status_code == 200, allowed.json
    assert ApiTask.query.count() == 0

    artifact = Artifact.query.filter_by(artifact_id=artifact_id).one()
    artifact.job.strategy = "default"
    db.session.commit()
    # Classic references and their pre-existing shared replay behavior are unchanged.
    assert client.post(url, headers=headers["bob"], json=payload).status_code == 200


def test_skill_replay_and_invocation_reads_check_original_private_references(app_ctx, client, headers, video_file):
    alice_source = owned_upload(client, headers["alice"], io.BytesIO(video_file.read_bytes()), "alice.mp4")
    bob_source = owned_upload(client, headers["bob"], io.BytesIO(video_file.read_bytes()), "bob.mp4")
    payload = {"role": "system", "idempotency_key": "private-analysis",
               "input": {"source_artifact_id": alice_source}}
    response = client.post("/api/skills/analyze_video/invoke", headers=headers["alice"], json=payload)
    assert response.status_code == 200, response.json
    invocation_id = response.json["data"]["invocation_id"]
    payload["input"]["source_artifact_id"] = bob_source
    replay = client.post("/api/skills/analyze_video/invoke", headers=headers["bob"], json=payload)
    assert replay.status_code == 404
    assert replay.json["error"]["code"] == "ATTACHMENT_NOT_FOUND"
    assert ToolInvocation.query.count() == 1

    url = f"/api/skills/invocations/{invocation_id}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers["bob"]).status_code == 404
    assert client.get(url, headers=headers["alice"]).status_code == 200
    status_payload = {"role": "system", "input": {"invocation_id": invocation_id}}
    assert client.post("/api/skills/get_task_status/invoke", headers=headers["bob"], json=status_payload).status_code == 404
    assert client.post("/api/skills/get_task_status/invoke", headers=headers["alice"], json=status_payload).status_code == 200


def test_skill_scope_and_scope_replay_cannot_impersonate_another_agent_run(app_ctx, client, headers):
    run = AgentRun(owner_id="alice", request_key="scope-owner", request={"goal": "A cat", "budget_limit": 100})
    db.session.add(run)
    db.session.commit()
    payload = {"role": "production", "approved": True, "budget_scope": run.run_id,
               "idempotency_key": "owned-run-image", "input": {"prompt": "A cat"}}
    denied = client.post("/api/skills/generate_image/invoke", headers=headers["bob"], json=payload)
    assert denied.status_code == 404
    assert denied.json["error"]["code"] == "AGENT_RUN_NOT_FOUND"
    assert ToolInvocation.query.count() == 0
    allowed = client.post("/api/skills/generate_image/invoke", headers=headers["alice"], json=payload)
    assert allowed.status_code == 200, allowed.json
    payload["budget_scope"] = "default"
    assert client.post("/api/skills/generate_image/invoke", headers=headers["bob"], json=payload).status_code == 404
    invocation_id = allowed.json["data"]["invocation_id"]
    assert client.get(f"/api/skills/invocations/{invocation_id}", headers=headers["bob"]).status_code == 404


def test_skill_reference_checks_do_not_interpret_prompt_text(app_ctx, client, headers):
    artifact_id = owned_upload(client, headers["alice"], image_file(), "portrait.png")
    payload = {"role": "production", "approved": True,
               "input": {"prompt": f'A cat next to a sign saying "source_artifact_id: {artifact_id}"'}}
    response = client.post("/api/skills/generate_image/invoke", headers=headers["bob"], json=payload)
    assert response.status_code == 200, response.json


def test_internal_agent_invocation_reads_use_scope_without_public_tool_schema(app_ctx, client, headers):
    run = AgentRun(owner_id="alice", request_key="director-owner", request={"goal": "A cat"})
    db.session.add(run)
    db.session.flush()
    invocation = ToolInvocation(tool_name="agent_director", caller_role="director", budget_scope=run.run_id,
                                idempotency_key="internal-director", status="success",
                                input_payload={"original_goal": "A cat"}, output_payload={"title": "A cat"})
    db.session.add(invocation)
    db.session.commit()
    url = f"/api/skills/invocations/{invocation.invocation_id}"
    assert client.get(url, headers=headers["alice"]).status_code == 200
    denied = client.get(url, headers=headers["bob"])
    assert denied.status_code == 404
    assert denied.json["error"]["code"] == "AGENT_RUN_NOT_FOUND"
    # Reading internal history does not expose that tool for external invocation.
    invoked = client.post("/api/skills/agent_director/invoke", headers=headers["alice"],
                          json={"role": "system", "input": {"original_goal": "A cat"}})
    assert invoked.status_code == 404
    assert invoked.json["error"]["code"] == "TOOL_NOT_FOUND"
