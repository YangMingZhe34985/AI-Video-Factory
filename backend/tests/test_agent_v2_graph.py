"""A6 acceptance: persisted v2 graph and real Job execution with Mock providers."""

from copy import deepcopy
from io import BytesIO
import time

import pytest
from PIL import Image
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from werkzeug.datastructures import FileStorage

from app.agent.attachments import upload_attachment
from app.agent.graph_v2 import build_graph
from app.agent.worker import checkpoint_path
from app.extensions import db
from app.models import AgentRun, ApiTask, Job, ToolInvocation
from app.services.job_run_service import JobRunService
from app.skills.budget import BudgetGuard
from app.utils.ids import new_id
from tests.test_agent_remix import video_file

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_VISION_MODEL="qwen3.7-plus")


def image():
    content = BytesIO()
    Image.new("RGB", (320, 320), "blue").save(content, format="PNG")
    content.seek(0)
    return upload_attachment(FileStorage(stream=content, filename="portrait.png"), "local")["attachment_id"]


def create(text, ids=(), budget=100):
    row = AgentRun(owner_id="local", request_key=new_id("test"), request={
        "schema_version": 2, "text": text, "attachment_ids": list(ids), "budget_limit": budget,
    })
    db.session.add(row)
    db.session.commit()
    return row.run_id


def tick(run_id, decision=None):
    row = AgentRun.query.filter_by(run_id=run_id).one()
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 100}
    with SqliteSaver.from_conn_string(str(checkpoint_path())) as saver:
        graph = build_graph(saver)
        snapshot = graph.get_state(config)
        if not snapshot.values:
            value = {"run_id": run_id, "budget_limit": row.request["budget_limit"], "status": "understanding",
                     "shots": {}, "results": [], "mock": True}
        elif decision:
            value = Command(resume={**decision, "command_id": new_id("test_command")})
        elif snapshot.interrupts:
            if snapshot.interrupts[0].value["kind"] not in {"tasks", "analysis"}:
                return dict(snapshot.values)
            value = Command(resume={"action": "poll"})
        else:
            value = None
        graph.invoke(value, config)
        result = dict(graph.get_state(config).values)
    db.session.refresh(row)
    row.snapshot = result
    row.status = result["status"]
    db.session.commit()
    return result


def finish(run_id):
    for _ in range(200):
        state = tick(run_id)
        if state["status"] not in {"understanding", "producing", "planning"}:
            return state
        time.sleep(0.03)
    pytest.fail("v2 did not reach a human gate or terminal state")


def test_portrait_edit_short_recipe_and_direct_delivery(app_ctx):
    run_id = create("生成我的一张西装照", [image()])
    state = tick(run_id)
    assert state["status"] == "awaiting_approval"
    assert state["plan"]["recipe"] == "image_edit"
    assert state["plan"]["image"]["mode"] == "i2i"
    assert not state.get("clarifications")
    assert ApiTask.query.count() == 0
    plan = deepcopy(state["plan"])
    plan["image"]["prompt"] = "保留我的面部外观，换成深蓝色西装"
    tick(run_id, {"action": "approve", "plan": plan})
    state = finish(run_id)
    assert state["status"] == "success", state  # simple recipes deliver without an extra approval
    assert list(state["shots"]) == ["image"]
    assert len(state["results"]) == 1
    task = ApiTask.query.one()
    assert task.request_payload["model"] == plan["image"]["model_id"]
    assert "保留我的面部" in str(task.request_payload)
    count, spent = ApiTask.query.count(), BudgetGuard.spent(run_id)
    assert not state.get("packages")
    tick(run_id)
    assert ApiTask.query.count() == count
    assert BudgetGuard.spent(run_id) == spent


@pytest.mark.parametrize("use_image", [False, True])
def test_single_clip_waits_for_first_frame_or_reuses_attachment(app_ctx, use_image):
    ids = [image()] if use_image else []
    text = "用这张图作为首帧，生成5秒猫跳舞视频" if use_image else "生成5秒猫跳舞视频"
    run_id = create(text, ids)
    state = tick(run_id)
    assert state["status"] == "awaiting_approval", state
    assert state["plan"]["recipe"] == "single_clip"
    assert bool(state["plan"]["image"]) is not use_image
    assert ApiTask.query.count() == 0
    tick(run_id, {"action": "approve"})
    state = finish(run_id)
    assert state["status"] == "success", state
    assert len(state["results"]) == 1 and state["results"][0]["kind"] == "video"
    assert ApiTask.query.count() == (1 if use_image else 2)
    assert all(shot["status"] == "success" for shot in state["shots"].values())


def test_multiple_image_outputs_deliver_all_candidates(app_ctx):
    run_id = create("生成三张不同的猫咪海报")
    state = tick(run_id)
    plan = deepcopy(state["plan"])
    plan["image"]["n"] = 3
    plan["image"]["params"]["n"] = 3
    tick(run_id, {"action": "approve", "plan": plan})
    state = finish(run_id)
    assert state["status"] == "success", state
    assert len(state["results"]) == 3
    assert len({ref["artifact_id"] for ref in state["results"]}) == 3
    assert ApiTask.query.count() == 1


def test_simple_auto_approval_and_restart_do_not_duplicate_jobs(app_ctx, monkeypatch):
    from flask import current_app
    current_app.config["AGENT_AUTO_APPROVE_CREDITS"] = 30
    original = JobRunService.start
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: {})
    run_id = create("生成一张猫咪海报")
    state = tick(run_id)
    assert state["status"] == "producing", state
    assert Job.query.count() == 1
    monkeypatch.setattr(JobRunService, "start", original)
    state = finish(run_id)
    assert state["status"] == "success", state
    assert Job.query.count() == 1
    assert ToolInvocation.query.filter_by(tool_name="generate_image", budget_scope=run_id).count() == 1


def test_unknown_model_requires_choice_without_generation(app_ctx):
    run_id = create("生成5秒视频，使用 future999 系列模型")
    state = tick(run_id)
    assert state["status"] == "awaiting_input", state
    card = state["pending_card"]
    assert card["asked_by"] == "director"
    assert ApiTask.query.count() == 0
    state = tick(run_id, {"action": "answer", "card_id": card["card_id"], "answers": [
        {"question_id": card["questions"][0]["question_id"], "option_id": "server_default"},
    ]})
    assert state["status"] == "awaiting_approval", state
    assert state["clarifications"][-1]["asked"] is True
    assert ApiTask.query.count() == 0


def test_two_minute_story_uses_capability_durations_and_no_video_before_approval(app_ctx):
    run_id = create("生成两分钟猫咪冒险的多镜头故事短片", budget=250)
    state = tick(run_id)
    assert state["status"] == "awaiting_approval", state
    assert state["request_spec"]["recipe_hint"] == "story_video"
    assert not state["plan_issues"], state
    assert len(state["plan"]["shots"]) > 1
    assert sum(shot["video_params"]["duration"] for shot in state["plan"]["shots"]) == 120
    assert ApiTask.query.count() == 0
    tick(run_id, {"action": "approve"})
    state = finish(run_id)
    assert state["status"] == "awaiting_delivery", state
    assert len(state["results"]) == len(state["plan"]["shots"])
    state = tick(run_id, {"action": "deliver"})
    assert state["status"] == "success"
    assert len(state["packages"]) == len(state["plan"]["shots"])


def test_remix_reuses_intake_video_analysis_and_keeps_original_clip(app_ctx, video_file):
    with video_file.open("rb") as stream:
        uploaded = upload_attachment(FileStorage(stream=stream, filename="source.mp4"), "local")
    run_id = create("改造这个视频，保留原片画面", [uploaded["attachment_id"]])
    state = finish(run_id)
    assert state["status"] == "awaiting_approval", state
    assert state["mode"] == "remix"
    assert ToolInvocation.query.filter_by(tool_name="analyze_video", budget_scope=run_id).count() == 1
    assert state["analysis"]["job_id"] == state["analysis_jobs"][uploaded["attachment_id"]]
    plan = deepcopy(state["plan"])
    for shot in plan["shots"]:
        shot["action"] = "keep"
    tick(run_id, {"action": "approve", "plan": plan})
    state = finish(run_id)
    assert state["status"] == "awaiting_delivery", state
    assert all(shot["status"] == "success" for shot in state["shots"].values())
    assert ApiTask.query.count() == 0
    assert tick(run_id, {"action": "deliver"})["status"] == "success"

def test_invalid_simple_draft_is_editable_without_replanning(app_ctx, monkeypatch):
    import app.agent.director_lite as director_module
    original = director_module.structured_call

    def invalid_draft(*args, **kwargs):
        result = original(*args, **kwargs)
        result.plan.video.params["duration"] = 2.5  # Provider schema requires integer seconds.
        return result

    monkeypatch.setattr(director_module, "structured_call", invalid_draft)
    run_id = create("生成5秒猫跳舞视频")
    state = tick(run_id)
    assert state["status"] == "awaiting_approval"
    assert state["plan_issues"]
    assert ApiTask.query.count() == 0
    before = ToolInvocation.query.filter_by(tool_name="agent_director_lite", budget_scope=run_id).count()
    plan = deepcopy(state["plan"])
    plan["video"]["params"]["duration"] = 5
    tick(run_id, {"action": "approve", "plan": plan})
    state = finish(run_id)
    assert state["status"] == "success", state
    assert state["plan_issues"] == []
    assert ToolInvocation.query.filter_by(tool_name="agent_director_lite", budget_scope=run_id).count() == before == 1


def test_simple_rejection_and_first_frame_failure_start_no_video(app_ctx, monkeypatch):
    from app.api import AppError
    from app.services.node_runner import NodeRunner
    rejected = create("生成5秒猫跳舞视频")
    assert tick(rejected)["status"] == "awaiting_approval"
    assert tick(rejected, {"action": "reject"})["status"] == "cancelled"
    assert ApiTask.query.count() == 0

    def failed_image(*_args, **_kwargs):
        raise AppError("API_TASK_FAILED", "injected image failure", 502)

    monkeypatch.setattr(NodeRunner, "_run_submit_first_frame_image", failed_image)
    run_id = create("生成5秒小狗跑步视频")
    tick(run_id)
    tick(run_id, {"action": "approve"})
    state = finish(run_id)
    assert state["status"] == "failed", state
    assert state["shots"]["image"]["status"] == "failed"
    assert state["shots"]["video"]["error"]["code"] == "DEPENDENCY_FAILED"
    assert ToolInvocation.query.filter_by(tool_name="animate_shot", budget_scope=run_id).count() == 0


def test_simple_auto_approval_publishes_video_constraints_before_submit(app_ctx):
    from flask import current_app
    current_app.config["AGENT_AUTO_APPROVE_CREDITS"] = 30
    run_id = create("生成5秒猫跳舞视频，使用 wan2.7 系列")
    state = finish(run_id)
    assert state["status"] == "success", state
    assert state["video_model_policy"]["requested"] == ["wan2.7"]
    videos = ApiTask.query.filter_by(branch_key="i2v").all()
    assert len(videos) == 1 and videos[0].model_id.startswith("wan2.7-")


def test_intake_questions_after_the_round_limit_do_not_stall_the_run(app_ctx, monkeypatch):
    from flask import current_app
    import app.agent.intake as intake_module
    from app.agent.graph_v2 import UNRESOLVED_INTAKE_NOTE

    current_app.config["AGENT_MAX_CLARIFY_ROUNDS"] = 0
    original = intake_module.mock_request_spec

    def always_ask(data):
        spec = dict(original(data))
        spec["open_questions"] = [{
            "question_id": "style", "text": "偏写实还是插画？", "why": "影响整体画风",
            "options": [{"option_id": "real", "label": "写实"}, {"option_id": "art", "label": "插画"}],
            "recommended_option_id": "art", "blocking": True,
        }]
        return spec

    monkeypatch.setattr(intake_module, "mock_request_spec", always_ask)
    run_id = create("生成一张猫咪海报")
    state = finish(run_id)
    assert state["status"] == "awaiting_approval", state
    assert [record["asked"] for record in state["clarifications"]] == [False]
    assert UNRESOLVED_INTAKE_NOTE in state["assumptions"]
    assert ApiTask.query.count() == 0

