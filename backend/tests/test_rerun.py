"""Resume, restart batches and partial re-execution."""

from app.extensions import db
from app.models import ApiTask
from app.services.job_run_state_service import JobRunStateService
from app.services.workflow_service import WorkflowService


def test_second_run_skips_successful_nodes(app_ctx, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)
    first_run_count = len(h.node_runs(job, current_run_only=False))
    task_count = ApiTask.query.filter_by(job_id=job.id).count()

    job = h.run_full(job.job_id)

    assert job.status == "success"
    new_runs = h.node_runs(job, current_run_only=False)[first_run_count:]
    assert new_runs
    assert {run.status for run in new_runs} == {"skipped"}
    assert {(run.output_snapshot or {}).get("reason") for run in new_runs} == {"already_success"}
    # Nothing was resubmitted to the provider.
    assert ApiTask.query.filter_by(job_id=job.id).count() == task_count


def test_restart_creates_new_run_batch(app_ctx, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)
    first_batch = {item["artifact_id"] for item in h.artifacts(job)}

    nodes = [node.node_key for node in WorkflowService.list_nodes() if WorkflowService.is_node_enabled(job, node)]
    JobRunStateService.begin_restart(job, nodes)
    db.session.commit()
    job = h.run_full(job.job_id, force=True)

    assert job.status == "success"
    assert JobRunStateService.current_run_id(job)
    current = {item["artifact_id"] for item in h.artifacts(job)}
    history = {item["artifact_id"] for item in h.artifacts(job, include_history=True)}
    assert current.isdisjoint(first_batch)
    assert first_batch <= history
    assert "i2v_video" in h.artifact_types(job)


def test_run_from_reexecutes_downstream_nodes(app_ctx, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)
    i2v_tasks = ApiTask.query.filter_by(job_id=job.id, branch_key="i2v").count()

    job = h.run_from(job.job_id, "submit_i2v", force=True)

    assert job.status == "success"
    tail = [(run.node_key, run.status) for run in h.node_runs(job)][-3:]
    assert tail == [("submit_i2v", "success"), ("poll_i2v", "success"), ("export_manifest", "success")]
    assert ApiTask.query.filter_by(job_id=job.id, branch_key="i2v").count() == i2v_tasks + 1


def test_run_node_marks_job_partial_success(app_ctx, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)

    job = h.run_node(job.job_id, "poll_i2v", force=True)

    assert job.status == "partial_success"
    assert h.node_runs(job, "poll_i2v")[-1].status == "success"
