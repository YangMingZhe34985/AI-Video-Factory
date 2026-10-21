"""Explicit user geometry across generic plans, composition and QC; no providers."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest
from pydantic import ValidationError
from werkzeug.datastructures import FileStorage

from app.agent.attachments import upload_attachment
from app.agents.workspace import write_workspace
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentWorkspaceItem, Job, ToolInvocation
from app.plans.aspect import (constrained_nodes, delivery_checks, dimensions, generation_params,
                              delivery_geometry_issues, delivery_inputs, display_ratio, fit_display_canvas, geometry, output_geometry,
                              ratio_for, target_size, valid_target, video_geometry)
from app.plans.compiler import compile_plan
from app.plans.node_tools import ComposeInput, QcInput
from app.services.video_composition_service import VideoCompositionService
from app.tools import build_v3_registry
from app.tools.spec import ToolContext
from tests.test_v3_plan_compiler import codes, make_run, node, plan, video_plan


def aspect_run(*, aspect="16:9", deliverable="video", ids=(), preferences=()):
    run = make_run(deliverable=deliverable, ids=ids, preferences=preferences)
    if aspect:
        payload = deepcopy(AgentWorkspaceItem.query.filter_by(run_id=run.run_id, kind="brief").one().payload)
        payload["aspect_ratio"] = aspect
        delegation = AgentDelegation.query.filter_by(run_id=run.run_id).one()
        write_workspace("brief", "brief", payload, ToolContext(role="producer", caller_agent="producer",
            delegation_id=delegation.id, budget_scope=run.run_id, idempotency_key="aspect-brief"))
    return run


def chain(*, image_params=None, last_frame=False):
    nodes = [node("kf", params=image_params or {})]
    inputs = {"first_frame_artifact_id": {"ref": "kf.image"}, "prompt": "moves"}
    if last_frame:
        nodes.append(node("last"))
        inputs["last_frame_artifact_id"] = {"ref": "last.image"}
    nodes.append(node("clip", "animate_shot", inputs, params={"duration": 5}))
    return plan(nodes, [{"kind": "video", "node_id": "clip", "output": "video"}])


def delivery(nodes):
    videos = [{"ref": item["id"] + ".video"} for item in nodes if item["tool"] in {"animate_shot", "generate_video"}]
    return plan([*nodes,
        node("compose", "compose_video", {"video_artifact_ids": videos}),
        node("qc", "qc_video", {"artifact_id": {"ref": "compose.artifact_id"}, "video_artifact_ids": videos}),
        node("package", "package_story", {"artifact_id": {"ref": "compose.artifact_id"}}, depends_on=["qc"])],
        [{"kind": "video", "node_id": "compose", "output": "artifact_id"},
         {"kind": "package", "node_id": "package", "output": "artifact_id"}])


def test_c7_twelve_shots_omitted_geometry_compiles_to_explicit_landscape(app_ctx):
    run = aspect_run()
    nodes = [node("cast_a", gate="preview", characters=["a"]), node("cast_b", gate="preview", characters=["b"])]
    for index in range(12):
        if index == 9:
            nodes.append(node("shot_10", "generate_video", {"mode": "t2v", "prompt": "empty wide view"},
                              params={"duration": 10}, characters=[]))
            continue
        kf = f"kf_{index + 1:02}"
        nodes += [node(kf, inputs={"mode": "i2i", "prompt": "two characters",
            "reference_artifact_ids": [{"ref": "cast_a.image"}, {"ref": "cast_b.image"}]},
            model_id="qwen-image-3.0", characters=["a", "b"]),
            node(f"shot_{index + 1:02}", "animate_shot", {"prompt": "two characters perform the given plot",
                "first_frame_artifact_id": {"ref": kf + ".image"}}, params={"duration": 10}, characters=["a", "b"])]
    draft = delivery(nodes)
    draft["character_references"] = {"a": [{"ref": "cast_a.image"}], "b": [{"ref": "cast_b.image"}]}
    before = Job.query.count(), ToolInvocation.query.count()
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert (Job.query.count(), ToolInvocation.query.count()) == before
    by_id = {item["id"]: item for item in result["plan"]["nodes"]}
    assert by_id["cast_a"]["params"]["size"] == "1280*1280"
    assert all(geometry(by_id[f"kf_{i + 1:02}"]["params"]["size"])["aspect_ratio"] == "16:9" for i in range(12) if i != 9)
    assert by_id["shot_10"]["params"]["ratio"] == "16:9"
    assert "ratio" not in by_id["shot_01"]["params"]
    assert result["estimates"]["video_seconds"] == 120
    assert by_id["compose"]["inputs"]["target_size"] == "1280*720"
    assert by_id["qc"]["inputs"]["target_size"] == "1280*720"
    assert compile_plan(result["plan"], run)["issues"] == []


@pytest.mark.parametrize("aspect,size", [("16:9", "1280*720"), ("9:16", "720*1280"), ("1:1", "1024*1024")])
def test_supported_frame_defaults_and_i2v_inheritance(app_ctx, aspect, size):
    result = compile_plan(chain(), aspect_run(aspect=aspect))
    assert result["issues"] == []
    assert result["plan"]["nodes"][0]["params"]["size"] == size
    assert result["output_metadata"]["clip"]["video"]["aspect_ratio"] == aspect
    assert "ratio" not in result["validated_inputs"]["clip"]["params"]


def test_no_explicit_brief_retains_legacy_defaults(app_ctx):
    result = compile_plan(delivery(chain()["nodes"]), aspect_run(aspect=None))
    assert result["issues"] == []
    assert result["plan"]["nodes"][0]["params"]["size"] == "1280*1280"
    assert "target_size" not in result["plan"]["nodes"][-3]["inputs"]
    assert compile_plan(video_plan(), aspect_run(aspect=None))["plan"]["nodes"][0]["params"]["ratio"] == "9:16"


@pytest.mark.parametrize("params", [{"size": "1024*1024"}, {"size": "720*1280"}])
def test_explicit_frame_conflict_is_blocking_and_actionable(app_ctx, params):
    result = compile_plan(chain(image_params=params), aspect_run())
    issue = next(item for item in result["issues"] if item["code"] == "PLAN_ASPECT_RATIO_MISMATCH")
    assert issue["node_id"] == "kf"
    assert all(text in issue["message"] for text in ("params.size", params["size"], "16:9"))


def test_explicit_video_ratio_conflict_not_silently_replaced(app_ctx):
    draft = video_plan()
    draft["nodes"][0]["params"]["ratio"] = "9:16"
    assert "PLAN_ASPECT_RATIO_MISMATCH" in codes(compile_plan(draft, aspect_run()))
    assert draft["nodes"][0]["params"]["ratio"] == "9:16"


def test_unsupported_image_ratio_is_refused(app_ctx):
    result = compile_plan(chain(), aspect_run(aspect="4:3"))
    assert "PLAN_ASPECT_RATIO_UNSUPPORTED" in codes(result)


def test_dynamic_image_size_uses_registered_legal_preset(app_ctx):
    draft = chain()
    draft["nodes"][0]["model_id"] = "qwen-image-3.0"
    app_ctx.config["DEFAULT_IMAGE_MODEL"] = "qwen-image-3.0"
    result = compile_plan(draft, aspect_run(aspect="4:3"))
    assert result["issues"] == []
    assert result["plan"]["nodes"][0]["params"]["size"] == "1024*768"


def test_dynamic_size_without_presets_obeys_area_bound():
    model = SimpleNamespace(model_id="dynamic", default_params={"size": "1024*1024"}, parameter_schema={"size": {"format": "image_size",
        "min_pixels": 512**2, "max_pixels": 2048**2, "min_aspect_ratio": 1/8, "max_aspect_ratio": 8}})
    result = generation_params({"id": "frame", "tool": "generate_image"}, model, {}, "16:9", "t2i", {})
    width, height = dimensions(result["size"])
    assert 512**2 <= width*height <= 2048**2 and ratio_for(width, height) == "16:9"
    assert abs(width*height - 1024**2) / 1024**2 < .1


@pytest.mark.parametrize("value", ["SECRET" * 10000, {"secret": "do not echo"}, ["private"], None],
                         ids=["long-string", "object", "array", "null"])
def test_conflict_message_does_not_reflect_unvalidated_parameter_content(value):
    model = SimpleNamespace(model_id="wan", parameter_schema={"size": {}})
    with pytest.raises(AppError) as error:
        generation_params({"id": "kf", "tool": "generate_image"}, model, {"size": value}, "16:9", "t2i", {})
    assert "SECRET" not in error.value.message and "private" not in error.value.message and "do not echo" not in error.value.message
    assert len(error.value.message) < 160


def test_choice_requires_every_candidate_to_have_requested_frame_ratio(app_ctx):
    draft = plan([node("one"), node("two"), node("choice", "select_image",
        {"candidate_artifact_ids": [{"ref": "one.image"}, {"ref": "two.image"}]}, gate="choice"),
        node("clip", "animate_shot", {"prompt": "moves", "first_frame_artifact_id": {"ref": "choice.image"}})],
        [{"kind": "video", "node_id": "clip", "output": "video"}])
    run = aspect_run()
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert result["output_metadata"]["choice"]["image"]["aspect_ratio"] == "16:9"
    draft["nodes"][1]["params"] = {"size": "1024*1024"}
    assert "PLAN_ASPECT_RATIO_MISMATCH" in codes(compile_plan(draft, run))


def test_multi_image_array_choice_inherits_all_candidate_shapes(app_ctx):
    draft = plan([node("variants", params={"n": 3}), node("choice", "select_image",
        {"candidate_artifact_ids": {"ref": "variants.images"}}, gate="choice"),
        node("clip", "animate_shot", {"prompt": "moves", "first_frame_artifact_id": {"ref": "choice.image"}})],
        [{"kind": "video", "node_id": "clip", "output": "video"}])
    result = compile_plan(draft, aspect_run())
    assert result["issues"] == []
    assert all(item["aspect_ratio"] == "16:9" for item in result["output_metadata"]["variants"]["images"]["items"])


def test_reference_use_is_exempt_but_cast_used_as_first_frame_is_not():
    draft = chain()
    draft["nodes"].insert(0, node("cast", params={"size": "1024*1024"}, gate="preview", characters=["cat"]))
    draft["nodes"][1]["inputs"]["reference_artifact_ids"] = [{"ref": "cast.image"}]
    draft["nodes"][1]["inputs"]["mode"] = "i2i"
    assert constrained_nodes(draft) == {"kf", "clip"}
    draft["nodes"][2]["inputs"]["first_frame_artifact_id"] = {"ref": "cast.image"}
    assert constrained_nodes(draft) == {"cast", "clip"}


def test_cast_auxiliary_image_deliverable_remains_exempt_unless_also_first_frame(app_ctx):
    run = aspect_run()
    draft = chain()
    cast = node("cast", gate="preview", characters=["cat"], params={"size": "1024*1024"})
    draft["nodes"].insert(0, cast)
    draft["nodes"][1]["inputs"].update(mode="i2i", reference_artifact_ids=[{"ref": "cast.image"}])
    draft["nodes"][1]["characters"] = ["cat"]
    draft["nodes"][2]["characters"] = ["cat"]
    draft["character_references"] = {"cat": [{"ref": "cast.image"}]}
    draft["deliverables"].append({"kind": "image", "node_id": "cast", "output": "image"})
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert result["plan"]["nodes"][0]["params"]["size"] == "1024*1024"
    draft["nodes"][2]["inputs"]["first_frame_artifact_id"] = {"ref": "cast.image"}
    assert "PLAN_ASPECT_RATIO_MISMATCH" in codes(compile_plan(draft, run))


def test_direct_image_brief_does_not_exempt_a_cast_deliverable():
    draft = plan([node("cast", gate="preview", characters=["cat"])],
                 [{"kind": "image", "node_id": "cast", "output": "image"}])
    draft["character_references"] = {"cat": [{"ref": "cast.image"}]}
    assert constrained_nodes(draft, deliverable="video") == set()
    assert constrained_nodes(draft, deliverable="image") == {"cast"}


def upload(size):
    stream = BytesIO()
    Image.new("RGB", size, "blue").save(stream, "PNG")
    stream.seek(0)
    return upload_attachment(FileStorage(stream=stream, filename="frame.png", content_type="image/png"), "owner")["attachment_id"]


@pytest.mark.parametrize("size,valid", [((640, 360), True), ((360, 640), False)])
def test_uploaded_first_frame_is_measured_not_trusted_from_prompt(app_ctx, size, valid):
    artifact_id = upload(size)
    draft = plan([node("clip", "animate_shot", {"prompt": "16:9", "first_frame_artifact_id": {"artifact": artifact_id}})],
                 [{"kind": "video", "node_id": "clip", "output": "video"}])
    result = compile_plan(draft, aspect_run(ids=[artifact_id]))
    assert (not result["issues"]) is valid
    if not valid:
        assert "PLAN_ASPECT_RATIO_MISMATCH" in codes(result)


def test_last_frame_is_checked_independently():
    node_data = {"id": "clip", "tool": "animate_shot"}
    model = SimpleNamespace(model_id="wan", parameter_schema={"resolution": {}})
    with pytest.raises(AppError, match="last_frame_artifact_id"):
        generation_params(node_data, model, {}, "16:9", "i2v", {
            "first_frame_artifact_id": {"aspect_ratio": "16:9"}, "last_frame_artifact_id": {"aspect_ratio": "1:1"}})


@pytest.mark.parametrize("field,value", [("target_aspect_ratio", "9:16"), ("target_size", "720*1280")])
def test_explicit_compose_target_conflict_is_blocked(app_ctx, field, value):
    draft = delivery(video_plan()["nodes"])
    draft["nodes"][1]["inputs"][field] = value
    assert "PLAN_ASPECT_RATIO_MISMATCH" in codes(compile_plan(draft, aspect_run()))


def test_qc_size_cannot_disagree_with_approved_compose_canvas(app_ctx):
    draft = delivery(video_plan()["nodes"])
    draft["nodes"][1]["inputs"].update(target_aspect_ratio="16:9", target_size="1920*1080")
    draft["nodes"][2]["inputs"].update(target_aspect_ratio="16:9", target_size="1280*720")
    assert "PLAN_ASPECT_RATIO_MISMATCH" in codes(compile_plan(draft, aspect_run()))


def test_empty_compose_sources_return_schema_issue_without_crashing(app_ctx):
    draft = plan([node("compose", "compose_video", {"video_artifact_ids": []})],
                 [{"kind": "video", "node_id": "compose", "output": "artifact_id"}])
    assert "INVALID_NODE_INPUT" in codes(compile_plan(draft, aspect_run()))


@pytest.mark.parametrize("size", ["1280*721", "1*1", "10000*10000", "1024*1024", "1280x720"])
def test_private_delivery_schema_rejects_invalid_canvas(size):
    with pytest.raises(ValidationError):
        ComposeInput(plan_version=1, video_artifact_ids=["clip"], target_aspect_ratio="16:9", target_size=size)


def test_legacy_registry_schema_does_not_gain_v3_fields():
    from app.tools.specs.compose_video import ComposeVideoInput
    assert "target_size" not in ComposeVideoInput.model_fields
    assert "target_size" in ComposeInput.model_fields and "target_size" in QcInput.model_fields
    assert ComposeInput(plan_version=1, video_artifact_ids=["clip"]).model_dump(mode="json") == {
        "plan_version": 1, "video_artifact_ids": ["clip"], "compress_output": False}
    assert QcInput(plan_version=1, artifact_id="master", video_artifact_ids=["clip"]).model_dump(mode="json") == {
        "plan_version": 1, "artifact_id": "master", "video_artifact_ids": ["clip"]}


def test_historical_approved_plan_resumes_without_recompile_or_hash_rewrite(monkeypatch):
    from app.agent import plan_versions
    from app.plans import compiler, runtime
    historical = plan([node("image", params={"size": "1024*1024"})])
    digest = plan_versions.inputs_hash(historical)
    version = SimpleNamespace(version=1, plan=historical)
    run = SimpleNamespace(status="executing", snapshot={"v3_execution": {
        "approved_version": 1, "approval_hash": digest}})
    monkeypatch.setattr(plan_versions, "require_current_version", lambda *_a: version)
    monkeypatch.setattr(compiler, "compile_plan", lambda *_a, **_kw: pytest.fail("Historical approval must stay frozen"))
    assert runtime.begin(run, version, registry=object()) == "executing"
    assert plan_versions.inputs_hash(version.plan) == digest
    assert run.snapshot["v3_execution"]["approval_hash"] == digest


def test_historical_approval_still_rejects_a_mutated_plan(monkeypatch):
    from app.agent import plan_versions
    from app.plans import runtime
    historical = plan()
    run = SimpleNamespace(status="executing", snapshot={"v3_execution": {
        "approved_version": 1, "approval_hash": plan_versions.inputs_hash(historical)}})
    historical["nodes"][0]["params"] = {"size": "1280*720"}
    version = SimpleNamespace(version=1, plan=historical)
    monkeypatch.setattr(plan_versions, "require_current_version", lambda *_a: version)
    with pytest.raises(AppError) as error:
        runtime.begin(run, version, registry=object())
    assert error.value.code == "PLAN_APPROVAL_MISMATCH"


def test_direct_image_delivery_obeys_explicit_ratio(app_ctx):
    result = compile_plan(plan(), aspect_run(deliverable="image", aspect="9:16"))
    assert result["issues"] == []
    assert result["plan"]["nodes"][0]["params"]["size"] == "720*1280"


def test_patch_recompile_preserves_hard_ratio_and_original_plan(app_ctx):
    from app.plans.patches import apply_patch_draft
    run = aspect_run()
    base = compile_plan(chain(), run)["plan"]
    replacement = deepcopy(base["nodes"][0])
    replacement["params"]["size"] = "1024*1024"
    patch = {"base_version": 1, "reason": "change only frame", "ops": [
        {"op": "replace_node", "node_id": "kf", "node": replacement}]}
    changed = apply_patch_draft(base, patch, trusted_author="director")
    assert "PLAN_ASPECT_RATIO_MISMATCH" in codes(compile_plan(changed, run, plan_version=2))
    assert base["nodes"][0]["params"]["size"] == "1280*720"


def test_unknown_first_frame_geometry_is_not_inferred_from_prompt():
    model = SimpleNamespace(model_id="wan", parameter_schema={})
    with pytest.raises(AppError) as error:
        generation_params({"id": "clip", "tool": "animate_shot"}, model, {}, "16:9", "i2v",
                          {"first_frame_artifact_id": {"type": "image"}})
    assert error.value.code == "PLAN_ASPECT_RATIO_UNKNOWN"


@pytest.mark.parametrize("actual,code", [("9:16", "PLAN_ASPECT_RATIO_MISMATCH"), (None, "PLAN_ASPECT_RATIO_UNKNOWN")])
def test_direct_retained_video_requires_output_ratio_proof(actual, code):
    draft = plan([node("retained", "retain_video_segment", {"video_artifact_id": {"artifact": "source"},
        "source_start_sec": 0.0, "source_end_sec": 5.0})],
        [{"kind": "video", "node_id": "retained", "output": "artifact_id"}])
    output = {"retained": {"artifact_id": {"type": "video", "aspect_ratio": actual}}}
    assert delivery_geometry_issues(draft, output, "16:9", deliverable="video")[0]["code"] == code
    assert delivery_geometry_issues(draft, output, None, deliverable="video") == []


def test_direct_image_choice_mixed_uploaded_ratios_is_blocked(app_ctx):
    first, second = upload((640, 360)), upload((360, 640))
    draft = plan([node("choice", "select_image", {"candidate_artifact_ids": [
        {"artifact": first}, {"artifact": second}]}, gate="choice")],
        [{"kind": "image", "node_id": "choice", "output": "image"}])
    result = compile_plan(draft, aspect_run(ids=[first, second], deliverable="image"))
    assert "PLAN_ASPECT_RATIO_UNKNOWN" in codes(result)


@pytest.mark.parametrize("source", [{"ref": "retained.artifact_id"}, {"artifact": "source"}])
def test_package_only_delivery_checks_its_actual_master(source):
    draft = plan([node("package", "package_story", {"artifact_id": source})],
        [{"kind": "package", "node_id": "package", "output": "artifact_id"}])
    video = {"type": "video", "aspect_ratio": "9:16"}
    output = {"retained": {"artifact_id": video}, "package": {"artifact_id": {"type": "package"}}}
    result = delivery_geometry_issues(draft, output, "16:9", known_artifacts={"source": video})
    assert result[0]["code"] == "PLAN_ASPECT_RATIO_MISMATCH"
    assert result[0]["node_id"] == "package"


@pytest.mark.parametrize("compose,size,sar,code", [
    (False, (360, 640), "1:1", "PLAN_ASPECT_RATIO_MISMATCH"),
    (True, (360, 640), "1:1", None),
    (False, (1280, 720), "2:1", "PLAN_ASPECT_RATIO_MISMATCH"),
    (False, (1280, 720), None, "PLAN_ASPECT_RATIO_UNKNOWN"),
    (True, (1280, 720), "2:1", None)])
def test_retained_source_delivery_needs_explicit_canvas_adaptation(app_ctx, monkeypatch, compose, size, sar, code):
    from app.models import Artifact
    from app.services.storage_service import StorageService
    from app.services.media_probe_service import MediaProbeService
    source_id = upload((360, 640))
    artifact = Artifact.query.filter_by(artifact_id=source_id).one()
    source = StorageService.root() / "source.mp4"
    source.write_bytes(b"local video inspection stub")
    artifact.file_path, artifact.file_name = str(source), source.name
    artifact.artifact_type, artifact.mime_type = "source_video", "video/mp4"
    artifact.meta = {"media": {"kind": "video"}}
    db.session.commit()
    monkeypatch.setattr(MediaProbeService, "probe", lambda *_a, **_kw: {
        "duration_sec": 5, "width": size[0], "height": size[1], "video": {"sar": sar}})
    nodes = [node("keep", "retain_video_segment", {"video_artifact_id": {"artifact": source_id},
        "source_start_sec": 0.0, "source_end_sec": 5.0})]
    if compose:
        nodes.append(node("compose", "compose_video", {"video_artifact_ids": [{"ref": "keep.artifact_id"}]}))
    draft = plan(nodes, [{"kind": "video", "node_id": nodes[-1]["id"], "output": "artifact_id"}])
    result = compile_plan(draft, aspect_run(ids=[source_id]))
    if compose:
        assert result["issues"] == []
        assert result["plan"]["nodes"][-1]["inputs"]["target_size"] == "1280*720"
        assert result["output_metadata"]["keep"]["artifact_id"]["aspect_ratio"] == display_ratio(*size, sar)
    else:
        assert code in codes(result)


def test_reference_only_compose_and_qc_keep_their_own_target(app_ctx):
    nodes = [node("reference", "generate_video", {"mode": "t2v", "prompt": "portrait visual reference"},
                  params={"duration": 5, "ratio": "9:16"}),
        node("reference_compose", "compose_video", {"video_artifact_ids": [{"ref": "reference.video"}],
            "target_aspect_ratio": "9:16", "target_size": "720*1280"}),
        node("reference_qc", "qc_video", {"artifact_id": {"ref": "reference_compose.artifact_id"},
            "video_artifact_ids": [{"ref": "reference.video"}],
            "target_aspect_ratio": "9:16", "target_size": "720*1280"}),
        node("final", "transform_video", {"operation": "reference", "prompt": "landscape output",
            "media": [{"type": "reference_video", "artifact_id": {"ref": "reference_compose.artifact_id"}}]},
            model_id="wan3.0-video", params={"duration": 5, "resolution": "720P"}, depends_on=["reference_qc"])]
    draft = plan(nodes, [{"kind": "video", "node_id": "final", "output": "video"}])
    assert constrained_nodes(draft) == {"final"}
    result = compile_plan(draft, aspect_run(preferences=["wan3.0系列"]))
    assert result["issues"] == []
    assert result["plan"]["nodes"][1]["inputs"]["target_aspect_ratio"] == "9:16"
    assert result["plan"]["nodes"][2]["inputs"]["target_aspect_ratio"] == "9:16"
    assert result["plan"]["nodes"][-1]["params"]["ratio"] == "16:9"


@pytest.mark.parametrize("sar,proven", [("1:1", True), ("2:1", False), (None, False)])
def test_extracted_frame_does_not_reuse_anamorphic_display_proof(sar, proven):
    source = {"type": "video", **video_geometry({"width": 1280, "height": 720, "video": {"sar": sar}})}
    output = {"artifact_id": {"type": "image"}}
    output_geometry({"tool": "extract_frame", "params": {}}, {}, {"video_artifact_id": source}, output)
    assert (output["artifact_id"].get("aspect_ratio") == "16:9") is proven
    assert "sample_aspect_ratio" not in output["artifact_id"]
    assert output["artifact_id"].get("geometry_unverified", False) is (not proven)


@pytest.mark.parametrize("tool", ["compose_video", "qc_video"])
def test_delivery_compile_blocks_known_unverified_source_but_allows_generated_intent(tool):
    source = {"type": "video", **video_geometry({"width": 1280, "height": 720, "video": {"sar": None}})}
    retained = {"artifact_id": {"type": "video"}}
    output_geometry({"tool": "retain_video_segment", "params": {}}, {}, {"video_artifact_id": source}, retained)
    assert retained["artifact_id"]["geometry_unverified"] is True
    def metadata(value):
        return {"artifact_id": value} if tool == "qc_video" else {"video_artifact_ids": [value]}
    data = {"id": "delivery", "tool": tool, "inputs": {}}
    with pytest.raises(AppError) as error:
        delivery_inputs(data, metadata(retained["artifact_id"]), "16:9")
    assert error.value.code == "PLAN_ASPECT_RATIO_UNKNOWN"
    intended = {"type": "video", "width": 1280, "height": 720, "aspect_ratio": "16:9", "sample_aspect_ratio": "1:1"}
    delivery_inputs(data, metadata(intended), "16:9")
    assert data["inputs"]["target_size"] == "1280*720"


@pytest.mark.parametrize("explicit,expected", [(None, "1280*720"), ("1920*1080", "1920*1080")])
def test_anamorphic_pixel_canvas_is_not_inherited_as_square_pixel_target(explicit, expected):
    source = {"type": "video", **video_geometry({"width": 720, "height": 576, "video": {"sar": "64:45"}})}
    assert source["aspect_ratio"] == "16:9"
    compose = {"id": "compose", "tool": "compose_video", "inputs": {}, "params": {}}
    if explicit:
        compose["inputs"].update(target_aspect_ratio="16:9", target_size=explicit)
    delivery_inputs(compose, {"video_artifact_ids": [source]}, "16:9")
    validated = ComposeInput.model_validate({"plan_version": 1, "video_artifact_ids": ["source"], **compose["inputs"]})
    assert validated.target_size == expected
    outputs = {"artifact_id": {"type": "video"}}
    output_geometry(compose, validated.model_dump(mode="json"), {"video_artifact_ids": [source]}, outputs)
    qc = {"id": "qc", "tool": "qc_video", "inputs": {}}
    delivery_inputs(qc, {"artifact_id": outputs["artifact_id"], "video_artifact_ids": [source]}, "16:9")
    checked = QcInput.model_validate({"plan_version": 1, "artifact_id": "master", "video_artifact_ids": ["source"], **qc["inputs"]})
    assert checked.target_size == expected and checked.target_aspect_ratio == "16:9"
    assert (source["width"], source["height"]) == (720, 576)


@pytest.mark.parametrize("sar", [None, "0:1", "invalid"])
def test_explicit_canvas_refuses_unknown_sample_aspect(sar):
    with pytest.raises(AppError) as error:
        fit_display_canvas({"width": 320, "height": 180, "video": {"sar": sar}}, 320, 180)
    assert error.value.code == "INVALID_SOURCE"


def test_existing_reference_video_shape_does_not_become_an_output_constraint():
    draft = plan([node("ref_video", "generate_video", {"mode": "t2v", "prompt": "portrait source"}),
        node("final", "transform_video", {"operation": "reference", "prompt": "wide result", "media": [
            {"type": "reference_video", "artifact_id": {"ref": "ref_video.video"}}]})],
        [{"kind": "video", "node_id": "final", "output": "video"}])
    assert constrained_nodes(draft) == {"final"}


@pytest.mark.parametrize("aspect", ["16:9", "9:16", "1:1", "4:3", "3:4"])
def test_derived_canvas_exact_ratio_and_even_pixels(aspect):
    assert valid_target(aspect, target_size(aspect, 480))


def test_qc_checks_both_pixel_canvas_and_display_sar():
    valid = {"width": 1280, "height": 720, "video": {"sar": "1:1"}}
    assert all(item["passed"] for item in delivery_checks(valid, "16:9", "1280*720"))
    assert not delivery_checks({**valid, "width": 720, "height": 1280}, "16:9", "1280*720")[0]["passed"]
    assert not delivery_checks({**valid, "video": {"sar": "2:1"}}, "16:9", "1280*720")[1]["passed"]
    assert not delivery_checks({**valid, "video": {"sar": None}}, "16:9", "1280*720")[1]["passed"]
    assert delivery_checks(valid, None, None) == []


def test_composition_uses_explicit_canvas_and_preserves_sources(app_ctx, tmp_path):
    from app.services.storage_service import StorageService
    from app.services.media_probe_service import MOCK_VIDEO_BYTES, MediaProbeService
    source = StorageService.root() / "source.mp4"
    source.write_bytes(MOCK_VIDEO_BYTES)
    target = StorageService.root() / "final.mp4"
    result = VideoCompositionService.compose([source], target, durations=[.2], shot_ids=["clip"],
        target_aspect_ratio="9:16", target_size="180*320")
    assert (result["width"], result["height"]) == (180, 320)
    assert result["mode"] == "normalized" and result["compressed_path"] is None
    assert source.read_bytes() == MOCK_VIDEO_BYTES
    assert all(item["passed"] for item in delivery_checks(MediaProbeService.probe(target), "9:16", "180*320"))


def test_composition_preserves_anamorphic_display_shape_with_letterboxing(app_ctx):
    from app.services.storage_service import StorageService
    from app.services.media_probe_service import MediaProbeService
    from app.services.video_media_service import VideoMediaService
    root = StorageService.root()
    image, source, target, frame = (root / name for name in ("blue.png", "wide-sar.mp4", "canvas.mp4", "master.png"))
    Image.new("RGB", (320, 180), (0, 0, 255)).save(image)
    VideoMediaService._run(["-loop", "1", "-i", str(image), "-t", "0.2", "-r", "25", "-vf", "setsar=2/1",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], 30)
    original = source.read_bytes()
    measured = MediaProbeService.probe(source)
    assert video_geometry(measured)["aspect_ratio"] == "32:9"
    result = VideoCompositionService.compose([source], target, durations=[.2], shot_ids=["wide"],
        target_aspect_ratio="16:9", target_size="320*180")
    assert result["mode"] == "normalized" and result["compressed_path"] is None
    assert source.read_bytes() == original
    assert all(item["passed"] for item in delivery_checks(MediaProbeService.probe(target), "16:9", "320*180"))
    VideoMediaService.extract_frame(target, frame, position="first")
    with Image.open(frame).convert("RGB") as pixels:
        assert max(pixels.getpixel((160, 10))) < 20
        assert pixels.getpixel((160, 90))[2] > 200
        assert max(pixels.getpixel((160, 170))) < 20


@pytest.mark.parametrize("suffix,unverified", [("", False),
    ("\nStream mapping:\n  displaymatrix: rotation of 90.00 degrees", False),
    ("\n  Side data:\n    displaymatrix: rotation of 90.00 degrees", True),
    ("\n  Metadata:\n    rotate          : 90", True)])
def test_probe_marks_only_input_display_transform_evidence(suffix, unverified):
    from app.services.media_probe_service import MediaProbeService
    header = "Duration: 00:00:01.00\nStream #0:0: Video: h264 (High), yuv420p, 1280x720 [SAR 1:1 DAR 16:9], 25 fps, 12800 tbn"
    value = MediaProbeService._metadata(header + suffix)
    assert value.get("display_transform_unverified", False) is unverified
    if not unverified:
        assert "display_transform_unverified" not in value
    assert (video_geometry(value)["aspect_ratio"] == "16:9") is (not unverified)
    assert delivery_checks(value, "16:9", "1280*720")[1]["passed"] is (not unverified)


def test_rotated_local_source_cannot_stream_copy_around_explicit_canvas_guard(app_ctx, monkeypatch):
    from app.services.storage_service import StorageService
    from app.services.media_probe_service import MediaProbeService
    from app.services.video_media_service import VideoMediaService
    root = StorageService.root()
    source, rotated, target = (root / name for name in ("original.mp4", "rotated.mp4", "target.mp4"))
    VideoCompositionService._materialize_mock(source, .2, "rotate", 0, size=(320, 180))
    VideoMediaService._run(["-display_rotation:v:0", "90", "-noautorotate", *VideoMediaService._input(source),
        "-map", "0:v:0", "-c", "copy", str(rotated)], 30)
    original = rotated.read_bytes()
    measured = MediaProbeService.probe(rotated)
    assert (measured["width"], measured["height"]) == (320, 180)
    assert measured["display_transform_unverified"] is True
    assert video_geometry(measured)["aspect_ratio"] is None
    assert not delivery_checks(measured, "16:9", "320*180")[1]["passed"]
    monkeypatch.setattr(VideoCompositionService, "_compatible", lambda _media: pytest.fail("Reject before stream-copy selection"))
    monkeypatch.setattr(VideoCompositionService, "_normalize", lambda *_a, **_kw: pytest.fail("Do not rotate implicitly"))
    with pytest.raises(AppError) as error:
        VideoCompositionService.compose([rotated], target, durations=[.2], shot_ids=["rotated"],
            target_aspect_ratio="16:9", target_size="320*180")
    assert error.value.code == "INVALID_SOURCE"
    assert rotated.read_bytes() == original and not target.exists()


def test_tool_resource_schemas_equal_private_runtime_models():
    root = Path(__file__).resolve().parents[1] / "skills/plan-review/resources/tools"
    registry = build_v3_registry()
    for name in ("compose_video", "qc_video"):
        document = json.loads((root / (name + ".json")).read_text(encoding="utf-8"))
        assert document["resolved_input_schema"] == registry.get(name).input_model.model_json_schema()
