"""Deterministic Blueprint parity with v2; no LLM or provider invocation."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
from pydantic import ValidationError
import yaml

from app.agent.plan_spec import RemixShotSpec, shot_cost
from app.agent.production_plan import estimate_production_plan
from app.agent.simple_plan import validate_simple_plan
from app.agents.schemas import RequirementBrief
from app.agents.skill_library import SkillLibrary
from app.extensions import db
from app.models import AgentDelegation, AgentRun, AgentWorkspaceItem, Job, ToolInvocation
from app.plans.blueprints import BUILDERS, VERSION
from app.plans.compiler import compile_plan, plan_digest
from app.tools import build_v3_registry
from app.utils.ids import new_id
from tests.test_simple_plan import clip_plan, image_plan, image_reference, request_spec


def authored(raw):
    value = deepcopy(raw)
    for key in ("estimated_cost", "estimates", "plan_version", "manifest", "cost_breakdown", "plan_hash", "quote_id"):
        value.pop(key, None)
    return value


def make_run(spec):
    value = deepcopy(spec)
    value.pop("recipe_hint", None)
    payload = RequirementBrief.model_validate(value).model_dump(mode="json")
    run = AgentRun(owner_id="owner", request_key=new_id("req"), request={"schema_version": 3,
        "text": payload["summary"], "budget_limit": 1000,
        "attachment_ids": [item["attachment_id"] for item in payload["attachments"]]}, snapshot={})
    db.session.add(run)
    db.session.flush()
    delegation = AgentDelegation(run_id=run.run_id, agent="producer", task="Test blueprint", request_key="root", credits_limit=20)
    db.session.add(delegation)
    db.session.flush()
    db.session.add(AgentWorkspaceItem(run_id=run.run_id, key="brief", version=1, kind="brief",
        payload=payload, artifact_ids=run.request["attachment_ids"], author_agent="producer",
        delegation_id=delegation.id, request_key=new_id("brief"), inputs_hash="fixture"))
    db.session.commit()
    return run


def build(name, params, run=None):
    return BUILDERS[name][1](params, run=run or SimpleNamespace(request={"text": "创作测试"}))


def compile_built(name, params, run):
    draft = build(name, params, run)["plan"]
    normalized = compile_plan(draft, run)
    assert normalized["issues"] == [], normalized["issues"]
    run.snapshot = {**(run.snapshot or {}), "v3_blueprint_receipts": [
        {"name": name, "version": VERSION, "raw_hash": plan_digest(draft),
         "normalized_hash": plan_digest(normalized["plan"])}]}
    db.session.commit()
    compiled = compile_plan(draft, run)
    assert compiled["issues"] == [], compiled["issues"]
    return compiled


def story_data():
    story = {"story": {"logline": "寻找星光", "synopsis": "主角寻找星光并把它带回家。",
        "acts": [{"act_id": "a1", "title": "寻找", "summary": "寻找星光"}],
        "beats": [{"beat_id": "b1", "act_id": "a1", "summary": "寻找星光", "duration_sec": 15,
                   "character_ids": ["hero"], "location": "森林", "emotion": "期待"}]},
        "characters": [{"character_id": "hero", "name": "小岚", "role": "主角", "lock_description": "蓝发白衣",
            "personality": "好奇", "reference": {"source": "generate", "artifact_ids": [], "generate_prompt": "完整定妆照"}}],
        "style": {"visual_style": "动画", "palette": "蓝色", "lighting": "柔光", "camera_language": "跟拍",
                  "prompt_prefix": "二维动画"}}
    shot = {"shot_id": "s01", "scene_id": "forest", "order": 1, "beat_ids": ["b1"], "character_ids": ["hero"],
        "summary": "沿森林前行", "framing": "中景", "duration_sec": 5.0, "transition_in": "start",
        "first_frame": {"method": "generate", "image_mode": "i2i", "model_id": "wan2.7-image", "prompt": "蓝发主角位于森林"},
        "motion": {"model_id": "wan2.7-i2v", "prompt": "向前行走", "params": {"duration": 900}}, "rationale": "推进情节"}
    second = deepcopy(shot)
    second.update(shot_id="s02", order=2, transition_in="tail_frame", duration_sec=10.0,
                  first_frame={"method": "tail_frame"}, depends_on=["invented"])
    plan = {"title": "寻找星光", "target_duration_sec": 15.0, "aspect_ratio": "16:9",
            "scenes": [{"scene_id": "forest", "location": "森林", "time_of_day": "夜晚", "summary": "寻找星光"}],
            "shots": [shot, second]}
    return {"plan": plan, "story": story}


def remix_data():
    return {"source_artifact_id": "source", "plan": {"title": "局部改造", "mode": "remix", "shots": [
        {"shot_id": "keep-1", "action": "keep", "source_start": 0.0, "source_end": 1.0, "edit_reason": "保留开场"},
        {"shot_id": "replace-2", "action": "regenerate", "source_start": 1.0, "source_end": 2.5,
         "edit_reason": "修改动作", "first_frame_mode": "source", "i2v_prompt": "向前行走",
         "video_model_id": "wan2.7-i2v", "video_params": {"duration": 5}}]}}


def test_metadata_schemas_match_builders_and_all_six_are_available():
    root = Path(__file__).resolve().parents[1] / "skills"
    library = SkillLibrary(root, build_v3_registry(), strict=True)
    assert {item["name"] for item in library.list_skills() if item["blueprint"]} == set(BUILDERS)
    for name, (schema, builder) in BUILDERS.items():
        metadata = yaml.safe_load((root / name / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1])
        # Skill guidance evolves independently of deterministic Blueprint provenance.
        assert VERSION == 2
        assert metadata["version"] == (4 if name == "image-create" else 2)
        assert metadata["blueprint"]["builder"] == builder.__module__ + ":build"
        assert metadata["blueprint"]["params_schema"] == schema.model_json_schema()


@pytest.mark.parametrize("name,raw,recipe", [
    ("image-create", image_plan(), "image_create"),
    ("single-clip", clip_plan(5), "single_clip"),
    ("single-clip", clip_plan(15), "single_clip"),
])
def test_simple_blueprint_matches_v2_effective_models_params_cost(app_ctx, name, raw, recipe):
    spec = request_spec(recipe)
    run = make_run(spec)
    expected = validate_simple_plan(raw, spec, owner_id=run.owner_id)
    before = (ToolInvocation.query.count(), Job.query.count(), AgentWorkspaceItem.query.count())
    result = compile_built(name, {"plan": authored(raw)}, run)
    assert result["estimates"]["total_credits"] == expected["estimated_cost"]
    assert not result["experimental"]
    for key in ("image", "video"):
        if not expected.get(key):
            continue
        actual = next(item for item in result["plan"]["nodes"] if item["id"] == key)
        assert actual["model_id"] == expected[key]["model_id"]
        assert actual["params"] == {**expected[key]["params"], **({"n": expected[key]["n"]} if key == "image" else {})}
    assert (ToolInvocation.query.count(), Job.query.count(), AgentWorkspaceItem.query.count()) == before


@pytest.mark.parametrize("count", [1, 4])
def test_image_edit_preserves_all_outputs_and_refs(app_ctx, count):
    image = image_reference()
    spec = request_spec("image_edit", [image])
    run = make_run(spec)
    raw = authored(image_plan("i2i", [image["attachment_id"]]))
    raw["image"]["n"] = count
    expected = validate_simple_plan(raw, spec, owner_id=run.owner_id)
    result = compile_built("image-edit", {"plan": raw}, run)
    assert result["plan"]["nodes"][0]["inputs"]["reference_artifact_ids"] == [{"artifact": image["attachment_id"]}]
    assert result["plan"]["deliverables"] == [{"kind": "image", "node_id": "image", "output": "images"}]
    assert result["estimates"]["total_credits"] == expected["estimated_cost"]


def test_single_clip_owned_first_frame_does_not_generate_an_image(app_ctx):
    image = image_reference()
    image["role"] = "first_frame"
    run = make_run(request_spec("single_clip", [image]))
    raw = authored(clip_plan())
    raw.pop("image")
    raw["video"].update(first_frame="user_attachment", first_frame_attachment_id=image["attachment_id"])
    result = compile_built("single-clip", {"plan": raw}, run)
    assert [item["tool"] for item in result["plan"]["nodes"]] == ["animate_shot"]
    assert result["estimates"]["total_credits"] == 5


def test_story_blueprint_preserves_v2_cost_and_role_gate_dependency(app_ctx):
    spec = request_spec("single_clip")
    spec.update(recipe_hint="story_video", target_duration_sec=15)
    run = make_run(spec)
    params = story_data()
    result = compile_built("story-video", params, run)
    expected = estimate_production_plan(params["plan"], params["story"], spec)
    assert result["estimates"]["total_credits"] == expected["total_credits"] == 19
    assert result["estimates"]["generated_video_seconds"] == result["estimates"]["video_seconds"] == 15
    nodes = {item["id"]: item for item in result["plan"]["nodes"]}
    assert nodes["character_001"]["gate"] == nodes["s01_first"]["gate"] == "preview"
    assert nodes["s01_first"]["inputs"]["reference_artifact_ids"] == [{"ref": "character_001.image"}]
    assert nodes["s02_first"]["inputs"] == {"video_artifact_id": {"ref": "s01.video"}, "position": "last"}
    assert nodes["s02"]["params"]["duration"] == 10
    assert result["dag"]["dependencies"]["s02_first"] == ["s01"]
    assert nodes["compose"]["inputs"]["compress_output"] is False
    assert nodes["package"]["depends_on"] == ["qc"]
    assert ToolInvocation.query.count() == 0


def test_independent_story_shots_and_existing_identity_skip_generated_portrait(app_ctx):
    image = image_reference()
    run = make_run(request_spec("single_clip", [image]))
    params = story_data()
    params["story"]["characters"][0]["reference"] = {"source": "attachment", "artifact_ids": [image["attachment_id"]]}
    second = params["plan"]["shots"][1]
    second.update(transition_in="independent", first_frame=deepcopy(params["plan"]["shots"][0]["first_frame"]))
    result = compile_built("story-video", params, run)
    nodes = {item["id"]: item for item in result["plan"]["nodes"]}
    assert "character_001" not in nodes
    assert result["dag"]["dependencies"]["s02_first"] == []
    assert nodes["s02_first"]["inputs"]["reference_artifact_ids"] == [{"artifact": image["attachment_id"]}]


def test_first_last_frame_is_explicitly_capability_gated(app_ctx):
    from flask import current_app
    run = make_run(request_spec("single_clip"))
    params = story_data()
    shot = params["plan"]["shots"][1]
    shot.update(transition_in="keyframe_bridge", first_frame=deepcopy(params["plan"]["shots"][0]["first_frame"]),
                end_frame=deepcopy(params["plan"]["shots"][0]["first_frame"]))
    shot["motion"]["mode"] = "first_last_frame"
    draft = build("story-video", params, run)["plan"]
    denied = compile_plan(draft, run)
    assert any(item["code"] == "KEYFRAME_BRIDGE_UNAVAILABLE" for item in denied["issues"])
    current_app.config["AGENT_ENABLE_KEYFRAME_BRIDGE"] = True
    allowed = compile_plan(draft, run)
    assert allowed["issues"] == []
    motion = next(item for item in allowed["plan"]["nodes"] if item["id"] == "s02")
    assert motion["inputs"]["last_frame_artifact_id"] == {"ref": "s02_last.image"}


@pytest.mark.parametrize("mutate", [
    lambda value: value["plan"]["shots"][0].update(order=2),
    lambda value: value["plan"]["shots"][1].update(scene_id="unknown"),
    lambda value: value["plan"]["shots"][1].update(character_ids=["unknown"]),
    lambda value: value["plan"]["shots"][1].update(end_frame={"method": "tail_frame"}),
    lambda value: value["plan"]["shots"][0]["first_frame"].update(image_mode="t2i"),
])
def test_invalid_story_semantics_do_not_emit_a_blueprint(app_ctx, mutate):
    run = make_run(request_spec("single_clip"))
    params = story_data()
    mutate(params)
    with pytest.raises(ValueError):
        build("story-video", params, run)


@pytest.mark.parametrize("generated_frame", [False, True])
def test_remix_separates_retained_source_range_and_generated_seconds(app_ctx, monkeypatch, generated_frame):
    monkeypatch.setattr("app.plans.blueprints.video_remix.source_duration", lambda _run, _id: 3)
    params = remix_data()
    shot = params["plan"]["shots"][1]
    if generated_frame:
        shot.update(first_frame_mode="generate", first_frame_prompt="蓝发主角", image_model_id="wan2.6-image")
    before = ToolInvocation.query.count()
    draft = build("video-remix", params)["plan"]
    nodes = {item["id"]: item for item in draft["nodes"]}
    assert nodes["s001"]["tool"] == "retain_video_segment"
    assert nodes["s001"]["inputs"] == {"video_artifact_id": {"artifact": "source"}, "source_start_sec": 0.0, "source_end_sec": 1.0}
    assert nodes["s002"]["params"]["duration"] == 5
    assert nodes["s002_frame"]["tool"] == ("generate_image" if generated_frame else "extract_frame")
    if not generated_frame:
        assert nodes["s002_frame"]["inputs"]["timestamp_sec"] == 1.0
    assert shot_cost(RemixShotSpec.model_validate(shot)) == (7 if generated_frame else 5)
    assert shot_cost(RemixShotSpec.model_validate(params["plan"]["shots"][0])) == 0
    assert ToolInvocation.query.count() == before


@pytest.fixture
def source_video(app_ctx, tmp_path):
    from werkzeug.datastructures import FileStorage
    from app.agent.attachments import upload_attachment
    from app.services.video_compression_service import VideoCompressionService
    path = tmp_path / "source.mp4"
    subprocess.run([VideoCompressionService.resolve_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=256x256:r=20", "-t", "5.25", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True, timeout=30)
    with path.open("rb") as stream:
        return upload_attachment(FileStorage(stream=stream, filename="source.mp4"), "owner")["attachment_id"]


def test_remix_compiler_matches_source_ranges_output_order_and_v2_cost(app_ctx, source_video):
    spec = request_spec("single_clip", [{"attachment_id": source_video, "kind": "video", "role": "remix_source",
                                          "description": "原片", "reason": "保留并改造"}])
    run = make_run(spec)
    params = remix_data()
    params["source_artifact_id"] = source_video
    compiled = compile_built("video-remix", params, run)
    expected = sum(shot_cost(RemixShotSpec.model_validate(value)) for value in params["plan"]["shots"])
    assert compiled["estimates"]["total_credits"] == expected == 5
    assert compiled["estimates"]["video_seconds"] == 6
    assert compiled["estimates"]["generated_video_seconds"] == 5
    compose = next(item for item in compiled["plan"]["nodes"] if item["tool"] == "compose_video")
    assert compose["inputs"]["video_artifact_ids"] == [{"ref": "s001.artifact_id"}, {"ref": "s002.video"}]
    params["plan"]["shots"][1]["source_end"] = 500.0
    from app.api import AppError
    with pytest.raises(AppError) as invalid:
        build("video-remix", params, run)
    assert invalid.value.code == "INVALID_SOURCE_RANGE"
    assert ToolInvocation.query.count() == 0


@pytest.mark.parametrize("operation", ["reference", "edit", "extend"])
def test_transform_blueprint_matches_v2_measured_input_plus_output_quote(app_ctx, source_video, operation):
    from app.agent.transform_plan import validate_transform_plan
    spec = request_spec("single_clip", [{"attachment_id": source_video, "kind": "video",
        "role": "content_ref" if operation == "reference" else "transform_source", "description": "原片", "reason": "视频变换"}],
        preferences=["wan3.0系列"])
    spec.update(recipe_hint="video_transform", transform={"operation": operation,
        "source_attachment_id": None if operation == "reference" else source_video})
    run = make_run(spec)
    plan = {"operation": operation, "title": "视频变换", "model_id": "wan3.0-video", "prompt": "保留主体自然运动",
            "media": [{"type": "reference_video", "artifact_id": source_video}],
            "params": {"duration": 8, "resolution": "720P"}, "rationale": "保留原片主体"}
    if operation != "reference":
        plan["source_artifact_id"] = source_video
    expected = validate_transform_plan(plan, spec, run=run, check_budget=False)
    compiled = compile_built("video-transform", {"plan": plan}, run)
    estimate = compiled["estimates"]["nodes"][0]
    assert estimate["input_video_seconds"] == expected["cost_breakdown"]["input_video_seconds"] == 5.25
    assert estimate["output_video_seconds"] == expected["cost_breakdown"]["output_video_seconds"] == 8
    assert estimate["estimated_cost"] == expected["estimated_cost"]
    assert compiled["plan"]["nodes"][0]["params"] == expected["params"]
    assert ToolInvocation.query.count() == 0


@pytest.mark.parametrize("operation", ["reference", "edit", "extend"])
def test_transform_preserves_native_semantics_without_accepting_client_media_facts(operation):
    raw = {"operation": operation, "title": "改造视频", "model_id": "wan3.0-video", "prompt": "保留主体",
           "params": {"duration": 8, "resolution": "720P"}, "rationale": "实现需求",
           "media": [{"type": "reference_video", "artifact_id": "source"}]}
    if operation != "reference":
        raw["source_artifact_id"] = "source"
    draft = build("video-transform", {"plan": raw})["plan"]
    video = draft["nodes"][0]
    assert video["tool"] == "transform_video" and video["model_id"] == "wan3.0-video"
    assert video["params"] == raw["params"]
    assert video["inputs"]["media"] == [{"type": "reference_video", "artifact_id": {"artifact": "source"}}]
    assert "plan_hash" not in video["inputs"]
    assert ("source_artifact_id" in video["inputs"]) is (operation != "reference")


@pytest.mark.parametrize("name,params,key", [
    ("image-create", {"plan": authored(image_plan())}, "estimated_cost"),
    ("story-video", story_data(), "plan_version"),
    ("story-video", story_data(), "estimates"),
    *[("video-transform", {"plan": {"operation": "reference", "title": "参考视频", "model_id": "wan3.0-video",
       "prompt": "按参考创作", "media": [{"type": "reference_image", "artifact_id": "image"}], "rationale": "参考"}}, key)
      for key in ("manifest", "cost_breakdown", "plan_hash", "quote_id", "estimated_cost")],
])
def test_author_schema_rejects_server_fields(name, params, key):
    params = deepcopy(params)
    params["plan"][key] = 0
    with pytest.raises(ValidationError):
        BUILDERS[name][0].model_validate(params)


def test_builder_does_not_mutate_input_and_output_cannot_alias_next_call():
    params = {"plan": authored(clip_plan())}
    snapshot = deepcopy(params)
    first = build("single-clip", params)
    first["plan"]["nodes"][0]["params"]["n"] = 4
    assert params == snapshot
    assert build("single-clip", params)["plan"]["nodes"][0]["params"]["n"] == 1
