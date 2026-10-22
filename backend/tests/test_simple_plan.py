"""Simple approvals use owned references, catalog constraints and real estimates."""

from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError
from werkzeug.datastructures import FileStorage

from app.agent.attachments import upload_attachment
from app.agent.model_selection import candidates_for_request, select_for_request, validate_generation_model, video_policy_for_request
from app.agent.simple_plan import approval_request_spec, validate_simple_plan
from app.api import AppError
from app.extensions import db
from app.models import ToolInvocation
from app.services.model_service import ModelService


def request_spec(recipe="image_create", attachments=None, preferences=None, exclusions=None):
    return {"deliverable": "video" if recipe == "single_clip" else "image", "recipe_hint": recipe,
            "summary": "生成猫的画面", "attachments": attachments or [], "confidence": 0.9,
            "constraints": {"model_preferences": preferences or [], "model_exclusions": exclusions or []}}


def image_reference(owner="owner"):
    content = BytesIO()
    Image.new("RGB", (256, 256), "blue").save(content, "PNG")
    content.seek(0)
    uploaded = upload_attachment(FileStorage(stream=content, filename="ref.png"), owner)
    return {"attachment_id": uploaded["attachment_id"], "kind": "image", "role": "identity_ref",
            "description": "蓝色测试图片", "reason": "保留主体"}


def image_plan(mode="t2i", refs=None):
    return {"recipe": "image_edit" if mode == "i2i" else "image_create", "title": "测试图片", "rationale": "保留主体",
            "estimated_cost": 99999, "image": {"mode": mode, "model_id": "wan2.7-image" if mode == "i2i" else "wan2.6-image",
              "prompt": "A cat in a suit", "reference_attachment_ids": refs or [], "params": {}, "n": 1}}


def clip_plan(duration=5):
    plan = image_plan()
    plan.update(recipe="single_clip", video={"mode": "i2v", "model_id": "wan2.7-i2v", "prompt": "Cat dances",
                                            "first_frame": "generated_image", "params": {"duration": duration}})
    return plan


def test_plan_cost_is_recomputed_and_final_params_are_frozen(app_ctx):
    five = validate_simple_plan(clip_plan(5), request_spec("single_clip"), owner_id="owner")
    fifteen = validate_simple_plan(clip_plan(15), request_spec("single_clip"), owner_id="owner")
    assert five["estimated_cost"] == 7
    assert fifteen["estimated_cost"] == 17
    assert "n" not in five["image"]["params"]
    assert five["video"]["params"]["resolution"] == "720P"


def test_image_edit_uses_owned_attached_images(app_ctx):
    ref = image_reference()
    raw = image_plan("i2i", [ref["attachment_id"]])
    spec = request_spec("image_edit", [ref])
    assert validate_simple_plan(raw, spec, owner_id="owner")["estimated_cost"] == 2
    with pytest.raises(AppError) as forbidden:
        validate_simple_plan(raw, spec, owner_id="another-owner")
    assert forbidden.value.code == "ATTACHMENT_NOT_FOUND"
    unrelated = image_reference()
    raw["image"]["reference_attachment_ids"] = [unrelated["attachment_id"]]
    with pytest.raises(AppError) as missing:
        validate_simple_plan(raw, spec, owner_id="owner")
    assert missing.value.code == "INVALID_ATTACHMENT"


def test_reference_count_and_parameter_errors_cannot_reach_generation(app_ctx):
    refs = [image_reference(), image_reference()]
    with pytest.raises(AppError) as too_many:
        validate_simple_plan(image_plan("i2i", [item["attachment_id"] for item in refs]),
                             request_spec("image_edit", refs), owner_id="owner")
    assert too_many.value.code == "MODEL_CAPABILITY_MISMATCH"
    raw = image_plan()
    raw["image"]["params"] = {"model_id": "hidden-choice"}
    with pytest.raises(AppError) as invalid:
        validate_simple_plan(raw, request_spec(), owner_id="owner")
    assert invalid.value.code == "INVALID_INPUT"


def test_family_preference_also_limits_supporting_image(app_ctx):
    # D-062: a family with image models (wan2.7-image) constrains images too;
    # previously "wan2.7系列" silently left the first frame on wan2.6-image.
    spec = request_spec("single_clip", preferences=["wan2.7系列"], exclusions=["HappyHorse"])
    assert select_for_request(spec, "t2i").model_id == "wan2.7-image"
    assert select_for_request(spec, "i2v").model_id == "wan2.7-i2v"
    policy = video_policy_for_request(spec)
    assert policy["source"] == "user"
    assert policy["allowed_model_ids"] == ["wan2.7-i2v", "wan2.7-t2v"]
    with pytest.raises(AppError):
        validate_simple_plan(clip_plan(), spec, owner_id="owner")
    plan = clip_plan()
    plan["image"]["model_id"] = "wan2.7-image"
    assert validate_simple_plan(plan, spec, owner_id="owner")["estimated_cost"] > 0


def test_unknown_family_and_disabled_default_never_silently_switch(app_ctx):
    with pytest.raises(AppError):
        select_for_request(request_spec("single_clip", preferences=["missing-series"]), "i2v")
    model = ModelService.get_model("wan2.7-i2v")
    model.enabled = False
    db.session.commit()
    with pytest.raises(AppError):
        select_for_request(request_spec("single_clip"), "i2v")


def test_duration_step_is_checked_in_addition_to_provider_parameter_schema(app_ctx):
    model = ModelService.get_model("wan2.7-i2v")
    model.capabilities = {**model.capabilities, "duration": {"min": 2, "max": 16, "step": 2}}
    db.session.commit()
    with pytest.raises(AppError) as invalid:
        validate_generation_model(model, "i2v", {"duration": 5}, reference_count=1)
    assert invalid.value.code == "MODEL_CAPABILITY_MISMATCH"
    assert validate_generation_model(model, "i2v", {"duration": 6}, reference_count=1)["duration"] == 6


def test_approval_model_edit_is_explicit_but_cannot_break_series_constraint(app_ctx):
    original = clip_plan()
    edited = deepcopy(original)
    edited["video"]["model_id"] = "wan2.6-i2v-flash"
    spec = request_spec("single_clip")
    with pytest.raises(AppError):
        validate_simple_plan(edited, spec, owner_id="owner")
    confirmed = approval_request_spec(spec, original, edited)
    assert confirmed["constraints"]["model_preferences"] == ["wan2.6-i2v-flash"]
    assert validate_simple_plan(edited, confirmed, owner_id="owner")["video"]["model_id"] == "wan2.6-i2v-flash"
    with pytest.raises(AppError):
        approval_request_spec(request_spec("single_clip", preferences=["wan2.7系列"]), original, edited)


def test_approval_count_and_duration_edits_remain_allowed(app_ctx):
    spec = request_spec("single_clip")
    spec["target_duration_sec"] = 5
    assert validate_simple_plan(clip_plan(15), spec, owner_id="owner")["video"]["params"]["duration"] == 15
    image = image_plan()
    image["image"]["n"] = 4
    assert validate_simple_plan(image, request_spec(), owner_id="owner")["estimated_cost"] == 8
    image["image"]["params"]["n"] = 1
    with pytest.raises(ValidationError):
        validate_simple_plan(image, request_spec(), owner_id="owner")


def test_plan_budget_includes_already_spent_understanding(app_ctx):
    db.session.add(ToolInvocation(tool_name="agent_intake", idempotency_key="spent", caller_role="intake",
                                 budget_scope="run-budget", status="success", estimated_cost=4))
    db.session.commit()
    with pytest.raises(AppError) as denied:
        validate_simple_plan(image_plan(), request_spec(), owner_id="owner", budget_scope="run-budget", budget_limit=5)
    assert denied.value.code == "BUDGET_EXCEEDED"
    assert denied.value.payload["spent"] == 4
    assert denied.value.payload["requested"] == 2


@pytest.mark.parametrize("update", [
    {"video": None}, {"image": None},
    {"video": {"mode": "t2v", "model_id": "wan2.7-t2v", "prompt": "dance", "first_frame": "generated_image"}},
])
def test_inconsistent_simple_recipe_is_rejected(app_ctx, update):
    with pytest.raises(ValidationError):
        validate_simple_plan({**clip_plan(), **update}, request_spec("single_clip"), owner_id="owner")


@pytest.mark.parametrize("update", [{"image": 1}, {"image": {}}, {"extra": "forbidden"}])
def test_approval_helper_rejects_malformed_edits_before_nested_access(app_ctx, update):
    original = image_plan()
    with pytest.raises(ValidationError):
        approval_request_spec(request_spec(), original, {**original, **update})


def test_aspect_capability_does_not_override_provider_size_schema(app_ctx):
    model = ModelService.get_model("wan2.6-image")
    model.capabilities = {**model.capabilities, "aspect_ratios": ["4:3"]}
    db.session.commit()
    with pytest.raises(AppError) as stopped:
        validate_generation_model(model, "t2i", {"size": "1200*900"})
    assert stopped.value.code == "INVALID_INPUT"


def test_exclusions_alone_never_expand_server_default_candidates(app_ctx):
    spec = request_spec("single_clip", exclusions=["HappyHorse"])
    assert [item.model_id for item in candidates_for_request(spec, "i2v")] == ["wan2.7-i2v"]
    with pytest.raises(AppError):
        select_for_request(request_spec("single_clip", exclusions=["wan2.7"]), "i2v")


def test_approved_plan_roundtrip_count_edit_uses_single_count_field(app_ctx):
    spec = request_spec()
    original = validate_simple_plan(image_plan(), spec, owner_id="owner")
    edited = deepcopy(original)
    edited["image"]["n"] = 3
    confirmed = approval_request_spec(spec, original, edited)
    result = validate_simple_plan(edited, confirmed, owner_id="owner")
    assert result["image"]["n"] == 3
    assert "n" not in result["image"]["params"]
    assert result["estimated_cost"] == 6
