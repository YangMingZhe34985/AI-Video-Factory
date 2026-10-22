"""Lossless Plan normalization without changing raw decisions or authority."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.agents.schemas import PlanDraft
from app.models import Job, ToolInvocation
from app.plans.aspect import delivery_inputs
from app.plans.compiler import compile_plan, plan_digest
from app.plans.node_tools import ComposeInput, QcInput
from tests.test_v3_plan_compiler import codes, make_run, node, plan, video_plan
from tests.test_v12_aspect import aspect_run, delivery

LOCAL_TOOLS = ("extract_frame", "retain_video_segment", "compose_video", "probe_media", "qc_video", "package_story", "select_image")
GENERATORS = ("generate_image", "animate_shot", "generate_video", "transform_video")


@pytest.mark.parametrize("tool", LOCAL_TOOLS)
def test_only_known_local_empty_character_lists_are_removed_before_identity(app_ctx, tool):
    raw = plan([node("local", tool, {}, characters=[])])
    before = deepcopy(raw)
    result = compile_plan(raw, make_run())
    # Other node input errors remain visible; only this redundant declaration is normalized.
    assert "characters" not in result["plan"]["nodes"][0]
    assert not any(i["code"] == "PLAN_INVALID_CHARACTER_REFERENCE" for i in result["issues"])
    assert raw == before and raw["nodes"][0]["characters"] == []


@pytest.mark.parametrize("tool", GENERATORS)
def test_generation_empty_character_lists_keep_their_empty_shot_meaning(app_ctx, tool):
    raw = plan([node("generated", tool, {}, characters=[])])
    result = compile_plan(raw, make_run())
    assert result["plan"]["nodes"][0]["characters"] == []
    assert PlanDraft.model_validate(raw).model_dump(mode="json")["nodes"][0]["characters"] == []


@pytest.mark.parametrize("characters", [["hero"], ["hero", "hero"], "", {}, False])
def test_nonempty_or_malformed_local_characters_are_not_erased(app_ctx, characters):
    result = compile_plan(plan([node("local", "compose_video", {}, characters=characters)]), make_run())
    assert codes(result) & {"INVALID_PLAN", "PLAN_INVALID_CHARACTER_REFERENCE"}
    assert result["plan"]["nodes"][0]["characters"] == characters


@pytest.mark.parametrize("tool", ["unknown_tool", [], {}])
def test_unknown_or_malformed_tool_is_rejected_without_normalizer_crash(app_ctx, tool):
    result = compile_plan(plan([node("bad", tool, {}, characters=[])]), make_run())
    assert codes(result) & {"INVALID_PLAN", "PLAN_TOOL_FORBIDDEN"}
    assert result["plan"]["nodes"][0]["characters"] == []


@pytest.mark.parametrize("aspect,size", [("16:9", "1280*720"), ("9:16", "720*1280"),
    ("1:1", "720*720"), ("4:3", "960*720"), ("3:4", "720*960")])
@pytest.mark.parametrize("tool", ["compose_video", "qc_video"])
def test_ratio_only_uses_deterministic_canvas_when_source_has_no_same_canvas(aspect, size, tool):
    value = node("delivery", tool, {"target_aspect_ratio": aspect})
    delivery_inputs(value, {}, None)
    assert value["inputs"] == {"target_aspect_ratio": aspect, "target_size": size}


@pytest.mark.parametrize("tool", ["compose_video", "qc_video"])
def test_ratio_only_inherits_same_verified_source_canvas(tool):
    source = {"width": 1920, "height": 1080, "aspect_ratio": "16:9"}
    metadata = {"artifact_id": source} if tool == "qc_video" else {"video_artifact_ids": [source]}
    value = node("delivery", tool, {"target_aspect_ratio": "16:9", "target_size": None})
    delivery_inputs(value, metadata, None)
    assert value["inputs"]["target_size"] == "1920*1080"


def test_generic_delivery_compiles_normalized_plan_without_writes_or_raw_mutation(app_ctx):
    run = make_run(deliverable="video")
    raw = delivery(video_plan(5)["nodes"])
    raw["nodes"][0]["characters"] = []
    for item in raw["nodes"][1:]:
        item["characters"] = []
        if item["tool"] in {"compose_video", "qc_video"}:
            item["inputs"]["target_aspect_ratio"] = "16:9"
    before, counts = deepcopy(raw), (Job.query.count(), ToolInvocation.query.count())
    result = compile_plan(raw, run)
    assert result["issues"] == []
    by_id = {item["id"]: item for item in result["plan"]["nodes"]}
    assert by_id["clip"]["characters"] == []
    assert all("characters" not in item for item in result["plan"]["nodes"][1:])
    assert by_id["compose"]["inputs"]["target_size"] == by_id["qc"]["inputs"]["target_size"] == "1280*720"
    again = compile_plan(result["plan"], run)
    assert again["issues"] == [] and plan_digest(again["plan"]) == plan_digest(result["plan"])
    assert raw == before and counts == (Job.query.count(), ToolInvocation.query.count())


@pytest.mark.parametrize("extra", [
    {"target_aspect_ratio": "2:1"}, {"target_size": "1280*720"},
    {"target_aspect_ratio": "16:9", "target_size": "720*1280"},
    {"target_aspect_ratio": "16:9", "target_size": "1279*720"},
    {"ratio": "16:9"}, {"size": "1280*720"}, {"videos": []},
])
def test_other_delivery_errors_and_aliases_are_not_normalized(app_ctx, extra):
    raw = delivery(video_plan(5)["nodes"])
    raw["nodes"][1]["inputs"].update(extra)
    result = compile_plan(raw, make_run(deliverable="video"))
    assert "INVALID_NODE_INPUT" in codes(result)


def test_ratio_only_never_overrides_an_explicit_brief_conflict(app_ctx):
    raw = delivery(video_plan(5)["nodes"])
    raw["nodes"][1]["inputs"]["target_aspect_ratio"] = "9:16"
    result = compile_plan(raw, aspect_run(aspect="16:9"))
    assert "PLAN_ASPECT_RATIO_MISMATCH" in codes(result)


@pytest.mark.parametrize("model,fields", [
    (ComposeInput, {"video_artifact_ids": ["video"]}),
    (QcInput, {"artifact_id": "master", "video_artifact_ids": ["video"]}),
])
def test_execution_schema_still_rejects_ratio_without_approved_size(model, fields):
    with pytest.raises(ValidationError):
        model.model_validate({"plan_version": 1, "target_aspect_ratio": "16:9", **fields})


def test_no_geometry_or_characters_still_preserves_old_unconstrained_shape(app_ctx):
    raw = delivery(video_plan(5)["nodes"])
    result = compile_plan(raw, make_run(deliverable="video"))
    assert result["issues"] == []
    assert all("characters" not in item for item in result["plan"]["nodes"])
    assert all("target_aspect_ratio" not in item["inputs"] and "target_size" not in item["inputs"]
               for item in result["plan"]["nodes"])


@pytest.mark.parametrize("raw", [[], [1], "plan", 1, None])
def test_nonobject_json_stays_a_structured_validation_failure(app_ctx, raw):
    result = compile_plan(raw, make_run())
    # finite_json historically rejects non-object payloads before PlanDraft.
    assert codes(result) == {"INVALID_WORKSPACE_PAYLOAD"}
    assert result["plan"] == {} and result["dag"]["order"] == []
