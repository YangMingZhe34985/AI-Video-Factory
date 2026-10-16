"""Explicit integration suite. Only the task-owned localhost test containers are allowed."""
import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import conftest as offline  # Pins mock providers before importing application config.
import pytest
import requests
from redis import Redis
from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import ApiTask, JobDispatch, TaskOutbox
from app.adapters.mock import MockAdapter
from app.queue.dispatch import dispatch_once
from app.queue.execution import process_event, recover_expired
from app.queue.state import enqueue
from app.queue.transport import Streams
from app.services.job_run_service import JobRunService
from app.utils.time_utils import utc_now
from tests import helpers as h


@pytest.fixture
def environment(tmp_path, monkeypatch):
    assert os.environ.get("CINECREW_MQ_INTEGRATION") == "isolated-1017", "Explicit isolated integration opt-in required"
    monkeypatch.setattr(requests.Session, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("HTTP blocked")))
    app = create_app("testing", config_overrides={
        "SQLALCHEMY_DATABASE_URI": "mysql+pymysql://root:cinecrew-isolated-test@127.0.0.1:13306/cinecrew_mq_test",
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_size": 12, "max_overflow": 4},
        "STORAGE_ROOT": str(tmp_path / "storage"), "UPLOAD_FOLDER": str(tmp_path / "storage/uploads"),
        "AUTO_REPAIR_SCHEMA": False, "MQ_ENABLED": True, "MQ_WORKER_ACTIVE": True,
        "REDIS_URL": "redis://127.0.0.1:16379/15", "MODEL_ADAPTER_MODE": "mock",
        "WORKFLOW_MAX_PARALLEL_NODES": 4, "VIDEO_COMPRESSION_ENABLED": False,
    })
    with app.app_context():
        # Drop only our explicitly named, disposable integration schema's tables.
        db.drop_all()
        db.session.execute(db.text("DROP TABLE IF EXISTS alembic_version"))
        db.session.commit()
        upgrade(directory=str(offline.BACKEND_DIR / "migrations"))
        result = app.test_cli_runner().invoke(args=["seed-defaults"])
        assert result.exit_code == 0, result.output
        client = Redis.from_url(app.config["REDIS_URL"], decode_responses=True)
        client.flushdb()  # DB 15 in our isolated container, never a user Redis instance.
        streams = Streams(client)
        streams.ensure_groups()
        yield app, streams
        db.session.remove()
        db.engine.dispose()
        client.close()


def cycle(streams):
    JobDispatch.query.filter_by(status="ready").update({"available_at": utc_now()})
    TaskOutbox.query.filter_by(consumed_at=None).update({"available_at": utc_now()})
    db.session.commit()
    dispatch_once()
    streams.publish()
    for phase in ("submit", "poll", "download"):
        for _ in range(20):
            if not streams.consume(phase, process_event):
                break


def test_real_mysql_redis_end_to_end_and_transport_loss(environment, tmp_path):
    app, streams = environment
    source = tmp_path / "source.mp4"
    source.write_bytes(b"Mock source")
    job = h.make_job(source, paths=("core", "first_i2v", "t2v"))
    JobRunService.start(job.job_id, "run_full")
    dispatch_once()
    streams.publish()
    assert TaskOutbox.query.filter(TaskOutbox.published_at.is_not(None)).count()
    # Redis loss after XADD but before consumption: SQL outbox rebuilds transport.
    streams.client.flushdb()
    streams.ensure_groups()
    TaskOutbox.query.update({"published_at": utc_now() - timedelta(seconds=120)})
    db.session.commit()
    for _ in range(40):
        cycle(streams)
        if h.reload_job(job.job_id).status in h.TERMINAL_STATUSES:
            break
    result = h.reload_job(job.job_id)
    assert result.status == "success", result.error_summary
    assert {"i2v_video", "t2v_video"} <= set(h.artifact_types(result))
    assert TaskOutbox.query.filter_by(consumed_at=None).count() == 0
    from app.services.job_service import JobService
    assert JobService.delete_job(job.job_id, job.job_id)["deleted"]
    assert TaskOutbox.query.count() == JobDispatch.query.count() == 0


def test_mysql_concurrent_claims_submit_once(environment, monkeypatch):
    app, streams = environment
    job = h.make_job(paths=())
    task = ApiTask(job_id=job.id, branch_key="test", model_id="wan2.7-t2v", adapter_name="mock_video",
                   queue_generation=0, queue_data={"generation": True, "wire_payload": {}})
    db.session.add(task)
    db.session.flush()
    enqueue(task, "submit")
    db.session.commit()
    event_id = TaskOutbox.query.one().id
    barrier = threading.Barrier(6)
    calls = []
    original = MockAdapter.submit
    def counted(self, payload):
        calls.append(True)
        return original(self, payload)
    monkeypatch.setattr(MockAdapter, "submit", counted)
    def worker():
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                process_event(event_id)
            finally:
                db.session.remove()
    db.session.remove()
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: worker(), range(6)))
    assert calls == [True]
    assert db.session.get(TaskOutbox, event_id).consumed_at


def test_pending_reclaimed_after_consumer_loss(environment):
    from app.queue.transport import GROUP
    app, streams = environment
    job = h.make_job(paths=())
    task = ApiTask(job_id=job.id, branch_key="test", model_id="wan2.7-t2v", adapter_name="mock_video",
                   provider_task_id="retained-id", queue_generation=0, queue_data={"generation": True})
    db.session.add(task)
    db.session.flush()
    enqueue(task, "poll")
    db.session.commit()
    streams.publish()
    messages = streams.client.xreadgroup(GROUP, "dead-consumer", {streams.stream("poll"): ">"})
    message_id = messages[0][1][0][0]
    # Simulate a dead process's idle PEL entry without wall-clock sleeping.
    streams.client.xclaim(streams.stream("poll"), GROUP, "dead-consumer", 0, [message_id], idle=120000)
    assert streams.consume("poll", process_event) == 1
    assert streams.client.xpending(streams.stream("poll"), GROUP)["pending"] == 0
    assert ApiTask.query.one().queue_phase == "generated"


def test_process_exit_after_claim_does_not_resubmit(environment):
    import json
    import subprocess
    app, streams = environment
    job = h.make_job(paths=())
    task = ApiTask(job_id=job.id, branch_key="test", model_id="wan2.7-t2v", adapter_name="mock_video",
                   queue_generation=0, queue_data={"generation": True, "wire_payload": {}})
    db.session.add(task)
    db.session.flush()
    enqueue(task, "submit")
    db.session.commit()
    task_id, generation = task.id, task.queue_generation
    config = {key: app.config[key] for key in ("SQLALCHEMY_DATABASE_URI", "STORAGE_ROOT", "UPLOAD_FOLDER")}
    config.update(AUTO_REPAIR_SCHEMA=False, MODEL_ADAPTER_MODE="mock")
    code = """
import json, os, sys
from app import create_app
from app.queue.state import claim
app = create_app('testing', config_overrides=json.loads(sys.argv[1]))
with app.app_context():
    assert claim(int(sys.argv[2]), 'submit', int(sys.argv[3]))
    os._exit(0)
"""
    result = subprocess.run([sys.executable, "-c", code, json.dumps(config), str(task_id), str(generation)],
                            cwd=str(offline.BACKEND_DIR), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    db.session.expire_all()
    task = db.session.get(ApiTask, task_id)
    assert task.queue_phase == "submit_active"
    task.lease_until = utc_now() - timedelta(seconds=1)
    db.session.commit()
    assert recover_expired() == 1
    assert task.queue_phase == "submit_unknown"
    process_event(TaskOutbox.query.one().id)
    assert not task.provider_task_id
    assert TaskOutbox.query.one().consumed_at
