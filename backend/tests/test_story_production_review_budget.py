"""Returning to review prices exact reusable videos without rewriting old checks."""

from copy import deepcopy

import pytest
from flask_jwt_extended import create_access_token

from app.adapters.mock import MockAdapter
from app.agent import plan_versions as versions, preview_production as previews
from app.agent.plan_check import check_plan
from app.agent.production_actions import apply_command
from app.agent.production_engine import begin_production, validate_start
from app.agent.production_state import remaining_video_cost, video_inputs
from app.agent.story_actions import public_view, validate_command
from app.api import AppError
from app.extensions import db
from app.models import ToolInvocation
from app.services.job_run_service import JobRunService
from app.skills.budget import BudgetGuard
from tests.test_production_recovery import settle
from tests.test_story_previews import setup, create_keyframes

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
                               AGENT_STORY_PRODUCTION_ENABLED=True)


def partial_story(monkeypatch):
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    run, initial, registry = setup(characters=False)
    checked = check_plan(initial.plan, initial.story_package, run.snapshot["request_spec"], run=run)
    assert not checked["issues"]
    version = versions.create_version(run, checked["plan"], initial.story_package,
        {"issues": checked["issues"], "estimates": checked["estimates"]})
    create_keyframes(run, version, registry)
    original = MockAdapter.submit
    calls = []
    def submit(self, payload):
        calls.append(payload)
        if len(calls) == 3:
            raise AppError("API_TASK_FAILED", "Injected parameter rejection", 400,
                           payload={"response": {"code": "InvalidParameter"}})
        return original(self, payload)
    monkeypatch.setattr(MockAdapter, "submit", submit)
    run.status = "storyboard_approved"
    db.session.commit()
    begin_production(run, version)
    assert settle(run, registry) == "production_attention"
    assert len(calls) == 3
    result = apply_command(run, {"action": "review_plan", "plan_version": version.version,
                                 "request_key": "back-to-board"}, registry)
    run.status = result["status"]
    run.request = {**run.request, "budget_limit": BudgetGuard.spent(run.run_id) + 5}
    db.session.commit()
    return run, version, registry


def edited_version(run, old, change=None):
    plan = deepcopy(old.plan)
    plan["title"] = "回到审核后的标题"
    if change:
        change(plan)
    checked = check_plan(plan, old.story_package, run.snapshot["request_spec"], run=run,
                         preview_credits=previews.remaining_preview_cost(run, plan, old.story_package))
    version = versions.create_version(run, checked["plan"], old.story_package,
        {"issues": checked["issues"], "estimates": checked["estimates"]}, author="user", base_version=old.version)
    previews.prepare_previews(run, version)
    return version


def codes(view):
    return {item["code"] for item in view["plan_issues"]}


def test_unchanged_completed_shots_do_not_block_returned_review_with_double_budget(app_ctx, monkeypatch):
    run, old, registry = partial_story(monkeypatch)
    version = edited_version(run, old)
    saved = deepcopy(version.check)
    assert "BUDGET_EXCEEDED" in {item["code"] for item in saved["issues"]}
    assert remaining_video_cost(run, version) == 5
    before_calls, before_spent = ToolInvocation.query.count(), BudgetGuard.spent(run.run_id)
    assert "BUDGET_EXCEEDED" not in codes(public_view(run))
    assert validate_command(run, {"action": "approve_storyboard", "plan_version": version.version}) == 0
    assert version.check == saved
    assert ToolInvocation.query.count() == before_calls and BudgetGuard.spent(run.run_id) == before_spent


def test_changed_motion_is_charged_again_and_remains_blocking(app_ctx, monkeypatch):
    run, old, registry = partial_story(monkeypatch)
    version = edited_version(run, old, lambda plan: plan["shots"][0]["motion"].update(prompt="镜头向右移动，主体挥手"))
    assert remaining_video_cost(run, version) == 10
    assert "BUDGET_EXCEEDED" in codes(public_view(run))
    with pytest.raises(AppError) as error:
        validate_command(run, {"action": "approve_storyboard", "plan_version": version.version})
    assert error.value.code == "BUDGET_EXCEEDED"


def test_stale_keyframe_keeps_saved_budget_issue_until_preview_is_ready(app_ctx, monkeypatch):
    run, old, registry = partial_story(monkeypatch)
    version = edited_version(run, old, lambda plan: plan["shots"][0]["first_frame"].update(prompt="新静态构图，蓝色街道"))
    view = public_view(run)
    assert view["previews"]["keyframes"]["s01"]["stale"]
    assert "BUDGET_EXCEEDED" in codes(view)
    with pytest.raises(AppError) as error:
        validate_command(run, {"action": "approve_storyboard", "plan_version": version.version})
    assert error.value.code == "PREVIEW_INCOMPLETE"


def test_budget_projection_preserves_unrelated_plan_errors(app_ctx, monkeypatch):
    run, old, registry = partial_story(monkeypatch)
    version = edited_version(run, old, lambda plan: plan["shots"][0].update(scene_id="unknown-scene"))
    view = public_view(run)
    assert "INVALID_REFERENCE" in codes(view)
    assert "BUDGET_EXCEEDED" not in codes(view)
    with pytest.raises(AppError) as error:
        validate_command(run, {"action": "approve_storyboard", "plan_version": version.version})
    assert error.value.code == "INVALID_PRODUCTION_PLAN"


def test_original_phase_c_view_preserves_immutable_budget_check(app_ctx, monkeypatch):
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    run, old, registry = setup(characters=False)
    create_keyframes(run, old, registry)
    run.status = "awaiting_storyboard"
    run.request = {**run.request, "budget_limit": BudgetGuard.spent(run.run_id)}
    db.session.commit()
    version = edited_version(run, old)
    assert "production" not in run.snapshot
    assert public_view(run)["plan_issues"] == version.check["issues"]
    assert "BUDGET_EXCEEDED" in codes(public_view(run))


@pytest.mark.parametrize("prompt", ["", "   "])
def test_incomplete_returned_draft_remains_readable_without_authorizing_video(app_ctx, client, monkeypatch, prompt):
    run, old, registry = partial_story(monkeypatch)
    version = edited_version(run, old, lambda plan: plan["shots"][0]["motion"].update(prompt=prompt))
    app_ctx.config["API_AUTH_REQUIRED"] = True
    before_count, before_spent = ToolInvocation.query.count(), BudgetGuard.spent(run.run_id)
    token = create_access_token(identity=run.owner_id)
    response = client.get(f"/api/agent/runs/{run.run_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.json
    assert response.json["data"]["status"] == "awaiting_storyboard"
    assert video_inputs(run, version, version.plan["shots"][0]) is None
    with pytest.raises(AppError) as error:
        validate_start(run, version)
    assert error.value.code == "INVALID_PRODUCTION_PLAN"
    assert ToolInvocation.query.count() == before_count
    assert BudgetGuard.spent(run.run_id) == before_spent
