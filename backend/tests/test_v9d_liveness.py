"""Paid nodes must feed deliverables by typed data flow, not mere ordering."""

from copy import deepcopy

import pytest

from app.extensions import db
from app.models import AgentPlanVersion, Job, ToolInvocation
from app.plans.compiler import _unused_paid_nodes, compile_plan
from app.plans.dry_run import dry_run
from app.tools import build_v3_registry
from tests.test_v3_plan_compiler import codes, counts, make_run, node, plan, video_plan


pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)


@pytest.mark.parametrize("tool", ["generate_image", "generate_video", "animate_shot", "transform_video"])
def test_each_paid_vocabulary_member_needs_a_data_path(tool):
    nodes = {"dead": node("dead", tool), "live": node("live", depends_on=["dead"])}
    targets = [{"kind": "image", "node_id": "live", "output": "image"}]
    assert _unused_paid_nodes(nodes, targets) == ["dead"]
    nodes["live"]["inputs"]["reference_artifact_ids"] = [{"ref": "dead.image"}]
    assert _unused_paid_nodes(nodes, targets) == []


def test_orphan_paid_image_blocks_without_deleting_nodes_prices_or_writing(app_ctx, monkeypatch):
    run, registry = make_run(), build_v3_registry()
    draft = plan([node("unused", gate="preview"), node()], [{"kind": "image", "node_id": "image", "output": "images"}])
    untouched, before = deepcopy(draft), counts()
    versions_before = AgentPlanVersion.query.count()
    monkeypatch.setattr(registry, "invoke", lambda *_a, **_k: pytest.fail("Compiler must not dispatch"))
    with monkeypatch.context() as patch:
        patch.setattr(db.session, "commit", lambda: pytest.fail("Compiler must not commit"))
        patch.setattr(db.session, "flush", lambda *_a, **_k: pytest.fail("Compiler must not flush"))
        checked = compile_plan(draft, run, registry=registry)
        assert not dry_run(checked, registry=registry)["passed"]
    unused = [item for item in checked["issues"] if item["code"] == "PLAN_UNUSED_PAID_NODE"]
    assert [item["node_id"] for item in unused] == ["unused"]
    assert draft == untouched and [item["id"] for item in checked["plan"]["nodes"]] == ["unused", "image"]
    assert len(checked["estimates"]["nodes"]) == 2 and all(item["estimated_cost"] > 0 for item in checked["estimates"]["nodes"])
    assert checked["estimates"]["total_credits"] == sum(item["estimated_cost"] for item in checked["estimates"]["nodes"])
    assert counts() == before and AgentPlanVersion.query.count() == versions_before
    assert Job.query.count() == ToolInvocation.query.count() == 0


def test_explicit_additional_deliverable_makes_optional_paid_output_live(app_ctx):
    run = make_run()
    draft = plan([node(), node("reference_sheet", gate="preview")])
    rejected = compile_plan(draft, run)
    draft["deliverables"].append({"kind": "image", "node_id": "reference_sheet", "output": "images"})
    accepted = compile_plan(draft, run)
    assert "PLAN_UNUSED_PAID_NODE" in codes(rejected)
    assert accepted["issues"] == [] and dry_run(accepted)["passed"]
    assert accepted["estimates"]["total_credits"] == rejected["estimates"]["total_credits"]


def test_control_dependency_cannot_hide_an_unused_paid_node(app_ctx):
    run = make_run()
    checked = compile_plan(plan([node("unused"), node(depends_on=["unused"])]), run)
    assert "unused" in checked["dag"]["dependencies"]["image"]
    assert [(issue["code"], issue["node_id"]) for issue in checked["issues"]] == [
        ("PLAN_UNUSED_PAID_NODE", "unused")]


def test_data_chain_through_image_edit_video_and_free_extraction_is_live(app_ctx):
    run = make_run(deliverable="video")
    nodes = [
        node("frame", "extract_frame", {"video_artifact_id": {"ref": "clip.video"}, "position": "last"}),
        node("clip", "animate_shot", {"prompt": "cat moves", "first_frame_artifact_id": {"ref": "edit.image"}},
             params={"duration": 5}),
        node("edit", "generate_image", {"mode": "i2i", "prompt": "cat dressed",
             "reference_artifact_ids": [{"ref": "image.image"}]}),
        node(),
    ]
    checked = compile_plan(plan(nodes, [{"kind": "image", "node_id": "frame", "output": "artifact_id"}]), run)
    assert checked["issues"] == []
    assert checked["dag"]["order"] == ["image", "edit", "clip", "frame"]
    assert dry_run(checked)["passed"]


@pytest.mark.parametrize("array", [False, True])
def test_all_choice_candidates_are_live_before_user_selects_one(app_ctx, array):
    run = make_run()
    if array:
        nodes = [node("candidates", params={"n": 3})]
        references = {"ref": "candidates.images"}
    else:
        nodes = [node(f"c{i}") for i in range(3)]
        references = [{"ref": f"c{i}.image"} for i in range(3)]
    nodes.append(node("pick", "select_image", {"candidate_artifact_ids": references}, gate="choice"))
    checked = compile_plan(plan(nodes, [{"kind": "image", "node_id": "pick", "output": "image"}]), run)
    assert checked["issues"] == []
    assert dry_run(checked)["passed"]
    assert checked["estimates"]["total_credits"] > 0


def test_qc_and_probe_control_nodes_are_exempt_and_do_not_make_side_generation_live(app_ctx):
    run = make_run(deliverable="video")
    draft = video_plan()
    draft["nodes"] += [
        node("probe", "probe_media", {"artifact_id": {"ref": "clip.video"}}),
        node("qc", "qc_video", {"artifact_id": {"ref": "clip.video"}, "video_artifact_ids": [{"ref": "clip.video"}]},
             depends_on=["probe"]),
        node("package", "package_story", {"artifact_id": {"ref": "clip.video"}}, depends_on=["qc"]),
    ]
    draft["deliverables"] = [{"kind": "package", "node_id": "package", "output": "artifact_id"}]
    accepted = compile_plan(draft, run)
    assert accepted["issues"] == [] and dry_run(accepted)["passed"]
    draft["nodes"] += [
        node("unused_clip", "generate_video", {"mode": "t2v", "prompt": "unused"}, params={"duration": 5}),
        node("unused_probe", "probe_media", {"artifact_id": {"ref": "unused_clip.video"}}),
    ]
    draft["nodes"][2]["depends_on"].append("unused_probe")
    rejected = compile_plan(draft, run)
    assert [(item["code"], item["node_id"]) for item in rejected["issues"]] == [
        ("PLAN_UNUSED_PAID_NODE", "unused_clip")]
    assert len(rejected["estimates"]["nodes"]) == 6


def test_invalid_reference_remains_a_compile_error_without_inventing_a_data_edge(app_ctx):
    run = make_run()
    draft = plan([node("unused"), node(inputs={"prompt": "cat", "reference_artifact_ids": [{"ref": "unused.image", "extra": True}]})])
    checked = compile_plan(draft, run)
    assert "INVALID_REFERENCE" in codes(checked) and "PLAN_UNUSED_PAID_NODE" in codes(checked)
    assert not dry_run(checked)["passed"]
