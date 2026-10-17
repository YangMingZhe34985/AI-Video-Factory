"""Model intent is immutable and enforced before any video submission."""

from copy import deepcopy

import pytest

from app.agent.model_policy import build_policy, select_video_model
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ApiTask, Job, ModelRegistry, ToolInvocation
from app.services.artifact_service import ArtifactService
from app.services.storage_service import StorageService
from app.services.workflow_service import WorkflowService
from app.skills import get_registry
from app.skills.spec import ToolContext
from tests.test_agent_mvp import action, create, detail, finish, tick

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True)


@pytest.mark.parametrize("goal, expected", [
    ("我想生成一只猫跳舞的视频，要求使用 wan2.7系列的视频生成模型", "wan2.7-i2v"),
    ("生成猫跳舞，使用 WAN 2.7 系列", "wan2.7-i2v"),
    ("Make a dancing cat video using Wan 2.7 series", "wan2.7-i2v"),
    ("猫跳舞，使用 happy-horse-i2v 视频模型", "happyhorse-1.0-i2v"),
    ("猫跳舞，使用 HappyHorse 模型", "happyhorse-1.0-i2v"),
    ("不要用 wan2.6，使用 wan2.7 系列生成猫跳舞", "wan2.7-i2v"),
    ("Don't use wan2.6, use wan2.7 for a dancing cat video", "wan2.7-i2v"),
    ("不要用wan2.6但要求使用wan2.7系列生成猫跳舞", "wan2.7-i2v"),
    ("Don't use wan2.6 but use wan2.7 for a dancing cat", "wan2.7-i2v"),
    ("猫跳舞，使用wan2.6-i2v-flash模型", "wan2.6-i2v-flash"),
])
def test_natural_language_family_specific_model_and_aliases(app_ctx, goal, expected):
    policy = build_policy(goal)
    assert policy["source"] == "user"
    assert select_video_model(policy, "i2v").model_id == expected


def test_no_preference_uses_node_default_and_rejects_llm_override(app_ctx):
    node = WorkflowService.get_node("submit_i2v")
    node.config = {"model_id": "happyhorse-1.0-i2v"}
    db.session.commit()
    policy = build_policy("一只猫跳舞的视频")
    assert policy["source"] == "server_default"
    assert select_video_model(policy, "i2v").model_id == "happyhorse-1.0-i2v"
    with pytest.raises(AppError, match="不符合"):
        select_video_model(policy, "i2v", "wan2.7-i2v")


def test_a_model_name_in_the_story_is_not_a_model_instruction(app_ctx):
    assert build_policy("一只名字叫wan2.7的猫在跳舞")["source"] == "server_default"
    assert build_policy("使用wan2.7-image模型生成首帧，猫跳舞视频使用服务器默认")["source"] == "server_default"


@pytest.mark.parametrize("goal", [
    "使用wan2.9系列模型生成猫跳舞", "使用wan2.70系列生成猫跳舞", "使用unknown-i2v模型生成猫跳舞",
    "使用wan2.7-pro模型生成猫跳舞", "同时必须使用wan2.7和happyhorse模型",
    "使用wan2.7-pro生成猫跳舞", "Please use unknownModel video model for a dancing cat",
])
def test_unknown_or_conflicting_requirements_do_not_fall_back(app_ctx, client, goal):
    with pytest.raises(AppError) as error:
        build_policy(goal)
    assert error.value.code == "MODEL_PREFERENCE_UNAVAILABLE"
    assert AgentRun.query.count() == Job.query.count() == ToolInvocation.query.count() == 0


def test_disabled_matching_model_is_not_replaced(app_ctx, client):
    ModelRegistry.query.filter_by(model_id="happyhorse-1.0-i2v").update({"enabled": False})
    db.session.commit()
    with pytest.raises(AppError) as error:
        select_video_model(build_policy("猫跳舞，使用happyhorse模型"), "i2v")
    assert error.value.status_code == 422
    assert Job.query.count() == 0


def test_family_applies_to_t2v_i2v_and_r2v_capabilities(app_ctx):
    policy = build_policy("一只猫跳舞，要求使用wan2.7系列的视频模型")
    assert select_video_model(policy, "t2v").model_id == "wan2.7-t2v"
    assert select_video_model(policy, "i2v").model_id == "wan2.7-i2v"
    with pytest.raises(AppError) as error:
        select_video_model(policy, "r2v")
    assert error.value.code == "MODEL_CAPABILITY_UNAVAILABLE"
    for mode, wrong in [("i2v", "happyhorse-1.0-i2v"), ("i2v", "wan2.6-i2v-flash"), ("r2v", "wan2.6-r2v-flash")]:
        with pytest.raises(AppError):
            select_video_model(policy, mode, wrong)


def test_user_requirement_overrides_server_default_end_to_end(app_ctx, client):
    node = WorkflowService.get_node("submit_i2v")
    node.config = {"model_id": "happyhorse-1.0-i2v"}
    db.session.commit()
    run_id = create(client, goal="猫跳舞，要求使用wan2.7系列视频模型", shot_count=2)
    tick()
    planned = detail(client, run_id)
    assert planned["status"] == "awaiting_approval", planned
    assert planned["request"]["video_model_policy"]["requested"] == ["wan2.7"]
    assert {shot["video_model_id"] for shot in planned["snapshot"]["plan"]["shots"]} == {"wan2.7-i2v"}
    # An edited approval cannot erase the user's original constraint.
    plan = deepcopy(planned["snapshot"]["plan"])
    plan["shots"][0]["video_model_id"] = "happyhorse-1.0-i2v"
    response = client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "approve", "plan": plan})
    assert response.status_code == 422
    assert Job.query.count() == 0
    action(client, run_id, "approve")
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert {task.model_id for task in ApiTask.query.filter_by(branch_key="i2v")} == {"wan2.7-i2v"}
    assert all(job.config["video_model_policy"]["requested"] == ["wan2.7"] for job in Job.query.all())


def test_explicit_api_preference_and_idempotency_keep_original_policy(app_ctx, client):
    run_id = create(client, goal="一只猫跳舞", shot_count=1, video_model_preference="happyhorse-i2v")
    assert create(client, goal="一只猫跳舞", shot_count=1, video_model_preference="happyhorse-i2v") == run_id
    tick()
    planned = detail(client, run_id)
    assert planned["snapshot"]["plan"]["shots"][0]["video_model_id"] == "happyhorse-1.0-i2v"
    action(client, run_id, "approve")
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert ApiTask.query.filter_by(branch_key="i2v").one().model_id == "happyhorse-1.0-i2v"


def test_hallucinated_creative_model_is_blocked_before_generation(app_ctx, client, monkeypatch):
    import app.agent.graph as graph_module
    original = graph_module.invoke_once
    def hallucinate(registry, name, data, ctx):
        result = original(registry, name, data, ctx)
        if name == "agent_creative":
            result["output"]["shots"][0]["video_model_id"] = "wan2.6-i2v-flash"
        return result
    monkeypatch.setattr(graph_module, "invoke_once", hallucinate)
    run_id = create(client, goal="要求使用wan2.7系列视频模型生成猫跳舞", shot_count=1)
    tick()
    result = detail(client, run_id)
    assert result["status"] == "awaiting_approval"
    assert result["snapshot"]["plan_issues"][0]["code"] == "MODEL_PREFERENCE_VIOLATION"
    assert client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "approve"}).status_code == 422
    assert Job.query.count() == ApiTask.query.count() == 0


def test_disabled_model_after_approval_does_not_switch_family(app_ctx, client):
    run_id = create(client, goal="猫跳舞，使用happyhorse模型", shot_count=1)
    tick()
    action(client, run_id, "approve")
    ModelRegistry.query.filter_by(model_id="happyhorse-1.0-i2v").update({"enabled": False})
    db.session.commit()
    tick()
    result = detail(client, run_id)
    assert result["status"] == "needs_attention", result
    assert Job.query.count() == ApiTask.query.count() == 0


@pytest.mark.parametrize("mode, wrong", [
    ("t2v", "wan2.7-t2v"), ("i2v", "wan2.7-i2v"), ("r2v", "wan2.6-r2v-flash"),
])
def test_video_tool_cannot_escape_exact_model_requirement(app_ctx, client, h, mode, wrong):
    run_id = create(client, goal="猫跳舞，使用happyhorse-i2v模型", shot_count=1)
    source = h.make_job(paths=())
    path = StorageService.write_mock_png(source.job_id, ["outputs", "reference.png"])
    frame = ArtifactService.register_artifact(source, path, "first_frame_image")
    db.session.commit()
    payload = {"mode": mode, "prompt": "cat dances", "model_id": wrong}
    if mode == "i2v":
        payload["first_frame_artifact_id"] = frame.artifact_id
    elif mode == "r2v":
        payload["reference_artifact_ids"] = [frame.artifact_id]
    with pytest.raises(AppError) as error:
        get_registry().invoke("generate_video", payload,
                              ToolContext(role="production", approved=True, budget_scope=run_id))
    assert error.value.code in {"MODEL_CAPABILITY_UNAVAILABLE", "MODEL_PREFERENCE_VIOLATION"}
    assert Job.query.count() == 1  # Only the fixture's existing image job.
    assert ApiTask.query.count() == 0


def test_valid_t2v_tool_uses_same_family_constraint(app_ctx, client, h):
    run_id = create(client, goal="猫跳舞，使用wan2.7系列视频模型", shot_count=1)
    result = get_registry().invoke("generate_video", {"mode": "t2v", "prompt": "cat dances"},
                                   ToolContext(role="production", approved=True, budget_scope=run_id))
    job = h.wait_for_terminal(result["output"]["job_id"])
    assert ApiTask.query.filter_by(job_id=job.id, branch_key="t2v").one().model_id == "wan2.7-t2v"


def test_tampered_pinned_job_model_is_blocked_on_recovery(app_ctx, client, monkeypatch):
    from app.services.job_run_service import JobRunService
    run_id = create(client, goal="猫跳舞，使用wan2.7系列模型", shot_count=1)
    tick()
    action(client, run_id, "approve")
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: {})
    tick()
    job = Job.query.one()
    config = deepcopy(job.config)
    config["node_models"]["submit_i2v"] = "happyhorse-1.0-i2v"
    job.config = config
    db.session.commit()
    tick()
    result = detail(client, run_id)
    assert result["status"] == "failed", result
    assert result["snapshot"]["shots"]["shot_1"]["error"]["code"] == "MODEL_PREFERENCE_VIOLATION"
    assert ApiTask.query.count() == 0


def test_registered_custom_display_name_is_a_supported_selector(app_ctx):
    db.session.add(ModelRegistry(model_id="model-lab-i2v", display_name="Studio Model", provider="mock",
                                 task_type="image_to_video", adapter_name="mock_video", enabled=True))
    db.session.commit()
    policy = build_policy("猫跳舞", "Studio Model")
    assert select_video_model(policy, "i2v").model_id == "model-lab-i2v"


def test_registered_r2v_in_requested_family_can_be_used(app_ctx, client, h):
    original = ModelRegistry.query.filter_by(model_id="wan2.6-r2v-flash").one()
    db.session.add(ModelRegistry(model_id="wan2.7-r2v-test", display_name="Wan 2.7 R2V Test", provider="mock",
                                 task_type=original.task_type, adapter_name=original.adapter_name,
                                 parameter_schema=original.parameter_schema, default_params=original.default_params))
    db.session.commit()
    run_id = create(client, goal="猫跳舞，使用wan2.7系列视频模型", shot_count=1)
    source = h.make_job(paths=())
    path = StorageService.write_mock_png(source.job_id, ["outputs", "reference.png"])
    frame = ArtifactService.register_artifact(source, path, "first_frame_image")
    db.session.commit()
    result = get_registry().invoke("generate_video", {"mode": "r2v", "prompt": "cat dances",
                                                      "reference_artifact_ids": [frame.artifact_id]},
                                   ToolContext(role="production", approved=True, budget_scope=run_id))
    job = h.wait_for_terminal(result["output"]["job_id"])
    assert ApiTask.query.filter_by(job_id=job.id, branch_key="r2v_flash").one().model_id == "wan2.7-r2v-test"


def test_idempotency_replay_cannot_borrow_a_different_run_job(app_ctx, client, h):
    shot = {"shot_id": "s1", "first_frame_prompt": "a cat", "i2v_prompt": "cat dances"}
    result = get_registry().invoke("produce_shot", shot, ToolContext(role="production", approved=True,
                                                                   idempotency_key="shared-key"))
    h.wait_for_terminal(result["output"]["job_id"])
    run_id = create(client, goal="猫跳舞，使用wan2.7系列视频模型", shot_count=1)
    before = Job.query.count(), ApiTask.query.count()
    with pytest.raises(AppError) as error:
        get_registry().invoke("produce_shot", shot, ToolContext(role="production", approved=True,
                                                               budget_scope=run_id, idempotency_key="shared-key"))
    assert error.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert (Job.query.count(), ApiTask.query.count()) == before


def test_disabling_model_after_job_finished_preserves_available_results(app_ctx, client, monkeypatch):
    from app.services.job_run_service import JobRunService
    run_id = create(client, goal="猫跳舞，使用happyhorse模型", shot_count=1)
    tick()
    action(client, run_id, "approve")
    original = JobRunService.start
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: {})
    tick()
    job = Job.query.one()
    monkeypatch.setattr(JobRunService, "start", original)
    JobRunService.run_inline(job.job_id)
    ModelRegistry.query.filter_by(model_id="happyhorse-1.0-i2v").update({"enabled": False})
    db.session.commit()
    tick()
    result = detail(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert result["summary"]["success"] == 1
    assert result["snapshot"]["shots"]["shot_1"]["artifacts"]
