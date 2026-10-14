"""REST surface smoke tests with JWT auth enabled."""

import io
import time
import zipfile

import pytest

from app.services.job_queue_service import JobQueueService
from app.services.job_run_service import JobRunService

TERMINAL_STATUSES = {"success", "failed", "partial_success", "cancelled"}

pytestmark = pytest.mark.config(API_AUTH_REQUIRED=True)


@pytest.fixture
def auth_headers(client):
    registered = client.post(
        "/api/auth/register", json={"username": "tester", "password": "secret123"}
    )
    assert registered.status_code == 201
    login = client.post("/api/auth/login", json={"username": "tester", "password": "secret123"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json['data']['access_token']}"}


def _wait_for_terminal(client, headers, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=headers).json["data"]["job"]
        queued = JobQueueService._running.get(job_id)
        busy = JobRunService.is_running_in_thread(job_id) or bool(queued and queued.is_alive())
        if job["status"] in TERMINAL_STATUSES and not busy:
            return job
        time.sleep(0.2)
    raise AssertionError(f"Job {job_id} did not finish within {timeout}s")


def _create_job_via_api(client, headers) -> str:
    response = client.post(
        "/api/jobs",
        headers=headers,
        data={
            "template_id": "default",
            "strategy": "workflow_selection",
            "source_video": (io.BytesIO(b"fake mp4 bytes"), "source.mp4"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 201, response.json
    assert response.json["success"] is True
    return response.json["data"]["job_id"]


def test_protected_routes_require_token(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json["data"]["app"] == "CineCrew"
    response = client.get("/api/jobs")
    assert response.status_code == 401
    assert response.json["success"] is False
    assert response.json["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/me",
        "/api/dashboard/summary",
        "/api/series",
        "/api/templates",
        "/api/templates/default",
        "/api/templates/default/prompts",
        "/api/prompts",
        "/api/workflow/nodes",
        "/api/models",
        "/api/models/by-task/i2v",
        "/api/artifacts",
        "/api/jobs",
        "/api/jobs/queue/status",
    ],
)
def test_read_endpoints_return_success_envelope(client, auth_headers, path):
    response = client.get(path, headers=auth_headers)
    assert response.status_code == 200, response.json
    assert response.json["success"] is True
    assert "data" in response.json


def test_validate_run_reports_required_inputs(client, auth_headers):
    response = client.post(
        "/api/workflow/validate-run",
        headers=auth_headers,
        json={"enabled_nodes": ["reverse_prompts", "rewrite_prompts"], "disabled_nodes": []},
    )
    assert response.status_code == 200
    required = [item["key"] for item in response.json["data"]["required_inputs"]]
    assert "source_video" in required


def _run_and_package(client, headers):
    job_id = _create_job_via_api(client, headers)

    started = client.post(f"/api/jobs/{job_id}/run-full", headers=headers, json={})
    assert started.status_code == 200
    job = _wait_for_terminal(client, headers, job_id)
    assert job["status"] == "success"

    artifacts = client.get(f"/api/jobs/{job_id}/artifacts", headers=headers).json["data"]["artifacts"]
    assert any(item["artifact_type"] == "i2v_video" for item in artifacts)

    events = client.get(f"/api/jobs/{job_id}/events", headers=headers)
    assert events.status_code == 200
    assert any(event["event_type"] == "JOB_SUCCESS" for event in events.json["data"]["events"])

    packaged = client.post(f"/api/jobs/{job_id}/package", headers=headers)
    assert packaged.status_code == 201
    download = client.get(packaged.json["data"]["download_url"])
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
        assert "package_manifest.json" in archive.namelist()
    return job_id


def test_create_run_and_package_job_without_queue(client, auth_headers):
    _run_and_package(client, auth_headers)


@pytest.mark.config(API_AUTH_REQUIRED=True, JOB_QUEUE_ENABLED=True)
def test_create_run_and_package_job_with_queue(client, auth_headers):
    _run_and_package(client, auth_headers)


def test_event_stream_replays_existing_events(client, auth_headers):
    job_id = _create_job_via_api(client, auth_headers)

    response = client.get(f"/api/jobs/{job_id}/stream", buffered=False)
    try:
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        first_chunk = next(iter(response.response))
    finally:
        response.close()
    text = first_chunk.decode() if isinstance(first_chunk, bytes) else first_chunk
    assert text.startswith("id: ")
    assert "JOB_CREATED" in text
