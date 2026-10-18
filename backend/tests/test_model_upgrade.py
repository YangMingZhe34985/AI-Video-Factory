"""Catalog, capability, family and price upgrades use isolated Mock state."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from app.agent.director_lite import _aspect_params
from app.agent.model_policy import build_policy, select_video_model
from app.agent.model_selection import candidates_for_request, select_for_request, validate_generation_model
from app.api import AppError
from app.extensions import db
from app.services.model_service import ModelService
from app.skills import model_guard
from app.skills.budget import estimate_model_cost
from tests.test_simple_plan import request_spec
VIDEO_IDS = {"wan3.0-video", "wan3.0-video-prime"}

def test_new_seeds_preserve_old_records_and_operator_prices(app_ctx):
    video = ModelService.get_model("wan3.0-video")
    assert (video.task_type, video.adapter_name) == ("text_to_video", "dashscope_wan3")
    assert set(video.capabilities["modes"]) == {"t2v", "i2v", "first_last_frame", "r2v", "omni_reference", "video_edit", "video_extend"}
    assert video.capabilities["reference_images"]["max"] == 10
    assert video.capabilities["provider_capabilities"]["reference_video"]["agent_enabled"]
    chat = ModelService.get_model("deepseek-v4.1-flash")
    assert (chat.provider, chat.adapter_name, chat.task_type) == ("dashscope", "qwen_chat", "prompt_rewrite")
    assert chat.default_params["enable_thinking"] is False
    old = deepcopy(ModelService.get_model("wan2.7-i2v").to_dict())
    custom = {**video.capabilities, "agent_selectable": False, "pricing": {"unit": "second", "credits_per_unit": 9}}
    video.capabilities = deepcopy(custom)
    db.session.commit()
    assert ModelService.seed_defaults() == 0
    assert video.capabilities == custom
    updated = ModelService.get_model("wan2.7-i2v").to_dict()
    assert all(old[key] == updated[key] for key in ("default_params", "parameter_schema", "capabilities", "adapter_name"))

@pytest.mark.parametrize("mode,task", [("t2v", "text_to_video"), ("i2v", "image_to_video"), ("r2v", "reference_to_video")])
def test_unified_wan_modes_in_guard_api_and_both_agents(app_ctx, client, mode, task):
    video = ModelService.get_model("wan3.0-video")
    assert ModelService.supports_task_type(video, task)
    assert model_guard.resolve_model(video.model_id, mode).model_id == video.model_id
    for path in (f"/api/models?task_type={task}", f"/api/models/by-task/{task}"):
        assert VIDEO_IDS <= {m["model_id"] for m in client.get(path).json["data"]["models"]}
    spec = request_spec("single_clip", preferences=["wan3.0系列"])
    assert {m.model_id for m in candidates_for_request(spec, mode)} == VIDEO_IDS
    assert select_video_model(build_policy("使用 wan3.0 系列视频模型生成猫跳舞"), mode).model_id in VIDEO_IDS

def test_provider_metadata_does_not_grant_execute_or_llm_roles(app_ctx):
    model = ModelService.get_model("deepseek-v4.1-flash")
    model.capabilities = {**model.capabilities, "provider_capabilities": {"modes": ["i2v", "image_understanding"]}}
    assert not ModelService.supports_task_type(model, "image_to_video")
    assert not ModelService.supports_task_type(model, "video_understanding")
    legacy = SimpleNamespace(task_type="image_to_video", capabilities={})
    assert ModelService.supports_mode(legacy, "i2v")
    assert not ModelService.supports_mode(legacy, "first_last_frame")
    assert not ModelService.supports_mode(SimpleNamespace(task_type="text_to_image", capabilities={}), "i2i")

@pytest.mark.parametrize("phrase", ["wan3.0系列", "WAN 3.0 series", "wan3.0视频模型"])
def test_family_boundaries_and_exact_exclusions(app_ctx, phrase):
    spec = request_spec("single_clip", preferences=[phrase], exclusions=["wan3.0-video-prime"])
    assert [m.model_id for m in candidates_for_request(spec, "i2v")] == ["wan3.0-video"]
    assert not candidates_for_request(request_spec("single_clip", preferences=["wan3.01系列"]), "i2v")

def test_exact_image_id_never_silently_selects_family_pro(app_ctx):
    spec = request_spec(preferences=["qwen-image-3.0"])
    assert [m.model_id for m in candidates_for_request(spec, "i2i")] == ["qwen-image-3.0"]
    assert len(candidates_for_request(request_spec(preferences=["qwen-image-3.0系列"]), "i2i")) == 2
    ModelService.get_model("qwen-image-3.0").enabled = False
    db.session.commit()
    assert candidates_for_request(spec, "i2i") == []

def test_defaults_are_unchanged(app_ctx):
    for mode, expected in (("t2i", "wan2.6-image"), ("i2i", "wan2.7-image"), ("i2v", "wan2.7-i2v"), ("t2v", "wan2.7-t2v")):
        assert select_for_request(request_spec("single_clip" if mode.endswith("2v") else "image_create"), mode).model_id == expected

@pytest.mark.parametrize("size", ["512*512", "2048*2048", "512*4096", "4096*512", "1000*777"])
def test_dynamic_size_accepts_legal_nonpresets(app_ctx, size):
    assert validate_generation_model(ModelService.get_model("qwen-image-3.0"), "t2i", {"size": size, "n": 6})["size"] == size

@pytest.mark.parametrize("size", ["511*511", "2049*2048", "4097*512", "0*1024", "-512*512", "1024x1024", "100*100000", "1" * 5000 + "*512"])
def test_dynamic_size_rejects_invalid_range_and_syntax(app_ctx, size):
    with pytest.raises(AppError):
        validate_generation_model(ModelService.get_model("qwen-image-3.0"), "t2i", {"size": size})

def test_image_reference_extension_and_aspect_rules(app_ctx):
    model = ModelService.get_model("qwen-image-3.0-pro")
    params = _aspect_params({"parameters": model.parameter_schema}, "16:9")
    assert params == {"size": "1536*864"}
    assert _aspect_params({"parameters": model.parameter_schema}, "4:3") == {"size": "1024*768"}
    assert _aspect_params({"parameters": model.parameter_schema}, "3:4") == {"size": "768*1024"}
    assert validate_generation_model(model, "i2i", params, reference_count=3)
    with pytest.raises(AppError): validate_generation_model(model, "i2i", {}, reference_count=4)
    with pytest.raises(AppError): validate_generation_model(model, "i2i", {"prompt_extend_mode": "agent"}, reference_count=1)
    assert validate_generation_model(model, "t2i", {"prompt_extend_mode": "agent"})

@pytest.mark.parametrize("duration", [-1, 1, 31, 5.5, True])
def test_fixed_wan_duration_rejects_unpriced_auto(app_ctx, duration):
    with pytest.raises(AppError):
        validate_generation_model(ModelService.get_model("wan3.0-video"), "i2v", {"duration": duration}, reference_count=1)

def test_resolution_price_and_trusted_input_seconds(app_ctx):
    model = ModelService.get_model("wan3.0-video")
    for resolution, expected in (("480P", 5), ("720P", 10), ("1080P", 15)):
        assert estimate_model_cost(model, {"duration": 5, "resolution": resolution}) == expected
    assert estimate_model_cost(model, {"duration": 5, "n_outputs": 2}, input_video_seconds=3) == 26
    assert estimate_model_cost(model, {"duration": 5, "input_video_seconds": 100}) == 10
    assert estimate_model_cost(model, {}) == 10
    assert estimate_model_cost(ModelService.get_model("wan3.0-video-prime"), {"duration": 5}) == 20

@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "3"])
def test_invalid_input_seconds_never_reduce_estimate(app_ctx, value):
    with pytest.raises(AppError):
        estimate_model_cost(ModelService.get_model("wan3.0-video"), {"duration": 5}, input_video_seconds=value)

def test_unknown_resolution_and_billing_basis_fail_closed(app_ctx):
    model = ModelService.get_model("wan3.0-video")
    with pytest.raises(AppError): estimate_model_cost(model, {"duration": 5, "resolution": "4K"})
    model.capabilities = {**model.capabilities, "pricing": {**model.capabilities["pricing"], "billing_basis": "unknown"}}
    with pytest.raises(AppError): estimate_model_cost(model, {"duration": 5})


@pytest.mark.parametrize("resolution", [None, [], False, "4K"])
def test_invalid_resolution_input_raises_a_structured_error(app_ctx, resolution):
    with pytest.raises(AppError) as error:
        estimate_model_cost(ModelService.get_model("wan3.0-video"), {"duration": 5, "resolution": resolution})
    assert error.value.code == "INVALID_INPUT"


@pytest.mark.parametrize("model_id", sorted(VIDEO_IDS))
def test_wan_random_seed_and_prime_speed_metadata(app_ctx, model_id):
    model = ModelService.get_model(model_id)
    assert model_guard.validate_params(model, {"seed": -1}) == {"seed": -1}
    assert validate_generation_model(model, "i2v", {"seed": -1}, reference_count=1)["seed"] == -1
    with pytest.raises(AppError):
        validate_generation_model(model, "i2v", {"seed": -2}, reference_count=1)
    assert model.capabilities["quality_tier"] == ("fast" if model_id.endswith("-prime") else "standard")
    assert "画质未实测" in model.capabilities["notes"]
    with pytest.raises(AppError):
        model_guard.validate_params(ModelService.get_model("qwen-image-3.0"), {"seed": -1})
