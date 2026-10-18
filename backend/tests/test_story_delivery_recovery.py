"""Delivery cache, retry receipts and local QC failure boundaries."""
from copy import deepcopy
import pytest
from app.agent import delivery
from app.extensions import db
from app.models import ApiTask, Artifact, ToolInvocation
from app.services.storage_service import StorageService
from app.services.media_probe_service import MediaProbeService
from app.skills.budget import BudgetGuard
from tests.test_media_probe import configure_ffmpeg
from tests.test_production_actions import fixture
from tests.test_story_delivery_graph import registry

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_STORY_DELIVERY_ENABLED=True)


def prepared(app, compress=False):
    configure_ffmpeg(app)
    run, version, _unused = fixture()
    if compress:
        snapshot = deepcopy(run.snapshot)
        snapshot["request_spec"]["constraints"]["compress_output"] = True
        run.snapshot = snapshot
        db.session.commit()
    run.status = delivery.begin_delivery(run, version)
    db.session.commit()
    return run, version, registry()


def drive(run, tools):
    for _ in range(8):
        run.status = delivery.tick(run, tools)
        db.session.commit()
        if run.status != "editing":
            return run
    pytest.fail("Local Editor did not finish")


def body(run, kind):
    data = run.snapshot["delivery"]
    artifact_id = data["package"]["artifact_id"] if kind == "package" else data["composition"]["artifact_id"]
    artifact = Artifact.query.filter_by(artifact_id=artifact_id).one()
    return StorageService.resolve(artifact.file_path)


@pytest.mark.parametrize("kind", ["master", "package"])
def test_nonempty_corrupt_output_hidden_and_free_retry_allowed(app_ctx, kind):
    run, version, tools = prepared(app_ctx)
    assert drive(run, tools).status == "success", run.snapshot["delivery"]
    before = ApiTask.query.count(), BudgetGuard.spent(run.run_id)
    body(run, kind).write_bytes(b"nonempty corrupt cache")
    shown = delivery.public_delivery(run)
    assert shown[kind] is None and shown["can_retry"]
    command = {"action": "retry_delivery", "plan_version": version.version, "request_key": "repair"}
    assert delivery.validate_command(run, command) == 0
    run.status = delivery.apply_command(run, command)["status"]
    db.session.commit()
    assert drive(run, tools).status == "success", run.snapshot["delivery"]
    assert delivery.public_delivery(run)[kind]
    assert (ApiTask.query.count(), BudgetGuard.spent(run.run_id)) == before


def test_retry_crash_after_begin_preserves_reserved_attempt(app_ctx, monkeypatch):
    run, version, tools = prepared(app_ctx)
    assert drive(run, tools).status == "success"
    body(run, "package").unlink()
    command = {"action": "retry_delivery", "plan_version": version.version, "request_key": "repair"}
    original = delivery.begin_delivery
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise SystemExit("Crash after attempt was persisted")
    monkeypatch.setattr(delivery, "begin_delivery", crash)
    with pytest.raises(SystemExit):
        delivery.apply_command(run, command)
    assert run.snapshot["delivery"]["attempt"] == 2
    assert run.snapshot["delivery_action_receipts"]["repair"]["intent"]["target_attempt"] == 2
    monkeypatch.setattr(delivery, "begin_delivery", original)
    run.status = delivery.apply_command(run, command)["status"]
    db.session.commit()
    assert run.snapshot["delivery"]["attempt"] == 2
    assert drive(run, tools).status == "success"
    assert ToolInvocation.query.filter_by(tool_name="compose_video").count() == 1


def test_optional_compressed_video_is_decoded_and_reported(app_ctx):
    run, _version, tools = prepared(app_ctx, compress=True)
    assert drive(run, tools).status == "success", run.snapshot["delivery"]
    result = delivery.public_delivery(run)
    assert result["compressed"]
    checks = {entry["code"]: entry["passed"] for entry in result["qc"]["checks"]}
    assert all(checks[code] for code in ("COMPRESSED_DECODE", "COMPRESSED_DURATION", "COMPRESSED_DIMENSIONS", "COMPRESSED_FRAME_RATE"))


def test_corrupt_compressed_output_blocks_final_delivery(app_ctx):
    run, _version, tools = prepared(app_ctx, compress=True)
    assert delivery.tick(run, tools) == "editing"
    assert delivery.tick(run, tools) == "editing"
    artifact = Artifact.query.filter_by(artifact_id=run.snapshot["delivery"]["composition"]["compressed_artifact_id"]).one()
    StorageService.resolve(artifact.file_path).write_bytes(b"bad compressed media")
    assert delivery.tick(run, tools) == "delivery_attention"
    assert not run.snapshot["delivery"]["qc"]["passed"]
    assert any(item["code"] == "COMPRESSED_DECODE" and not item["passed"] for item in run.snapshot["delivery"]["qc"]["checks"])
    assert not ToolInvocation.query.filter_by(tool_name="package_story").count()


def test_qc_compares_approved_duration_not_original_user_target(app_ctx, monkeypatch):
    run, _version, tools = prepared(app_ctx)
    snapshot = deepcopy(run.snapshot)
    snapshot["request_spec"]["target_duration_sec"] = 300
    run.snapshot = snapshot
    db.session.commit()
    assert delivery.tick(run, tools) == "editing"
    assert delivery.tick(run, tools) == "editing"
    assert delivery.tick(run, tools) == "editing"
    assert run.snapshot["delivery"]["qc"]["passed"]
    original = MediaProbeService.probe
    def wrong_duration(path, **kwargs):
        result = original(path, **kwargs)
        if not result["mock"]:
            result["duration_sec"] += 2
        return result
    monkeypatch.setattr(MediaProbeService, "probe", wrong_duration)
    delivery.update(run, stage="checking")
    assert delivery.tick(run, tools) == "delivery_attention"
    assert any(item["code"] == "TOTAL_DURATION" and not item["passed"] for item in run.snapshot["delivery"]["qc"]["checks"])


def test_qc_target_geometry_comes_from_first_source_not_output_self_report(app_ctx, monkeypatch):
    run, _version, tools = prepared(app_ctx)
    assert delivery.tick(run, tools) == "editing"
    assert delivery.tick(run, tools) == "editing"
    snapshot = deepcopy(run.snapshot)
    snapshot["delivery"]["composition"]["composition"].update(width=640, height=360, fps=30.0)
    run.snapshot = snapshot
    db.session.commit()
    original = MediaProbeService.probe
    def wrong_geometry(path, **kwargs):
        result = original(path, **kwargs)
        if not result["mock"]:
            result.update(width=640, height=360, fps=30.0)
        return result
    monkeypatch.setattr(MediaProbeService, "probe", wrong_geometry)
    assert delivery.tick(run, tools) == "delivery_attention"
    failed = {item["code"] for item in run.snapshot["delivery"]["qc"]["checks"] if not item["passed"]}
    assert {"OUTPUT_DIMENSIONS", "OUTPUT_FRAME_RATE"} <= failed
