"""Phase C acceptance through the real inbox, persisted graph and Mock image Jobs."""

from copy import deepcopy
from dataclasses import replace
import time

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.graph_v2 import build_graph
from app.agent.worker import AgentWorker, checkpoint_path
from app.extensions import db
from app.models import AgentRun, AgentPlanVersion, AgentShotTask, ToolInvocation
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from tests.test_agent_v2_graph import create, image

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
                               AGENT_VISION_MODEL="qwen3.7-plus")
TEXT = "制作猫咪探索城市的故事短片，约2分钟，使用wan2.7系列，不要使用happy-horse"


def advance(run_id, registry=None):
    with SqliteSaver.from_conn_string(str(checkpoint_path())) as saver:
        AgentWorker(None, build_graph(saver, registry)).advance(run_id)
    db.session.expire_all()
    return AgentRun.query.filter_by(run_id=run_id).one()


def settle(run_id, registry=None):
    for _ in range(160):
        row = advance(run_id, registry)
        if row.status not in {"queued", "understanding", "planning", "previewing", "researching"}:
            return row
        time.sleep(0.02)
    pytest.fail("Story did not settle at an approval gate")


def act(client, run_id, action, **payload):
    return client.post(f"/api/agent/runs/{run_id}/actions", json={"action": action, **payload})


def view(client, run_id):
    response = client.get(f"/api/agent/runs/{run_id}")
    assert response.status_code == 200, response.json
    return response.json["data"]


def storyboard(client, text=TEXT, ids=()):
    run_id = create(text, ids, budget=500)
    row = settle(run_id)
    assert row.status in {"awaiting_characters", "awaiting_storyboard"}, row.error or row.snapshot
    if row.status == "awaiting_characters":
        response = act(client, run_id, "approve_characters")
        assert response.status_code == 202, response.json
        row = settle(run_id)
    assert row.status == "awaiting_storyboard", row.error or row.snapshot
    return run_id, view(client, run_id)


def test_two_minute_story_stops_at_both_reviews_and_never_calls_video(app_ctx, client):
    run_id = create(TEXT, budget=500)
    row = settle(run_id)
    assert row.status == "awaiting_characters", row.error or row.snapshot
    initial = view(client, run_id)
    assert initial["previews"]["characters"]
    assert initial["estimates"]["preview_spent_credits"] > 0
    assert not ToolInvocation.query.filter(ToolInvocation.tool_name.in_(["animate_shot", "generate_video", "produce_shot"])).count()
    assert act(client, run_id, "approve_characters").status_code == 202
    row = settle(run_id)
    assert row.status == "awaiting_storyboard", row.error or row.snapshot
    current = view(client, run_id)
    assert current["plan_issues"] == []
    assert sum(shot["duration_sec"] for shot in current["plan"]["shots"]) == 120
    assert current["estimates"]["video_credits"] == 120
    assert all(v["status"] == "success" for v in current["previews"]["keyframes"].values())
    assert act(client, run_id, "approve_storyboard", plan_version=current["plan_version"]).status_code == 202
    row = settle(run_id)
    assert row.status == "storyboard_approved", row.error
    count, spent = ToolInvocation.query.count(), BudgetGuard.spent(run_id)
    for _ in range(3):
        advance(run_id)
    assert ToolInvocation.query.count() == count
    assert BudgetGuard.spent(run_id) == spent
    assert not ToolInvocation.query.filter(ToolInvocation.tool_name.in_(["animate_shot", "generate_video", "produce_shot"])).count()


def test_single_edit_rewrites_only_changed_shot_and_requires_stale_repair(app_ctx, client):
    run_id, before = storyboard(client)
    plan = deepcopy(before["plan"])
    plan["shots"][0]["summary"] = "猫咪在蓝色门前发现一张城市地图"
    prompts_before = ToolInvocation.query.filter_by(tool_name="write_shot_prompts").count()
    response = act(client, run_id, "edit_plan", plan=plan, base_version=before["plan_version"], request_key="edit-one")
    assert response.status_code == 202, response.json
    settle(run_id)
    after = view(client, run_id)
    assert after["plan_version"] > before["plan_version"]
    assert ToolInvocation.query.filter_by(tool_name="write_shot_prompts").count() == prompts_before + 1
    assert after["previews"]["keyframes"]["s01"]["stale"]
    assert act(client, run_id, "approve_storyboard", plan_version=after["plan_version"]).status_code == 409
    assert act(client, run_id, "regenerate_stale", request_key="stale-one").status_code == 202
    settle(run_id)
    final = view(client, run_id)
    assert final["previews"]["keyframes"]["s01"]["status"] == "success"
    for sid in before["previews"]["keyframes"]:
        if sid != "s01":
            assert before["previews"]["keyframes"][sid]["artifact_id"] == final["previews"]["keyframes"][sid]["artifact_id"]
    assert AgentPlanVersion.query.filter_by(run_id=run_id, version=before["plan_version"]).one().plan == before["plan"]


def test_regeneration_idempotency_conflict_and_receipt_survive_worker_restart(app_ctx, client):
    run_id, before = storyboard(client)
    payload = {"target_type": "keyframe", "target_id": "s01", "request_key": "redo"}
    response = act(client, run_id, "regenerate", **payload)
    assert response.status_code == 202, response.json
    assert act(client, run_id, "regenerate", **payload).status_code == 202
    settle(run_id)
    spent = BudgetGuard.spent(run_id)
    current = view(client, run_id)
    assert current["previews"]["keyframes"]["s01"]["artifact_id"] != before["previews"]["keyframes"]["s01"]["artifact_id"]
    assert act(client, run_id, "regenerate", **payload).status_code == 202
    assert BudgetGuard.spent(run_id) == spent
    conflict = act(client, run_id, "regenerate", **{**payload, "prompt": "另一张图"})
    assert conflict.status_code == 409
    assert conflict.json["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert AgentRun.query.filter_by(run_id=run_id).one().snapshot["story_action_receipts"]["redo"]


def test_character_redo_marks_related_frames_stale_without_automatic_regeneration(app_ctx, client):
    run_id, before = storyboard(client)
    cid = next(iter(before["previews"]["characters"]))
    frame_jobs = ToolInvocation.query.filter_by(tool_name="generate_image").count()
    response = act(client, run_id, "regenerate", target_type="character", target_id=cid, request_key="character-redo")
    assert response.status_code == 202, response.json
    row = settle(run_id)
    assert row.status == "awaiting_storyboard", row.error or row.snapshot
    after = view(client, run_id)
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == frame_jobs + 1
    assert any(item["stale"] for item in after["previews"]["keyframes"].values())
    assert act(client, run_id, "approve_storyboard", plan_version=after["plan_version"]).status_code == 409
    for sid, old in before["previews"]["keyframes"].items():
        assert after["previews"]["keyframes"][sid]["artifact_id"] == old["artifact_id"]


def test_invalid_business_edit_stays_editable_then_repaired(app_ctx, client):
    run_id, before = storyboard(client)
    plan = deepcopy(before["plan"])
    plan["shots"][0]["duration_sec"] = 200
    response = act(client, run_id, "edit_plan", plan=plan, base_version=before["plan_version"], request_key="bad-duration")
    assert response.status_code == 202, response.json
    row = settle(run_id)
    assert row.status == "awaiting_storyboard", row.error
    invalid = view(client, run_id)
    assert {issue["code"] for issue in invalid["plan_issues"]} >= {"DURATION_MISMATCH", "MODEL_CAPABILITY_MISMATCH"}
    response = act(client, run_id, "edit_plan", plan=before["plan"], base_version=invalid["plan_version"], request_key="fix-duration")
    assert response.status_code == 202, response.json
    settle(run_id)
    assert view(client, run_id)["plan_issues"] == []


def test_version_conflict_and_schema_error_do_not_queue_commands(app_ctx, client):
    run_id, before = storyboard(client)
    response = act(client, run_id, "edit_plan", plan=before["plan"], base_version=before["plan_version"] + 20, request_key="conflict")
    assert response.status_code == 409
    bad = deepcopy(before["plan"])
    bad["shots"][0]["motion"]["mode"] = "t2v"
    response = act(client, run_id, "edit_plan", plan=bad, base_version=before["plan_version"], request_key="schema")
    assert response.status_code == 422
    assert response.json["error"]["code"] == "INVALID_PRODUCTION_PLAN"
    assert AgentRun.query.filter_by(run_id=run_id).one().command is None


def test_reject_cancels_at_character_gate(app_ctx, client):
    run_id = create(TEXT, budget=500)
    assert settle(run_id).status == "awaiting_characters"
    assert act(client, run_id, "reject").status_code == 202
    assert settle(run_id).status == "cancelled"


def test_research_selected_references_skip_character_generation_and_reach_storyboard(app_ctx, client):
    from tests.test_research_agent import answer
    run_id = create("制作 DeepSeek 和 ChatGPT 的 AI 拟人故事视频，约2分钟，使用wan2.7，不要happy-horse", budget=500)
    row = settle(run_id)
    assert row.status == "awaiting_input", row.error or row.snapshot
    submission = answer(row.snapshot)
    response = client.post(f"/api/agent/runs/{run_id}/actions", json=submission)
    assert response.status_code == 202, response.json
    row = settle(run_id)
    assert row.status == "awaiting_storyboard", row.error or row.snapshot
    current = view(client, run_id)
    assert all(c["reference"]["source"] == "research" for c in current["story"]["characters"])
    assert not AgentShotTask.query.filter_by(run_id=run_id, target_type="character").count()
    assert current["plan_issues"] == []

def test_explicit_review_model_overrides_default_without_relaxing_exclusions(app_ctx, client):
    from app.models import ModelRegistry
    from app.services.model_service import ModelService
    base = ModelService.get_model("wan2.7-i2v")
    for model_id in ("review-model-i2v", "happyhorse-review-i2v"):
        db.session.add(ModelRegistry(model_id=model_id, display_name=model_id, task_type=base.task_type,
            provider=base.provider, adapter_name=base.adapter_name, enabled=True,
            default_params=deepcopy(base.default_params), parameter_schema=deepcopy(base.parameter_schema),
            capabilities=deepcopy(base.capabilities)))
    db.session.commit()
    run_id, before = storyboard(client, text="制作猫咪探索城市的故事短片，约2分钟，不要使用happy-horse")
    plan = deepcopy(before["plan"])
    plan["shots"][0]["motion"]["model_id"] = "review-model-i2v"
    assert act(client, run_id, "edit_plan", plan=plan, base_version=before["plan_version"], request_key="choose-model").status_code == 202
    assert settle(run_id).status == "awaiting_storyboard"
    selected = view(client, run_id)
    assert selected["plan_issues"] == []
    assert selected["plan"]["shots"][0]["motion"]["model_id"] == "review-model-i2v"
    plan = deepcopy(selected["plan"])
    plan["shots"][0]["motion"]["model_id"] = "happyhorse-review-i2v"
    assert act(client, run_id, "edit_plan", plan=plan, base_version=selected["plan_version"], request_key="excluded-model").status_code == 202
    assert settle(run_id).status == "awaiting_storyboard"
    refused = view(client, run_id)
    assert "MODEL_CAPABILITY_MISMATCH" in {issue["code"] for issue in refused["plan_issues"]}
    assert act(client, run_id, "approve_storyboard", plan_version=refused["plan_version"]).status_code != 202
    assert not ToolInvocation.query.filter(ToolInvocation.tool_name.in_(["animate_shot", "generate_video", "produce_shot"])).count()
