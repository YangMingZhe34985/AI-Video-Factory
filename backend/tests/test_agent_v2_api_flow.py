"""Public v2 API acceptance with real durable graphs and mocked providers."""

import time
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.graph import build_graph
from app.agent.worker import AgentWorker, checkpoint_path, worker_lock
from app.extensions import db
from app.models import AgentRun, ApiTask, Job, ToolInvocation

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_VISION_MODEL="qwen3.7-plus")


def tick():
    from app.agent.graph_v2 import build_graph as build_graph_v2
    with worker_lock(), SqliteSaver.from_conn_string(str(checkpoint_path())) as saver:
        AgentWorker(build_graph(saver), build_graph_v2(saver)).tick()
    db.session.expire_all()


def detail(client, run_id):
    response = client.get(f"/api/agent/runs/{run_id}")
    assert response.status_code == 200, response.json
    return response.json["data"]


def action(client, run_id, name, **fields):
    return client.post(f"/api/agent/runs/{run_id}/actions", json={"action": name, **fields})


def create(client, text, **fields):
    response = client.post("/api/agent/runs", json={"text": text, "request_key": "v2-flow", **fields})
    assert response.status_code == 202, response.json
    return response.json["data"]["run_id"]


def finish_production(client, run_id):
    for _ in range(200):
        tick()
        result = detail(client, run_id)
        if result["status"] != "producing":
            return result
        time.sleep(0.05)
    pytest.fail("v2 production did not reach a terminal or delivery state")


def test_upload_portrait_to_i2i_delivery_without_legacy_fields(app_ctx, client):
    stream = BytesIO()
    Image.new("RGB", (256, 256), "blue").save(stream, "PNG")
    stream.seek(0)
    upload = client.post("/api/agent/attachments", data={"file": (stream, "portrait.png")})
    assert upload.status_code == 201
    attachment_id = upload.json["data"]["attachment_id"]
    run_id = create(client, "把这张人像换成西装照", attachment_ids=[attachment_id])
    tick()
    planned = detail(client, run_id)
    assert planned["status"] == "awaiting_approval", planned
    assert planned["request_spec"]["recipe_hint"] == "image_edit"
    assert planned["plan"]["image"]["mode"] == "i2i"
    assert planned["plan"]["image"]["reference_attachment_ids"] == [attachment_id]
    assert Job.query.count() == 1  # Upload only; approval has not authorized generation.
    assert action(client, run_id, "approve").status_code == 202
    assert "plan" not in AgentRun.query.filter_by(run_id=run_id).one().command
    delivered = finish_production(client, run_id)
    assert delivered["status"] == "success", delivered  # no separate delivery step for simple recipes
    assert delivered["summary"] == {"steps_total": 1, "steps_success": 1, "steps_failed": 0}
    assert len(delivered["results"]) == 1 and delivered["results"][0]["kind"] == "image"
    assert action(client, run_id, "deliver").status_code == 409
    assert client.get(delivered["results"][0]["download_url"]).status_code == 200
    calls, spent = ApiTask.query.count(), delivered["estimated_spent"]
    tick()
    assert ApiTask.query.count() == calls
    assert detail(client, run_id)["estimated_spent"] == spent
    assert "goal" not in AgentRun.query.filter_by(run_id=run_id).one().request


def test_approval_edit_changes_model_count_and_cost_only_when_consumed(app_ctx, client):
    run_id = create(client, "生成一张橘猫插画")
    tick()
    planned = detail(client, run_id)
    assert planned["status"] == "awaiting_approval", planned
    original = deepcopy(planned["request_spec"])
    plan = deepcopy(planned["plan"])
    plan["image"].update(model_id="wan2.7-image", params={}, n=3)
    plan["estimated_cost"] = 0
    response = action(client, run_id, "approve", plan=plan)
    assert response.status_code == 202, response.json
    row = AgentRun.query.filter_by(run_id=run_id).one()
    assert row.snapshot["request_spec"] == original
    assert row.command["plan"]["estimated_cost"] > 0
    ready = finish_production(client, run_id)
    assert ready["status"] == "success", ready
    assert ready["plan"]["image"]["model_id"] == "wan2.7-image"
    assert "wan2.7-image" in ready["request_spec"]["constraints"]["model_preferences"]
    assert len(ready["results"]) == 3


def test_approval_can_change_only_the_image_count(app_ctx, client):
    run_id = create(client, "生成一张橘猫插画")
    tick()
    plan = detail(client, run_id)["plan"]
    unit_cost = plan["estimated_cost"]
    assert "n" not in plan["image"]["params"]
    plan["image"]["n"] = 3
    response = action(client, run_id, "approve", plan=plan)
    assert response.status_code == 202, response.json
    accepted = AgentRun.query.filter_by(run_id=run_id).one().command["plan"]
    assert accepted["image"]["n"] == 3
    assert accepted["estimated_cost"] == 3 * unit_cost


@pytest.mark.parametrize("change", ["shape", "duration", "family"])
def test_invalid_approval_never_enters_command_inbox(app_ctx, client, change):
    run_id = create(client, "生成5秒猫跳舞视频，使用wan2.7系列")
    tick()
    planned = detail(client, run_id)
    assert planned["status"] == "awaiting_approval", planned
    plan = deepcopy(planned["plan"])
    if change == "shape":
        plan["image"] = 1
    elif change == "duration":
        plan["video"]["params"]["duration"] = 999
    else:
        plan["video"]["model_id"] = "wan2.6-i2v-flash"
    before = ToolInvocation.query.count()
    response = action(client, run_id, "approve", plan=plan)
    assert response.status_code == 422, response.json
    row = AgentRun.query.filter_by(run_id=run_id).one()
    assert row.command is None and row.status == "awaiting_approval"
    assert ToolInvocation.query.count() == before and Job.query.count() == 0


def test_unknown_video_preference_requires_explicit_answer(app_ctx, client):
    run_id = create(client, "生成5秒猫跳舞视频，使用future999-i2v模型")
    tick()
    waiting = detail(client, run_id)
    assert waiting["status"] == "awaiting_input", waiting
    card = waiting["pending_card"]
    question = card["questions"][0]
    assert question["question_id"] == "model_i2v"
    before = ToolInvocation.query.count()
    incomplete = action(client, run_id, "answer", card_id=card["card_id"], answers=[])
    assert incomplete.status_code == 409
    assert AgentRun.query.filter_by(run_id=run_id).one().command is None
    assert ToolInvocation.query.count() == before and Job.query.count() == 0
    answer = action(client, run_id, "answer", card_id=card["card_id"], answers=[
        {"question_id": question["question_id"], "option_id": "server_default"}])
    assert answer.status_code == 202, answer.json
    tick()
    planned = detail(client, run_id)
    assert planned["status"] == "awaiting_approval", planned
    assert planned["pending_card"] is None
    assert planned["request_spec"]["constraints"]["model_preferences"] == []
    assert "future999" in planned["text"]
    assert Job.query.count() == 0


def test_story_duration_mismatch_requires_an_explicit_edited_plan(app_ctx, client):
    from app.agent.model_selection import video_policy_for_request
    from app.agent.request_spec import RequestSpec
    run_id = create(client, "生成60秒剧情短片")
    row = AgentRun.query.filter_by(run_id=run_id).one()
    spec = RequestSpec(deliverable="video", recipe_hint="story_video", summary="剧情短片",
                       target_duration_sec=60, confidence=0.9).model_dump(mode="json")
    draft = {"title": "可修改草稿", "shots": [{"shot_id": "s1", "first_frame_prompt": "猫在窗前",
              "i2v_prompt": "猫跳舞", "video_params": {"duration": 5}}]}
    row.status = "awaiting_approval"
    row.snapshot = {"run_id": run_id, "budget_limit": 100, "shot_count": 1, "mode": "from_scratch",
                    "request_spec": spec, "video_model_policy": video_policy_for_request(spec), "plan": draft}
    db.session.commit()
    rejected = action(client, run_id, "approve")
    assert rejected.status_code == 422
    assert rejected.json["error"]["code"] == "INVALID_PLAN"
    assert AgentRun.query.filter_by(run_id=run_id).one().command is None
    # An explicit edited plan is the user's new duration choice, subject to model/budget checks.
    accepted = action(client, run_id, "approve", plan=draft)
    assert accepted.status_code == 202, accepted.json
    assert AgentRun.query.filter_by(run_id=run_id).one().command["plan"]["shots"][0]["video_params"]["duration"] == 5
