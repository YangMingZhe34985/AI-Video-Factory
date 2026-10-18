"""Phase D acceptance through authenticated API inbox and persisted LangGraph."""

from copy import deepcopy
from dataclasses import replace
import time

import pytest

from app.agent import plan_versions as versions
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, AgentShotTask, ToolInvocation
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from tests.test_story_review import advance, act, storyboard, view

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_VISION_MODEL="qwen3.7-plus")


def settle_production(run_id, registry=None):
    for _ in range(180):
        row = advance(run_id, registry)
        if row.status != "producing":
            return row
        time.sleep(0.03)
    pytest.fail("Production did not settle")


def approved(client):
    run_id, board = storyboard(client)
    assert act(client, run_id, "approve_storyboard", plan_version=board["plan_version"]).status_code == 202
    assert advance(run_id).status == "storyboard_approved"
    return run_id, board


def start(client, run_id, board, registry=None, key="start"):
    response = act(client, run_id, "start_production", plan_version=board["plan_version"], request_key=key)
    assert response.status_code == 202, response.json
    return settle_production(run_id, registry)


def quote(client, run_id, board, sid, operation="redo"):
    response = client.post(f"/api/agent/runs/{run_id}/production/quote", json={
        "base_version": board["plan_version"], "shot_id": sid, "operation": operation})
    assert response.status_code == 200, response.json
    return response.json["data"]


def test_explicit_start_restart_redo_only_and_final_clip_review(app_ctx, client):
    run_id, initial = approved(client)
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == 0
    advance(run_id)
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == 0
    row = start(client, run_id, initial)
    assert row.status == "awaiting_video_review", row.error or row.snapshot
    board = view(client, run_id)
    assert all(shot["status"] == "success" for shot in board["production"]["shots"])
    assert board["production"]["estimates"]["remaining_credits"] == 0
    count = ToolInvocation.query.filter_by(tool_name="animate_shot").count()
    spent = BudgetGuard.spent(run_id)
    assert act(client, run_id, "start_production", plan_version=initial["plan_version"], request_key="start").status_code == 202
    assert settle_production(run_id).status == "awaiting_video_review"
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == count
    assert BudgetGuard.spent(run_id) == spent
    tail = next(shot for shot in board["plan"]["shots"] if shot["transition_in"] == "tail_frame")
    source = tail["depends_on"][0]
    prior = {shot["shot_id"]: shot["artifact_id"] for shot in board["production"]["shots"]}
    estimate = quote(client, run_id, board, source)
    assert set(estimate["affected_shot_ids"]) == {source, tail["shot_id"]}
    response = act(client, run_id, "redo_shot", base_version=board["plan_version"], shot_id=source,
        quote_id=estimate["quote_id"], scope="only", request_key="redo-one")
    assert response.status_code == 202, response.json
    row = settle_production(run_id)
    assert row.status == "awaiting_video_review", row.error or row.snapshot
    after = view(client, run_id)
    assert after["plan_version"] > board["plan_version"]
    for shot in after["production"]["shots"]:
        assert (shot["artifact_id"] != prior[shot["shot_id"]]) == (shot["shot_id"] == source)
    assert tail["shot_id"] in after["production"]["kept_downstream"]
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == count + 1
    response = act(client, run_id, "approve_videos", plan_version=after["plan_version"], request_key="clips")
    assert response.status_code == 202, response.json
    assert settle_production(run_id).status == "videos_approved"
    assert not ToolInvocation.query.filter_by(tool_name="package_project").count()


def test_one_invalid_shot_preserves_independent_work_then_returns_to_editable_plan(app_ctx, client):
    run_id, board = approved(client)
    registry = build_default_registry()
    original = registry.get("animate_shot")
    rejected = board["plan"]["shots"][0]["shot_id"]

    def handler(data, ctx):
        if db.session.get(AgentShotTask, ctx.shot_task_id).target_id == rejected:
            raise AppError("INVALID_INPUT", "Injected unsupported parameter", 422)
        return original.handler(data, ctx)

    registry._specs["animate_shot"] = replace(original, handler=handler)
    row = start(client, run_id, board, registry)
    assert row.status == "production_attention", row.error or row.snapshot
    current = view(client, run_id)
    shots = current["production"]["shots"]
    assert any(item["status"] == "failed" for item in shots)
    successful = {item["shot_id"]: item["artifact_id"] for item in shots if item["status"] == "success"}
    assert successful
    assert act(client, run_id, "review_plan", plan_version=board["plan_version"], request_key="replan").status_code == 202
    assert advance(run_id).status == "awaiting_storyboard"
    # The completed independent outputs and their original immutable attempts
    # survive returning to Director review; no automatic whole-film regeneration.
    for sid, artifact in successful.items():
        task = versions.latest_task(AgentRun.query.filter_by(run_id=run_id).one(), board["plan_version"], "video", sid)
        assert task.status == "success" and task.artifact_ids == [artifact]
