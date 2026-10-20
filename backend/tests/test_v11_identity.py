"""Identity coverage is a typed data proof, never a prompt/control-edge claim."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.agents.schemas import PlanDraft
from app.extensions import db
from app.models import AgentDelegation, AgentPlanVersion, AgentWorkspaceItem
from app.plans.compiler import compile_plan, plan_digest
from app.plans.dry_run import dry_run
from tests.test_v3_blueprints import story_data
from tests.test_v3_plan_compiler import counts, image, make_run, node, plan


def ref(name):
    return {"ref": f"{name}.image"}


def seed(name, character):
    return node(name, gate="preview", params={"n": 1}, characters=[character])


def frame(name, characters, references):
    return node(name, inputs={"mode": "i2i", "prompt": "The declared characters in one frame",
                             "reference_artifact_ids": references}, characters=characters)


def video(name, source, characters):
    return node(name, "animate_shot", {"first_frame_artifact_id": source, "prompt": "Both characters talk"},
                params={"duration": 5}, characters=characters)


def story_plan(*, fixed=False):
    nodes = [seed("cast_deepseek", "deepseek"), seed("cast_gpt", "gpt")]
    if fixed:
        nodes.append(frame("frame", ["deepseek", "gpt"], [ref("cast_deepseek"), ref("cast_gpt")]))
    nodes.append(video("s03", ref("frame" if fixed else "cast_deepseek"), ["deepseek", "gpt"]))
    nodes[-1]["depends_on"] = ["cast_deepseek", "cast_gpt"]
    value = plan(nodes, [{"kind": "image", "node_id": "cast_gpt", "output": "image"},
                         {"kind": "video", "node_id": "s03", "output": "video"}])
    value["character_references"] = {"deepseek": [ref("cast_deepseek")], "gpt": [ref("cast_gpt")]}
    return value


def issue_codes(draft, run):
    return {item["code"] for item in compile_plan(draft, run)["issues"]}


def assert_valid(draft, run):
    checked = compile_plan(draft, run)
    assert not checked["issues"], checked["issues"]
    assert dry_run(checked)["passed"]
    assert compile_plan(checked["plan"], run)["plan"] == checked["plan"]
    return checked


def save_story(run, *, key="story", version=1, payload=None):
    value = payload or story_data()["story"]
    row = AgentWorkspaceItem(run_id=run.run_id, delegation_id=AgentDelegation.query.filter_by(run_id=run.run_id).first().id,
                             key=key, version=version, kind="story", payload=value,
                             artifact_ids=[], author_agent="creative", request_key=f"{key}:{version}",
                             inputs_hash="fixture")
    db.session.add(row)
    db.session.commit()
    return row


def test_v10_c3_second_single_identity_first_frame_is_blocked_without_execution(app_ctx):
    run = make_run(deliverable="video")
    draft = story_plan()
    before = deepcopy(draft), counts()
    checked = compile_plan(draft, run)
    missing = [item for item in checked["issues"] if item["code"] == "PLAN_CHARACTER_REFERENCE_MISSING"]
    assert any(item["node_id"] == "s03" and "gpt" in item["message"] for item in missing)
    assert not dry_run(checked)["passed"]
    assert (draft, counts()) == before


def test_multireference_keyframe_proves_both_characters_and_default_capacity(app_ctx):
    checked = assert_valid(story_plan(fixed=True), make_run(deliverable="video"))
    selected = next(item for item in checked["plan"]["nodes"] if item["id"] == "frame")
    assert selected["model_id"] == "qwen-image-3.0"
    assert selected["characters"] == ["deepseek", "gpt"]


@pytest.mark.parametrize("declaration", [None, [], ["deepseek"]])
def test_frame_cannot_claim_an_identity_it_does_not_declare(app_ctx, declaration):
    draft = story_plan(fixed=True)
    draft["nodes"][2]["characters"] = declaration
    assert "PLAN_CHARACTER_REFERENCE_MISSING" in issue_codes(draft, make_run())


def test_control_and_json_outputs_never_add_identity(app_ctx):
    draft = story_plan()
    draft["nodes"].append(node("probe", "probe_media", {"artifact_id": {"ref": "s03.video"}}))
    draft["nodes"][-2]["rationale"] = "Both identities exist in the control dependencies"
    assert "PLAN_CHARACTER_REFERENCE_MISSING" in issue_codes(draft, make_run())


@pytest.mark.parametrize("change", ["array", "no_gate", "two_characters", "shared_root", "unknown_root", "choice_root"])
def test_invalid_future_identity_roots_cannot_self_certify(app_ctx, change):
    draft = story_plan(fixed=True)
    if change == "array":
        draft["nodes"][0]["params"]["n"] = 2
    elif change == "no_gate":
        draft["nodes"][0]["gate"] = None
    elif change == "two_characters":
        draft["nodes"][0]["characters"] = ["deepseek", "gpt"]
    elif change == "shared_root":
        draft["character_references"]["gpt"] = [ref("cast_deepseek")]
    elif change == "unknown_root":
        draft["character_references"]["gpt"] = [ref("unknown")]
    else:
        draft["nodes"][0].update(tool="select_image", gate="choice", params={},
            inputs={"candidate_artifact_ids": [ref("cast_gpt"), ref("frame")]})
    assert "PLAN_INVALID_CHARACTER_REFERENCE" in issue_codes(draft, make_run())


def test_existing_references_require_all_images_of_each_identity(app_ctx):
    ids = [image(), image()]
    run = make_run(ids=ids)
    draft = plan([frame("image", ["hero"], [{"artifact": ids[0]}])])
    draft["character_references"] = {"hero": [{"artifact": item} for item in ids]}
    assert "PLAN_CHARACTER_REFERENCE_MISSING" in issue_codes(draft, run)
    draft["nodes"][0]["inputs"]["reference_artifact_ids"].append({"artifact": ids[1]})
    assert_valid(draft, run)


def test_foreign_artifact_cannot_be_registered_as_identity(app_ctx):
    foreign = image(owner="somebody-else")
    draft = plan([node(characters=["hero"])])
    draft["character_references"] = {"hero": [{"artifact": foreign}]}
    assert "PLAN_INVALID_CHARACTER_REFERENCE" in issue_codes(draft, make_run())


@pytest.mark.parametrize("complete", [False, True])
def test_selector_requires_each_candidate_to_cover_every_identity(app_ctx, complete):
    draft = story_plan(fixed=True)
    alternative = frame("alternative", ["deepseek", "gpt"] if complete else ["deepseek"],
                        [ref("cast_deepseek"), ref("cast_gpt")] if complete else [ref("cast_deepseek")])
    selector = node("choose", "select_image",
                    {"candidate_artifact_ids": [ref("frame"), ref("alternative")]}, gate="choice")
    draft["nodes"] = draft["nodes"][:3] + [alternative, selector, video("s03", ref("choose"), ["deepseek", "gpt"])]
    checked = compile_plan(draft, make_run())
    if complete:
        assert not checked["issues"], checked["issues"]
    else:
        assert "PLAN_CHARACTER_REFERENCE_MISSING" in {item["code"] for item in checked["issues"]}


def test_tail_frame_propagates_valid_identity_and_rejects_added_character(app_ctx):
    draft = story_plan(fixed=True)
    draft["nodes"].extend([node("tail", "extract_frame", {"video_artifact_id": {"ref": "s03.video"},
                                                       "position": "last"}),
                           video("s04", {"ref": "tail.artifact_id"}, ["deepseek", "gpt"])])
    draft["deliverables"].append({"kind": "video", "node_id": "s04", "output": "video"})
    run = make_run()
    assert_valid(draft, run)
    draft["nodes"][2]["characters"] = ["deepseek"]
    assert "PLAN_CHARACTER_REFERENCE_MISSING" in issue_codes(draft, run)


def test_compose_then_extract_cannot_union_characters_from_different_clips(app_ctx):
    draft = story_plan()
    draft["nodes"][2]["characters"] = ["deepseek"]
    draft["nodes"].extend([video("s04", ref("cast_gpt"), ["gpt"]),
        node("master", "compose_video", {"video_artifact_ids": [{"ref": "s03.video"}, {"ref": "s04.video"}]}),
        node("tail", "extract_frame", {"video_artifact_id": {"ref": "master.artifact_id"}, "position": "last"}),
        video("s05", {"ref": "tail.artifact_id"}, ["deepseek", "gpt"])])
    draft["deliverables"].append({"kind": "video", "node_id": "s05", "output": "video"})
    assert "PLAN_CHARACTER_REFERENCE_MISSING" in issue_codes(draft, make_run())


@pytest.mark.parametrize("field", ["character_references", "characters"])
def test_known_story_cannot_be_silently_omitted_from_new_draft(app_ctx, field):
    run = make_run()
    data = story_data()
    save_story(run, payload=data["story"])
    draft = plan([seed("identity", "hero"), frame("image", ["hero"], [ref("identity")])])
    draft["character_references"] = {"hero": [ref("identity")]}
    if field == "character_references":
        draft.pop(field)
    else:
        draft["nodes"][1].pop(field)
    expected = "PLAN_CHARACTER_REFERENCE_REQUIRED" if field == "character_references" else "PLAN_CHARACTERS_REQUIRED"
    assert expected in issue_codes(draft, run)


def test_story_version_freezes_and_later_story_does_not_rebind(app_ctx):
    run = make_run()
    save_story(run)
    draft = plan([seed("identity", "hero"), frame("image", ["hero"], [ref("identity")])])
    draft["character_references"] = {"hero": [ref("identity")]}
    checked = assert_valid(draft, run)
    assert checked["plan"]["story_ref"] == {"key": "story", "version": 1}
    changed = story_data()["story"]
    changed["characters"][0]["character_id"] = "other"
    changed["story"]["beats"][0]["character_ids"] = ["other"]
    save_story(run, version=2, payload=changed)
    assert_valid(checked["plan"], run)
    assert "PLAN_UNKNOWN_CHARACTER" in issue_codes(draft, run)


def test_story_existing_reference_cannot_be_swapped(app_ctx):
    ids = [image(), image()]
    run = make_run(ids=ids)
    story = story_data()["story"]
    story["characters"][0]["reference"] = {"source": "attachment", "artifact_ids": [ids[0]]}
    save_story(run, payload=story)
    draft = plan([frame("image", ["hero"], [{"artifact": ids[1]}])])
    draft["character_references"] = {"hero": [{"artifact": ids[1]}]}
    assert "PLAN_INVALID_CHARACTER_REFERENCE" in issue_codes(draft, run)


def test_foreign_story_and_fake_legacy_version_do_not_bypass_checks(app_ctx):
    run, other = make_run(), make_run()
    save_story(other)
    draft = plan()
    draft["story_ref"] = {"key": "story", "version": 1}
    assert "PLAN_INVALID_STORY_REFERENCE" in issue_codes(draft, run)
    save_story(run)
    draft.pop("story_ref")
    draft["plan_version"] = 99
    assert "PLAN_CHARACTER_REFERENCE_REQUIRED" in issue_codes(draft, run)


def test_new_optional_defaults_preserve_legacy_digest_and_persisted_plan(app_ctx):
    run = make_run()
    checked = assert_valid(plan(), run)
    original = deepcopy(checked["plan"])
    assert "character_references" not in original and "story_ref" not in original
    assert "characters" not in original["nodes"][0]
    digest = plan_digest(original)
    db.session.add(AgentPlanVersion(run_id=run.run_id, version=1, author="director",
                                   plan=original, story_package={}, check={}))
    db.session.commit()
    save_story(run)
    assert compile_plan(original, run)["plan"] == original
    assert plan_digest(original) == digest
    assert "PLAN_CHARACTER_REFERENCE_REQUIRED" in issue_codes(plan(), run)


def test_legacy_patch_identity_upgrade_is_rechecked_as_a_complete_new_plan(app_ctx):
    from app.plans.patches import apply_patch_draft
    run = make_run()
    authored = plan([seed("identity", "hero"), frame("image", ["hero"], [ref("identity")])])
    legacy = deepcopy(authored)
    for item in legacy["nodes"]:
        item.pop("characters")
    compiled = assert_valid(legacy, run)
    db.session.add(AgentPlanVersion(run_id=run.run_id, version=1, author="director",
                                   plan=compiled["plan"], story_package={}, check={}))
    db.session.commit()
    save_story(run)
    patch = {"base_version": 1, "reason": "Upgrade explicit identity coverage",
             "identity_upgrade": {"character_references": {"hero": [ref("identity")]},
                                  "story_ref": {"key": "story", "version": 1}},
             "ops": [{"op": "replace_node", "node_id": item["id"], "node": item} for item in authored["nodes"]]}
    upgraded = apply_patch_draft(compiled["plan"], patch)
    assert_valid(upgraded, run)
    patch["ops"].pop()
    incomplete = apply_patch_draft(compiled["plan"], patch)
    assert "PLAN_CHARACTERS_REQUIRED" in issue_codes(incomplete, run)


@pytest.mark.parametrize("value", [["hero", "hero"], ["bad space"], [1]])
def test_character_schema_rejects_duplicate_or_malformed_ids(value):
    with pytest.raises(ValidationError):
        PlanDraft.model_validate(plan([node(characters=value)]))
