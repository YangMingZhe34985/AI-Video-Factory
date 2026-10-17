"""/api/skills is only exposed behind AGENT_MODE_ENABLED."""

import pytest

from app.services.job_run_service import JobRunService

SHOT = {"shot_id": "s1", "first_frame_prompt": "a cat sits", "i2v_prompt": "the cat jumps"}


def test_skills_api_is_absent_by_default(client):
    assert client.get("/api/skills").status_code == 404
    assert client.get("/api/health").json["data"]["agent_mode"] is False


@pytest.mark.config(AGENT_MODE_ENABLED=True)
def test_skills_api_lists_and_invokes_tools(client, app):
    assert client.get("/api/health").json["data"]["agent_mode"] is True

    listing = client.get("/api/skills")
    assert listing.status_code == 200
    assert len(listing.json["data"]["skills"]) == 11

    denied = client.post("/api/skills/produce_shot/invoke", json={"role": "production", "input": SHOT})
    assert denied.status_code == 403
    assert denied.json["error"]["code"] == "APPROVAL_REQUIRED"

    invoked = client.post(
        "/api/skills/produce_shot/invoke",
        json={"role": "production", "approved": True, "input": SHOT},
    )
    assert invoked.status_code == 200
    result = invoked.json["data"]
    job_id = result["output"]["job_id"]

    replay = client.post(
        "/api/skills/produce_shot/invoke",
        json={"role": "production", "approved": True, "input": SHOT},
    )
    assert replay.json["data"]["replayed"] is True
    assert replay.json["data"]["output"]["job_id"] == job_id

    with app.app_context():
        from tests import helpers

        helpers.wait_for_terminal(job_id)
    assert not JobRunService.is_running_in_thread(job_id)

    invocation = client.get(f"/api/skills/invocations/{result['invocation_id']}")
    assert invocation.status_code == 200
    assert invocation.json["data"]["job_public_id"] == job_id

    report = client.post(
        "/api/skills/get_task_status/invoke",
        json={"role": "director", "input": {"job_id": job_id}},
    )
    assert report.json["data"]["output"]["status"] == "success"


@pytest.mark.config(AGENT_MODE_ENABLED=True)
def test_skills_api_rejects_bad_requests(client):
    assert client.post("/api/skills/produce_shot/invoke", json={"role": "intern", "input": SHOT}).status_code == 422
    unknown = client.post("/api/skills/no_such_tool/invoke", json={"role": "system"})
    assert unknown.status_code == 404
    assert unknown.json["error"]["code"] == "TOOL_NOT_FOUND"
    assert client.get("/api/skills/invocations/tinv_missing").status_code == 404


@pytest.mark.config(AGENT_MODE_ENABLED=True, API_AUTH_REQUIRED=True)
def test_skills_api_requires_auth(client):
    response = client.get("/api/skills")
    assert response.status_code == 401
