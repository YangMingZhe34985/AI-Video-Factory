"""D4 replay, aggregate authorization and local dependency recovery regressions."""

from copy import deepcopy
from dataclasses import replace

import pytest

from app.agent import plan_versions as versions, production_actions as actions, production_engine as engine
from app.agent.production_state import latest_tasks, usable_artifact
from app.agent.production_view import public_production
from app.api import AppError
from app.extensions import db
from app.models import AgentShotTask, ApiTask, ToolInvocation
from app.services.model_service import ModelService
from app.services.storage_service import StorageService
from app.skills.budget import BudgetGuard
from tests.test_production_actions import drive, fixture, priced, redo_command
from tests.test_production_recovery import fail_submit_once, inline_jobs

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_MAX_SHOT_AUTO_REPAIRS=0)


def retry_command(quoted, key="retry"):
    return {"action": "retry_shot", "shot_id": quoted["shot_id"], "base_version": quoted["base_version"],
            "quote_id": quoted["quote_id"], "request_key": key}


def start(row, version, registry):
    return actions.apply_command(row, {"action": "start_production", "plan_version": version.version,
                                      "request_key": "start"}, registry)


def price(rate):
    model = ModelService.get_model("wan2.7-i2v")
    model.capabilities = {**model.capabilities, "pricing": {"unit": "second", "credits_per_unit": rate}}
    db.session.commit()


def attention(row):
    row.status = "production_attention"
    db.session.commit()


def paid_count():
    return ToolInvocation.query.filter_by(tool_name="animate_shot").count()


def test_consecutive_only_redos_keep_original_downstream_provenance(app_ctx, inline_jobs):
    row, original, registry = fixture()
    original_task = latest_tasks(row, original)["s02"]
    for index in range(2):
        current = versions.current_version(row)
        actions.apply_command(row, redo_command(priced(row, current), key=f"redo-{index}"), registry)
        assert drive(row, registry) == "awaiting_video_review"
        retained = row.snapshot["production"]["retained_sources"]["s02"]
        assert retained["source_version"] == original.version
        assert retained["task_id"] == original_task.id
        assert retained["artifact_ids"] == original_task.artifact_ids
        assert retained["inputs_hash"] == original_task.inputs_hash
    assert paid_count() == 2


def test_retry_crash_revalidates_repair_and_continuation_total(app_ctx, inline_jobs, monkeypatch):
    calls = fail_submit_once(monkeypatch)
    row, version, registry = fixture(complete=False)
    start(row, version, registry)
    assert drive(row, registry) == "production_attention"
    attention(row)
    assert set(latest_tasks(row, version)) == {"s01", "s03"}
    price(.5)
    quoted = priced(row, version, "s01", "retry")
    assert quoted["estimated_credits"]["only"] == 5
    assert quoted["continuation_shot_ids"] == ["s02"]
    command = retry_command(quoted)
    original = engine.retry_shot
    def crash(*args, **kwargs):
        raise RuntimeError("after intent, before repair reservation")
    monkeypatch.setattr(engine, "retry_shot", crash)
    with pytest.raises(RuntimeError):
        actions.apply_command(row, command, registry)
    assert row.snapshot["production_action_receipts"]["retry"]["intent"]
    before = (paid_count(), len(calls), AgentShotTask.query.count(), BudgetGuard.spent(row.run_id))
    price(.75)  # Each 3.75-credit video fits old 5-credit approval; their sum exceeds this quote.
    monkeypatch.setattr(engine, "retry_shot", original)
    with pytest.raises(AppError) as error:
        actions.apply_command(row, command, registry)
    assert error.value.code == "PRODUCTION_QUOTE_EXPIRED"
    assert (paid_count(), len(calls), AgentShotTask.query.count(), BudgetGuard.spent(row.run_id)) == before


def test_retry_quote_freezes_pending_continuation_prices(app_ctx, inline_jobs, monkeypatch):
    calls = fail_submit_once(monkeypatch)
    row, version, registry = fixture(complete=False)
    start(row, version, registry)
    assert drive(row, registry) == "production_attention"
    attention(row)
    price(.5)
    command = retry_command(priced(row, version, "s01", "retry"))
    actions.apply_command(row, command, registry)
    assert row.snapshot["production"]["approved_shot_costs"]["s02"] == 2.5
    before = len(calls)
    price(.75)
    assert drive(row, registry) == "production_attention"
    blocked = latest_tasks(row, version)["s02"]
    assert blocked.error["code"] == "MODEL_PRICE_CHANGED"
    assert len(calls) == before  # No fresh call can use the higher, historical start approval.


def failed_tail(monkeypatch):
    row, version, registry = fixture(complete=False)
    original = registry.get("extract_frame")
    calls = []
    def unavailable(data, ctx):
        calls.append(ctx.shot_task_id)
        raise AppError("FRAME_EXTRACTION_FAILED", "Injected local media outage", 503)
    registry._specs["extract_frame"] = replace(original, handler=unavailable)
    start(row, version, registry)
    assert drive(row, registry) == "production_attention"
    attention(row)
    registry._specs["extract_frame"] = original
    return row, version, registry, calls


@pytest.mark.parametrize("crash_after_attempt", [False, True])
def test_failed_tail_retries_locally_and_never_regenerates_source(app_ctx, inline_jobs, monkeypatch, crash_after_attempt):
    row, version, registry, failures = failed_tail(monkeypatch)
    videos = latest_tasks(row, version)
    assert set(videos) == {"s01", "s03"}
    source = videos["s01"]
    old_tail = versions.latest_task(row, version.version, "tail_frame", "s01")
    source_identity = (source.id, source.job_id, source.invocation_id, deepcopy(source.artifact_ids))
    view = next(item for item in public_production(row)["shots"] if item["shot_id"] == "s02")
    assert view["status"] == "blocked" and view["can_retry"]
    assert view["error"]["stage"] == "local" and view["error"]["submission_state"] == "not_submitted"
    quoted = priced(row, version, "s02", "retry")
    assert quoted["can_retry"] and quoted["estimated_credits"]["only"] == 5
    assert quoted["continuation_shot_ids"] == ["s02"]
    before_spent, before_calls = BudgetGuard.spent(row.run_id), paid_count()
    command = retry_command(quoted)
    if crash_after_attempt:
        original = engine._run_tail
        monkeypatch.setattr(engine, "_run_tail", lambda *_a: (_ for _ in ()).throw(RuntimeError("after new tail attempt")))
        with pytest.raises(RuntimeError):
            actions.apply_command(row, command, registry)
        created_id = versions.latest_task(row, version.version, "tail_frame", "s01").id
        monkeypatch.setattr(engine, "_run_tail", original)
    result = actions.apply_command(row, command, registry)
    assert result["status"] == "producing"
    restored = versions.latest_task(row, version.version, "tail_frame", "s01")
    assert restored.attempt == old_tail.attempt + 1
    if crash_after_attempt:
        assert restored.id == created_id
    assert usable_artifact(restored)
    assert BudgetGuard.spent(row.run_id) == before_spent
    assert paid_count() == before_calls
    assert actions.apply_command(row, command, registry) == result
    assert drive(row, registry) == "awaiting_video_review"
    assert (source.id, source.job_id, source.invocation_id, source.artifact_ids) == source_identity
    assert paid_count() == before_calls + 1
    assert BudgetGuard.spent(row.run_id) == before_spent + 5
    assert len(failures) == 1
    before_replay = (paid_count(), ToolInvocation.query.count(), AgentShotTask.query.count(), ApiTask.query.count())
    actions.apply_command(row, command, registry)
    assert (paid_count(), ToolInvocation.query.count(), AgentShotTask.query.count(), ApiTask.query.count()) == before_replay


@pytest.mark.parametrize("corruption", [None, b"", b"broken PNG cache"])
def test_missing_successful_tail_restores_same_receipt_without_video_resubmission(app_ctx, inline_jobs, corruption):
    app_ctx.config["AGENT_MAX_PARALLEL_SHOTS"] = 1
    row, version, registry = fixture(complete=False)
    start(row, version, registry)
    engine.tick_production(row, registry)
    engine._poll(row, version, registry)
    assert engine._extract_tail(row, version, "s01", registry)
    tail = versions.latest_task(row, version.version, "tail_frame", "s01")
    original = (tail.id, tail.invocation_id, deepcopy(tail.artifact_ids))
    path = StorageService.resolve(usable_artifact(tail).file_path)
    if corruption is None:
        path.unlink()
    else:
        path.write_bytes(corruption)
    attention(row)
    view = next(item for item in public_production(row)["shots"] if item["shot_id"] == "s02")
    assert view["can_retry"] and view["status"] == "blocked"
    quoted = priced(row, version, "s02", "retry")
    assert quoted["estimated_credits"]["only"] == 10  # Two ungenerated videos, free frame restoration.
    before = (paid_count(), ToolInvocation.query.filter_by(tool_name="extract_frame").count(), BudgetGuard.spent(row.run_id))
    command = retry_command(quoted)
    actions.apply_command(row, command, registry)
    restored = versions.latest_task(row, version.version, "tail_frame", "s01")
    assert (restored.id, restored.invocation_id, restored.artifact_ids) == original
    assert usable_artifact(restored)
    assert (paid_count(), ToolInvocation.query.filter_by(tool_name="extract_frame").count(), BudgetGuard.spent(row.run_id)) == before
    assert drive(row, registry) == "awaiting_video_review"
    assert paid_count() == 3


def test_tail_recovery_refuses_unknown_source(app_ctx, inline_jobs, monkeypatch):
    row, version, registry, _calls = failed_tail(monkeypatch)
    source = latest_tasks(row, version)["s01"]
    source.status = "failed"
    source.error = {"category": "submit_unknown", "submission_state": "unknown"}
    db.session.commit()
    before = (paid_count(), ToolInvocation.query.count())
    assert not engine.recoverable_tail(row, version, "s02")
    assert not next(item for item in public_production(row)["shots"] if item["shot_id"] == "s02")["can_retry"]
    with pytest.raises(AppError) as error:
        priced(row, version, "s02", "retry")
    assert error.value.code == "INVALID_AGENT_STATE"
    assert (paid_count(), ToolInvocation.query.count()) == before


@pytest.mark.parametrize("crash_before_receipt", [False, True])
def test_missing_successful_tail_failure_keeps_immutable_receipt_then_recovers(app_ctx, inline_jobs, monkeypatch, crash_before_receipt):
    app_ctx.config["AGENT_MAX_PARALLEL_SHOTS"] = 1
    row, version, registry = fixture(complete=False)
    start(row, version, registry)
    engine.tick_production(row, registry)
    engine._poll(row, version, registry)
    assert engine._extract_tail(row, version, "s01", registry)
    tail = versions.latest_task(row, version.version, "tail_frame", "s01")
    original = (tail.invocation_id, deepcopy(tail.artifact_ids), deepcopy(tail.error))
    StorageService.resolve(usable_artifact(tail).file_path).unlink()
    attention(row)
    spec = registry.get("extract_frame")
    def outage(*args):
        raise AppError("FRAME_EXTRACTION_FAILED", "Media service still unavailable", 503)
    registry._specs["extract_frame"] = replace(spec, handler=outage)
    command = retry_command(priced(row, version, "s02", "retry"))
    if crash_before_receipt:
        original_save = actions._save_receipt
        def interrupted(run, key, **changes):
            if changes.get("status") == "completed":
                raise RuntimeError("after failed restoration before result receipt")
            return original_save(run, key, **changes)
        monkeypatch.setattr(actions, "_save_receipt", interrupted)
        with pytest.raises(RuntimeError):
            actions.apply_command(row, command, registry)
        monkeypatch.setattr(actions, "_save_receipt", original_save)
    result = actions.apply_command(row, command, registry)
    assert result["status"] == "production_attention"
    assert versions.latest_task(row, version.version, "tail_frame", "s01").id == tail.id
    assert tail.status == "stale"
    assert (tail.invocation_id, tail.artifact_ids, tail.error) == original
    assert actions.apply_command(row, command, registry) == result
    assert paid_count() == 1
    registry._specs["extract_frame"] = spec
    next_command = retry_command(priced(row, version, "s02", "retry"), key="tail-again")
    assert actions.apply_command(row, next_command, registry)["status"] == "producing"
    current = versions.latest_task(row, version.version, "tail_frame", "s01")
    assert current.attempt == tail.attempt + 1 and usable_artifact(current)
    assert drive(row, registry) == "awaiting_video_review"
    assert paid_count() == 3
