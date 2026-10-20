"""Pure identity lineage regression; no media or database calls."""
from copy import deepcopy

import pytest

from app.plans.identity import validate_identity

FIELDS = {
    "generate_image": {"reference_artifact_ids": "image[]"},
    "animate_shot": {"first_frame_artifact_id": "image", "last_frame_artifact_id": "image"},
    "generate_video": {"first_frame_artifact_id": "image", "reference_artifact_ids": "image[]"},
    "transform_video": {"media": "json", "source_artifact_id": "video"},
    "select_image": {"candidate_artifact_ids": "image[]"},
    "compose_video": {"video_artifact_ids": "video[]"},
    "extract_frame": {"video_artifact_id": "video"},
    "retain_video_segment": {"video_artifact_id": "video"},
}


def ref(node, field="image"):
    return {"ref": f"{node}.{field}"}


def node(node_id, tool, inputs, characters=None, **kw):
    return {"id": node_id, "tool": tool, "inputs": inputs, "characters": characters, "params": {}, **kw}


def root(character):
    return node("cast_" + character, "generate_image", {"mode": "t2i"}, [character], gate="preview")


def frame(node_id="frame", characters=None, refs=None, **kw):
    return node(node_id, "generate_image", {"mode": "i2i", "reference_artifact_ids": refs or [ref("cast_a"), ref("cast_b")]},
                ["a", "b"] if characters is None else characters, **kw)


def video(node_id="video", source=None, characters=None, **kw):
    return node(node_id, "animate_shot", {"first_frame_artifact_id": source or ref("frame")},
                ["a", "b"] if characters is None else characters, **kw)


def plan(*extra):
    return {"character_references": {"a": [ref("cast_a")], "b": [ref("cast_b")]},
            "nodes": [root("a"), root("b"), *extra]}


def check(value, *, metadata=None, known=None, order=None):
    outputs = {}
    for item in value["nodes"]:
        tool, node_id = item["tool"], item["id"]
        if tool == "generate_image":
            count = item["params"].get("n", 1)
            outputs[node_id] = {"image": {"type": "image"}, "images": {"type": "image[]", "count": count}}
        elif tool in {"animate_shot", "generate_video", "transform_video"}:
            outputs[node_id] = {"video": {"type": "video"}}
        elif tool == "select_image":
            outputs[node_id] = {"image": {"type": "image"}}
        elif tool == "extract_frame":
            outputs[node_id] = {"artifact_id": {"type": "image"}}
        elif tool in {"compose_video", "retain_video_segment"}:
            outputs[node_id] = {"artifact_id": {"type": "video"}, "compressed_artifact_id": {"type": "video"}}
        elif tool == "qc_video":
            outputs[node_id] = {"checks": {"type": "json"}}
        elif tool == "package_story":
            outputs[node_id] = {"artifact_id": {"type": "package"}}
    if metadata:
        outputs.update(metadata)
    return validate_identity(value, order=order if order is not None else [n["id"] for n in value["nodes"]],
        output_metadata=outputs, known_artifacts=known or {},
        media_fields={n["id"]: FIELDS.get(n["tool"], {}) for n in value["nodes"]})


def missing(issues, node_id="video"):
    return [item for item in issues if item["node_id"] == node_id and item["code"] == "PLAN_CHARACTER_REFERENCE_MISSING"]


def test_two_identity_keyframe_then_video_passes_without_mutation():
    value = plan(frame(), video())
    before = deepcopy(value)
    assert check(value) == []
    assert value == before


def test_v10_fallback_dependencies_do_not_cover_second_character():
    value = plan(video(source=ref("cast_a"), depends_on=["cast_a", "cast_b"]))
    errors = missing(check(value))
    assert len(errors) == 1 and "Character b " in errors[0]["message"]


def test_intermediate_output_does_not_keep_undeclared_identity():
    assert len(missing(check(plan(frame(characters=["a"]), video())))) == 1


def test_empty_shot_clears_all_identity_evidence():
    assert len(missing(check(plan(frame(characters=[]), video())))) == 2


@pytest.mark.parametrize("complete", [False, True])
def test_all_selected_reference_images_for_one_character_are_required(complete):
    refs = [{"artifact": "front"}, {"artifact": "side"}]
    value = {"character_references": {"a": refs}, "nodes": [frame(characters=["a"], refs=refs if complete else refs[:1])]}
    errors = check(value, known={"front": {"type": "image"}, "side": {"type": "image"}})
    assert bool(missing(errors, "frame")) is not complete


@pytest.mark.parametrize("same", [False, True])
def test_selector_intersects_every_independent_candidate(same):
    first = frame("first", characters=["a", "b"] if same else ["a"])
    second = frame("second", characters=["a", "b"] if same else ["b"])
    selector = node("choose", "select_image", {"candidate_artifact_ids": [ref("first"), ref("second")]}, gate="choice")
    errors = check(plan(first, second, selector, video(source=ref("choose"))))
    assert bool(missing(errors)) is not same


def test_selector_image_array_retains_all_candidates_common_evidence():
    candidates = frame("candidates", params={"n": 3})
    selector = node("choose", "select_image", {"candidate_artifact_ids": ref("candidates", "images")}, gate="choice")
    assert check(plan(candidates, selector, video(source=ref("choose")))) == []


@pytest.mark.parametrize("same", [False, True])
def test_composition_and_extracted_tail_use_common_segment_evidence(same):
    first = video("first", source=ref("cast_a"), characters=["a"])
    second = video("second", source=ref("cast_a" if same else "cast_b"), characters=["a" if same else "b"])
    composition = node("compose", "compose_video", {"video_artifact_ids": [ref("first", "video"), ref("second", "video")]})
    extracted = node("tail", "extract_frame", {"video_artifact_id": ref("compose", "artifact_id")})
    final = video(source=ref("tail", "artifact_id"), characters=["a"])
    errors = check(plan(first, second, composition, extracted, final))
    assert bool(missing(errors)) is not same


def test_retained_video_and_tail_keep_valid_identity_chain():
    clip = video("clip", source=ref("cast_a"), characters=["a"])
    retained = node("keep", "retain_video_segment", {"video_artifact_id": ref("clip", "video")})
    extracted = node("tail", "extract_frame", {"video_artifact_id": ref("keep", "artifact_id")})
    assert check(plan(clip, retained, extracted, video(source=ref("tail", "artifact_id"), characters=["a"]))) == []


@pytest.mark.parametrize("change", ["count", "gate", "roles", "array", "selector", "cycle"])
def test_invalid_future_identity_roots_are_blocked(change):
    value = plan()
    if change == "count":
        value["nodes"][0]["params"]["n"] = 2
    elif change == "gate":
        value["nodes"][0]["gate"] = None
    elif change == "roles":
        value["nodes"][0]["characters"] = ["a", "b"]
    elif change == "array":
        value["character_references"]["a"] = [ref("cast_a", "images")]
    elif change == "selector":
        value["nodes"][0]["tool"] = "select_image"
    errors = check(value, order=["cast_b"] if change == "cycle" else None)
    assert any(item["code"] == "PLAN_INVALID_CHARACTER_REFERENCE" for item in errors)


def test_catalog_existing_artifact_requires_verified_image_type():
    value = {"character_references": {"a": [{"artifact": "other_run"}]}, "nodes": []}
    assert check(value)[0]["code"] == "PLAN_INVALID_CHARACTER_REFERENCE"
    assert check(value, known={"other_run": {"type": "video"}})[0]["code"] == "PLAN_INVALID_CHARACTER_REFERENCE"


def test_missing_and_unknown_character_declarations_are_blocked():
    value = plan(node("unknown", "generate_image", {}, ["not_known"]), node("unspecified", "generate_image", {}))
    codes = {item["code"] for item in check(value)}
    assert {"PLAN_UNKNOWN_CHARACTER", "PLAN_CHARACTERS_REQUIRED"} <= codes


def test_non_generation_node_cannot_declare_characters():
    value = plan(node("choose", "select_image", {"candidate_artifact_ids": [ref("cast_a"), ref("cast_b")]}, ["a"]))
    assert any(item["code"] == "PLAN_INVALID_CHARACTER_REFERENCE" for item in check(value))


def test_unrelated_named_output_cannot_inherit_node_identity():
    value = plan(frame(), video(source=ref("frame", "unrelated_image")))
    metadata = {"frame": {"image": {"type": "image"}, "images": {"type": "image[]", "count": 1},
                          "unrelated_image": {"type": "image"}}}
    assert len(missing(check(value, metadata=metadata))) == 2


@pytest.mark.parametrize("kind, expected", [("reference_image", False), ("reference_audio", True), ("file", True)])
def test_transform_only_uses_visual_media(kind, expected):
    target = node("video", "transform_video", {"media": [{"type": kind, "artifact_id": ref("cast_a")}]}, ["a"])
    assert bool(missing(check(plan(target)))) is expected


def test_transform_can_use_traced_video_evidence():
    clip = video("clip", source=ref("cast_a"), characters=["a"])
    target = node("video", "transform_video", {"media": [{"type": "reference_video", "artifact_id": ref("clip", "video")}],
                                              "source_artifact_id": ref("clip", "video")}, ["a"])
    assert check(plan(clip, target)) == []


def test_untyped_prompt_reference_is_not_identity_input():
    target = node("video", "animate_shot", {"prompt": ref("cast_a"), "first_frame_artifact_id": "random"}, ["a"])
    assert missing(check(plan(target)))


def test_legacy_no_identity_plan_remains_compatible():
    assert check({"nodes": [node("image", "generate_image", {"prompt": "cat"})]}) == []
