"""Offline queue acceptance: real SQL transactions, no provider network access."""
from datetime import timedelta

import pytest

from app.adapters.mock import MockAdapter
from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Artifact, Job, JobDispatch, TaskOutbox
from app.queue.dispatch import dispatch_once
from app.queue.execution import process_event, recover_expired
from app.queue.state import claim, enqueue
from app.services.job_run_service import JobRunService
from app.utils.time_utils import utc_now

pytestmark = pytest.mark.config(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True, WORKFLOW_MAX_PARALLEL_NODES=1,
                               AGENT_MODE_ENABLED=True)


def step():
    JobDispatch.query.filter_by(status="ready").update({"available_at": utc_now()})
    db.session.commit()
    dispatch_once()
    TaskOutbox.query.filter_by(consumed_at=None).update({"available_at": utc_now()})
    db.session.commit()
    ids = [event.id for event in TaskOutbox.query.filter_by(consumed_at=None).all()]
    for event_id in ids:
        process_event(event_id)
    db.session.expire_all()


def drain(job_id, limit=60):
    for _ in range(limit):
        step()
        job = Job.query.filter_by(job_id=job_id).one()
        if job.status in {"success", "partial_success", "failed", "cancelled"}:
            return job
    pytest.fail(f"MQ job did not finish: {job.status}; tasks=" + repr([
        (t.branch_key, t.queue_phase, t.error_message) for t in ApiTask.query.all()]))


def test_classic_shared_queue_end_to_end_and_local_rerun(app_ctx, h, source_video, monkeypatch):
    submitted = []
    original = MockAdapter.submit
    def counted(self, payload):
        submitted.append(self.model_id)
        return original(self, payload)
    monkeypatch.setattr(MockAdapter, "submit", counted)
    job = h.make_job(source_video, paths=("core", "first_i2v", "t2v", "r2v_flash"))
    assert JobRunService.start(job.job_id, "run_full")["queue"] == "redis"
    assert ApiTask.query.count() == 0  # HTTP ingress never calls a provider.
    result = drain(job.job_id)
    assert result.status == "success", result.error_summary
    assert {"i2v_video", "t2v_video", "r2v_flash_video"} <= set(h.artifact_types(result))
    count = len(submitted)
    events = [event.id for event in TaskOutbox.query.all()]
    for event_id in events:
        process_event(event_id)  # Duplicate messages including old generations.
    assert len(submitted) == count
    video_count = Artifact.query.filter_by(artifact_type="i2v_video").count()
    JobRunService.start(job.job_id, "run_node", "submit_i2v", force=True)
    assert drain(job.job_id).status == "partial_success"
    JobRunService.start(job.job_id, "run_node", "poll_i2v", force=True)
    assert drain(job.job_id).status == "partial_success"
    assert Artifact.query.filter_by(artifact_type="i2v_video").count() == video_count + 1
    assert len(submitted) == count + 1


def test_outbox_rollback_and_duplicate_claim(app_ctx, h):
    job = h.make_job(paths=())
    task = ApiTask(job_id=job.id, branch_key="t2v", model_id="mock", adapter_name="mock",
                   queue_generation=0, request_payload={}, queue_data={"generation": True})
    db.session.add(task)
    db.session.flush()
    enqueue(task, "submit")
    db.session.rollback()
    assert ApiTask.query.count() == TaskOutbox.query.count() == 0
    db.session.add(task)
    db.session.flush()
    enqueue(task, "submit")
    db.session.commit()
    assert claim(task.id, "submit", task.queue_generation)
    assert claim(task.id, "submit", task.queue_generation) is None


def test_unknown_submit_is_never_automatically_retried(app_ctx, h, source_video, monkeypatch):
    calls = []
    def lost(self, payload):
        calls.append(payload)
        raise ConnectionError("response lost after provider acceptance")
    monkeypatch.setattr(MockAdapter, "submit", lost)
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    assert drain(job.job_id).status == "failed"
    assert len(calls) == 1
    assert ApiTask.query.one().queue_phase == "submit_unknown"
    with pytest.raises(AppError, match="Reconcile"):
        JobRunService.start(job.job_id, "run_full", force=True)
    db.session.rollback()
    for _ in range(4):
        step()
    assert len(calls) == 1


def test_agent_and_classic_use_same_ingress_and_drain_after_disabled(app_ctx, client, h, source_video):
    from tests.test_agent_mvp import create, tick, action, detail
    run_id = create(client, shot_count=1)
    tick()
    action(client, run_id, "approve")
    tick()
    assert JobDispatch.query.count() == 1
    classic = h.make_job(source_video)
    JobRunService.start(classic.job_id, "run_full")
    assert JobDispatch.query.count() == 2
    app_ctx.config["MQ_ENABLED"] = False
    for _ in range(60):
        step()
        tick()
        if detail(client, run_id)["status"] == "awaiting_delivery" and h.reload_job(classic.job_id).status == "success":
            break
    assert detail(client, run_id)["status"] == "awaiting_delivery"
    assert h.reload_job(classic.job_id).status == "success"
    assert all(task.operation_key for task in ApiTask.query.all())


def test_expired_submit_is_unknown_poll_is_rescheduled(app_ctx, h):
    job = h.make_job(paths=())
    for phase in ("submit", "poll"):
        task = ApiTask(job_id=job.id, branch_key=phase, model_id="mock", adapter_name="mock",
                       queue_generation=0, request_payload={}, queue_data={"generation": True})
        db.session.add(task)
        db.session.flush()
        enqueue(task, phase)
        db.session.commit()
        assert claim(task.id, phase, task.queue_generation)
        task.lease_until = utc_now() - timedelta(seconds=1)
        db.session.commit()
    assert recover_expired() == 2
    assert ApiTask.query.filter_by(branch_key="submit").one().queue_phase == "submit_unknown"
    assert ApiTask.query.filter_by(branch_key="poll").one().queue_phase == "poll"


def test_file_survives_database_failure_without_second_download(app_ctx, h, source_video, monkeypatch):
    from app.services.artifact_service import ArtifactService
    original = ArtifactService.register_artifact
    failures, downloads = [], []
    download = MockAdapter.download_outputs
    def tracked(self, response, output_dir):
        downloads.append(output_dir)
        return download(self, response, output_dir)
    def broken(*args, **kwargs):
        if len(args) > 2 and args[2] == "i2v_video" and not failures:
            failures.append(True)
            raise RuntimeError("DB connection lost after atomic file rename")
        return original(*args, **kwargs)
    monkeypatch.setattr(MockAdapter, "download_outputs", tracked)
    monkeypatch.setattr(ArtifactService, "register_artifact", broken)
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    assert drain(job.job_id).status == "success"
    assert failures == [True]
    assert len(downloads) == 2  # One image + one video, despite a download retry.
    assert Artifact.query.filter_by(artifact_type="i2v_video").count() == 1
    assert ApiTask.query.filter_by(branch_key="i2v").count() == 1


def test_download_exhaustion_keeps_provider_id_and_never_resubmits(app_ctx, h, source_video, monkeypatch):
    attempts = []
    original = MockAdapter.download_outputs
    def broken(self, response, output_dir):
        if response.get("output_kind") == "video":
            attempts.append(True)
            raise ConnectionError("download disconnected")
        return original(self, response, output_dir)
    monkeypatch.setattr(MockAdapter, "download_outputs", broken)
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    assert drain(job.job_id).status == "failed"
    task = ApiTask.query.filter_by(branch_key="i2v").one()
    assert task.provider_task_id and task.queue_phase == "failed"
    assert len(attempts) == 3
    assert TaskOutbox.query.filter_by(task_id=task.id, phase="submit").count() == 1


def test_i2i_samples_pipeline_past_slow_and_failed_images(app_ctx, h, source_video, monkeypatch):
    original_submit = MockAdapter.submit
    original_poll = MockAdapter.poll
    ids, videos = {}, []
    release_slow = False
    def submit(self, payload):
        response = original_submit(self, payload)
        active = ApiTask.query.filter_by(queue_phase="submit_active", model_id=self.model_id).one()
        index = active.request_payload.get("test_index")
        if self.output_kind == "image" and index:
            ids[response["provider_task_id"]] = index
        if self.output_kind == "video" and index:
            videos.append(index)
        return response
    def poll(self, provider_id):
        index = ids.get(provider_id)
        if index == 1 and not release_slow:
            return {"status": "running"}
        if index == 2:
            return {"status": "failed", "error_message": "sample 2 rejected"}
        return original_poll(self, provider_id)
    monkeypatch.setattr(MockAdapter, "submit", submit)
    monkeypatch.setattr(MockAdapter, "poll", poll)
    app_ctx.config["MAX_POLL_ROUNDS"] = 90
    job = h.make_job(source_video, paths=("core", "i2i_test"),
                     job_config={"i2i_test": {"test_count": 3, "mode": "single_male"}})
    JobRunService.start(job.job_id, "run_full")
    for _ in range(20):
        step()
        if 3 in videos:
            break
    assert 3 in videos and 1 not in videos and 2 not in videos
    release_slow = True
    result = drain(job.job_id)
    assert result.status == "partial_success", result.error_summary
    assert sorted(videos) == [1, 3]
    assert Artifact.query.filter_by(artifact_type="i2i_test_video").count() == 2
    items = result.config["i2i_test_batch"]["items"]
    assert [item["image_status"] for item in items] == ["success", "failed", "success"]
    from app.services.job_package_service import JobPackageService
    assert JobPackageService.create_or_refresh(result)["artifact"]


def test_poll_due_time_and_stale_generation(app_ctx, h):
    job = h.make_job(paths=())
    task = ApiTask(job_id=job.id, branch_key="t2v", model_id="mock", adapter_name="mock_video",
                   provider_task_id="known", queue_generation=0, queue_data={"generation": True})
    db.session.add(task)
    db.session.flush()
    enqueue(task, "poll", delay=300)
    db.session.commit()
    event_id = TaskOutbox.query.one().id
    process_event(event_id)
    assert task.poll_count == 0 and not TaskOutbox.query.one().consumed_at
    enqueue(task, "poll")
    db.session.commit()
    TaskOutbox.query.filter_by(id=event_id).update({"available_at": utc_now()})
    db.session.commit()
    process_event(event_id)
    assert task.poll_count == 0
    assert db.session.get(TaskOutbox, event_id).consumed_at


def test_unknown_media_can_bind_confirmed_provider_without_post(app_ctx, h, source_video, monkeypatch):
    from app.queue.operations import reconcile, status
    original = MockAdapter.submit
    videos = []
    def lost_video(self, payload):
        if self.output_kind == "video":
            videos.append(True)
            raise ConnectionError("accepted but response lost")
        return original(self, payload)
    monkeypatch.setattr(MockAdapter, "submit", lost_video)
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    assert drain(job.job_id).status == "failed"
    task = ApiTask.query.filter_by(branch_key="i2v").one()
    assert status()["submit_unknown"][0]["api_task_id"] == task.api_task_id
    reconcile(task.api_task_id, provider_id="operator-confirmed-task", reason="Checked provider task history")
    assert drain(job.job_id).status == "success"
    assert videos == [True]
    assert Artifact.query.filter_by(artifact_type="i2v_video").count() == 1


def test_redis_outage_retains_committed_outbox(app_ctx, h, source_video):
    from app.queue.transport import Streams
    class OfflineRedis:
        def xadd(self, *args, **kwargs):
            raise ConnectionError("Redis unavailable")
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    dispatch_once()
    with pytest.raises(ConnectionError):
        Streams(OfflineRedis()).publish()
    event = TaskOutbox.query.one()
    assert not event.published_at and not event.consumed_at
    assert event.attempts == 1
    assert ApiTask.query.one().queue_phase == "submit"


def test_sync_media_goes_directly_to_download(app_ctx, h, source_video, monkeypatch):
    original = MockAdapter.submit
    def sync_image(self, payload):
        if self.output_kind == "image":
            return {"status": "success", "synchronous": True, "output_kind": "image",
                    "provider_task_id": "sync://" + "long-url" * 100, "result_url": "mock-image"}
        return original(self, payload)
    monkeypatch.setattr(MockAdapter, "submit", sync_image)
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    assert drain(job.job_id).status == "success"
    task = ApiTask.query.filter_by(branch_key="first_frame_image").one()
    assert task.provider_task_id is None
    assert TaskOutbox.query.filter_by(task_id=task.id, phase="poll").count() == 0


def test_pause_resume_cancel_and_queue_status(app_ctx, client, h, source_video):
    from app.services.job_service import JobService
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    assert client.get("/api/jobs/queue/status").json["data"]["queued_count"] == 1
    JobService.pause(job.job_id)
    step()
    assert ApiTask.query.count() == 0
    JobRunService.start(job.job_id, "run_full")
    assert drain(job.job_id).status == "success"
    count = ApiTask.query.count()
    cancelled = h.make_job(source_video)
    JobRunService.start(cancelled.job_id, "run_full")
    JobService.cancel(cancelled.job_id)
    step()
    assert ApiTask.query.count() == count


def test_force_restart_is_new_run_and_old_messages_cannot_submit(app_ctx, h, source_video):
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    assert drain(job.job_id).status == "success"
    old_task = ApiTask.query.filter_by(branch_key="i2v").one()
    old_id = old_task.id
    JobRunService.start(job.job_id, "run_full", force=True, restart=True)
    enqueue(old_task, "poll")  # A delayed message from the previous full run.
    db.session.commit()
    assert drain(job.job_id).status == "success"
    assert db.session.get(ApiTask, old_id).queue_phase == "failed"
    assert Artifact.query.filter_by(artifact_type="i2v_video").count() == 2
    assert h.artifact_types(h.reload_job(job.job_id)).count("i2v_video") == 1


def test_waiting_node_freezes_operation_when_defaults_change(app_ctx, h, source_video):
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    dispatch_once()
    task = ApiTask.query.one()
    original_parameters = task.queue_data["params"]
    job = h.reload_job(job.job_id)
    job.config = {**job.config, "model_params": {"video_understanding": {"temperature": 0.99}}}
    db.session.commit()
    assert drain(job.job_id).status == "success"
    tasks = ApiTask.query.filter_by(branch_key="reverse_prompts").all()
    assert len(tasks) == 1
    assert tasks[0].queue_data["params"] == original_parameters


def test_i2i_catchup_reuses_inline_operation_after_local_write_failure(app_ctx, h, source_video, monkeypatch):
    from app.services.node_runner import NodeRunner
    original = NodeRunner._write_json_artifact
    failures = []
    def interrupt(self, job, node_run, relative_parts, *args, **kwargs):
        if node_run.node_key == "poll_i2i_test_image" and "i2i_test_i2v" in relative_parts and not failures:
            failures.append(True)
            raise OSError("Local payload log failed after task/outbox commit")
        return original(self, job, node_run, relative_parts, *args, **kwargs)
    monkeypatch.setattr(NodeRunner, "_write_json_artifact", interrupt)
    job = h.make_job(source_video, paths=("core", "i2i_test"),
                    job_config={"i2i_test": {"test_count": 1, "mode": "single_male"}})
    JobRunService.start(job.job_id, "run_full")
    assert drain(job.job_id).status == "success"
    assert failures == [True]
    task = ApiTask.query.filter_by(branch_key="i2i_test_i2v").one()
    assert TaskOutbox.query.filter_by(task_id=task.id, phase="submit").count() == 1
    assert Artifact.query.filter_by(artifact_type="i2i_test_video").count() == 1


def test_disabled_model_blocks_new_submit_but_preserves_accepted_result(app_ctx, h, source_video):
    from app.models import ModelRegistry
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    for _ in range(15):
        step()
        task = ApiTask.query.filter_by(branch_key="first_frame_image").first()
        if task and task.provider_task_id:
            break
    assert task and task.provider_task_id
    model = ModelRegistry.query.filter_by(model_id=task.model_id).one()
    model.enabled = False
    db.session.commit()
    assert drain(job.job_id).status == "success"
    assert Artifact.query.filter_by(artifact_type="first_frame_image").count() == 1


def test_mq_admission_cannot_duplicate_an_active_legacy_job(app_ctx, h):
    job = h.make_job(paths=())
    job.status = "running"
    db.session.commit()
    with pytest.raises(AppError, match="Drain"):
        JobRunService.start(job.job_id, "run_full")
    db.session.rollback()
    assert JobDispatch.query.count() == 0
    assert ApiTask.query.count() == 0


def test_cancel_during_download_does_not_register_late_video(app_ctx, h, source_video, monkeypatch):
    from app.services.job_service import JobService
    original = MockAdapter.download_outputs
    def cancel(self, response, output_dir):
        outputs = original(self, response, output_dir)
        if response.get("output_kind") == "video":
            task = ApiTask.query.filter_by(queue_phase="download_active").one()
            job = db.session.get(Job, task.job_id)
            JobService.cancel(job.job_id)
        return outputs
    monkeypatch.setattr(MockAdapter, "download_outputs", cancel)
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    assert drain(job.job_id).status == "cancelled"
    assert Artifact.query.filter_by(artifact_type="i2v_video").count() == 0
    assert ApiTask.query.filter_by(branch_key="i2v").one().provider_task_id


def test_delete_completed_mq_job_cleans_outbox_and_stale_messages(app_ctx, h, source_video):
    from app.services.job_service import JobService
    job = h.make_job(source_video)
    JobRunService.start(job.job_id, "run_full")
    assert drain(job.job_id).status == "success"
    event_id = TaskOutbox.query.first().id
    assert JobService.delete_job(job.job_id, job.job_id)["deleted"]
    assert TaskOutbox.query.count() == JobDispatch.query.count() == ApiTask.query.count() == 0
    process_event(event_id)  # A stale Redis message for deleted history is harmless.
