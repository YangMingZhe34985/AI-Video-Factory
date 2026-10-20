"""Patch decisions and read-only quotes, using isolated SQLite and Mock jobs."""

from copy import deepcopy

import pytest

from app.agent import plan_versions as versions
from app.agents.schemas import validate_payload
from app.agents.workspace import write_workspace
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentPlanVersion, AgentWorkspaceItem, Artifact, Job, ModelRegistry, PlanNodeTask, ToolInvocation
from app.plans import execution, patches, runtime
from app.plans.patch_schemas import PatchDraft
from app.plans.patch_intent import save_assessment
from tests.patch_provenance_fixtures import add_proposal_evidence
from app.services.job_run_service import JobRunService
from app.services.storage_service import StorageService
from app.tools.spec import ToolContext
from tests.test_v4_execution import drain_plan, image_node, setup, video_node

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)


def draft(node_id="image", *, scope="only", evidence=()):
    return {"base_version": 1, "reason": "修订该节点", "evidence_refs": list(evidence), "scope": scope,
            "ops": [{"op": "update_inputs", "node_id": node_id, "inputs": {"prompt": "A calm orange cat"}}]}


def reviewed(run, payload, *, trigger=None, patch_id="patch-test"):
    director = AgentDelegation(run_id=run.run_id, agent="director", task="Review patch", request_key=patch_id, credits_limit=2)
    db.session.add(director)
    db.session.commit()
    value = patches.normalize_patch(payload)
    ctx = ToolContext(role="director", caller_agent="director", delegation_id=director.id,
        budget_scope=run.run_id, idempotency_key=patch_id + ":review")
    ref = write_workspace("patch." + patch_id, "patch", value, ctx)["workspace_ref"]
    record = {"patch_id": patch_id, "draft": value, "review_delegation_id": director.id, "status": "reviewed",
        "trigger": trigger or {"kind": "user_revision", "node_ids": [], "task_ids": []},
        "director_review": {"verdict": "approve", "reason": "局部修订", "delegation_id": director.id,
            "review_ref": ref, "draft_hash": patches.patch_digest(value), "request_key": ctx.idempotency_key, "base_version": 1,
            "intent_preserved": True, "changed_elements": []}}
    review = record["director_review"]
    review["assessment_ref"] = save_assessment(run, director, patch_id, review)
    db.session.commit()
    return add_proposal_evidence(run, record, author="director")


def failed(run, node_id="image", category="invalid_parameters", code="INVALID_INPUT"):
    task = runtime.latest_tasks(run)[node_id]
    task.status, task.error = "failed", {"category": category, "code": code, "submission_state": "not_submitted"}
    run.status = "attention"
    db.session.commit()
    return task


def failed_case(*, nodes=None, allowance=20, deliverables=None):
    run, version, registry = setup(nodes, deliverables=deliverables)
    runtime.begin(run, version, repair_budget_credits=allowance, registry=registry)
    task = failed(run)
    record = reviewed(run, draft(evidence=[{"task_id": task.id}]),
        trigger={"kind": "failure", "node_ids": ["image"], "task_ids": [task.id]})
    return run, version, registry, task, record


def completed(monkeypatch, nodes=None, deliverables=None):
    run, version, registry = setup(nodes, deliverables=deliverables)
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, repair_budget_credits=20, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    return run, version, registry


@pytest.mark.parametrize("extra", [{"patch_id": "forged"}, {"proposed_by": "director"}, {"director_review": {}}, {"quote": {}}])
def test_patch_schema_rejects_authority_fields(app_ctx, extra):
    with pytest.raises(AppError):
        validate_payload("patch", {**draft(), **extra})


def test_patch_schema_requires_typed_evidence_and_unique_targets(app_ctx):
    assert validate_payload("patch", draft())["scope"] == "only"
    for evidence in [["task1"], [{"task_id": 1, "artifact_id": "a"}], [{"task_id": True}]]:
        with pytest.raises(AppError):
            patches.normalize_patch(draft(evidence=evidence))
    value = draft()
    value["ops"].append(deepcopy(value["ops"][0]))
    with pytest.raises(AppError):
        patches.normalize_patch(value)


def test_apply_is_shallow_independent_and_before_is_only_a_control_edge(app_ctx):
    run, version, _registry = setup([image_node(), image_node("other")],
        deliverables=[
            {"kind": "image", "node_id": "image", "output": "image"},
            {"kind": "image", "node_id": "other", "output": "image"},
        ])
    original = deepcopy(version.plan)
    value = draft()
    value["ops"].append({"op": "insert_node", "node": image_node("inserted"), "before": "other"})
    candidate = patches.apply_patch_draft(version.plan, value)
    assert version.plan == original
    by_id = {node["id"]: node for node in candidate["nodes"]}
    assert by_id["image"]["inputs"]["prompt"] == "A calm orange cat"
    assert by_id["other"]["depends_on"] == ["inserted"]
    assert by_id["other"]["inputs"] == original["nodes"][1]["inputs"]
    value["ops"] = [{"op": "replace_node", "node_id": "image", "node": image_node("wrong")}]
    with pytest.raises(AppError):
        patches.apply_patch_draft(version.plan, value)


def test_invalid_removal_stays_editable_with_compiler_issues(app_ctx):
    run, version, registry = setup([image_node(), image_node("other")],
        deliverables=[
            {"kind": "image", "node_id": "image", "output": "image"},
            {"kind": "image", "node_id": "other", "output": "image"},
        ])
    runtime.begin(run, version, registry=registry)
    value = draft()
    value["ops"] = [{"op": "remove_node", "node_id": "image"}]
    bundle = patches.quote_patch(run, reviewed(run, value), registry=registry)
    assert not bundle["quote"]["can_apply"]
    assert "INVALID_DELIVERABLE" in {issue["code"] for issue in bundle["quote"]["issues"]}
    assert AgentPlanVersion.query.count() == 1


@pytest.mark.parametrize("case", ["director", "author", "hash", "base", "assignment", "payload"])
def test_review_evidence_is_verified_not_claimed(app_ctx, case):
    run, _version, registry, _task, record = failed_case()
    if case == "director":
        db.session.get(AgentDelegation, record["review_delegation_id"]).agent = "repair"
    elif case == "author":
        AgentWorkspaceItem.query.filter_by(run_id=run.run_id,
            key=record["director_review"]["review_ref"]["key"], kind="patch").one().author_agent = "repair"
    elif case == "hash":
        record["director_review"]["draft_hash"] = "0" * 64
    elif case == "base":
        record["director_review"]["base_version"] = 2
    elif case == "assignment":
        record["review_delegation_id"] += 100
    else:
        record["draft"]["ops"][0]["inputs"]["prompt"] = "unreviewed"
        record["director_review"]["draft_hash"] = patches.patch_digest(record["draft"])
    # Workspace rows are immutable; author mutation above is deliberately dirty
    # test data visible only in this no-autoflush quote call.
    with pytest.raises(AppError) as error:
        patches.quote_patch(run, record, registry=registry)
    assert error.value.code == "PATCH_REVIEW_REQUIRED"
    db.session.rollback()


def test_foreign_task_and_workspace_evidence_are_rejected(app_ctx):
    run, _version, registry, _task, _record = failed_case()
    other, other_version, other_registry = setup()
    runtime.begin(other, other_version, registry=other_registry)
    foreign = runtime.latest_tasks(other)["image"]
    with pytest.raises(AppError) as error:
        record = reviewed(run, draft(evidence=[{"task_id": foreign.id}]), patch_id="foreign")
        patches.quote_patch(run, record, registry=registry)
    assert error.value.code == "INVALID_PATCH_EVIDENCE"


def test_quote_has_zero_writes_and_reports_incremental_continuation(app_ctx, monkeypatch):
    run, version, registry, task, record = failed_case(nodes=[image_node(), image_node("later")],
        deliverables=[
            {"kind": "image", "node_id": "image", "output": "image"},
            {"kind": "image", "node_id": "later", "output": "image"},
        ])
    before = (Job.query.count(), ToolInvocation.query.count(), AgentPlanVersion.query.count(), PlanNodeTask.query.count())
    monkeypatch.setattr(db.session, "commit", lambda: pytest.fail("Quote cannot commit"))
    monkeypatch.setattr(db.session, "flush", lambda *_a, **_kw: pytest.fail("Quote cannot flush"))
    monkeypatch.setattr(registry, "invoke", lambda *_a, **_kw: pytest.fail("Quote cannot invoke tools"))
    bundle = patches.quote_patch(run, record, registry=registry)
    quote = bundle["quote"]
    assert quote["can_apply"] and quote["automatic"]["eligible"]
    assert quote["continuation_node_ids"] == ["later"]
    assert quote["estimated_credits"] == {"repair": 2, "continuation": 2, "total": 4}
    monkeypatch.undo()
    assert (Job.query.count(), ToolInvocation.query.count(), AgentPlanVersion.query.count(), PlanNodeTask.query.count()) == before
    assert run.snapshot["v3_execution"]["approved_version"] == version.version


def test_only_retains_completed_generation_but_cascade_forces_it(app_ctx, monkeypatch):
    run, version, registry = completed(monkeypatch, [image_node(), video_node()], [{"kind": "video", "node_id": "clip", "output": "video"}])
    record = reviewed(run, draft())
    only = patches.quote_patch(run, record, scope="only", registry=registry)
    cascade = patches.quote_patch(run, record, scope="cascade", registry=registry)
    assert only["quote"]["can_apply"] and cascade["quote"]["can_apply"]
    assert only["decisions"]["nodes"]["clip"]["action"] == "retain"
    assert only["quote"]["kept_node_ids"] == ["clip"] and only["quote"]["warnings"]
    assert cascade["decisions"]["nodes"]["clip"]["force_rerun"]
    assert cascade["quote"]["estimated_credits"]["total"] > only["quote"]["estimated_credits"]["total"]
    assert only["quote"]["quote_id"] != cascade["quote"]["quote_id"]
    assert not only["quote"]["automatic"]["eligible"]
    source = runtime.latest_tasks(run)["clip"]
    assert only["decisions"]["sources"]["clip"] == patches.source_proof(source)
    unrelated_failure = deepcopy(record)
    unrelated_failure["trigger"] = {"kind": "failure", "node_ids": ["unrelated"], "task_ids": []}
    assert not patches.quote_patch(run, unrelated_failure, registry=registry)["quote"]["can_apply"]


def test_unsubmitted_dependent_video_uses_continuation_not_repair_allowance(app_ctx):
    run, _version, registry, _task, record = failed_case(nodes=[image_node(), video_node()], allowance=2,
        deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    quote = patches.quote_patch(run, record, registry=registry)["quote"]
    assert quote["can_apply"] and quote["automatic"]["eligible"]
    assert quote["estimated_credits"]["repair"] == 2
    assert quote["continuation_node_ids"] == ["clip"] and quote["estimated_credits"]["continuation"] > 2


def test_automatic_can_use_its_reserved_pool_but_manual_must_preserve_it(app_ctx):
    run, _version, registry, _task, record = failed_case(allowance=2)
    run.request = {**run.request, "budget_limit": 2}
    db.session.commit()
    quote = patches.quote_patch(run, record, registry=registry)["quote"]
    assert quote["can_apply"] and quote["automatic"]["eligible"]
    assert not quote["manual_can_apply"]
    assert quote["warnings"][0]["code"] == "MANUAL_BUDGET_RESERVED"
    run.request = {**run.request, "budget_limit": 1}
    db.session.commit()
    quote = patches.quote_patch(run, record, registry=registry)["quote"]
    assert not quote["can_apply"] and not quote["automatic"]["eligible"]
    assert "TOTAL_BUDGET_EXCEEDED" in quote["automatic"]["reasons"]


def test_unapproved_plan_cannot_enter_patch_approval_path(app_ctx):
    run, _version, registry = setup()
    with pytest.raises(AppError) as error:
        patches.quote_patch(run, reviewed(run, draft()), registry=registry)
    assert error.value.code == "PATCH_BASE_NOT_APPROVED"


def test_unrelated_success_is_free_but_failure_is_preserved(app_ctx, monkeypatch):
    run, _version, registry = completed(monkeypatch, [image_node(), image_node("kept"), image_node("broken")],
        [
            {"kind": "image", "node_id": "image", "output": "image"},
            {"kind": "image", "node_id": "kept", "output": "image"},
            {"kind": "image", "node_id": "broken", "output": "image"},
        ])
    failed(run, "image")
    other = failed(run, "broken", "permanent")
    record = reviewed(run, draft())
    bundle = patches.quote_patch(run, record, registry=registry)
    assert bundle["quote"]["can_apply"]
    assert bundle["decisions"]["nodes"]["kept"]["action"] == "reuse"
    assert bundle["decisions"]["nodes"]["broken"]["action"] == "preserve_failure"
    assert bundle["decisions"]["sources"]["broken"]["task_id"] == other.id
    assert bundle["quote"]["estimated_credits"]["total"] == 2


def test_only_rebuilds_all_delivery_from_selected_new_and_retained_media(app_ctx, monkeypatch):
    nodes = [image_node(), video_node(),
        {"id": "master", "tool": "compose_video", "inputs": {"video_artifact_ids": [{"ref": "clip.video"}]}, "rationale": "compose"},
        {"id": "qc", "tool": "qc_video", "inputs": {"artifact_id": {"ref": "master.artifact_id"},
            "video_artifact_ids": [{"ref": "clip.video"}]}, "rationale": "inspect"},
        {"id": "package", "tool": "package_story", "inputs": {"artifact_id": {"ref": "master.artifact_id"}},
            "depends_on": ["qc"], "rationale": "deliver"}]
    run, _version, registry = completed(monkeypatch, nodes, [{"kind": "package", "node_id": "package", "output": "artifact_id"}])
    record = reviewed(run, draft(), trigger={"kind": "user_revision", "node_ids": ["image"], "task_ids": []})
    bundle = patches.quote_patch(run, record, registry=registry)
    assert bundle["quote"]["can_apply"]
    assert bundle["quote"]["kept_node_ids"] == ["clip"]
    for node_id in ("master", "qc", "package"):
        decision = bundle["decisions"]["nodes"][node_id]
        assert decision["action"] == "execute" and decision["force_rerun"] and decision["estimated_cost"] == 0


def test_removed_reference_cannot_hide_its_old_descendant_impact(app_ctx):
    run, version, registry = setup([image_node(), video_node()], deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    runtime.begin(run, version, registry=registry)
    payload = draft()
    payload["ops"] = [{"op": "remove_node", "node_id": "image"}]
    quote = patches.quote_patch(run, reviewed(run, payload), registry=registry)["quote"]
    assert not quote["can_apply"] and quote["removed_node_ids"] == ["image"]
    assert quote["affected_node_ids"] == ["clip", "image"]


def test_reused_output_mapping_must_match_its_frozen_artifact_fingerprints(app_ctx, monkeypatch):
    run, _version, registry = completed(monkeypatch, [image_node(), image_node("kept")],
        [
            {"kind": "image", "node_id": "image", "output": "image"},
            {"kind": "image", "node_id": "kept", "output": "image"},
        ])
    failed(run)
    other = runtime.latest_tasks(run)["kept"]
    other.output = {"image": "forged", "images": ["forged"]}
    db.session.commit()
    quote = patches.quote_patch(run, reviewed(run, draft()), registry=registry)["quote"]
    assert not quote["can_apply"]
    assert "PATCH_SOURCE_UNAVAILABLE" in {issue["code"] for issue in quote["issues"]}


def test_later_patch_preserves_previously_approved_historical_outputs(app_ctx, monkeypatch):
    from app.plans.patch_execution import approve_patch
    from tests.test_v5_patch_execution import reviewed_patch
    run, _version, registry = completed(monkeypatch, [image_node(), video_node(), image_node("other")],
        [{"kind": "video", "node_id": "clip", "output": "video"},
         {"kind": "image", "node_id": "other", "output": "image"}])
    first = reviewed_patch(run)
    quote = patches.quote_patch(run, first, registry=registry)["quote"]
    approve_patch(run, first["patch_id"], quote["quote_id"], "only", registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    second = reviewed_patch(run, node_id="other")
    bundle = patches.quote_patch(run, second, registry=registry)
    assert bundle["quote"]["can_apply"]
    assert bundle["decisions"]["nodes"]["clip"]["action"] == "reuse"
    # A mutable flag alone cannot replace the original user's only approval.
    snapshot = deepcopy(run.snapshot)
    snapshot["v3_patches"][first["patch_id"]]["quote"]["kept_node_ids"] = []
    run.snapshot = snapshot
    db.session.commit()
    invalid = patches.quote_patch(run, second, registry=registry)["quote"]
    assert not invalid["can_apply"]
    assert "PATCH_SOURCE_CHANGED" in {issue["code"] for issue in invalid["issues"]}


@pytest.mark.parametrize("category,code", [("submit_unknown", "UNKNOWN"), ("permanent", "UNAUTHORIZED"),
    ("invalid_parameters", "MODEL_PRICE_CHANGED"), ("invalid_parameters", "PLAN_INPUT_CHANGED")])
def test_nonrepairable_failures_never_receive_automatic_authority(app_ctx, category, code):
    run, _version, registry, task, record = failed_case()
    task.error = {"category": category, "code": code, "submission_state": "unknown" if category == "submit_unknown" else "not_submitted"}
    db.session.commit()
    quote = patches.quote_patch(run, record, registry=registry)["quote"]
    assert not quote["automatic"]["eligible"]
    if category == "submit_unknown":
        assert not quote["can_apply"]


def test_auto_repair_pool_and_attempt_limit_survive_versions(app_ctx):
    run, _version, registry, _task, record = failed_case()
    run.snapshot = {**run.snapshot, "v3_repair": {"budget_limit": 5, "repair_claims": {
        "one": {"credits": 2, "automatic": True, "node_ids": ["image"]},
        "two": {"credits": 2, "automatic": True, "node_ids": ["image"]},
        "manual": {"credits": 100, "automatic": False, "node_ids": ["image"]}}}}
    db.session.commit()
    quote = patches.quote_patch(run, record, registry=registry)["quote"]
    assert quote["automatic"]["remaining_credits"] == 1
    assert set(quote["automatic"]["reasons"]) >= {"AUTO_REPAIR_LIMIT", "REPAIR_BUDGET_EXCEEDED"}


def test_quote_id_changes_on_price_task_or_output_changes(app_ctx, monkeypatch):
    run, _version, registry = completed(monkeypatch, [image_node(), image_node("kept")],
        [
            {"kind": "image", "node_id": "image", "output": "image"},
            {"kind": "image", "node_id": "kept", "output": "image"},
        ])
    failed(run)
    record = reviewed(run, draft())
    first = patches.quote_patch(run, record, registry=registry)["quote"]
    model = ModelRegistry.query.filter_by(model_id="wan2.6-image").one()
    model.capabilities = {**model.capabilities, "pricing": {"unit": "image", "credits_per_unit": 3}}
    db.session.commit()
    second = patches.quote_patch(run, record, registry=registry)["quote"]
    assert first["quote_id"] != second["quote_id"]
    artifact = Artifact.query.filter_by(artifact_id=runtime.latest_tasks(run)["kept"].output["image"]).one()
    StorageService.resolve(artifact.file_path).write_bytes(b"tampered")
    third = patches.quote_patch(run, record, registry=registry)["quote"]
    assert not third["can_apply"] and third["quote_id"] != second["quote_id"]


def test_quote_rejects_stale_version_and_changed_model_parameters_need_approval(app_ctx):
    run, version, registry, _task, record = failed_case()
    value = draft()
    value["ops"] = [{"op": "replace_node", "node_id": "image", "node": {**image_node(), "params": {"n": 2}}}]
    changed = reviewed(run, value, patch_id="changed")
    assert not patches.quote_patch(run, changed, registry=registry)["quote"]["automatic"]["eligible"]
    versions.create_version(run, version.plan, {}, version.check, author="system", base_version=1)
    with pytest.raises(AppError):
        patches.quote_patch(run, record, registry=registry)
