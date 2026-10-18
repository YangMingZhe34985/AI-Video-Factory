"""Agent compression is explicit; both executors preserve classic behavior."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.output_policy import for_submission, compression_enabled
from app.extensions import db
from app.models import AgentRun, Artifact, Job
from app.services.job_run_service import JobRunService
from app.services.storage_service import StorageService
from app.services.video_compression_service import VideoCompressionService
from app.skills import get_registry
from app.skills.spec import ToolContext


def make_run(value=None):
    row = AgentRun(owner_id="local", request_key="compression", request={
        "schema_version": 2, "text": "A cat walks", "attachment_ids": [], "budget_limit": 100},
        snapshot={"request_spec": {"deliverable": "video", "recipe_hint": "single_clip",
                  "summary": "A cat walks", "confidence": 1,
                  "constraints": {} if value is None else {"compress_output": value}}})
    db.session.add(row)
    db.session.commit()
    return row


def test_policy_is_boolean_and_story_sources_are_originals(app_ctx):
    row = make_run()
    ctx = ToolContext(role="production", budget_scope=row.run_id)
    for value in (None, False, "true", 1, True):
        row.snapshot = {"request_spec": {"constraints": {"compress_output": value}}}
        db.session.commit()
        assert for_submission(ctx) == {"compress_output": value is True}
    ctx.shot_task_id = 1
    assert for_submission(ctx) == {"compress_output": False}
    assert compression_enabled(SimpleNamespace(config={"skill": {}})) is None
    assert compression_enabled(SimpleNamespace(config={"skill": {"tool_name": "old"}})) is False
    assert compression_enabled(SimpleNamespace(config={"agent_story_production": {"run_id": row.run_id},
        "agent_output_policy": {"compress_output": True}})) is False


@pytest.mark.parametrize("mq", [False, True])
@pytest.mark.parametrize("kind", ["default_agent", "explicit_agent", "classic"])
def test_download_policy_and_original_bytes(app_ctx, h, monkeypatch, mq, kind):
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq, VIDEO_COMPRESSION_ENABLED=True)
    calls = []
    def compress(_ffmpeg, source, target):
        calls.append(source)
        target.write_bytes(b"tiny")
        return ["ignored"]
    monkeypatch.setattr(VideoCompressionService, "resolve_ffmpeg", lambda: "mock-local-ffmpeg")
    monkeypatch.setattr(VideoCompressionService, "_command", compress)
    # Only the compression subprocess is replaced; provider adapters remain Mock.
    monkeypatch.setattr("app.services.video_compression_service.subprocess.run", lambda *a, **k: None)
    if kind == "classic":
        job = h.make_job(paths=("t2v",), initial_prompts={"t2v": "A cat walks"})
        JobRunService.start(job.job_id, "run_full")
    else:
        row = make_run(True if kind == "explicit_agent" else None)
        result = get_registry().invoke("generate_video", {"mode": "t2v", "prompt": "A cat walks"},
            ToolContext(role="production", approved=True, budget_scope=row.run_id))
        job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
        assert job.config["agent_output_policy"] == {"compress_output": kind == "explicit_agent"}
    if mq:
        from tests.test_shared_queue import drain
        job = drain(job.job_id)
    else:
        job = h.wait_for_terminal(job.job_id)
    assert job.status == "success", job.error_summary
    artifact = Artifact.query.filter_by(job_id=job.id, artifact_type="t2v_video").one()
    compressed = kind != "default_agent"
    assert bool(calls) is compressed
    metadata = artifact.meta["compression"]
    assert metadata["enabled"] is compressed
    assert metadata["status"] == ("success" if compressed else "disabled")
    original = StorageService.resolve(metadata["original_file_path"])
    assert original.is_file() and original.read_bytes() != b"tiny"
    if compressed:
        assert StorageService.resolve(artifact.file_path).read_bytes() == b"tiny"
        assert original != StorageService.resolve(artifact.file_path)
    else:
        assert original == StorageService.resolve(artifact.file_path)


def test_frozen_agent_policy_ignores_later_global_or_request_changes(app_ctx, monkeypatch):
    row = make_run(True)
    monkeypatch.setattr(JobRunService, "start", lambda *a, **kw: {})
    result = get_registry().invoke("generate_video", {"mode": "t2v", "prompt": "A cat walks"},
        ToolContext(role="production", approved=True, budget_scope=row.run_id))
    job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
    row.snapshot = {"request_spec": {"constraints": {"compress_output": False}}}
    db.session.commit()
    app_ctx.config["VIDEO_COMPRESSION_ENABLED"] = False
    assert compression_enabled(job) is True
    assert compression_enabled(SimpleNamespace(config={})) is None
