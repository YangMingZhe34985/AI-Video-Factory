"""Offline v3 multi-reference selection, immutable review and Mock dispatch."""
from copy import deepcopy

import pytest

from app.agent.model_selection import select_for_request, validate_generation_model
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, Job, ModelRegistry, ToolInvocation
from app.plans import runtime
from app.plans.blueprints import BUILDERS
from app.plans.compiler import compile_plan, request_spec_for_run
from app.plans.dry_run import dry_run
from app.plans.model_selection import select_generation_model
from app.services.job_run_service import JobRunService
from app.tools import build_v3_registry
from app.tools.budget import BudgetGuard
from app.tools.spec import ToolContext
from tests.test_v3_blueprints import story_data
from tests.test_v3_plan_compiler import image, make_run, node, plan
from tests.test_v4_execution import drain_plan, setup

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)


def edit_plan(ids, *, model_id=None, params=None):
    return plan([node("edit", inputs={"mode": "i2i", "prompt": "Put both identities in one frame",
        "reference_artifact_ids": [{"artifact": identity} for identity in ids]}, model_id=model_id,
        params={"n": 1} if params is None else params)],
        [{"kind": "image", "node_id": "edit", "output": "images"}])


def owned(count=2, **kwargs):
    ids = [image() for _ in range(count)]
    return make_run(ids=ids, **kwargs), ids


def valid(draft, run):
    result = compile_plan(draft, run)
    assert not result["issues"], result["issues"]
    assert dry_run(result)["passed"]
    return result


def model(identity="wan2.7-image"):
    return ModelRegistry.query.filter_by(model_id=identity).one()


def test_unspecified_multireference_keeps_every_identity_and_roundtrips_frozen_params(app_ctx):
    run, ids = owned()
    draft = edit_plan(ids)
    before = deepcopy(draft)
    result = valid(draft, run)
    output = result["plan"]["nodes"][0]
    assert output["model_id"] == "qwen-image-3.0"
    assert output["inputs"]["reference_artifact_ids"] == [{"artifact": item} for item in ids]
    assert output["params"]["prompt_extend_mode"] == "direct"
    assert output["params"]["enable_thinking"] is False
    assert draft == before
    again = valid(result["plan"], run)
    assert again["plan"] == result["plan"]
    assert again["estimates"] == result["estimates"]
    assert result["estimates"]["total_credits"] > 0
    assert ToolInvocation.query.count() == 0


@pytest.mark.parametrize("future_array", [False, True])
def test_future_references_count_arrays_and_separate_identity_nodes(app_ctx, future_array):
    run = make_run()
    if future_array:
        nodes = [node("identities", params={"n": 2}), node("edit", inputs={"mode": "i2i",
            "prompt": "Both characters together", "reference_artifact_ids": {"ref": "identities.images"}})]
    else:
        nodes = [node("first"), node("second"), node("edit", inputs={"mode": "i2i",
            "prompt": "Both characters together", "reference_artifact_ids": [{"ref": "first.image"}, {"ref": "second.image"}]})]
    result = valid(plan(nodes, [{"kind": "image", "node_id": "edit", "output": "images"}]), run)
    selected = next(item for item in result["plan"]["nodes"] if item["id"] == "edit")
    assert selected["model_id"] == "qwen-image-3.0"
    assert len(result["validated_inputs"]["edit"]["reference_artifact_ids"]) == 2
    assert result["dag"]["dependencies"]["edit"] == (["identities"] if future_array else ["first", "second"])


@pytest.mark.parametrize("count,default", [(1, "wan2.7-image"), (2, "qwen-image-3.0-pro")])
def test_capable_default_is_preserved_even_when_other_models_exist(app_ctx, count, default):
    app_ctx.config["DEFAULT_I2I_TEST_IMAGE_MODEL"] = default
    run, ids = owned(count)
    assert valid(edit_plan(ids), run)["plan"]["nodes"][0]["model_id"] == default


@pytest.mark.parametrize("selected,count", [("wan2.7-image", 2), ("qwen-image-3.0", 1)])
def test_concrete_incompatible_or_unnecessary_nondefault_is_not_replaced(app_ctx, selected, count):
    run, ids = owned(count)
    draft = edit_plan(ids, model_id=selected)
    result = compile_plan(draft, run)
    assert any(item["code"] == "MODEL_CAPABILITY_MISMATCH" for item in result["issues"])
    assert draft["nodes"][0]["model_id"] == selected


def test_unknown_concrete_model_error_does_not_echo_supplied_value(app_ctx):
    run, ids = owned()
    supplied = "private-user-model-input"
    result = compile_plan(edit_plan(ids, model_id=supplied), run)
    issue = next(item for item in result["issues"] if item["code"] == "MODEL_CAPABILITY_MISMATCH")
    assert "Requested 2 reference images" in issue["message"]
    assert supplied not in issue["message"]


@pytest.mark.parametrize("preferences", [("wan2.7-image",), ("Wan 2.7 Image",), ("wan2.7系列",)])
def test_user_exact_model_and_family_are_never_relaxed_for_capacity(app_ctx, preferences):
    run, ids = owned(preferences=preferences)
    result = compile_plan(edit_plan(ids), run)
    assert any(item["code"] == "MODEL_CAPABILITY_MISMATCH" for item in result["issues"])
    assert not result["estimates"]["nodes"]


def test_qualified_concrete_pool_member_and_explicit_family_remain_valid(app_ctx):
    run, ids = owned()
    result = valid(edit_plan(ids, model_id="qwen-image-3.0-pro"), run)
    assert result["plan"]["nodes"][0]["model_id"] == "qwen-image-3.0-pro"
    preferred, own_ids = owned(preferences=("qwen-image-3.0系列",), exclusions=("qwen-image-3.0-pro",))
    assert valid(edit_plan(own_ids), preferred)["plan"]["nodes"][0]["model_id"] == "qwen-image-3.0"


def test_exclusions_remove_candidates_and_all_excluded_reports_no_pool(app_ctx):
    run, ids = owned(exclusions=("qwen-image-3.0",))
    assert valid(edit_plan(ids), run)["plan"]["nodes"][0]["model_id"] == "qwen-image-3.0-pro"
    blocked, own_ids = owned(exclusions=("qwen-image-3.0系列",))
    result = compile_plan(edit_plan(own_ids), blocked)
    assert any("Requested 2 reference images" in item["message"] for item in result["issues"])
    assert not result["estimates"]["nodes"]


@pytest.mark.parametrize("break_default", ["disabled", "adapter", "unselectable", "excluded"])
def test_broken_or_excluded_default_does_not_enable_substitution(app_ctx, break_default):
    run, ids = owned(exclusions=("wan2.7-image",) if break_default == "excluded" else ())
    default = model()
    if break_default == "disabled":
        default.enabled = False
    elif break_default == "adapter":
        default.adapter_name = "not-integrated"
    elif break_default == "unselectable":
        default.capabilities = {**default.capabilities, "agent_selectable": False}
    db.session.commit()
    result = compile_plan(edit_plan(ids), run)
    assert any(item["code"] == "MODEL_CAPABILITY_MISMATCH" for item in result["issues"])
    assert not result["estimates"]["nodes"]


@pytest.mark.parametrize("bad_params", [{"invented_parameter": 1}, {"n": 99}, {"prompt_extend_mode": "agent"}])
def test_fallback_never_drops_invalid_parameters(app_ctx, bad_params):
    run, ids = owned()
    draft = edit_plan(ids, params=bad_params)
    result = compile_plan(draft, run)
    assert result["issues"]
    assert draft["nodes"][0]["params"] == bad_params
    assert not result["estimates"]["nodes"]


def test_unintegrated_or_disabled_candidate_is_not_selected(app_ctx):
    run, ids = owned()
    model("qwen-image-3.0").adapter_name = "not-integrated"
    db.session.commit()
    assert valid(edit_plan(ids), run)["plan"]["nodes"][0]["model_id"] == "qwen-image-3.0-pro"
    model("qwen-image-3.0-pro").enabled = False
    db.session.commit()
    assert compile_plan(edit_plan(ids), run)["issues"]


def test_automatic_candidate_validates_every_parameter_but_concrete_model_is_not_replaced(app_ctx):
    run, ids = owned()
    standard = model("qwen-image-3.0")
    standard.parameter_schema = {**standard.parameter_schema,
        "n": {**standard.parameter_schema["n"], "enum": [2]}}
    db.session.commit()
    assert valid(edit_plan(ids), run)["plan"]["nodes"][0]["model_id"] == "qwen-image-3.0-pro"
    draft = edit_plan(ids, model_id="qwen-image-3.0")
    assert any(item["code"] == "INVALID_INPUT" for item in compile_plan(draft, run)["issues"])
    assert draft["nodes"][0]["model_id"] == "qwen-image-3.0"


@pytest.mark.parametrize("code", ["BUDGET_EXCEEDED", "INTERNAL_ERROR"])
def test_candidate_loop_never_masks_unexpected_or_budget_errors(app_ctx, monkeypatch, code):
    run, _ids = owned()
    seen = []
    def fail(candidate, *_args, **_kwargs):
        seen.append(candidate.model_id)
        raise AppError(code, "Injected failure", 500)
    monkeypatch.setattr("app.plans.model_selection.validate_generation_model", fail)
    with pytest.raises(AppError) as failure:
        select_generation_model(request_spec_for_run(run), "i2i", None, {"n": 1},
            reference_count=2, run=run)
    assert failure.value.code == code and seen == ["qwen-image-3.0"]


def test_v2_selector_and_single_reference_validation_are_unchanged(app_ctx):
    run, _ids = owned()
    spec = request_spec_for_run(run)
    selected = select_for_request(spec, "i2i")
    assert selected.model_id == "wan2.7-image"
    with pytest.raises(AppError):
        validate_generation_model(selected, "i2i", {"n": 1}, reference_count=2)
    run.request = {**run.request, "schema_version": 2}
    with pytest.raises(AppError):
        select_generation_model(spec, "i2i", None, {"n": 1}, reference_count=2, run=run)


def test_blueprint_resolved_id_survives_submission_begin_and_real_mock_job(app_ctx, monkeypatch):
    run, ids = owned()
    result = valid(edit_plan(ids), run)
    chosen = result["plan"]["nodes"][0]["model_id"]
    parent = AgentDelegation.query.filter_by(run_id=run.run_id).one()
    registry = build_v3_registry()
    def context(key):
        return ToolContext(role="producer", caller_agent="producer", delegation_id=parent.id,
            budget_scope=run.run_id, budget_limit=1000, idempotency_key=key)
    built = registry.invoke("instantiate_blueprint", {"name": "image-edit", "params": {"plan": {
        "recipe": "image_edit", "title": "两人同框", "rationale": "保留两人身份", "image": {"mode": "i2i",
        "model_id": chosen, "prompt": "Both characters in one frame", "reference_attachment_ids": ids, "n": 1}}}},
        context("build"))["output"]
    assert not built["issues"]
    submitted = registry.invoke("submit_plan", {"plan_ref": built["workspace_ref"]}, context("submit"))["output"]
    assert submitted["submitted"]
    from app.agent.plan_versions import current_version
    version = current_version(run)
    runtime.begin(run, version, registry=registry)
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    assert drain_plan(run, registry) == "awaiting_result_review"
    task = runtime.latest_tasks(run)["image"]
    assert task.inputs["model_id"] == chosen
    assert task.inputs["reference_artifact_ids"] == ids
    assert task.status == "success" and task.output["image"]
    assert Job.query.filter_by(job_id=task.job_id).one().config["node_models"]["submit_first_frame_image"] == chosen
    assert BudgetGuard.spent(run.run_id) == task.estimated_cost


def test_new_model_quote_still_requires_budget_and_unchanged_price(app_ctx):
    run, ids = owned()
    _, version, registry = setup(edit_plan(ids)["nodes"], run=run,
        deliverables=[{"kind": "image", "node_id": "edit", "output": "images"}])
    run.request = {**run.request, "budget_limit": .01}
    db.session.commit()
    with pytest.raises(AppError) as low:
        runtime.begin(run, version, registry=registry)
    assert low.value.code == "BUDGET_EXCEEDED" and not runtime.latest_tasks(run)
    run.request = {**run.request, "budget_limit": 1000}
    selected = model(version.plan["nodes"][0]["model_id"])
    caps = deepcopy(selected.capabilities)
    caps["pricing"]["credits_per_unit"] *= 2
    selected.capabilities = caps
    db.session.commit()
    with pytest.raises(AppError) as drift:
        runtime.begin(run, version, registry=registry)
    assert drift.value.code == "MODEL_PRICE_CHANGED" and not runtime.latest_tasks(run)


def test_two_character_story_auto_frames_preserve_both_generated_references(app_ctx):
    run = make_run(deliverable="video")
    data = story_data()
    other = deepcopy(data["story"]["characters"][0])
    other.update(character_id="friend", name="小白", lock_description="白发黑衣")
    data["story"]["characters"].append(other)
    for shot in data["plan"]["shots"]:
        shot["character_ids"] = ["hero", "friend"]
        if shot["first_frame"]["method"] == "generate":
            shot["first_frame"]["model_id"] = None
    built = BUILDERS["story-video"][1](data, run=run, caller_agent="director")
    result = valid(built["plan"], run)
    first = next(item for item in result["plan"]["nodes"] if item["id"] == "s01_first")
    assert first["model_id"] == "qwen-image-3.0"
    assert first["inputs"]["reference_artifact_ids"] == [{"ref": "character_001.image"}, {"ref": "character_002.image"}]
    assert len(result["validated_inputs"]["s01_first"]["reference_artifact_ids"]) == 2
    assert valid(result["plan"], run)["plan"] == result["plan"]


def test_story_counts_shared_identity_artifact_once_and_keeps_default(app_ctx):
    identity = image()
    run = make_run(ids=[identity], deliverable="video")
    data = story_data()
    character = data["story"]["characters"][0]
    character["reference"] = {"source": "attachment", "artifact_ids": [identity]}
    other = deepcopy(character)
    other.update(character_id="friend", name="小白", lock_description="同一张双人定妆照中的白发角色")
    data["story"]["characters"].append(other)
    for shot in data["plan"]["shots"]:
        shot["character_ids"] = ["hero", "friend"]
        if shot["first_frame"]["method"] == "generate":
            shot["first_frame"].update(model_id=None, reference_artifact_ids=[identity])
    built = BUILDERS["story-video"][1](data, run=run, caller_agent="director")
    result = valid(built["plan"], run)
    first = next(item for item in result["plan"]["nodes"] if item["id"] == "s01_first")
    assert first["model_id"] == "wan2.7-image"
    assert first["inputs"]["reference_artifact_ids"] == [{"artifact": identity}]
