"""Dependency diffs survive unchanged authors and use actual applied history."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.plans import patch_origin, patches, views


def node(node_id, dependencies=()):
    return {"id": node_id, "depends_on": list(dependencies),
            "origin": {"agent": "director"}, "rationale": "Unchanged purpose"}


def insertion():
    return {"base_version": 1, "reason": "Add a prerequisite", "ops": [
        {"op": "insert_node", "node": node("inserted"), "before": "image"}]}


@pytest.mark.parametrize("incidental", [True, False])
def test_dependency_change_survives_unchanged_director_and_rationale(incidental):
    before = {"nodes": [node("image")]}
    after = {"nodes": [node("image", ["inserted"])]}
    draft = insertion() if incidental else {"ops": [
        {"op": "replace_node", "node_id": "image", "node": deepcopy(after["nodes"][0])}]}
    frozen = deepcopy((before, after, draft))
    assert patch_origin.metadata_changes(before, after, draft) == [{
        "node_id": "image", "incidental": incidental,
        "depends_on": {"before": [], "after": ["inserted"]}}]
    assert (before, after, draft) == frozen


def test_unchanged_dependencies_and_metadata_do_not_invent_diff():
    before = {"nodes": [node("image")]}
    assert patch_origin.metadata_changes(before, deepcopy(before), insertion()) == []


def public_fixture(monkeypatch, *, applied=True, approved=True, actual_dependencies=("archived_dependency",)):
    before = {"nodes": [node("image")]}
    after = {"nodes": [node("image", actual_dependencies), node("inserted")]}
    record = {"draft": insertion(), "status": "applied" if applied else "awaiting_approval", "approved_version": 2}
    run = SimpleNamespace(run_id="dependency-view", snapshot={"v3_patches": {"patch": record}})
    query = MagicMock()
    def filtered(**kwargs):
        assert kwargs["run_id"] == run.run_id
        plan = before if kwargs["version"] == 1 else after if approved and kwargs["version"] == 2 else None
        return SimpleNamespace(first=lambda: SimpleNamespace(plan=plan) if plan is not None else None)
    query.filter_by.side_effect = filtered
    monkeypatch.setattr(views, "AgentPlanVersion", SimpleNamespace(query=query))
    monkeypatch.setattr(patch_origin, "verified_patch_author", lambda *_args: {
        "agent": "director", "proposed_by": "director"})
    def candidate(*_args, **kwargs):
        assert not applied, "Applied history must not be simulated"
        assert kwargs["trusted_author"] == "director"
        return {"nodes": [node("image", ["inserted"]), node("inserted")]}
    monkeypatch.setattr(patches, "apply_patch_draft", candidate)
    return run, before, after


def test_pending_same_director_insertion_shows_incidental_dependency(monkeypatch):
    run, _before, _after = public_fixture(monkeypatch, applied=False)
    row = views.public_patches(run)[0]
    change = next(item for item in row["metadata_diff"] if item["node_id"] == "image")
    assert change == {"node_id": "image", "incidental": True,
                      "depends_on": {"before": [], "after": ["inserted"]}}


def test_applied_dependency_diff_uses_persisted_version_not_proposal(monkeypatch):
    run, before, after = public_fixture(monkeypatch)
    frozen = deepcopy((before, after))
    row = views.public_patches(run)[0]
    change = next(item for item in row["metadata_diff"] if item["node_id"] == "image")
    assert change == {"node_id": "image", "incidental": True,
                      "depends_on": {"before": [], "after": ["archived_dependency"]}}
    assert (before, after) == frozen


def test_applied_unchanged_dependency_does_not_copy_proposal_diff(monkeypatch):
    run, _before, _after = public_fixture(monkeypatch, actual_dependencies=())
    row = views.public_patches(run)[0]
    assert not any(item["node_id"] == "image" for item in row["metadata_diff"])


def test_missing_applied_version_has_no_simulated_dependency_diff(monkeypatch):
    run, _before, _after = public_fixture(monkeypatch, approved=False)
    row = views.public_patches(run)[0]
    assert row["metadata_diff"] == []
    assert row["diff_preview"][0]["after"] is None
