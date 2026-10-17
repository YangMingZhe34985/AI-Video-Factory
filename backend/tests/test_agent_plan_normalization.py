"""Regression for Creative's paid-trial output mixing model IDs into params."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent import planning
from app.agent.model_policy import build_policy
from app.agent.plan_spec import PlanSpec, ShotSpec
from app.agent.protocol import validate_plan
from app.api import AppError
from app.models import ApiTask, Job
from app.skills.tools.produce_shot import ProduceShotInput
from tests.test_agent_mvp import action, create, detail, finish, tick

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True)


def misplaced_plan():
    # Same parameter shape as the failed real server-default trial.
    return {"title": "Dancing dog", "shots": [{
        "shot_id": "shot_1", "first_frame_prompt": "A dog standing in a bright room",
        "i2v_prompt": "The dog dances, fixed camera",
        "image_params": {"model_id": "wan2.7-image", "size": "1280*720", "n": 1,
                         "prompt_extend": True, "watermark": False},
        "video_params": {"model_id": "wan2.7-i2v", "duration": 14, "resolution": "720P",
                         "prompt_extend": False, "watermark": False},
    }]}


@pytest.mark.parametrize("schema", [ShotSpec, ProduceShotInput])
def test_misplaced_ids_are_promoted_without_mutating_input(schema):
    raw = misplaced_plan()["shots"][0]
    before = deepcopy(raw)
    shot = schema.model_validate(raw)
    assert raw == before
    assert shot.image_model_id == "wan2.7-image"
    assert shot.video_model_id == "wan2.7-i2v"
    assert shot.image_params == {k: v for k, v in raw["image_params"].items() if k != "model_id"}
    assert shot.video_params == {k: v for k, v in raw["video_params"].items() if k != "model_id"}
    assert schema.model_validate(shot.model_dump()).model_dump() == shot.model_dump()


@pytest.mark.parametrize("kind, model", [("image", "wan2.7-image"), ("video", "wan2.7-i2v")])
@pytest.mark.parametrize("selected", [None, "same", "alias"])
def test_null_redundant_and_alias_model_selections(kind, model, selected):
    raw = misplaced_plan()["shots"][0]
    raw[f"{kind}_model_id"] = {None: None, "same": model, "alias": model.upper()}[selected]
    shot = ShotSpec.model_validate(raw)
    assert getattr(shot, f"{kind}_model_id") == (model.upper() if selected == "alias" else model)
    assert "model_id" not in getattr(shot, f"{kind}_params")


@pytest.mark.parametrize("kind", ["image", "video"])
def test_conflicting_model_selections_are_rejected(kind):
    raw = misplaced_plan()["shots"][0]
    raw[f"{kind}_model_id"] = "wan2.6-image" if kind == "image" else "wan2.6-i2v-flash"
    with pytest.raises(ValidationError, match=f"Conflicting {kind}_model_id"):
        ShotSpec.model_validate(raw)


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("value", ["", "  ", 12, True, {}, []])
def test_invalid_misplaced_ids_are_not_silently_discarded(kind, value):
    raw = misplaced_plan()["shots"][0]
    raw[f"{kind}_params"]["model_id"] = value
    with pytest.raises(ValidationError, match="must be a non-empty string or null"):
        ShotSpec.model_validate(raw)


def test_null_misplaced_ids_leave_server_selection_available(app_ctx):
    raw = misplaced_plan()
    for kind in ("image", "video"):
        raw["shots"][0][f"{kind}_params"] = {"model_id": None}
    result = validate_plan(raw, 1, 18, build_policy("a dancing dog"))
    shot = result["shots"][0]
    assert shot["image_model_id"] == app_ctx.config["DEFAULT_IMAGE_MODEL"]
    assert shot["video_model_id"] == app_ctx.config["DEFAULT_I2V_MODEL"]
    assert "model_id" not in shot["image_params"]
    assert "model_id" not in shot["video_params"]


def test_historical_paid_output_validates_and_retains_parameters(app_ctx):
    raw = misplaced_plan()
    validated = validate_plan(raw, 1, 18, build_policy("a dancing dog"))
    shot = validated["shots"][0]
    assert shot["image_model_id"] == "wan2.7-image"
    assert shot["video_model_id"] == "wan2.7-i2v"
    assert shot["video_params"]["duration"] == 14
    assert shot["image_params"]["size"] == "1280*720"
    assert "model_id" not in shot["image_params"]
    assert "model_id" not in shot["video_params"]


@pytest.mark.parametrize("goal", ["a dancing dog", "使用wan2.7系列视频模型生成跳舞的小狗"])
def test_promoted_id_still_cannot_escape_default_or_family_policy(app_ctx, goal):
    raw = misplaced_plan()
    raw["shots"][0]["video_params"]["model_id"] = "wan2.6-i2v-flash"
    with pytest.raises(AppError) as error:
        validate_plan(raw, 1, 14, build_policy(goal))
    assert error.value.code == "MODEL_PREFERENCE_VIOLATION"
    assert Job.query.count() == ApiTask.query.count() == 0


@pytest.mark.parametrize("kind, key, value", [
    ("image", "invented_parameter", 1), ("video", "invented_parameter", 1),
    ("video", "duration", "5"), ("video", "duration", 999), ("video", "resolution", "4K"),
])
def test_normalization_does_not_weaken_other_parameter_checks(app_ctx, kind, key, value):
    raw = misplaced_plan()
    raw["shots"][0][f"{kind}_params"][key] = value
    with pytest.raises(AppError) as error:
        validate_plan(raw, 1, 14, build_policy("a dancing dog"))
    assert error.value.code == "INVALID_INPUT"


def test_real_structured_response_boundary_and_prompt(app_ctx, monkeypatch):
    payloads = []
    adapter = SimpleNamespace(
        use_mock=False,
        build_payload=lambda data, params: {"input": data, "parameters": params},
        submit=lambda payload: payloads.append(payload) or {"json": misplaced_plan()},
    )
    monkeypatch.setattr(planning, "get_adapter", lambda *args, **kwargs: adapter)
    result = planning.creative(planning.CreativeInput(
        brief=planning.Brief(title="Dog", objective="dog dances", visual_style="realistic", story_arc="one shot"),
        shot_count=1, video_model_policy=build_policy("a dancing dog"),
    ), None)
    assert result.shots[0].video_model_id == "wan2.7-i2v"
    assert "model_id" not in result.shots[0].image_params
    assert "model_id" not in result.shots[0].video_params
    assert "model_id MUST NOT appear inside" in payloads[0]["input"]["user_prompt"]


def test_misplaced_creative_output_reaches_generation_and_delivery(app_ctx, client, monkeypatch):
    original = planning.structured_call

    def malformed_creative(instruction, data, schema, mock):
        if schema is PlanSpec:
            return schema.model_validate(misplaced_plan())
        return original(instruction, data, schema, mock)

    monkeypatch.setattr(planning, "structured_call", malformed_creative)
    run_id = create(client, goal="a dancing dog", shot_count=1)
    tick()
    planned = detail(client, run_id)
    assert planned["status"] == "awaiting_approval", planned
    assert planned["request"]["video_model_policy"]["source"] == "server_default"
    # An edited approval crosses the same normalization boundary.
    action(client, run_id, "approve", plan=misplaced_plan())
    generated = finish(client, run_id)
    assert generated["status"] == "awaiting_delivery", generated
    job = Job.query.one()
    assert job.config["node_models"] == {
        "submit_first_frame_image": "wan2.7-image", "submit_i2v": "wan2.7-i2v"}
    assert all("model_id" not in params for params in job.config["node_model_params"].values())
    assert {task.model_id for task in ApiTask.query.all()} == {"wan2.7-image", "wan2.7-i2v"}
    assert all("model_id" not in (task.request_payload or {}).get("parameters", {}) for task in ApiTask.query.all())
    action(client, run_id, "deliver")
    tick()
    assert detail(client, run_id)["status"] == "success"


def test_approval_rejects_conflicting_models_before_creating_job(app_ctx, client):
    run_id = create(client, goal="a dancing dog", shot_count=1)
    tick()
    raw = misplaced_plan()
    raw["shots"][0]["video_model_id"] = "wan2.6-i2v-flash"
    response = client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "approve", "plan": raw})
    assert response.status_code == 422
    assert "Conflicting video_model_id" in str(response.json)
    assert detail(client, run_id)["status"] == "awaiting_approval"
    assert Job.query.count() == ApiTask.query.count() == 0
