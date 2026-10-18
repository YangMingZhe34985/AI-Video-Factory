"""Editor acceptance via API commands, durable LangGraph and real local MP4s."""
from dataclasses import replace
import zipfile
import pytest
from app.agent import delivery
from app.extensions import db
from app.models import AgentRun, ApiTask, Artifact, ToolInvocation
from app.services.storage_service import StorageService
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from tests.test_media_probe import configure_ffmpeg
from tests.test_story_review import advance, act, storyboard, view
from tests.test_story_production_graph import settle_production
from tests.test_production_recovery import inline_jobs

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_STORY_DELIVERY_ENABLED=True, AGENT_VISION_MODEL="qwen3.7-plus")


def registry():
    result = build_default_registry()
    from app.skills.tools import compose_video, probe_media, qc_video, package_story
    for module in (compose_video, probe_media, qc_video, package_story):
        if module.SPEC.name not in result.names():
            result.register(module.SPEC)
    return result


def clips(app, client):
    configure_ffmpeg(app)
    run_id, board = storyboard(client, text="制作猫咪探索城市的故事短片，约15秒，使用wan2.7系列，不要happy-horse")
    assert act(client, run_id, "approve_storyboard", plan_version=board["plan_version"]).status_code == 202
    assert advance(run_id).status == "storyboard_approved"
    assert act(client, run_id, "start_production", plan_version=board["plan_version"], request_key="start").status_code == 202
    assert settle_production(run_id).status == "awaiting_video_review"
    return run_id, board["plan_version"]


def finish(run_id, tools=None):
    for _ in range(12):
        row = advance(run_id, tools or registry())
        if row.status != "editing":
            return row
    pytest.fail("Delivery did not settle")


def paid(run_id):
    return ApiTask.query.count(), BudgetGuard.spent(run_id)


def test_new_clip_approval_auto_delivers_owned_complete_package(app_ctx, client, inline_jobs):
    run_id, version = clips(app_ctx, client)
    before = paid(run_id)
    assert act(client, run_id, "approve_videos", plan_version=version, request_key="clips").status_code == 202
    row = finish(run_id)
    assert row.status == "success", row.error or row.snapshot
    final = view(client, run_id)["delivery"]
    assert final["stage"] == "complete" and final["qc"]["passed"]
    assert final["master"]["duration_sec"] == pytest.approx(15, abs=.5)
    assert not final["compressed"] and final["cost_credits"] == 0
    assert not final["can_start"] and not final["can_retry"]
    artifact = Artifact.query.filter_by(artifact_id=final["package"]["artifact_id"]).one()
    with zipfile.ZipFile(StorageService.resolve(artifact.file_path)) as archive:
        assert {"manifest.json", "plan.json", "story.json", "qc.json", "final/master.mp4"} <= set(archive.namelist())
        assert len([name for name in archive.namelist() if name.startswith("sources/")]) == len(row.snapshot["plan"]["shots"])
        manifest = archive.read("manifest.json").decode()
        assert "http://" not in manifest and "file_path" not in manifest and str(StorageService.root()) not in manifest
    assert paid(run_id) == before
    assert act(client, run_id, "approve_videos", plan_version=version, request_key="clips").status_code == 202
    assert advance(run_id, registry()).status == "success"
    assert paid(run_id) == before


def test_old_approved_run_stays_inert_until_explicit_start(app_ctx, client, inline_jobs):
    app_ctx.config["AGENT_STORY_DELIVERY_ENABLED"] = False
    run_id, version = clips(app_ctx, client)
    assert act(client, run_id, "approve_videos", plan_version=version, request_key="clips").status_code == 202
    assert advance(run_id).status == "videos_approved"
    before = paid(run_id)
    app_ctx.config["AGENT_STORY_DELIVERY_ENABLED"] = True
    assert advance(run_id, registry()).status == "videos_approved"
    assert not ToolInvocation.query.filter_by(tool_name="compose_video").count()
    assert view(client, run_id)["delivery"]["can_start"]
    assert act(client, run_id, "start_delivery", plan_version=version, request_key="deliver").status_code == 202
    assert finish(run_id).status == "success"
    assert act(client, run_id, "start_delivery", plan_version=version + 1, request_key="deliver").status_code == 409
    assert paid(run_id) == before


def test_missing_package_recovers_without_recomposing_or_paid_calls(app_ctx, client, inline_jobs):
    run_id, version = clips(app_ctx, client)
    assert act(client, run_id, "approve_videos", plan_version=version, request_key="clips").status_code == 202
    row = finish(run_id)
    assert row.status == "success", row.error
    before = paid(run_id)
    master = row.snapshot["delivery"]["composition"]["artifact_id"]
    artifact = Artifact.query.filter_by(artifact_id=row.snapshot["delivery"]["package"]["artifact_id"]).one()
    StorageService.resolve(artifact.file_path).unlink()
    shown = view(client, run_id)["delivery"]
    assert shown["can_retry"] and shown["package"] is None
    assert act(client, run_id, "retry_delivery", plan_version=version, request_key="retry").status_code == 202
    row = finish(run_id)
    assert row.status == "success", row.error
    assert row.snapshot["delivery"]["composition"]["artifact_id"] == master
    assert paid(run_id) == before


def test_source_bytes_changed_after_approval_stop_without_video_regeneration(app_ctx, client, inline_jobs):
    run_id, version = clips(app_ctx, client)
    assert act(client, run_id, "approve_videos", plan_version=version, request_key="clips").status_code == 202
    row = advance(run_id, registry())
    assert row.status == "editing"
    before = paid(run_id)
    artifact = Artifact.query.filter_by(artifact_id=row.snapshot["delivery"]["source_artifact_ids"][0]).one()
    StorageService.resolve(artifact.file_path).write_bytes(b"invalid replacement")
    row = finish(run_id)
    assert row.status == "delivery_attention"
    frozen = row.snapshot["delivery"]["source_sha256"]
    assert act(client, run_id, "retry_delivery", plan_version=version, request_key="retry").status_code == 202
    row = finish(run_id)
    assert row.status == "delivery_attention" and row.snapshot["delivery"]["source_sha256"] == frozen
    assert paid(run_id) == before


def test_tool_committed_before_checkpoint_crash_replays_without_duplicate_outputs(app_ctx, client, inline_jobs, monkeypatch):
    run_id, version = clips(app_ctx, client)
    tools = registry()
    assert act(client, run_id, "approve_videos", plan_version=version, request_key="clips").status_code == 202
    assert advance(run_id, tools).status == "editing"
    original = delivery._invoke
    def crash(run, tool_registry, name, payload, slot):
        result = original(run, tool_registry, name, payload, slot)
        if name == "compose_video":
            raise SystemExit("Simulated process death after tool commit")
        return result
    monkeypatch.setattr(delivery, "_invoke", crash)
    with pytest.raises(SystemExit):
        advance(run_id, tools)
    count = Artifact.query.filter_by(artifact_type="composed_video").count()
    before = paid(run_id)
    monkeypatch.setattr(delivery, "_invoke", original)
    row = finish(run_id, tools)
    assert row.status == "success", row.error or row.snapshot
    assert Artifact.query.filter_by(artifact_type="composed_video").count() == count
    assert ToolInvocation.query.filter_by(tool_name="compose_video").count() == 1
    assert paid(run_id) == before


def test_structural_qc_failure_stops_before_packaging(app_ctx, client, inline_jobs):
    run_id, version = clips(app_ctx, client)
    tools = registry()
    spec = tools.get("qc_video")
    tools._specs["qc_video"] = replace(spec, handler=lambda _data, _ctx: {
        "passed": False, "checks": [{"code": "TOTAL_DURATION", "passed": False, "summary": "injected deviation"}], "warnings": []})
    before = paid(run_id)
    assert act(client, run_id, "approve_videos", plan_version=version, request_key="clips").status_code == 202
    row = finish(run_id, tools)
    assert row.status == "delivery_attention"
    assert row.snapshot["delivery"]["error"]["code"] == "DELIVERY_QC_FAILED"
    assert not ToolInvocation.query.filter_by(tool_name="package_story").count()
    assert act(client, run_id, "retry_delivery", plan_version=version, request_key="retry").status_code == 202
    assert finish(run_id).status == "success"
    assert paid(run_id) == before
