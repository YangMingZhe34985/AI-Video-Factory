"""Patch author provenance from immutable server receipts; no external calls."""
from copy import deepcopy
import pytest
from app.agents import repair_flow
from app.api import AppError
from app.extensions import db
from app.models import AgentPlanVersion, AgentWorkspaceItem
from app.plans import patches
from app.plans.patch_execution import approve_patch
from app.plans.patch_origin import metadata_changes, verified_patch_author
from app.plans.views import public_patches
from tests.test_v4_execution import image_node
from tests.test_v5_patches import failed_case
from tests.test_v5_repair_flow import assigned, draft, failure, invoke

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)


def prepared(author="repair", operation="replace_node", *, revise=False):
    run, _root, task, registry = failure(allowance=20)
    if author == "director":
        repair_flow.revise_plan(run, {"command_id": "user-revise", "plan_version": 1, "message": "仅修改背景"})
        repair_flow.advance_repair_flow(run, registry)
        child = repair_flow.planning_delegation(run)
    else:
        child = assigned(run, registry)
    value = draft(task)
    if operation == "replace_node":
        node = image_node()
        node["origin"]["agent"] = "director" if author == "repair" else "repair"
        node["inputs"]["prompt"] = "A cat in a rainy street"
        node["rationale"] = "The user requested rain"
        value["ops"] = [{"op": "replace_node", "node_id": "image", "node": node}]
    proposed = invoke(run, child, registry, "propose_patch", {"draft": value}, "author-proposal")
    repair_flow.advance_repair_flow(run, registry)
    director = repair_flow.planning_delegation(run)
    review = {"patch_id": proposed["patch_id"], "verdict": "revise" if revise else "approve", "reason": "Checked local scope", "intent_preserved": True, "changed_elements": []}
    if revise:
        replacement = deepcopy(value)
        if operation == "replace_node":
            replacement["ops"][0]["node"]["inputs"]["prompt"] = "A cat in a softly lit rainy street"
            replacement["ops"][0]["node"]["origin"]["agent"] = "repair"
        else:
            replacement["ops"][0]["inputs"]["prompt"] = "A cat in a softly lit rainy street"
        review["revised_draft"] = replacement
    invoke(run, director, registry, "review_patch", review, "author-review")
    return run, registry, proposed["patch_id"], child, director


def stored(run, patch_id):
    return run.snapshot["v3_patches"][patch_id]


@pytest.mark.parametrize("author", ["repair", "director"])
@pytest.mark.parametrize("operation", ["replace_node", "update_inputs"])
def test_effective_node_author_matches_actual_writer(app_ctx, author, operation):
    run, registry, patch_id, writer, reviewer = prepared(author, operation)
    patch = stored(run, patch_id)
    proof = verified_patch_author(run, patch, patches.normalize_patch(patch["draft"]))
    assert proof["agent"] == author and proof["delegation_id"] == writer.id != reviewer.id
    bundle = patches.quote_patch(run, patch, registry=registry)
    candidate = bundle["compiled"]["plan"]["nodes"][0]
    assert candidate["origin"]["agent"] == author
    quote = bundle["quote"]
    run.status = "attention"; db.session.commit()
    version = approve_patch(run, patch_id, quote["quote_id"], quote["scope"], registry=registry)
    assert version.plan["nodes"][0]["origin"]["agent"] == author
    assert AgentPlanVersion.query.filter_by(run_id=run.run_id, version=1).one().plan["nodes"][0]["origin"]["agent"] == "director"
    public = public_patches(run)[0]
    assert public["author_verified"] and public["author"] == public["final_author"] == author
    if author == "director": assert public["trigger_kind"] == "user_revision"
    if operation == "replace_node":
        change = next(item for item in public["metadata_diff"] if item["node_id"] == "image")
        assert change["rationale"]["before"] == "Create a first frame"
        assert change["rationale"]["after"] == "The user requested rain"
    elif author == "repair":
        assert public["metadata_diff"][0]["origin"]["after"]["agent"] == "repair"
        assert "rationale" not in public["metadata_diff"][0]


@pytest.mark.parametrize("operation", ["replace_node", "update_inputs"])
def test_independent_director_revision_is_final_writer(app_ctx, operation):
    run, registry, patch_id, writer, reviewer = prepared("repair", operation, revise=True)
    patch = stored(run, patch_id)
    proof = verified_patch_author(run, patch, patches.normalize_patch(patch["draft"]))
    assert proof["source"] == "director_revision" and proof["agent"] == "director"
    assert proof["delegation_id"] == reviewer.id != writer.id and proof["proposed_by"] == "repair"
    assert patches.quote_patch(run, patch, registry=registry)["compiled"]["plan"]["nodes"][0]["origin"]["agent"] == "director"
    assert public_patches(run)[0]["author"] == "repair" and public_patches(run)[0]["final_author"] == "director"


@pytest.mark.parametrize("field,value", [("proposed_by", "director"), ("author_delegation_id", True), ("author_delegation_id", 99999), ("proposal_ref", {"key": "other", "version": 1})])
def test_snapshot_author_forgery_rejected(app_ctx, field, value):
    run, registry, patch_id, _writer, _reviewer = prepared()
    patch = deepcopy(stored(run, patch_id)); patch[field] = value
    with pytest.raises(AppError) as error: patches.quote_patch(run, patch, registry=registry)
    assert error.value.code == "PATCH_AUTHOR_REQUIRED"


@pytest.mark.parametrize("target", ["row_author", "row_delegation", "row_hash", "receipt_hash", "receipt_ref"])
def test_proposal_and_original_receipt_are_both_required(app_ctx, target):
    run, registry, patch_id, _writer, reviewer = prepared()
    patch = stored(run, patch_id)
    proposal = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key=patch["proposal_ref"]["key"]).one()
    if target == "row_author": proposal.author_agent = "director"
    elif target == "row_delegation": proposal.delegation_id = reviewer.id
    elif target == "row_hash": proposal.inputs_hash = "0" * 64
    else:
        state = deepcopy(run.snapshot)
        receipt = state["v3_patch_tool_receipts"][proposal.request_key]
        if target == "receipt_hash": receipt["input_hash"] = "0" * 64
        else: receipt["output"]["patch_ref"] = {"key": "wrong", "version": 1}
        run.snapshot = state
    with pytest.raises(AppError) as error: patches.quote_patch(run, patch, registry=registry)
    assert error.value.code == "PATCH_AUTHOR_REQUIRED"
    db.session.rollback()


def test_insert_before_origin_and_rationale_differences_are_separate(app_ctx):
    from tests.test_v4_execution import setup
    original = image_node("image")
    kept = image_node("kept")
    run, version, _registry = setup([original, kept], deliverables=[{"kind": "image", "node_id": "image", "output": "image"}, {"kind": "image", "node_id": "kept", "output": "image"}])
    inserted = image_node("inserted")
    value = {"base_version": 1, "reason": "insert before", "ops": [{"op": "insert_node", "node": inserted, "before": "image"}]}
    frozen = deepcopy(version.plan)
    normalized = patches.normalize_patch(value)
    candidate = patches.apply_patch_draft(version.plan, normalized, trusted_author="repair")
    nodes = {node["id"]: node for node in candidate["nodes"]}
    assert nodes["inserted"]["origin"]["agent"] == nodes["image"]["origin"]["agent"] == "repair"
    assert nodes["kept"] == patches.apply_patch_draft(version.plan, normalized)["nodes"][1]
    assert version.plan == frozen and nodes["image"]["rationale"] == original["rationale"]
    diff = {item["node_id"]: item for item in metadata_changes(version.plan, candidate, normalized)}
    assert diff["image"]["incidental"] and not diff["inserted"]["incidental"]
    assert "rationale" not in diff["image"] and diff["inserted"]["rationale"]["before"] is None


def test_historical_missing_author_stays_unknown_and_manual(app_ctx):
    run, _version, registry, _task, patch = failed_case()
    # Legacy records contain neither proof field; partial proof is separately rejected.
    for field in ("author_delegation_id", "proposal_ref"):
        patch.pop(field)
    quote = patches.quote_patch(run, patch, registry=registry)["quote"]
    assert quote["manual_can_apply"] and "PATCH_AUTHOR_UNVERIFIED" in quote["automatic"]["reasons"]
    run.snapshot = {**run.snapshot, "v3_patches": {patch["patch_id"]: patch}}
    public = public_patches(run)[0]
    assert not public["author_verified"] and public["final_author"] is None and public["metadata_diff"] == []


def test_applied_history_shows_persisted_wrong_origin_without_retroactive_fix(app_ctx):
    run, _registry, patch_id, _writer, _reviewer = prepared("director", "replace_node")
    patch = stored(run, patch_id)
    base = AgentPlanVersion.query.filter_by(run_id=run.run_id, version=1).one()
    historical = patches.apply_patch_draft(base.plan, patch["draft"])
    assert historical["nodes"][0]["origin"]["agent"] == "repair"
    saved = AgentPlanVersion(run_id=run.run_id, version=2, parent_version=1, author="user",
        plan={**historical, "plan_version": 2}, story_package={}, check={})
    db.session.add(saved)
    state = deepcopy(run.snapshot)
    state["v3_patches"][patch_id].update(status="applied", approved_version=2, approval={"version": 2, "automatic": False})
    run.snapshot = state; db.session.commit()
    before = deepcopy(saved.plan)
    view = public_patches(run)[0]
    assert view["author_verified"] and view["final_author"] == "director"
    assert view["diff_preview"][0]["after"]["origin"]["agent"] == "repair"
    difference = view["metadata_diff"][0]
    assert difference["origin"]["before"]["agent"] == "director"
    assert difference["origin"]["after"]["agent"] == "repair"
    assert difference["rationale"]["after"] == "The user requested rain"
    assert saved.plan == before


def test_applied_update_inputs_uses_saved_input_not_current_draft(app_ctx):
    run, _registry, patch_id, _writer, _reviewer = prepared("repair", "update_inputs")
    patch = stored(run, patch_id)
    base = AgentPlanVersion.query.filter_by(run_id=run.run_id, version=1).one()
    historical = patches.apply_patch_draft(base.plan, patch["draft"])
    historical["nodes"][0]["inputs"]["prompt"] = "The exact archived prompt"
    db.session.add(AgentPlanVersion(run_id=run.run_id, version=2, parent_version=1, author="user",
        plan={**historical, "plan_version": 2}, story_package={}, check={}))
    state = deepcopy(run.snapshot)
    state["v3_patches"][patch_id].update(status="applied", approved_version=2)
    run.snapshot = state; db.session.commit()
    assert public_patches(run)[0]["diff_preview"][0]["after"]["prompt"] == "The exact archived prompt"


def test_missing_applied_version_never_falls_back_to_simulated_candidate(app_ctx):
    run, _registry, patch_id, _writer, _reviewer = prepared("director", "replace_node")
    state = deepcopy(run.snapshot)
    state["v3_patches"][patch_id].update(status="applied", approved_version=999)
    run.snapshot = state; db.session.commit()
    view = public_patches(run)[0]
    assert view["author_verified"] and view["final_author"] == "director"
    assert view["diff_preview"][0]["after"] is None and view["metadata_diff"] == []
