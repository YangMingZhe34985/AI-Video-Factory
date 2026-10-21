"""Fast offline scope tests: no app bootstrap, database or model calls."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "v3_eval"))
from story_scope import ScopeViolation, audit_story_patch_scope


def node(key, tool, inputs, **kw):
    return {"id": key, "tool": tool, "inputs": inputs, "model_id": "image-v1" if tool == "generate_image" else "video-v1" if tool == "animate_shot" else None,
            "params": {"duration": 10} if tool == "animate_shot" else {}, "stage": None, "gate": None,
            "depends_on": [], "origin": {"agent": "director", "skills": [], "blueprint": None}, "rationale": "Original", **kw}


def base():
    nodes = [node("hero", "generate_image", {"prompt": "same hero"})]
    for i in range(1, 4):
        nodes += [node(f"frame_{i}", "generate_image", {"prompt": "day", "mode": "i2i", "reference_artifact_ids": [{"ref": "hero.image"}]}),
                  node(f"clip_{i}", "animate_shot", {"prompt": "walk", "first_frame_artifact_id": {"ref": f"frame_{i}.image"}})]
    nodes += [node("master", "compose_video", {"video_artifact_ids": [{"ref": f"clip_{i}.video"} for i in range(1, 4)]}),
              node("qc", "qc_video", {"artifact_id": {"ref": "master.artifact_id"}}),
              node("package", "package_story", {"artifact_id": {"ref": "master.artifact_id"}}, depends_on=["qc"])]
    return {"plan_version": 1, "nodes": nodes, "deliverables": [{"kind": "package", "node_id": "package", "output": "artifact_id"}]}


def fixtures(targets=("clip_3",)):
    plan = base()
    record = {"patch_id": "p", "draft": {"base_version": 1, "ops": [
        {"op": "update_inputs", "node_id": key, "inputs": {"prompt": "rainy night"}} for key in targets]}}
    affected = set(targets) | {"clip_3", "master", "qc", "package"}
    ids = {n["id"] for n in plan["nodes"]}
    quote = {"patch_id": "p", "base_version": 1, "scope": "cascade", "affected_node_ids": sorted(affected),
             "execute_node_ids": sorted(affected), "reused_node_ids": sorted(ids - affected), "kept_node_ids": [], "removed_node_ids": []}
    return plan, record, quote


@pytest.mark.parametrize("targets", [("clip_3",), ("frame_3",), ("frame_3", "clip_3")])
def test_prompt_revision_accepts_only_target_and_dedicated_frame(targets):
    plan, record, quote = fixtures(targets)
    frozen = deepcopy((plan, record, quote))
    result = audit_story_patch_scope(plan, record, quote, "clip_3")
    assert result["generation_node_ids"] == sorted(set(targets) | {"clip_3"})
    assert (plan, record, quote) == frozen


def replacement():
    plan, record, quote = fixtures()
    changed = deepcopy(next(n for n in plan["nodes"] if n["id"] == "clip_3"))
    changed["inputs"]["prompt"] = "rainy night"
    record["draft"]["ops"] = [{"op": "replace_node", "node_id": "clip_3", "node": changed}]
    return plan, record, quote, changed


def test_replace_node_is_compared_by_execution_diff_not_operation_name():
    plan, record, quote, changed = replacement()
    changed["origin"]["agent"] = "repair"
    changed["rationale"] = "Requested weather change"
    result = audit_story_patch_scope(plan, record, quote, "clip_3")
    assert result["metadata_changes"] == {"clip_3": ["origin", "rationale"]}


@pytest.mark.parametrize("field,value", [("model_id", "other-model"), ("params", {"duration": 11}), ("params", {"duration": 10, "resolution": "1080P"}),
    ("depends_on", ["frame_1"]), ("gate", "preview"), ("stage", "other"), ("tool", "generate_video"), ("id", "clip_1")])
def test_replace_cannot_change_execution_fields(field, value):
    plan, record, quote, changed = replacement()
    changed[field] = value
    with pytest.raises(ScopeViolation, match="execution field"):
        audit_story_patch_scope(plan, record, quote, "clip_3")


@pytest.mark.parametrize("field,value", [("first_frame_artifact_id", {"ref": "frame_1.image"}), ("reference_artifact_ids", [{"ref": "hero.image"}]),
                                       ("source_url", "https://example.invalid/new-reference"), ("mode", "r2v"), ("negative_prompt", "no hero")])
def test_replace_cannot_change_refs_or_other_inputs_including_redacted_urls(field, value):
    plan, record, quote, changed = replacement()
    changed["inputs"][field] = value
    with pytest.raises(ScopeViolation, match="execution field"):
        audit_story_patch_scope(plan, record, quote, "clip_3")


@pytest.mark.parametrize("target", ["clip_1", "frame_2", "hero", "master"])
def test_target_plus_unrelated_operation_is_rejected_even_if_quote_expands(target):
    plan, record, quote = fixtures()
    record["draft"]["ops"].append({"op": "update_inputs", "node_id": target, "inputs": {"prompt": "rainy night too"}})
    quote["execute_node_ids"].append(target)
    with pytest.raises(ScopeViolation, match="unrelated"):
        audit_story_patch_scope(plan, record, quote, "clip_3")


@pytest.mark.parametrize("kind", ["insert_node", "remove_node"])
def test_insert_remove_are_rejected(kind):
    plan, record, quote = fixtures()
    record["draft"]["ops"][0]["op"] = kind
    with pytest.raises(ScopeViolation, match="Insert/remove"):
        audit_story_patch_scope(plan, record, quote, "clip_3")


@pytest.mark.parametrize("shared", ["typed_ref", "depends_on", "image_deliverable"])
def test_shared_frame_is_not_a_dedicated_keyframe(shared):
    plan, record, quote = fixtures(("frame_3", "clip_3"))
    other = next(n for n in plan["nodes"] if n["id"] == "clip_1")
    if shared == "typed_ref":
        other["inputs"]["first_frame_artifact_id"] = {"ref": "frame_3.image"}
    elif shared == "depends_on":
        other["depends_on"] = ["frame_3"]
    else:
        plan["deliverables"].append({"kind": "image", "node_id": "frame_3", "output": "image"})
    with pytest.raises(ScopeViolation, match="shared/non-keyframe"):
        audit_story_patch_scope(plan, record, quote, "clip_3")


def test_reference_ancestor_is_not_allowed_merely_because_it_feeds_target():
    plan, record, quote = fixtures()
    record["draft"]["ops"].append({"op": "update_inputs", "node_id": "hero", "inputs": {"prompt": "new identity"}})
    with pytest.raises(ScopeViolation, match="shared/non-keyframe"):
        audit_story_patch_scope(plan, record, quote, "clip_3")


def test_valid_prompt_patch_with_quote_only_scope_expansion_is_rejected():
    plan, record, quote = fixtures()
    quote["execute_node_ids"].append("clip_1")
    quote["reused_node_ids"].remove("clip_1")
    with pytest.raises(ScopeViolation, match="execution scope"):
        audit_story_patch_scope(plan, record, quote, "clip_3")


def test_target_with_dependent_other_shot_cannot_be_silently_cascaded():
    plan, record, quote = fixtures()
    next(n for n in plan["nodes"] if n["id"] == "clip_1")["depends_on"] = ["clip_3"]
    with pytest.raises(ScopeViolation, match="another shot"):
        audit_story_patch_scope(plan, record, quote, "clip_3")


@pytest.mark.parametrize("field", ["patch_id", "base_version", "scope"])
def test_identity_version_scope_must_match(field):
    plan, record, quote = fixtures()
    quote[field] = "wrong" if field != "base_version" else 2
    with pytest.raises(ScopeViolation):
        audit_story_patch_scope(plan, record, quote, "clip_3")


def test_approval_callback_not_reached_for_wrong_scope():
    plan, record, quote = fixtures()
    record["draft"]["ops"].append({"op": "update_inputs", "node_id": "clip_1", "inputs": {"prompt": "wrong"}})
    approved = False
    with pytest.raises(ScopeViolation):
        audit_story_patch_scope(plan, record, quote, "clip_3")
        approved = True
    assert not approved


@pytest.mark.parametrize("target", ["clip_3", "frame_3"])
def test_update_inputs_accepts_identical_reference_passthrough(target):
    plan, record, quote = fixtures((target,))
    original = next(node for node in plan["nodes"] if node["id"] == target)
    record["draft"]["ops"][0]["inputs"] = {**deepcopy(original["inputs"]), "prompt": "rainy night"}
    frozen = deepcopy((plan, record, quote))
    result = audit_story_patch_scope(plan, record, quote, "clip_3")
    assert result["changed_prompt_node_ids"] == [target]
    assert (plan, record, quote) == frozen


@pytest.mark.parametrize("target,field,value", [
    ("clip_3", "first_frame_artifact_id", {"ref": "frame_1.image"}),
    ("frame_3", "reference_artifact_ids", [{"ref": "frame_2.image"}]),
    ("clip_3", "model_id", "other-model"),
    ("clip_3", "params", {"duration": 11}),
    ("clip_3", "negative_prompt", "different"),
])
def test_update_inputs_rejects_real_reference_or_other_field_change(target, field, value):
    plan, record, quote = fixtures((target,))
    record["draft"]["ops"][0]["inputs"][field] = value
    with pytest.raises(ScopeViolation, match="execution field"):
        audit_story_patch_scope(plan, record, quote, "clip_3")


@pytest.mark.parametrize("inputs", [
    {"first_frame_artifact_id": {"ref": "frame_3.image"}},
    {"prompt": "walk", "first_frame_artifact_id": {"ref": "frame_3.image"}},
    {"prompt": ""}, {"prompt": " "}, {},
])
def test_update_inputs_requires_a_real_nonempty_prompt_change(inputs):
    plan, record, quote = fixtures()
    record["draft"]["ops"][0]["inputs"] = inputs
    with pytest.raises(ScopeViolation, match="Missing or unchanged prompt"):
        audit_story_patch_scope(plan, record, quote, "clip_3")


@pytest.mark.parametrize("inputs", [None, [], "prompt"])
def test_update_inputs_requires_an_object(inputs):
    plan, record, quote = fixtures()
    record["draft"]["ops"][0]["inputs"] = inputs
    with pytest.raises(ScopeViolation, match="object"):
        audit_story_patch_scope(plan, record, quote, "clip_3")
