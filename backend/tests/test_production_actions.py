"""D4 quotes, explicit production decisions and immutable partial redos (offline Mock)."""

from copy import deepcopy
import time

import pytest
from pydantic import ValidationError

from app.agent import plan_versions as versions, production_actions as actions
from app.agent.preview_production import planned_inputs
from app.agent.production_engine import tick_production
from app.agent.production_plan import normalized_plan
from app.agent.production_state import latest_tasks, usable_artifact, video_inputs
from app.agent.protocol import ProductionQuote, RunAction
from app.api import AppError
from app.extensions import db
from app.models import AgentPlanVersion, AgentRun, AgentShotTask, ApiTask, ToolInvocation
from app.services.model_service import ModelService
from app.services.storage_service import StorageService
from app.skills.budget import BudgetGuard
from app.skills.tools.extract_frame import MOCK_VIDEO_BYTES
from tests.test_story_media import private_artifact, task
from tests.test_story_previews import setup
from tests.test_production_recovery import inline_jobs

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_MAX_SHOT_AUTO_REPAIRS=0)


def fixture(*, complete=True, tail=True):
    row, initial, registry = setup(characters=False)
    row.owner_id = "local"
    db.session.commit()
    plan = deepcopy(initial.plan)
    if tail:
        plan["shots"][1]["transition_in"] = "tail_frame"
        plan["shots"][1]["scene_id"] = plan["shots"][0]["scene_id"]
        plan["shots"][1]["first_frame"] = {"method": "tail_frame", "image_mode": None,
            "model_id": None, "prompt": "", "reference_artifact_ids": []}
    plan = normalized_plan(plan)
    version = versions.create_version(row, plan, initial.story_package, initial.check, author="user")
    for shot in version.plan["shots"]:
        sid = shot["shot_id"]
        if shot["first_frame"]["method"] != "tail_frame":
            frame = private_artifact(row)
            task(row, version, "keyframe", sid, planned_inputs(row, version, "keyframe", sid), frame)
        if complete:
            video = private_artifact(row, "i2v_video", MOCK_VIDEO_BYTES)
            current = task(row, version, "video", sid, video_inputs(row, version, shot), video)
            current.job_id = video.job.job_id
            current.estimated_cost = shot["duration_sec"]
            db.session.commit()
            frame = private_artifact(row)
            task(row, version, "tail_frame", sid, {"video_artifact_id": video.artifact_id,
                "position": "last", "timestamp_sec": None}, frame)
    row.status = "awaiting_video_review" if complete else "storyboard_approved"
    row.snapshot = {**row.snapshot, "production": {"approved_version": version.version if complete else None,
        "plan_version": version.version, "repair_budget_credits": 0, "status": row.status}}
    db.session.commit()
    return row, version, registry


def priced(row, version, sid="s01", operation="redo", **kwargs):
    return actions.quote(row, {"shot_id": sid, "base_version": version.version, "operation": operation, **kwargs})


def redo_command(quote, scope="only", key="redo", **kwargs):
    return {"action": "redo_shot", "shot_id": quote["shot_id"], "base_version": quote["base_version"],
        "quote_id": quote["quote_id"], "scope": scope, "request_key": key, **kwargs}


def drive(row, registry):
    for _ in range(120):
        result = tick_production(row, registry)
        if result != "producing":
            return result
        time.sleep(.02)
    pytest.fail("Production did not settle")


def test_quote_is_read_only_and_includes_actual_tail_closure(app_ctx):
    row, version, _registry = fixture()
    before = (AgentPlanVersion.query.count(), AgentShotTask.query.count(), ToolInvocation.query.count(), deepcopy(row.snapshot))
    quoted = priced(row, version)
    assert quoted["affected_shot_ids"] == ["s01", "s02"]
    assert quoted["kept_shot_ids"] == ["s02"]
    assert quoted["estimated_credits"] == {"only": 5, "cascade": 10}
    assert (AgentPlanVersion.query.count(), AgentShotTask.query.count(), ToolInvocation.query.count(), row.snapshot) == before
    assert priced(row, version) == quoted


@pytest.mark.parametrize("scope,count", [("only", 1), ("cascade", 2), ("cancel", 0)])
def test_redo_scope_preserves_unrelated_receipts_and_never_double_submits(app_ctx, scope, count):
    row, version, registry = fixture()
    originals = latest_tasks(row, version)
    quoted = priced(row, version)
    command = redo_command(quoted, scope)
    before = BudgetGuard.spent(row.run_id)
    result = actions.apply_command(row, command, registry)
    assert actions.apply_command(row, command, registry) == result
    if scope == "cancel":
        assert versions.current_version(row).version == version.version
        assert BudgetGuard.spent(row.run_id) == before
        return
    assert result["plan_version"] == version.version + 1
    assert drive(row, registry) == "awaiting_video_review"
    current = latest_tasks(row, versions.current_version(row))
    assert current["s03"].artifact_ids == originals["s03"].artifact_ids
    assert current["s01"].artifact_ids != originals["s01"].artifact_ids
    assert (current["s02"].artifact_ids != originals["s02"].artifact_ids) == (scope == "cascade")
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == count
    assert BudgetGuard.spent(row.run_id) == before + count * 5
    assert set(row.snapshot["production"]["retained_sources"]) == ({"s02"} if scope == "only" else set())
    assert versions.get_version(row, version.version).plan == version.plan
    assert all(usable_artifact(item) for item in originals.values())


def test_quote_binds_price_and_prompt_and_current_version(app_ctx):
    row, version, _registry = fixture()
    first = priced(row, version, motion_prompt="镜头缓慢拉远")
    with pytest.raises(AppError) as error:
        actions.validate_command(row, redo_command(first, motion_prompt="镜头缓慢推进"))
    assert error.value.code == "PRODUCTION_QUOTE_EXPIRED"
    model = ModelService.get_model("wan2.7-i2v")
    model.capabilities = {**model.capabilities, "pricing": {"unit": "second", "credits_per_unit": 2}}
    db.session.commit()
    with pytest.raises(AppError) as error:
        actions.validate_command(row, redo_command(first, motion_prompt="镜头缓慢拉远"))
    assert error.value.code == "PRODUCTION_QUOTE_EXPIRED"
    with pytest.raises(AppError) as error:
        priced(row, type("Version", (), {"version": version.version + 10})())
    assert error.value.code == "PLAN_VERSION_CONFLICT"


def test_changed_motion_only_changes_one_shot_and_keeps_static_previews(app_ctx):
    row, version, registry = fixture()
    frames = {item.target_id: item.artifact_ids for item in versions.list_tasks(row, version.version) if item.target_type == "keyframe"}
    quoted = priced(row, version, motion_prompt="缓慢拉远镜头")
    result = actions.apply_command(row, redo_command(quoted, motion_prompt="缓慢拉远镜头"), registry)
    current = versions.current_version(row)
    assert current.plan["shots"][0]["motion"]["prompt"] == "缓慢拉远镜头"
    assert current.plan["shots"][1:] == version.plan["shots"][1:]
    assert {item.target_id: item.artifact_ids for item in versions.list_tasks(row, current.version) if item.target_type == "keyframe"} == frames
    assert result["status"] == "producing"


def test_incomplete_initial_work_is_quoted_without_charging_completed_independent_shots(app_ctx):
    row, version, _registry = fixture()
    tasks = latest_tasks(row, version)
    db.session.delete(tasks["s02"])
    row.status = "production_attention"
    db.session.commit()
    quoted = priced(row, version)
    assert quoted["continuation_shot_ids"] == ["s02"]
    assert quoted["estimated_credits"] == {"only": 10, "cascade": 10}
    assert quoted["kept_shot_ids"] == []


def test_unknown_submission_is_never_retried_and_survives_an_unrelated_new_version(app_ctx):
    row, version, registry = fixture()
    old = latest_tasks(row, version)["s03"]
    old.status = "failed"
    old.job_id = None
    old.artifact_ids = []
    old.error = {"category": "submit_unknown", "submission_state": "unknown", "recovery_action": "stop"}
    row.status = "production_attention"
    db.session.commit()
    for operation in ("retry", "redo"):
        with pytest.raises(AppError) as error:
            priced(row, version, "s03", operation)
        assert error.value.code == "UNSAFE_RETRY"
    actions.apply_command(row, redo_command(priced(row, version)), registry)
    copied = latest_tasks(row, versions.current_version(row))["s03"]
    assert copied.status == "failed" and copied.error == old.error
    assert copied.inputs_hash == old.inputs_hash
    assert drive(row, registry) == "production_attention"
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == 1


def test_cascade_refuses_an_unknown_downstream_but_cancel_stays_free(app_ctx):
    row, version, registry = fixture()
    item = latest_tasks(row, version)["s02"]
    item.status, item.job_id, item.artifact_ids = "failed", None, []
    item.error = {"category": "submit_unknown", "submission_state": "unknown"}
    row.status = "production_attention"
    db.session.commit()
    quoted = priced(row, version)
    assert quoted["estimated_credits"]["cascade"] is None
    with pytest.raises(AppError) as error:
        actions.apply_command(row, redo_command(quoted, "cascade"), registry)
    assert error.value.code == "UNSAFE_RETRY"
    assert actions.apply_command(row, redo_command(quoted, "cancel"), registry)["status"] == "production_attention"


def test_begin_is_explicit_and_replay_does_not_generate_video(app_ctx):
    row, version, registry = fixture(complete=False)
    command = {"action": "start_production", "plan_version": version.version, "request_key": "start"}
    assert actions.validate_command(row, command) == 15
    result = actions.apply_command(row, command, registry)
    assert result["status"] == "producing"
    assert not ToolInvocation.query.filter_by(tool_name="animate_shot").count()
    assert actions.apply_command(row, command, registry) == result
    assert drive(row, registry) == "awaiting_video_review"
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == 3


def test_budget_failure_and_disabled_production_never_queue_work(app_ctx, client):
    row, version, _registry = fixture(complete=False)
    row.request = {**row.request, "budget_limit": BudgetGuard.spent(row.run_id) + 15}
    db.session.commit()
    payload = {"action": "start_production", "plan_version": version.version, "repair_budget_credits": 1, "request_key": "budget"}
    response = client.post(f"/api/agent/runs/{row.run_id}/actions", json=payload)
    assert response.status_code == 402, response.json
    assert row.command is None
    app_ctx.config["AGENT_STORY_PRODUCTION_ENABLED"] = False
    assert client.post(f"/api/agent/runs/{row.run_id}/actions", json={**payload, "repair_budget_credits": 0}).status_code == 409
    assert not ToolInvocation.query.filter_by(tool_name="animate_shot").count()


def test_api_owner_inbox_idempotency_and_long_key(app_ctx, client):
    row, version, _registry = fixture()
    endpoint = f"/api/agent/runs/{row.run_id}"
    quoted = client.post(endpoint + "/production/quote", json={"shot_id": "s01", "base_version": version.version, "operation": "redo"})
    assert quoted.status_code == 200, quoted.json
    command = redo_command(quoted.json["data"], key="r" * 128)
    first = client.post(endpoint + "/actions", json=command)
    assert first.status_code == 202, first.json
    assert first.json["data"]["action_estimated_credits"] == 5
    assert client.post(endpoint + "/actions", json=command).status_code == 202
    assert client.post(endpoint + "/actions", json={**command, "scope": "cascade"}).status_code == 409
    assert len(row.command["command_id"]) < 80
    assert not ToolInvocation.query.filter_by(tool_name="animate_shot").count()
    row.owner_id = "other"
    db.session.commit()
    assert client.post(endpoint + "/actions", json=command).status_code == 404
    assert client.post(endpoint + "/production/quote", json={"shot_id": "s01", "base_version": version.version, "operation": "redo"}).status_code == 404


def test_review_plan_and_approve_video_require_current_complete_version(app_ctx):
    row, version, registry = fixture()
    assert actions.apply_command(row, {"action": "approve_videos", "plan_version": version.version, "request_key": "approve"}, registry)["status"] == "videos_approved"
    row.status = "production_attention"
    db.session.commit()
    before = AgentShotTask.query.count()
    assert actions.apply_command(row, {"action": "review_plan", "plan_version": version.version, "request_key": "review"}, registry)["status"] == "awaiting_storyboard"
    assert AgentShotTask.query.count() == before
    assert row.snapshot["production"]["approved_version"] is None


def test_inflight_tasks_prevent_new_quotes_and_approvals(app_ctx):
    row, version, _registry = fixture()
    item = latest_tasks(row, version)["s03"]
    item.status = "running"
    db.session.commit()
    with pytest.raises(AppError) as error:
        priced(row, version)
    assert error.value.code == "INVALID_AGENT_STATE"
    with pytest.raises(AppError):
        actions.validate_command(row, {"action": "approve_videos", "plan_version": version.version, "request_key": "approve"})


def test_crash_after_version_commit_finishes_same_redo_once(app_ctx, monkeypatch):
    row, version, registry = fixture()
    command = redo_command(priced(row, version))
    original = actions._copy_tasks
    def crash(*_a, **_k):
        raise RuntimeError("crash after immutable version commit")
    monkeypatch.setattr(actions, "_copy_tasks", crash)
    with pytest.raises(RuntimeError):
        actions.apply_command(row, command, registry)
    number = versions.current_version(row).version
    monkeypatch.setattr(actions, "_copy_tasks", original)
    assert actions.apply_command(row, command, registry)["plan_version"] == number
    assert versions.current_version(row).version == number == version.version + 1
    assert drive(row, registry) == "awaiting_video_review"
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == 1


@pytest.mark.parametrize("payload", [
    {"action": "start_production", "plan_version": 1},
    {"action": "start_production", "plan_version": 1, "request_key": "a", "repair_budget_credits": True},
    {"action": "start_production", "plan_version": 1, "request_key": "a", "repair_budget_credits": float("inf")},
    {"action": "redo_shot", "shot_id": "s01", "base_version": 1, "quote_id": "q", "request_key": "a"},
    {"action": "retry_shot", "shot_id": "s01", "base_version": 1, "quote_id": "q", "request_key": "a", "motion_prompt": "changed"},
    {"action": "approve_videos", "plan_version": 1, "request_key": "a", "plan": {}},
])
def test_production_schema_rejects_ambiguous_or_unrelated_fields(payload):
    with pytest.raises(ValidationError):
        RunAction.model_validate(payload)


def test_quote_schema_does_not_accept_provider_models_or_retry_edits():
    for extra in ({"model_id": "other"}, {"motion_prompt": "edit"}):
        with pytest.raises(ValidationError):
            ProductionQuote.model_validate({"shot_id": "s01", "base_version": 1, "operation": "retry", **extra})


def test_manual_retry_uses_explicit_quote_when_auto_allowance_is_zero(app_ctx, inline_jobs, monkeypatch):
    from app.adapters.mock import MockAdapter
    original = MockAdapter.submit
    calls = {"count": 0}
    def fail_once(adapter, payload):
        calls["count"] += 1
        if calls["count"] == 1:
            raise AppError("RATE_LIMITED", "Injected rejection before submission", 429)
        return original(adapter, payload)
    monkeypatch.setattr(MockAdapter, "submit", fail_once)
    row, version, registry = fixture(complete=False)
    actions.apply_command(row, {"action": "start_production", "plan_version": version.version, "request_key": "start"}, registry)
    assert drive(row, registry) == "production_attention"
    row.status = "production_attention"
    db.session.commit()
    failed = next(item for item in latest_tasks(row, version).values() if item.status == "failed")
    quoted = priced(row, version, failed.target_id, "retry")
    assert quoted["can_retry"]
    assert quoted["estimated_credits"]["only"] >= 5
    before = ToolInvocation.query.filter_by(tool_name="animate_shot").count()
    command = {"action": "retry_shot", "base_version": version.version, "shot_id": failed.target_id,
               "quote_id": quoted["quote_id"], "request_key": "manual-retry"}
    actions.apply_command(row, command, registry)
    actions.apply_command(row, command, registry)
    assert drive(row, registry) == "awaiting_video_review"
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() <= before + 2
    assert row.snapshot["production_repairs"][str(failed.id)]["automatic"] is False
    assert row.snapshot["production"]["repair_budget_credits"] == 0


def test_missing_finished_video_recovers_original_download_during_review(app_ctx, inline_jobs):
    row, version, registry = fixture(complete=False)
    actions.apply_command(row, {"action": "start_production", "plan_version": version.version, "request_key": "start"}, registry)
    assert drive(row, registry) == "awaiting_video_review"
    row.status = "awaiting_video_review"
    db.session.commit()
    selected = latest_tasks(row, version)["s01"]
    artifact = usable_artifact(selected)
    original_api_ids = [item.id for item in ApiTask.query.order_by(ApiTask.id)]
    before = (BudgetGuard.spent(row.run_id), ToolInvocation.query.filter_by(tool_name="animate_shot").count())
    StorageService.resolve(artifact.file_path).unlink()
    with pytest.raises(AppError) as error:
        priced(row, version)
    assert error.value.code == "UNSAFE_RETRY"
    quoted = priced(row, version, "s01", "retry")
    assert quoted["can_retry"] and quoted["estimated_credits"]["only"] == 0
    assert selected.status == "success"  # The quote does not mutate persisted tasks.
    command = {"action": "retry_shot", "base_version": version.version, "shot_id": "s01",
               "quote_id": quoted["quote_id"], "request_key": "download"}
    actions.apply_command(row, command, registry)
    assert drive(row, registry) == "awaiting_video_review", {"snapshot": row.snapshot, "tasks": [t.to_dict() for t in latest_tasks(row, version).values()]}
    assert usable_artifact(latest_tasks(row, version)["s01"])
    assert [item.id for item in ApiTask.query.order_by(ApiTask.id)] == original_api_ids
    assert (BudgetGuard.spent(row.run_id), ToolInvocation.query.filter_by(tool_name="animate_shot").count()) == before


def test_price_increase_after_version_commit_never_exceeds_original_authorization(app_ctx, monkeypatch):
    row, version, registry = fixture()
    command = redo_command(priced(row, version))
    original = actions._copy_tasks
    monkeypatch.setattr(actions, "_copy_tasks", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError):
        actions.apply_command(row, command, registry)
    number = versions.current_version(row).version
    model = ModelService.get_model("wan2.7-i2v")
    model.capabilities = {**model.capabilities, "pricing": {"unit": "second", "credits_per_unit": 2}}
    db.session.commit()
    monkeypatch.setattr(actions, "_copy_tasks", original)
    with pytest.raises(AppError) as error:
        actions.apply_command(row, command, registry)
    assert error.value.code == "PRODUCTION_QUOTE_EXPIRED"
    assert versions.current_version(row).version == number
    assert not ToolInvocation.query.filter_by(tool_name="animate_shot").count()
