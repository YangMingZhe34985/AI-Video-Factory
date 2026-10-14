"""JobRunService keeps the run-dispatch behaviour previously inlined in api/jobs.py."""

import pytest

from app.api import AppError
from app.services.job_run_service import JobRunService
from app.services.job_run_state_service import JobRunStateService


def test_start_runs_in_background_thread_when_queue_disabled(app_ctx, h, source_video):
    job = h.make_job(source_video=source_video)

    response = JobRunService.start(job.job_id, "run_full")

    assert response == {"job_id": job.job_id, "status": "running"}
    assert h.wait_for_terminal(job.job_id).status == "success"


@pytest.mark.config(JOB_QUEUE_ENABLED=True)
def test_start_enqueues_when_queue_enabled(app_ctx, h, source_video):
    job = h.make_job(source_video=source_video)

    response = JobRunService.start(job.job_id, "run_full")

    assert response["job_id"] == job.job_id
    assert response["status"] in {"queued", "running"}
    assert h.wait_for_terminal(job.job_id).status == "success"


def test_restart_opens_a_new_run_batch_in_thread_mode(app_ctx, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)
    assert JobRunStateService.current_run_id(job) is None

    JobRunService.start(job.job_id, "run_full", force=True, restart=True)

    job = h.wait_for_terminal(job.job_id)
    assert job.status == "success"
    assert JobRunStateService.current_run_id(job)


def test_run_inline_executes_synchronously(app_ctx, h, source_video):
    job = h.make_job(source_video=source_video)

    JobRunService.run_inline(job.job_id)

    assert h.reload_job(job.job_id).status == "success"


def test_run_from_disabled_node_is_rejected(app_ctx, h, source_video):
    job = h.make_job(source_video=source_video)

    with pytest.raises(AppError) as exc:
        JobRunService.start(job.job_id, "run_from", node_key="submit_t2v")

    assert (exc.value.code, exc.value.status_code) == ("NODE_DISABLED", 400)


def test_run_node_with_unmet_dependencies_is_rejected(app_ctx, h, source_video):
    job = h.make_job(source_video=source_video)

    with pytest.raises(AppError) as exc:
        JobRunService.start(job.job_id, "run_node", node_key="submit_i2v")

    assert exc.value.code == "DEPENDENCY_MISSING"
    assert "poll_first_frame_image" in exc.value.payload["missing"]


def test_unknown_job_is_rejected(app_ctx):
    with pytest.raises(AppError) as exc:
        JobRunService.start("job_missing", "run_full")

    assert (exc.value.code, exc.value.status_code) == ("JOB_NOT_FOUND", 404)


def test_api_run_routes_keep_their_error_contract(app_ctx, client, h, source_video):
    job = h.make_job(source_video=source_video)

    response = client.post(f"/api/jobs/{job.job_id}/run-from", json={"node_key": "submit_t2v"})
    assert response.status_code == 400
    assert response.json["error"]["code"] == "NODE_DISABLED"

    response = client.post(f"/api/jobs/{job.job_id}/run-node", json={"node_key": "submit_i2v"})
    assert response.status_code == 400
    assert response.json["error"]["code"] == "DEPENDENCY_MISSING"

    assert client.post("/api/jobs/job_missing/run-full", json={}).status_code == 404
