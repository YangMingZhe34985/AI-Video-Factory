"""Pure legacy identity-upgrade checks; no database/app/HTTP needed."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.api import AppError
from app.plans.patch_schemas import PatchDraft
from app.plans import patches, views


def base():
    return {"title": "Legacy", "goal": "draw hero", "nodes": [
        {"id": "image", "tool": "generate_image", "inputs": {"prompt": "hero"}, "origin": {"agent": "director"}, "rationale": "portrait"}],
        "deliverables": [{"kind": "image", "node_id": "image", "output": "image"}]}


def draft(upgrade=False, count=1):
    value = {"base_version": 1, "reason": "identity upgrade", "ops": [
        {"op": "update_inputs", "node_id": "image" if i == 0 else f"node_{i}", "inputs": {"prompt": "hero"}} for i in range(count)]}
    if upgrade:
        value["identity_upgrade"] = {"character_references": {"hero": [{"artifact": "portrait"}]}}
    return value


def test_legacy_patch_normalization_stays_identical():
    value = draft()
    expected = {**value, "evidence_refs": [], "scope": "only"}
    assert patches.normalize_patch(value) == expected
    assert patches.normalize_patch({**value, "identity_upgrade": None}) == expected


def test_upgrade_adds_binding_without_mutating_base_or_draft():
    original, change = base(), draft(True)
    change["identity_upgrade"]["story_ref"] = {"key": "story", "version": 2}
    before = deepcopy((original, change))
    result = patches.apply_patch_draft(original, change)
    assert result["character_references"] == change["identity_upgrade"]["character_references"]
    assert result["story_ref"] == {"key": "story", "version": 2}
    assert (original, change) == before


def test_existing_identity_catalog_cannot_be_replaced_even_by_same_catalog():
    original, change = base(), draft(True)
    original["character_references"] = deepcopy(change["identity_upgrade"]["character_references"])
    with pytest.raises(AppError) as failure:
        patches.apply_patch_draft(original, change)
    assert failure.value.code == "PLAN_IDENTITY_UPGRADE_FORBIDDEN"


@pytest.mark.parametrize("new_story", [None, {"key": "story", "version": 1}])
def test_existing_fixed_story_is_retained(new_story):
    original, change = base(), draft(True)
    original["story_ref"] = {"key": "story", "version": 1}
    if new_story is not None:
        change["identity_upgrade"]["story_ref"] = new_story
    assert patches.apply_patch_draft(original, change)["story_ref"] == original["story_ref"]


def test_existing_fixed_story_cannot_be_rebound():
    original, change = base(), draft(True)
    original["story_ref"] = {"key": "story", "version": 1}
    change["identity_upgrade"]["story_ref"] = {"key": "story", "version": 2}
    with pytest.raises(AppError) as failure:
        patches.apply_patch_draft(original, change)
    assert failure.value.code == "PLAN_IDENTITY_UPGRADE_FORBIDDEN"


@pytest.mark.parametrize("refs", [{}, {"bad space": [{"artifact": "portrait"}]}, {"hero": []},
    {"hero": [{"artifact": "portrait"}] * 2}, {"hero": [{"artifact": str(i)} for i in range(4)]},
    {"hero": [{"ref": "identity.images"}]}])
def test_upgrade_catalog_reuses_identity_reference_contract(refs):
    value = draft(True)
    value["identity_upgrade"]["character_references"] = refs
    with pytest.raises(ValidationError):
        PatchDraft.model_validate(value)


def test_upgrade_cannot_smuggle_any_other_plan_fields():
    value = draft(True)
    value["identity_upgrade"]["goal"] = "change user intent"
    with pytest.raises(ValidationError):
        PatchDraft.model_validate(value)


@pytest.mark.parametrize("upgrade, count, valid", [(False, 50, True), (False, 51, False), (True, 200, True), (True, 201, False)])
def test_larger_operation_limit_is_only_for_upgrade(upgrade, count, valid):
    if valid:
        assert len(PatchDraft.model_validate(draft(upgrade, count)).ops) == count
    else:
        with pytest.raises(ValidationError):
            PatchDraft.model_validate(draft(upgrade, count))


def test_upgrade_cannot_become_prompt_only_automatic_repair(monkeypatch):
    monkeypatch.setattr(patches, "repair_budget", lambda run: {"remaining": 20, "node_attempts": {}})
    record = {"trigger": {"kind": "failure", "node_ids": ["image"], "task_ids": [1]}}
    task = SimpleNamespace(id=1, status="failed", error={"category": "content_policy"}, state={"tool": "generate_image"})
    monkeypatch.setattr(patches, "_unknown", lambda task: False)
    # Pure identity-policy test: isolate the separately tested immutable verifier.
    from app.plans.patch_intent import IntentAssessment
    assessment = IntentAssessment.model_validate({"intent_preserved": True, "changed_elements": []}).model_dump()
    monkeypatch.setattr(patches, "verified_assessment", lambda run, row, digest: assessment)
    args = (SimpleNamespace(), record)
    normal = patches._automatic(*args, draft(), {"image"}, {"image"}, {"image": task}, {1}, 2)
    upgraded = patches._automatic(*args, draft(True), {"image"}, {"image"}, {"image": task}, {1}, 2)
    assert normal["eligible"] is True
    assert upgraded["eligible"] is False
    assert upgraded["reasons"] == ["IDENTITY_UPGRADE_REQUIRES_REVIEW"]


def test_public_diff_exposes_identity_change_and_preserved_story(monkeypatch):
    original, change = base(), draft(True)
    original["story_ref"] = {"key": "story", "version": 1}
    query = MagicMock()
    query.filter_by.return_value.first.return_value = SimpleNamespace(plan=original)
    monkeypatch.setattr(views, "AgentPlanVersion", SimpleNamespace(query=query))
    run = SimpleNamespace(run_id="mock", snapshot={"v3_patches": {"patch": {"draft": change, "proposed_by": "repair"}}})
    row = views.public_patches(run)[0]
    delta = row["diff_preview"][0]
    assert delta["op"] == "identity_upgrade"
    assert delta["before"]["character_references"] == {}
    assert delta["after"]["character_references"] == change["identity_upgrade"]["character_references"]
    assert delta["after"]["story_ref"] == original["story_ref"]
    assert row["diff_summary"][0]["op"] == "identity_upgrade"
