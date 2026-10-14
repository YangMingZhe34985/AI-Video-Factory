"""Branch-level failure isolation, partial success and I2I sample isolation."""

from app.adapters.dashscope_i2v import DashScopeI2VAdapter
from app.adapters.dashscope_multimodal_image import DashScopeMultimodalSyncAdapter
from app.api import AppError


def _failing_submit(self, payload):
    raise AppError("API_TASK_FAILED", "injected i2v failure", 502)


def test_failed_branch_with_other_deliverable_is_partial_success(app_ctx, h, source_video, monkeypatch):
    monkeypatch.setattr(DashScopeI2VAdapter, "submit", _failing_submit)
    job = h.make_job(source_video=source_video, paths=("core", "first_i2v", "t2v"))
    job = h.run_full(job.job_id)

    states = h.latest_node_states(job)
    assert job.status == "partial_success"
    assert states["submit_i2v"] == "failed"
    # Only the failing branch is cascaded; the T2V branch and the manifest still run.
    assert states["poll_i2v"] == "path_failed"
    assert states["poll_t2v"] == "success"
    assert states["export_manifest"] == "success"
    assert "t2v_video" in h.artifact_types(job)
    assert "injected i2v failure" in job.error_summary


def test_failure_without_deliverable_marks_job_failed(app_ctx, h, source_video, monkeypatch):
    monkeypatch.setattr(DashScopeI2VAdapter, "submit", _failing_submit)
    job = h.run_full(h.make_job(source_video=source_video).job_id)

    states = h.latest_node_states(job)
    assert job.status == "failed"
    assert states["poll_first_frame_image"] == "success"
    assert states["poll_i2v"] == "path_failed"
    assert states["export_manifest"] == "success"


def test_i2i_single_sample_failure_is_isolated(app_ctx, h, source_video, monkeypatch):
    original_submit = DashScopeMultimodalSyncAdapter.submit
    calls = {"count": 0}

    def flaky_submit(self, payload):
        calls["count"] += 1
        if calls["count"] == 2:
            raise AppError("API_TASK_FAILED", "injected sample failure", 502)
        return original_submit(self, payload)

    monkeypatch.setattr(DashScopeMultimodalSyncAdapter, "submit", flaky_submit)
    job = h.make_job(
        source_video=source_video,
        paths=("core", "i2i_test"),
        job_config={"i2i_test": {"mode": "single_female", "test_count": 3}},
    )
    job = h.run_full(job.job_id)

    assert job.status == "success"
    items = {item["test_index"]: item for item in job.config["i2i_test_batch"]["items"]}
    assert items[2]["image_status"] == "failed"
    assert "injected sample failure" in items[2]["image_error"]
    assert items[1]["i2v_status"] == "success"
    assert items[3]["i2v_status"] == "success"
    assert h.artifact_types(job).count("i2i_test_video") == 2
