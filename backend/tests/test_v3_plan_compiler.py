"""Compiler and in-memory dry-run invariants without LLM or provider calls."""

from copy import deepcopy
from io import BytesIO

from PIL import Image
import pytest
from werkzeug.datastructures import FileStorage

from app.agent.attachments import upload_attachment
from app.agents.workspace import write_workspace
from app.extensions import db
from app.models import AgentDelegation, AgentRun, Artifact, Job, ModelRegistry, ToolInvocation
from app.plans.compiler import compile_plan, node_inputs, plan_digest, resolve_inputs
from app.plans.dry_run import dry_run
from app.tools import build_v3_registry
from app.tools.spec import ToolContext
from app.utils.ids import new_id


def make_run(*, deliverable="image", preferences=(), exclusions=(), ids=(), owner="owner", compress=False):
    row = AgentRun(owner_id=owner, request_key=new_id("req"), request={"schema_version": 3,
        "text": "生成图像视频 " + " ".join([*preferences, *exclusions]), "attachment_ids": list(ids), "budget_limit": 1000})
    db.session.add(row)
    db.session.flush()
    delegation = AgentDelegation(run_id=row.run_id, agent="producer", task="plan", request_key="root", credits_limit=20)
    db.session.add(delegation)
    db.session.commit()
    attachments = [{"attachment_id": item, "kind": Artifact.query.filter_by(artifact_id=item).one().meta["media"]["kind"],
                    "role": "content_ref", "description": "reference", "reason": "reference"} for item in ids]
    ctx = ToolContext(role="producer", caller_agent="producer", delegation_id=delegation.id,
                      budget_scope=row.run_id, idempotency_key="brief")
    write_workspace("brief", "brief", {"deliverable": deliverable, "summary": "test", "confidence": .9,
        "attachments": attachments, "constraints": {"model_preferences": list(preferences), "model_exclusions": list(exclusions), "compress_output": compress}}, ctx)
    return row


def image(owner="owner"):
    data = BytesIO()
    Image.new("RGB", (256, 256), "blue").save(data, "PNG")
    data.seek(0)
    return upload_attachment(FileStorage(stream=data, filename="test.png", content_type="image/png"), owner)["attachment_id"]


def node(node_id="image", tool="generate_image", inputs=None, **kwargs):
    return {"id": node_id, "tool": tool, "inputs": {"prompt": "cat"} if inputs is None else inputs,
            "origin": {"agent": "director", "skills": []}, "rationale": "test", **kwargs}


def plan(nodes=None, deliverables=None):
    return {"title": "Test", "goal": "make a cat", "nodes": nodes or [node()],
            "deliverables": deliverables or [{"kind": "image", "node_id": "image", "output": "images"}]}


def video_plan(seconds=5):
    return plan([node("clip", "generate_video", {"mode": "t2v", "prompt": "cat"}, params={"duration": seconds})],
                [{"kind": "video", "node_id": "clip", "output": "video"}])


def codes(result):
    return {item["code"] for item in result["issues"]}


def counts():
    return (Job.query.count(), Artifact.query.count(), ToolInvocation.query.count(), ModelRegistry.query.count())


def test_compile_freezes_defaults_and_dry_run_has_no_side_effects(app_ctx, monkeypatch):
    run = make_run()
    registry = build_v3_registry()
    before = counts()
    result = compile_plan(plan(), run, registry=registry)
    assert result["issues"] == []
    assert result["plan"]["nodes"][0]["model_id"] == "wan2.6-image"
    assert result["estimates"]["total_credits"] > 0
    assert result["experimental"] is True
    monkeypatch.setattr(registry, "invoke", lambda *_a, **_kw: pytest.fail("Dry run cannot invoke production tools"))
    monkeypatch.setattr(db.session, "commit", lambda: pytest.fail("Dry run cannot commit"))
    monkeypatch.setattr(db.session, "flush", lambda *_a, **_kw: pytest.fail("Dry run cannot flush"))
    verified = dry_run(result, registry=registry)
    assert verified["passed"] and verified["estimated_cost"] == 0
    assert verified["outputs"]["image"]["images"]
    # Querying counts can autoflush; leave the zero-write scope before reading.
    monkeypatch.undo()
    assert counts() == before


def test_compile_requires_a_validated_brief(app_ctx):
    run = AgentRun(owner_id="owner", request_key="none", request={"schema_version": 3})
    db.session.add(run)
    db.session.commit()
    assert "BRIEF_REQUIRED" in codes(compile_plan(plan(), run))


def test_invalid_nonfinite_draft_is_not_reflected_in_a_public_result(app_ctx):
    result = compile_plan(plan([node(params={"bad": float("nan")})]), make_run())
    assert result["issues"] and result["plan"] == {}


@pytest.mark.parametrize("field,value", [("model_id", "wan2.7-image"), ("params", {}), ("template_id", "classic"), ("plan_version", 1)])
def test_server_owned_node_fields_are_rejected_inside_inputs(app_ctx, field, value):
    run = make_run()
    value = compile_plan(plan([node(inputs={"prompt": "cat", field: value})]), run)
    assert "RESERVED_INPUT" in codes(value)


@pytest.mark.parametrize("bad", ["web_search", "agent_llm_turn", "run_workflow_template"])
def test_non_execution_tools_are_rejected(app_ctx, bad):
    assert "PLAN_TOOL_FORBIDDEN" in codes(compile_plan(plan([node(tool=bad)]), make_run()))


def test_references_and_scalar_array_outputs_are_strict(app_ctx):
    app_ctx.config["DEFAULT_I2I_TEST_IMAGE_MODEL"] = "qwen-image-3.0"
    run = make_run()
    draft = plan([node(params={"n": 2}), node("edit", inputs={"mode": "i2i", "prompt": "edit",
        "reference_artifact_ids": {"ref": "image.images"}})], [{"kind": "image", "node_id": "edit", "output": "images"}])
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert result["dag"]["dependencies"]["edit"] == ["image"]
    assert len(result["validated_inputs"]["edit"]["reference_artifact_ids"]) == 2
    assert dry_run(result)["passed"]
    draft["nodes"][1]["inputs"]["reference_artifact_ids"] = {"ref": "image.image"}
    assert "PLAN_TYPE_MISMATCH" in codes(compile_plan(draft, run))
    draft["nodes"][1]["inputs"]["reference_artifact_ids"] = [{"ref": "image.images"}]
    assert "PLAN_TYPE_MISMATCH" in codes(compile_plan(draft, run))
    draft["nodes"][1]["inputs"]["reference_artifact_ids"] = [{"ref": "image.image"}]
    assert compile_plan(draft, run)["issues"] == []


@pytest.mark.parametrize("value", [{"ref": "missing.image"}, {"ref": "image.no_such_output"},
    {"ref": "image.image", "fallback": "id"}, {"artifact": "x", "ref": "image.image"}, {"ref": "image"}])
def test_invalid_reference_objects_cannot_reach_execution(app_ctx, value):
    run = make_run()
    draft = plan([node(), node("edit", inputs={"mode": "i2i", "prompt": "edit", "reference_artifact_ids": [value]})])
    assert compile_plan(draft, run)["issues"]


def test_literal_and_wrapped_artifacts_both_require_run_ownership(app_ctx):
    own, foreign = image(), image("other")
    run = make_run(ids=[own])
    for value in (own, {"artifact": own}):
        assert compile_plan(plan([node(inputs={"mode": "i2i", "prompt": "edit", "reference_artifact_ids": [value]})]), run)["issues"] == []
    for value in (foreign, {"artifact": foreign}, "../../secret.png", "https://example.com/image.png"):
        assert compile_plan(plan([node(inputs={"mode": "i2i", "prompt": "edit", "reference_artifact_ids": [value]})]), run)["issues"]


def test_reference_cannot_hide_inside_unknown_field_or_parameters(app_ctx):
    run = make_run()
    for payload in ({"prompt": "cat", "arbitrary": {"artifact": "foo"}}, {"prompt": {"artifact": "foo"}}):
        assert compile_plan(plan([node(inputs=payload)]), run)["issues"]
    assert compile_plan(plan([node(params={"size": {"ref": "image.image"}})]), run)["issues"]


def test_explicit_dependencies_participate_in_cycle_depth_and_fanout(app_ctx):
    run = make_run()
    draft = plan([node(depends_on=["second"]), node("second", depends_on=["image"])])
    assert "PLAN_CYCLE" in codes(compile_plan(draft, run))
    chain = [node("n" + str(index), depends_on=["n" + str(index - 1)] if index else []) for index in range(31)]
    draft = plan(chain, [{"kind": "image", "node_id": "n30", "output": "image"}])
    assert "PLAN_DEPTH_LIMIT" in codes(compile_plan(draft, run))
    draft = plan([node(), *[node("n" + str(index), depends_on=["image"]) for index in range(51)]])
    assert "PLAN_FANOUT_LIMIT" in codes(compile_plan(draft, run))


def test_structural_schema_and_unknown_stages_are_checked(app_ctx):
    run = make_run()
    assert "INVALID_PLAN" in codes(compile_plan(plan([node() for _ in range(201)]), run))
    assert "UNKNOWN_STAGE" in codes(compile_plan(plan([node(stage="not_declared")]), run))
    assert "DUPLICATE_DEPENDENCY" in codes(compile_plan(plan([node(), node("next", depends_on=["image", "image"])]), run))


def test_model_family_and_exclusions_apply_to_every_video_mode(app_ctx):
    run = make_run(deliverable="video", preferences=["wan2.7系列"], exclusions=["happyhorse"])
    draft = video_plan()
    assert compile_plan(draft, run)["issues"] == []
    draft["nodes"][0]["model_id"] = "happy-horse-t2v"
    assert "MODEL_CAPABILITY_MISMATCH" in codes(compile_plan(draft, run))
    draft = plan([node(), node("clip", "animate_shot", {"first_frame_artifact_id": {"ref": "image.image"}, "prompt": "cat"},
        model_id="wan2.6-i2v-flash", params={"duration": 5})], [{"kind": "video", "node_id": "clip", "output": "video"}])
    assert "MODEL_CAPABILITY_MISMATCH" in codes(compile_plan(draft, run))


def test_no_user_model_preference_uses_server_default(app_ctx):
    run = make_run(deliverable="video")
    draft = video_plan()
    draft["nodes"][0]["model_id"] = "wan3.0-video"
    assert "MODEL_CAPABILITY_MISMATCH" in codes(compile_plan(draft, run))


def test_video_pricing_uses_seconds_and_rejects_illegal_durations(app_ctx):
    run = make_run(deliverable="video")
    five, fifteen = compile_plan(video_plan(5), run), compile_plan(video_plan(15), run)
    assert five["issues"] == fifteen["issues"] == []
    assert fifteen["estimates"]["total_credits"] == pytest.approx(five["estimates"]["total_credits"] * 3)
    assert compile_plan(video_plan(1000), run)["issues"]


def test_bridge_capability_requires_the_feature_flag(app_ctx):
    run = make_run(deliverable="video")
    draft = plan([node(), node("end"), node("clip", "animate_shot", {"prompt": "cat",
        "first_frame_artifact_id": {"ref": "image.image"}, "last_frame_artifact_id": {"ref": "end.image"}}, params={"duration": 5})],
        [{"kind": "video", "node_id": "clip", "output": "video"}])
    assert "KEYFRAME_BRIDGE_UNAVAILABLE" in codes(compile_plan(draft, run))
    app_ctx.config["AGENT_ENABLE_KEYFRAME_BRIDGE"] = True
    assert compile_plan(draft, run)["issues"] == []


def test_preview_gate_only_accepts_image_outputs(app_ctx):
    run = make_run(deliverable="video")
    draft = video_plan()
    draft["nodes"][0]["gate"] = "preview"
    assert "INVALID_PREVIEW_GATE" in codes(compile_plan(draft, run))


def test_composition_duration_is_not_double_counted_and_compression_is_explicit(app_ctx):
    run = make_run(deliverable="video")
    clips = [node("c" + str(index), "generate_video", {"mode": "t2v", "prompt": "cat"}, params={"duration": 5}) for index in range(2)]
    draft = plan([*clips, node("master", "compose_video", {"video_artifact_ids": [{"ref": "c0.video"}, {"ref": "c1.video"}]})],
        [{"kind": "video", "node_id": "master", "output": "artifact_id"}])
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert result["estimates"]["video_seconds"] == result["estimates"]["generated_video_seconds"] == 10
    assert dry_run(result)["passed"]
    draft["nodes"][-1]["inputs"]["compress_output"] = True
    assert "COMPRESSION_NOT_REQUESTED" in codes(compile_plan(draft, run))


def test_generated_and_delivered_duration_limits_are_separate(app_ctx):
    app_ctx.config["AGENT_V3_MAX_VIDEO_SECONDS"] = 9
    run = make_run(deliverable="video")
    draft = video_plan(5)
    draft["nodes"].append(node("unused", "generate_video", {"mode": "t2v", "prompt": "cat"}, params={"duration": 5}))
    result = compile_plan(draft, run)
    assert result["estimates"]["video_seconds"] == 5
    assert "PLAN_DURATION_LIMIT" in codes(result)


def test_optional_output_and_deliverable_type_are_checked(app_ctx):
    run = make_run(deliverable="video")
    draft = video_plan()
    draft["deliverables"][0]["kind"] = "image"
    assert "INVALID_DELIVERABLE_TYPE" in codes(compile_plan(draft, run))
    draft = plan([node("clip", "generate_video", {"mode": "t2v", "prompt": "cat"}, params={"duration": 5}),
                  node("master", "compose_video", {"video_artifact_ids": [{"ref": "clip.video"}]})],
                  [{"kind": "video", "node_id": "master", "output": "compressed_artifact_id"}])
    assert "INVALID_DELIVERABLE" in codes(compile_plan(draft, run))


def test_package_requires_qc_for_the_same_video(app_ctx):
    run = make_run(deliverable="video")
    draft = video_plan()
    draft["nodes"] += [node("qc", "qc_video", {"artifact_id": {"ref": "clip.video"}, "video_artifact_ids": [{"ref": "clip.video"}]}),
        node("package", "package_story", {"artifact_id": {"ref": "clip.video"}})]
    draft["deliverables"] = [{"kind": "package", "node_id": "package", "output": "artifact_id"}]
    assert "QC_REQUIRED" in codes(compile_plan(draft, run))
    draft["nodes"][-1]["depends_on"] = ["qc"]
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert result["estimates"]["video_seconds"] == 5
    assert dry_run(result)["passed"]
    draft["deliverables"].append({"kind": "video", "node_id": "clip", "output": "video"})
    assert compile_plan(draft, run)["estimates"]["video_seconds"] == 5


def compressed_package():
    draft = video_plan()
    draft["nodes"] += [node("master", "compose_video", {"video_artifact_ids": [{"ref": "clip.video"}], "compress_output": True}),
        node("qc", "qc_video", {"artifact_id": {"ref": "master.artifact_id"}, "video_artifact_ids": [{"ref": "clip.video"}]}),
        node("package", "package_story", {"artifact_id": {"ref": "master.artifact_id"},
             "compressed_artifact_id": {"ref": "master.compressed_artifact_id"}}, depends_on=["qc"])]
    draft["deliverables"] = [{"kind": "package", "node_id": "package", "output": "artifact_id"}]
    return draft


def test_compressed_package_requires_explicit_request_and_matching_composition(app_ctx):
    result = compile_plan(compressed_package(), make_run(deliverable="video", compress=True))
    assert result["issues"] == [] and dry_run(result)["passed"]
    assert "COMPRESSION_NOT_REQUESTED" in codes(compile_plan(compressed_package(), make_run(deliverable="video")))


@pytest.mark.parametrize("wrong_copy", ["clip.video", "master.artifact_id", "other.compressed_artifact_id"])
def test_package_cannot_label_another_video_as_its_compressed_copy(app_ctx, wrong_copy):
    draft = compressed_package()
    draft["nodes"].insert(2, node("other", "compose_video", {"video_artifact_ids": [{"ref": "clip.video"}], "compress_output": True}))
    draft["nodes"][-1]["inputs"]["compressed_artifact_id"] = {"ref": wrong_copy}
    assert "INVALID_COMPRESSED_COPY" in codes(compile_plan(draft, make_run(deliverable="video", compress=True)))


def test_package_requires_master_output_and_enabled_composition_compression(app_ctx):
    run = make_run(deliverable="video", compress=True)
    draft = compressed_package()
    draft["nodes"][1]["inputs"]["compress_output"] = False
    assert "INVALID_COMPRESSED_COPY" in codes(compile_plan(draft, run))
    draft = compressed_package()
    for item in draft["nodes"][-2:]:
        item["inputs"]["artifact_id"] = {"ref": "master.compressed_artifact_id"}
    assert "INVALID_COMPRESSED_COPY" in codes(compile_plan(draft, run))


def test_only_server_blueprint_receipts_disable_experimental(app_ctx):
    run = make_run()
    draft = plan()
    draft["nodes"][0]["origin"]["blueprint"] = {"name": "image-create", "version": 1}
    result = compile_plan(draft, run)
    assert result["experimental"] is True
    run.snapshot = {"v3_blueprint_receipts": [{"name": "image-create", "version": 1,
        "raw_hash": plan_digest(draft), "normalized_hash": plan_digest(result["plan"])}]}
    db.session.commit()
    assert compile_plan(draft, run)["experimental"] is False
    assert compile_plan(result["plan"], run)["experimental"] is False
    result["plan"]["nodes"][0]["inputs"]["prompt"] = "changed"
    assert compile_plan(result["plan"], run)["experimental"] is True


def test_image_count_is_frozen_once_and_array_deliverable_is_complete(app_ctx):
    result = compile_plan(plan([node(inputs={"prompt": "cat", "n": 2})]), make_run())
    assert result["issues"] == []
    assert "n" not in result["plan"]["nodes"][0]["inputs"]
    assert result["plan"]["nodes"][0]["params"]["n"] == 2
    assert len(dry_run(result)["outputs"]["image"]["images"]) == 2


def test_dry_run_detects_missing_outputs_and_incorrect_order(app_ctx):
    run = make_run()
    result = compile_plan(plan([node(), node("edit", inputs={"mode": "i2i", "prompt": "edit",
        "reference_artifact_ids": [{"ref": "image.image"}]})],
        [{"kind": "image", "node_id": "edit", "output": "image"}]), run)
    assert result["issues"] == []
    broken = deepcopy(result)
    broken["dag"]["order"].reverse()
    assert dry_run(broken)["issues"][0]["code"] == "DRY_RUN_ORDER"
    broken = deepcopy(result)
    broken["output_metadata"]["image"].pop("image")
    assert dry_run(broken)["issues"][0]["code"] == "MISSING_PLAN_OUTPUT"


def test_reference_resolver_does_not_flatten_or_evaluate_strings():
    assert resolve_inputs({"x": {"ref": "n.images"}}, {"n": {"images": ["a", "b"]}}) == {"x": ["a", "b"]}
    assert resolve_inputs("n.image", {}) == "n.image"
    assert node_inputs(node(), plan_version=3)["params"] == {}


def future_transform(*, source_seconds=5, output_seconds=10, operation="extend"):
    return plan([node("clip", "generate_video", {"mode": "t2v", "prompt": "cat"}, model_id="wan3.0-video", params={"duration": source_seconds, "resolution": "480P"}),
        node("transform", "transform_video", {"operation": operation, "prompt": "continue",
            "media": [{"type": "reference_video", "artifact_id": {"ref": "clip.video"}}],
            **({"source_artifact_id": {"ref": "clip.video"}} if operation != "reference" else {})},
            model_id="wan3.0-video", params={"duration": output_seconds, "resolution": "480P"})],
        [{"kind": "video", "node_id": "transform", "output": "video"}])


def test_future_transform_prices_input_plus_output_seconds(app_ctx):
    run = make_run(deliverable="video", preferences=["wan3.0系列"])
    result = compile_plan(future_transform(), run)
    assert result["issues"] == []
    quote = result["estimates"]["nodes"][-1]
    assert quote["input_video_seconds"] == 5
    assert quote["output_video_seconds"] == 10
    assert quote["estimated_cost"] == 15
    assert result["estimates"]["generated_video_seconds"] == 15
    assert result["estimates"]["video_seconds"] == 10
    assert dry_run(result)["passed"]


@pytest.mark.parametrize("changes", [{"source_seconds": 15, "output_seconds": 20},
    {"source_seconds": 10, "output_seconds": 10}, {"source_seconds": 16, "operation": "reference"}])
def test_future_transform_duration_constraints_cannot_be_bypassed(app_ctx, changes):
    run = make_run(deliverable="video", preferences=["wan3.0系列"])
    assert compile_plan(future_transform(**changes), run)["issues"]


def test_retained_range_uses_source_time_not_generation_duration(app_ctx):
    run = make_run(deliverable="video")
    draft = video_plan(15)
    draft["nodes"].append(node("keep", "retain_video_segment", {"video_artifact_id": {"ref": "clip.video"},
        "source_start_sec": 8.0, "source_end_sec": 12.0}))
    draft["deliverables"] = [{"kind": "video", "node_id": "keep", "output": "artifact_id"}]
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert result["estimates"]["video_seconds"] == 4
    assert result["estimates"]["generated_video_seconds"] == 15
    assert result["estimates"]["nodes"][-1]["estimated_cost"] == 0
    draft["nodes"][-1]["inputs"]["source_end_sec"] = 16.0
    assert "INVALID_SOURCE_RANGE" in codes(compile_plan(draft, run))


def test_transform_existing_input_uses_measured_not_claimed_seconds(app_ctx, monkeypatch):
    from app.services.storage_service import StorageService
    from app.services.media_probe_service import MediaProbeService
    from app.services.wan3_media_service import Wan3MediaService
    artifact = Artifact.query.filter_by(artifact_id=image()).one()
    path = StorageService.root() / "source.mp4"
    path.write_bytes(b"local inspection stub")
    artifact.file_path, artifact.file_name = str(path), path.name
    artifact.artifact_type, artifact.mime_type = "source_video", "video/mp4"
    artifact.meta = {"media": {"kind": "video", "duration": .01}}
    db.session.commit()
    monkeypatch.setattr(MediaProbeService, "probe", lambda *_a, **_kw: {"duration_sec": 4.25})
    calls = []
    def inspect(_path, kind):
        calls.append(kind)
        return {"duration_sec": 4.25}
    monkeypatch.setattr(Wan3MediaService, "inspect", inspect)
    run = make_run(deliverable="video", preferences=["wan3.0系列"], ids=[artifact.artifact_id])
    draft = plan([node("transform", "transform_video", {"operation": "extend", "prompt": "continue",
        "media": [{"type": "reference_video", "artifact_id": {"artifact": artifact.artifact_id}}],
        "source_artifact_id": {"artifact": artifact.artifact_id}}, model_id="wan3.0-video", params={"duration": 8, "resolution": "480P"})],
        [{"kind": "video", "node_id": "transform", "output": "video"}])
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert result["estimates"]["nodes"][0]["input_video_seconds"] == 4.25
    assert result["estimates"]["total_credits"] == 12.25
    assert calls == ["video"]


def test_compile_cannot_seed_missing_alias_or_write_any_receipt(app_ctx, monkeypatch):
    run = make_run()
    before = counts()
    monkeypatch.setattr(db.session, "commit", lambda: pytest.fail("Compile cannot commit"))
    monkeypatch.setattr(db.session, "flush", lambda *_a, **_kw: pytest.fail("Compile cannot flush"))
    value = compile_plan(plan([node(model_id="missing-image-alias")]), run)
    assert value["issues"]
    monkeypatch.undo()
    assert counts() == before
