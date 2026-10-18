"""Real background recovery cannot finalize a replacement from an old Job state."""

from threading import Event

import pytest

from app.adapters.mock import MockAdapter
from app.agent import plan_versions as versions, production_engine as engine
from app.agent.production_state import latest_tasks, usable_artifact
from app.agent.production_view import public_production
from app.extensions import db
from app.models import ApiTask, Job, JobDispatch, ToolInvocation
from app.services.job_queue_service import JobQueueService
from app.services.job_run_service import JobRunService
from app.services.storage_service import StorageService
from app.skills.budget import BudgetGuard
from tests.test_production_recovery import prepared, settle

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
                               AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_MAX_SHOT_AUTO_REPAIRS=0)


@pytest.mark.parametrize("queued", [False, True], ids=["background-thread", "local-queue"])
def test_free_download_waits_for_actual_background_completion(app_ctx, monkeypatch, queued):
    run, version, registry = prepared(allowance=0)
    submit = MockAdapter.submit
    calls = []
    monkeypatch.setattr(MockAdapter, "submit", lambda self, payload: calls.append(payload) or submit(self, payload))
    with monkeypatch.context() as initial:
        initial.setattr(JobRunService, "start", JobRunService.run_inline)
        assert settle(run, registry) == "awaiting_video_review"
    old = latest_tasks(run, version)["s01"]
    job = Job.query.filter_by(job_id=old.job_id).one()
    api = ApiTask.query.filter_by(job_id=job.id).one()
    provider_id, invocation_id = api.provider_task_id, old.invocation_id
    path = StorageService.resolve(usable_artifact(old).file_path)
    path.unlink()
    versions.mark_stale(run, version.version, target_type="video", target_ids={"s01"})
    before = BudgetGuard.spent(run.run_id)
    entered, release = Event(), Event()
    app_ctx.config["JOB_QUEUE_ENABLED"] = queued
    original = JobQueueService._execute_task if queued else JobRunService._dispatch

    def blocked(*args):
        entered.set()
        assert release.wait(10), "Test did not release the real background Job"
        return original(*args)

    monkeypatch.setattr(JobQueueService if queued else JobRunService,
                        "_execute_task" if queued else "_dispatch", staticmethod(blocked))
    worker = None
    try:
        assert engine.retry_shot(run, old, registry, automatic=False)
        assert entered.wait(5)
        worker = (JobQueueService._running if queued else JobRunService._threads)[old.job_id]
        replacement = latest_tasks(run, version)["s01"]
        assert replacement.attempt == 2 and replacement.status == "running"
        # The old completed status can remain visible before run_node starts.
        # Neither it nor a previously failed status is a recovery completion.
        assert engine.tick_production(run, registry) == "producing"
        assert latest_tasks(run, version)["s01"].status == "running"
        assert run.snapshot["production_repairs"][str(old.id)]["status"] == "running"
    finally:
        release.set()
        if worker:
            worker.join(10)
            assert not worker.is_alive()
    db.session.expire_all()
    assert settle(run, registry) == "awaiting_video_review"
    current = latest_tasks(run, version)["s01"]
    assert current.attempt == 2 and current.invocation_id == invocation_id and current.job_id == old.job_id
    assert path.is_file() and usable_artifact(current)
    assert ApiTask.query.count() == 1 and api.provider_task_id == provider_id
    assert len(calls) == 1 and BudgetGuard.spent(run.run_id) == before
    assert public_production(run)["estimates"]["repair_spent_credits"] == 0
    assert run.snapshot["production_repairs"][str(old.id)]["status"] == "completed"
    assert ToolInvocation.query.filter_by(tool_name="recover_story_read").count() == 1


@pytest.mark.parametrize("owner", ["dispatch-ready", "dispatch-running", "poll_active", "download", "download_active"])
def test_durable_mq_read_ownership_prevents_old_terminal_finalization(app_ctx, monkeypatch, owner):
    run, version, registry = prepared(allowance=0)
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    assert settle(run, registry) == "awaiting_video_review"
    old = latest_tasks(run, version)["s01"]
    path = StorageService.resolve(usable_artifact(old).file_path)
    content = path.read_bytes()
    path.unlink()
    versions.mark_stale(run, version.version, target_type="video", target_ids={"s01"})
    before = BudgetGuard.spent(run.run_id)
    # Hold the accepted recovery between durable ingress and consumer completion.
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: None)
    assert engine.retry_shot(run, old, registry, automatic=False)
    job = Job.query.filter_by(job_id=old.job_id).one()
    api = ApiTask.query.filter_by(job_id=job.id).one()
    if owner.startswith("dispatch-"):
        dispatch = JobDispatch(job_id=job.id, version="recovery-test", command={"run_type": "run_node"},
                               status=owner.removeprefix("dispatch-"))
        db.session.add(dispatch)
    else:
        api.operation_key, api.queue_phase = "mock-recovery-read", owner
    db.session.commit()
    assert job.status == "success"  # The previous run's completed status.
    assert engine.tick_production(run, registry) == "producing"
    assert latest_tasks(run, version)["s01"].status == "running"
    assert run.snapshot["production_repairs"][str(old.id)]["status"] == "running"
    if owner.startswith("dispatch-"):
        dispatch.status = "done"
    else:
        api.queue_phase = "done"
    job.status = "partial_success"
    path.write_bytes(content)
    db.session.commit()
    assert settle(run, registry) == "awaiting_video_review"
    assert usable_artifact(latest_tasks(run, version)["s01"])
    assert ApiTask.query.count() == 1 and BudgetGuard.spent(run.run_id) == before
