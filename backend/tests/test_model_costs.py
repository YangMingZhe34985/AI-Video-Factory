"""Cost estimates follow the selected catalog and final generation parameters."""
from types import SimpleNamespace

import pytest

from app.api import AppError
from app.agent.plan_spec import PlanSpec, RemixShotSpec, ShotSpec, shot_cost
from app.agent.model_policy import build_policy
from app.agent.protocol import CreateRun, validate_plan, validate_request
from app.extensions import db
from app.models import AgentRun, ApiTask, Job
from app.services.model_service import ModelService
from app.skills import get_registry
from app.skills.budget import estimate_model_cost, estimate_nodes_cost, BudgetGuard
from app.skills.spec import ToolContext
from app.skills.tools.rerun_node import RerunNodeInput, estimate_cost


def model(unit="second", rate=0.8, defaults=None):
    return SimpleNamespace(model_id="cost-fixture", task_type="image_to_video",
                           capabilities={"pricing": {"unit": unit, "credits_per_unit": rate},
                                         "duration": {"min": 2}}, default_params=defaults or {})


def test_seconds_outputs_and_final_parameter_precedence():
    item = model(defaults={"duration": 10, "n_outputs": 1})
    assert estimate_model_cost(item, {"duration": 5}) == 4
    assert estimate_model_cost(item, {"duration": 15}) == 12
    assert estimate_model_cost(item, {"duration": 5, "n_outputs": 3}) == 12
    assert estimate_model_cost(item, {}) == 8
    assert estimate_model_cost(model(), {}) == 1.6
    assert estimate_model_cost(model("image", 2, {"n": 4}), {}) == 8
    assert estimate_model_cost(model("image", 2, {"n": 4}), {"n": 2}) == 4
    assert estimate_model_cost(model("call", 1.25), {"n": 10}) == 1.25


@pytest.mark.parametrize("bad", [-1, 0, float("nan"), float("inf"), True, "5"])
def test_invalid_usage_cannot_reduce_budget(bad):
    with pytest.raises(AppError) as error:
        estimate_model_cost(model(), {"duration": bad})
    assert error.value.code == "INVALID_INPUT"


def test_missing_pricing_warns_and_keeps_legacy_rates(app_ctx, caplog):
    for task, expected in (("image_to_video", 10), ("text_to_image", 2), ("text_to_text", 1)):
        item = model()
        item.task_type, item.capabilities = task, {}
        assert estimate_model_cost(item, {"duration": 15, "n": 4}) == expected
    assert "Missing pricing" in caplog.text


def test_plan_and_generation_estimate_same_final_usage(app_ctx):
    image = ModelService.get_model("wan2.7-image")
    image.capabilities = {**image.capabilities, "pricing": {"unit": "image", "credits_per_unit": 3}}
    video = ModelService.get_model("wan2.7-i2v")
    video.capabilities = {**video.capabilities, "pricing": {"unit": "second", "credits_per_unit": 0.8}}
    db.session.commit()
    shot = ShotSpec(shot_id="s1", first_frame_prompt="cat", i2v_prompt="dance",
                    image_model_id=image.model_id, video_model_id=video.model_id,
                    image_params={"n": 1}, video_params={"duration": 15})
    assert shot_cost(shot) == 15
    plan = PlanSpec(title="test", shots=[shot])
    assert plan.estimated_cost == 17
    spec = get_registry().get("produce_shot")
    assert spec.cost_fn(spec.input_model.model_validate(shot.model_dump()), None) == shot_cost(shot)
    remix = RemixShotSpec(**shot.model_dump(), action="regenerate", source_start=0.0,
                          source_end=3.0, first_frame_mode="source", edit_reason="change motion")
    assert shot_cost(remix) == 12
    remix.action = "keep"
    assert shot_cost(remix) == 0


def test_node_estimate_uses_saved_configuration_and_sample_count(app_ctx):
    config = {"node_models": {"submit_i2v": "wan2.7-i2v"},
              "workflow_node_configs": {"submit_i2v": {"model_params": {"duration": 3}}},
              "model_params": {"i2v": {"duration": 5}},
              "node_model_params": {"submit_i2v": {"duration": 15}}}
    assert estimate_nodes_cost(["submit_i2v", "poll_i2v"], job_config=config) == 15
    assert estimate_nodes_cost(["submit_i2v"], job_config=config,
                               node_params={"submit_i2v": {"duration": 6}}) == 6
    assert estimate_nodes_cost(["submit_i2i_test_i2v"], sample_count=3,
                               node_params={"submit_i2i_test_i2v": {"duration": 5}}) == 15


def test_paid_rerun_uses_original_duration_and_new_key_accumulates(app_ctx, h):
    registry = get_registry()
    data = {"shot_id": "s1", "first_frame_prompt": "cat", "i2v_prompt": "dance",
            "video_params": {"duration": 5}}
    result = registry.invoke("produce_shot", data, ToolContext(role="production", approved=True,
                             budget_scope="seconds", budget_limit=100, idempotency_key="first"))
    h.wait_for_terminal(result["output"]["job_id"])
    assert BudgetGuard.spent("seconds") == 7
    rerun = RerunNodeInput(job_id=result["output"]["job_id"], node_key="submit_i2v")
    assert estimate_cost(rerun) == 5
    for key in ("redo-1", "redo-2"):
        repeated = registry.invoke("rerun_node", rerun.model_dump(), ToolContext(
            role="production", approved=True, budget_scope="seconds", budget_limit=100, idempotency_key=key))
        h.wait_for_terminal(repeated["output"]["job_id"])
    assert BudgetGuard.spent("seconds") == 17


def test_family_policy_uses_final_model_for_plan_admission_and_tool_budget(app_ctx):
    video = ModelService.get_model("wan2.6-i2v-flash")
    video.capabilities = {**video.capabilities, "pricing": {"unit": "second", "credits_per_unit": 7}}
    video.default_params = {**video.default_params, "duration": 5}
    db.session.commit()
    policy = build_policy("使用 wan2.6 系列生成猫跳舞视频")
    shot = {"shot_id": "s1", "first_frame_prompt": "cat", "i2v_prompt": "dance",
            "video_params": {"duration": 5}}
    raw = {"title": "cat", "shots": [shot]}
    with pytest.raises(AppError, match="39") as error:
        validate_plan(raw, 1, 38, policy)
    assert error.value.code == "BUDGET_EXCEEDED"
    valid = validate_plan(raw, 1, 39, policy)
    assert valid["shots"][0]["video_model_id"] == video.model_id
    # v2 admission reserves only understanding; generation is checked at approval.
    validate_request(CreateRun(text="使用 wan2.6 系列生成猫跳舞视频", budget_limit=38, request_key="family"))
    run = AgentRun(owner_id="test", request_key="family", request={"video_model_policy": policy})
    db.session.add(run)
    db.session.commit()
    with pytest.raises(AppError) as error:
        get_registry().invoke("produce_shot", shot, ToolContext(role="production", approved=True,
                              budget_scope=run.run_id, budget_limit=36))
    assert error.value.payload["requested"] == 37
    assert Job.query.count() == ApiTask.query.count() == 0


def test_completed_replay_does_not_reprice_or_require_enabled_model(app_ctx, h):
    registry = get_registry()
    data = {"prompt": "cat", "model_id": "wan2.7-image"}
    def context():
        return ToolContext(role="production", approved=True, budget_scope="replay", idempotency_key="image")
    result = registry.invoke("generate_image", data, context())
    h.wait_for_terminal(result["output"]["job_id"])
    item = ModelService.get_model(data["model_id"])
    item.enabled = False
    item.capabilities = {**item.capabilities, "pricing": {"unit": "image", "credits_per_unit": 99}}
    db.session.commit()
    repeated = registry.invoke("generate_image", data, context())
    assert repeated["replayed"] is True
    assert repeated["output"] == result["output"]
    assert BudgetGuard.spent("replay") == 2


def test_catalog_minimum_duration_reaches_provider_payload(app_ctx, h):
    item = ModelService.get_model("wan2.7-t2v")
    item.default_params = {}
    item.capabilities = {**item.capabilities, "duration": {"min": 2, "max": 15, "step": 1}}
    db.session.commit()
    result = get_registry().invoke("generate_video", {"mode": "t2v", "prompt": "cat dances",
                                    "model_id": item.model_id}, ToolContext(
        role="production", approved=True, budget_scope="minimum", budget_limit=2))
    job = h.wait_for_terminal(result["output"]["job_id"])
    assert job.status == "success", job.error_summary
    task = ApiTask.query.filter_by(job_id=job.id).one()
    assert task.request_payload["parameters"]["duration"] == 2
    assert BudgetGuard.spent("minimum") == 2


def test_submission_freezes_priced_defaults_for_queued_work(app_ctx, monkeypatch):
    from app.services.job_run_service import JobRunService
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: {"status": "queued"})
    result = get_registry().invoke("generate_video", {"mode": "t2v", "prompt": "cat dances"}, ToolContext(
        role="production", approved=True, budget_scope="queued"))
    job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
    quoted = BudgetGuard.spent("queued")
    item = ModelService.get_model(job.config["node_models"]["submit_t2v"])
    duration = item.default_params["duration"]
    item.default_params = {**item.default_params, "duration": 15}
    db.session.commit()
    assert job.config["node_model_params"]["submit_t2v"]["duration"] == duration
    assert estimate_nodes_cost(["submit_t2v"], job_config=job.config) == quoted
