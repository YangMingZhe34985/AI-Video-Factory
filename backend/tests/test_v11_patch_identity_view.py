"""Applied identity headers describe persisted versions, never raw upgrade guesses."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.plans import patches, views
from app.plans import patch_origin


def fixture(monkeypatch, *, applied=True, approved=True, base_story=None):
    base = {"nodes": [], "character_references": {}, "story_ref": base_story}
    proposed = {"character_references": {"hero": [{"artifact": "proposed"}]}}
    draft = {"base_version": 1, "reason": "Bind identity", "ops": [], "identity_upgrade": proposed}
    stored = {"nodes": [], "character_references": {"hero": [{"artifact": "actually_saved"} ]},
              "story_ref": {"key": "compiler.bound.story", "version": 3}}
    record = {"draft": draft, "status": "applied" if applied else "awaiting_approval", "approved_version": 2}
    run = SimpleNamespace(run_id="local-run", snapshot={"v3_patches": {"upgrade": record}})
    query = MagicMock()
    def filtered(**kwargs):
        assert kwargs["run_id"] == "local-run"
        value = base if kwargs["version"] == 1 else stored if approved and kwargs["version"] == 2 else None
        return SimpleNamespace(first=lambda: SimpleNamespace(plan=value) if value is not None else None)
    query.filter_by.side_effect=filtered
    monkeypatch.setattr(views, "AgentPlanVersion", SimpleNamespace(query=query))
    monkeypatch.setattr(patch_origin, "verified_patch_author", lambda *_a: None)
    if applied:
        monkeypatch.setattr(patches, "apply_patch_draft", lambda *_a, **_k: pytest.fail("Applied history must not be simulated"))
    else:
        monkeypatch.setattr(patches, "apply_patch_draft", lambda *_a, **_k: {**base, **proposed})
    return run, base, proposed, stored


def test_applied_identity_header_uses_persisted_references_and_compiler_story(monkeypatch):
    run, base, proposal, stored = fixture(monkeypatch)
    frozen = deepcopy((base, proposal, stored))
    row=views.public_patches(run)[0]
    header=row["diff_preview"][0]
    assert header["op"] == "identity_upgrade" and header["node_id"] is None
    assert header["before"] == {"character_references": {}, "story_ref": None}
    assert header["after"] == {key: stored[key] for key in ("character_references", "story_ref")}
    assert header["after"]["story_ref"] == {"key": "compiler.bound.story", "version": 3}
    assert row["diff_summary"][0]["fields"] == ["character_references", "story_ref"]
    assert (base, proposal, stored) == frozen


def test_missing_applied_identity_version_has_null_after(monkeypatch):
    run, _base, _proposal, _stored=fixture(monkeypatch, approved=False)
    row=views.public_patches(run)[0]
    assert row["diff_preview"][0]["after"] is None
    assert row["metadata_diff"] == []


@pytest.mark.parametrize("story", [None, {"key": "fixed.story", "version": 1}])
def test_pending_identity_header_still_describes_proposal(monkeypatch, story):
    run, _base, proposal, _stored=fixture(monkeypatch, applied=False, base_story=story)
    header=views.public_patches(run)[0]["diff_preview"][0]
    assert header["after"] == {"character_references": proposal["character_references"], "story_ref": story}
