"""Reviewed Patch approval is atomic, bounded and limited to quoted work."""
from copy import deepcopy
import json
import zipfile

import pytest

from app.agent import plan_versions as versions
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentPlanVersion, AgentWorkspaceItem, ApiTask, Artifact, ModelRegistry, PlanNodeTask, ToolInvocation
from app.plans import patch_execution, policy, runtime
from app.plans.patches import normalize_patch, patch_digest, quote_patch
from app.plans.patch_intent import save_assessment
from app.services.job_run_service import JobRunService
from app.services.storage_service import StorageService
from app.tools.budget import BudgetGuard
from app.utils.ids import new_id
from tests.test_v4_execution import delivery_nodes, drain_plan, image_node, setup, video_node

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)


def reviewed_patch(run, node_id="image", *, prompt="A happy orange cat wearing a blue hat", scope="only", automatic=False):
    version = versions.current_version(run)
    task = runtime.latest_tasks(run)[node_id]
    patch_id = new_id("patch")
    draft = normalize_patch({"base_version": version.version, "reason": "Improve the selected scene",
        "evidence_refs": [{"task_id": task.id}], "scope": scope,
        "ops": [{"op": "update_inputs", "node_id": node_id, "inputs": {"prompt": prompt}}]})
    director = AgentDelegation(run_id=run.run_id, agent="director", task="Review the proposed patch",
        request_key=new_id("review"), credits_limit=1, status="completed")
    db.session.add(director)
    db.session.flush()
    item = AgentWorkspaceItem(run_id=run.run_id, key=patch_id, version=1, kind="patch", payload=draft,
        author_agent="director", delegation_id=director.id, request_key=new_id("write"), inputs_hash=patch_digest(draft))
    db.session.add(item)
    record = {"patch_id": patch_id, "draft": draft, "proposed_by": "director", "status": "reviewed",
        "return_status": run.status, "review_delegation_id": director.id,
        "trigger": {"kind": "failure" if automatic else "user_revision", "node_ids": [node_id], "task_ids": [task.id]},
        "director_review": {"delegation_id": director.id, "verdict": "approve", "base_version": version.version,
            "reason": "Controlled Mock fixture preserves the requested content", "intent_preserved": True, "changed_elements": [],
            "draft_hash": patch_digest(draft), "request_key": director.request_key,
            "review_ref": {"key": item.key, "version": 1}}}
    review = record["director_review"]
    review["assessment_ref"] = save_assessment(run, director, patch_id, review)
    run.snapshot = {**run.snapshot, "v3_patches": {**run.snapshot.get("v3_patches", {}), patch_id: record}}
    db.session.commit()
    return record


def quoted(run, record, registry, *, scope=None):
    bundle = quote_patch(run, record, scope=scope, registry=registry)
    assert bundle["quote"]["can_apply"], bundle["quote"]
    return bundle["quote"]


def failed_plan(nodes=None, *, repair_budget=10, deliverables=None):
    run, version, registry = setup(nodes, deliverables=deliverables)
    runtime.begin(run, version, repair_budget_credits=repair_budget, registry=registry)
    mark_failed(run, "image")
    return run, version, registry


def mark_failed(run, node_id):
    task = runtime.latest_tasks(run)[node_id]
    task.status, task.error = "failed", {"category": "invalid_parameters", "code": "INVALID_INPUT",
        "summary": "Provider rejected invalid motion", "stage": "submit", "submission_state": "not_submitted",
        "recovery_action": "replan"}
    run.status = "attention"
    db.session.commit()
    return task


def test_patch_approval_and_replay_create_one_version_and_one_repair_claim(app_ctx, monkeypatch):
    run, first, registry = failed_plan()
    record = reviewed_patch(run, automatic=True)
    quote = quoted(run, record, registry)
    assert quote["automatic"]["eligible"]
    original = patch_execution.activate_patch_locked
    def crash_after_staging(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt("worker lost after staging the new version and tasks")
    with monkeypatch.context() as patch:
        patch.setattr(patch_execution, "activate_patch_locked", crash_after_staging)
        with pytest.raises(KeyboardInterrupt):
            patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
    assert AgentPlanVersion.query.count() == PlanNodeTask.query.count() == 1
    assert "v3_repair" not in run.snapshot and run.snapshot["v3_patches"][record["patch_id"]]["status"] == "reviewed"
    version = patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
    repeated = patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
    assert repeated.id == version.id and version.parent_version == first.version
    assert AgentPlanVersion.query.count() == PlanNodeTask.query.count() == 2
    assert len(run.snapshot["v3_repair"]["repair_claims"]) == 1
    assert BudgetGuard.spent(run.run_id) == 0 and ToolInvocation.query.count() == 0
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    assert drain_plan(run, registry) == "awaiting_result_review"
    assert ApiTask.query.count() == 1 and runtime.latest_tasks(run)["image"].attempt == 2


def test_only_retains_original_clip_lineage_and_rebuilds_delivery(app_ctx, monkeypatch):
    run, first, registry = setup(delivery_nodes(), deliverables=[{"kind": "package", "node_id": "package", "output": "artifact_id"}])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, first, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    original = runtime.latest_tasks(run)
    original_clip, original_input = original["clip"].output["video"], deepcopy(original["clip"].inputs)
    original_task = original["clip"].id
    last_package = original["package"].output["artifact_id"]
    for prompt in ("A happy orange cat with a blue hat", "A happy orange cat with a green hat"):
        record = reviewed_patch(run, prompt=prompt)
        quote = quoted(run, record, registry)
        assert "clip" in quote["kept_node_ids"]
        assert {"joined", "qc", "package"} <= set(quote["execute_node_ids"])
        version = patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", registry=registry)
        tasks = runtime.latest_tasks(run)
        assert tasks["clip"].output["video"] == original_clip and tasks["clip"].inputs == original_input
        assert tasks["clip"].state["source_task_id"] == original_task
        assert tasks["clip"].state["source_plan_version"] == first.version
        assert drain_plan(run, registry) == "awaiting_result_review"
        package_id = tasks["package"].output["artifact_id"]
        assert package_id != last_package
        last_package = package_id
        artifact = Artifact.query.filter_by(artifact_id=package_id).one()
        with zipfile.ZipFile(StorageService.resolve(artifact.file_path)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        assert manifest["plan_version"] == version.version
        assert manifest["retained_sources"][0]["source_plan_version"] == first.version
    assert ApiTask.query.count() == 4


def test_cascade_forces_control_descendant_despite_identical_input_hash(app_ctx, monkeypatch):
    first, descendant, other = image_node(), image_node("dependent"), image_node("other")
    descendant["depends_on"] = ["image"]
    other["inputs"]["prompt"] = "An unrelated landscape"
    run, version, registry = setup([first, descendant, other], deliverables=[
        {"kind": "image", "node_id": "image", "output": "image"},
        {"kind": "image", "node_id": "dependent", "output": "image"},
        {"kind": "image", "node_id": "other", "output": "image"},
    ])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    before = runtime.latest_tasks(run)
    prior = {key: deepcopy(task.output) for key, task in before.items()}
    record = reviewed_patch(run, scope="cascade")
    quote = quoted(run, record, registry)
    patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "cascade", registry=registry)
    tasks = runtime.latest_tasks(run)
    assert tasks["dependent"].state["force_execute"] and tasks["other"].status == "success"
    assert drain_plan(run, registry) == "awaiting_result_review"
    assert tasks["dependent"].inputs_hash == before["dependent"].inputs_hash
    assert tasks["dependent"].output != prior["dependent"]
    assert tasks["other"].output == prior["other"] and tasks["other"].estimated_cost == 0
    assert ApiTask.query.count() == 4


def test_automatic_repair_allowance_and_node_count_survive_versions(app_ctx):
    run, _version, registry = failed_plan(repair_budget=20)
    for index in range(2):
        record = reviewed_patch(run, automatic=True, prompt=f"A safely framed cat, take {index}")
        quote = quoted(run, record, registry)
        assert quote["automatic"]["eligible"]
        patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
        mark_failed(run, "image")
    state = deepcopy(run.snapshot["v3_repair"])
    assert state["budget_limit"] == 20 and len(state["repair_claims"]) == 2
    record = reviewed_patch(run, automatic=True, prompt="A third safe take")
    quote = quoted(run, record, registry)
    assert not quote["automatic"]["eligible"] and "AUTO_REPAIR_LIMIT" in quote["automatic"]["reasons"]
    with pytest.raises(AppError) as error:
        patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
    assert error.value.code == "PATCH_APPROVAL_REQUIRED"
    assert run.snapshot["v3_repair"] == state and AgentPlanVersion.query.count() == 3
    patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", registry=registry)
    assert run.snapshot["v3_repair"]["budget_limit"] == 20
    assert sum(item["automatic"] for item in run.snapshot["v3_repair"]["repair_claims"].values()) == 2


def test_unrelated_failed_node_is_carried_without_implicit_resubmission(app_ctx, monkeypatch):
    run, _version, registry = failed_plan([image_node(), image_node("unrelated")],
        deliverables=[
            {"kind": "image", "node_id": "image", "output": "image"},
            {"kind": "image", "node_id": "unrelated", "output": "image"},
        ])
    original = mark_failed(run, "unrelated")
    record = reviewed_patch(run, automatic=True)
    quote = quoted(run, record, registry)
    patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
    preserved = runtime.latest_tasks(run)["unrelated"]
    assert preserved.status == "failed" and preserved.error == original.error
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    assert drain_plan(run, registry) == "attention" and ApiTask.query.count() == 1
    assert runtime.latest_tasks(run)["image"].status == "success"


@pytest.mark.parametrize("change", ["scope", "price", "unknown", "running"])
def test_patch_activation_rejects_stale_or_unsafe_quote_without_mutations(app_ctx, change):
    run, version, registry = failed_plan()
    record = reviewed_patch(run)
    quote = quoted(run, record, registry)
    scope = "only"
    if change == "scope":
        scope = "cascade"
    elif change == "price":
        model = ModelRegistry.query.filter_by(model_id="wan2.6-image").one()
        capabilities = deepcopy(model.capabilities)
        capabilities["pricing"]["credits_per_unit"] *= 2
        model.capabilities = capabilities
    else:
        task = runtime.latest_tasks(run)["image"]
        if change == "unknown":
            task.error = {**task.error, "category": "submit_unknown", "submission_state": "unknown"}
        else:
            task.status = "running"
    db.session.commit()
    with pytest.raises(AppError) as error:
        patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], scope, registry=registry)
    assert error.value.code == {"scope": "PATCH_QUOTE_CHANGED", "price": "PATCH_QUOTE_CHANGED",
        "unknown": "RECOVERY_REQUIRED", "running": "PLAN_EXECUTION_ACTIVE"}[change]
    assert versions.current_version(run).id == version.id and PlanNodeTask.query.count() == 1
    assert "v3_repair" not in run.snapshot and ToolInvocation.query.count() == 0


def test_rejection_keeps_original_tasks_outputs_and_budget(app_ctx, monkeypatch):
    run, version, registry = setup()
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, repair_budget_credits=5, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    task = runtime.latest_tasks(run)["image"]
    output, spent = deepcopy(task.output), BudgetGuard.spent(run.run_id)
    record = reviewed_patch(run)
    quote = quoted(run, record, registry)
    for _ in range(2):
        assert patch_execution.reject_patch(run, record["patch_id"], quote["quote_id"], "only", registry=registry) == "awaiting_result_review"
    assert task.output == output and task.status == "success" and BudgetGuard.spent(run.run_id) == spent
    assert AgentPlanVersion.query.count() == PlanNodeTask.query.count() == 1
    with pytest.raises(AppError) as error:
        patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", registry=registry)
    assert error.value.code == "PATCH_REJECTED"


def test_repair_pool_is_shared_across_nodes_and_failed_claims_remain_reserved(app_ctx):
    run, version, registry = setup([image_node(), image_node("other")],
        deliverables=[
            {"kind": "image", "node_id": "image", "output": "image"},
            {"kind": "image", "node_id": "other", "output": "image"},
        ])
    cost = version.check["estimates"]["nodes"][0]["estimated_cost"]
    runtime.begin(run, version, repair_budget_credits=cost * 1.5, registry=registry)
    mark_failed(run, "image")
    mark_failed(run, "other")
    first = reviewed_patch(run, automatic=True)
    quote = quoted(run, first, registry)
    patch_execution.approve_patch(run, first["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
    mark_failed(run, "image")
    second = reviewed_patch(run, "other", automatic=True)
    quote = quoted(run, second, registry)
    assert quote["automatic"]["remaining_credits"] == pytest.approx(cost * .5)
    assert not quote["automatic"]["eligible"] and "REPAIR_BUDGET_EXCEEDED" in quote["automatic"]["reasons"]
    with pytest.raises(AppError) as error:
        patch_execution.approve_patch(run, second["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
    assert error.value.code == "PATCH_APPROVAL_REQUIRED"
    assert len(run.snapshot["v3_repair"]["repair_claims"]) == 1 and BudgetGuard.spent(run.run_id) == 0


def test_automatic_image_repair_does_not_reserve_original_pending_video_twice(app_ctx):
    run, version, registry = setup([image_node(), video_node()], deliverables=[
        {"kind": "video", "node_id": "clip", "output": "video"},
    ])
    image_cost = version.check["estimates"]["nodes"][0]["estimated_cost"]
    runtime.begin(run, version, repair_budget_credits=image_cost, registry=registry)
    mark_failed(run, "image")
    record = reviewed_patch(run, automatic=True)
    quote = quoted(run, record, registry)
    assert quote["automatic"]["eligible"]
    assert quote["estimated_credits"]["repair"] == image_cost
    assert quote["continuation_node_ids"] == ["clip"] and quote["estimated_credits"]["continuation"] > 0
    patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
    claim = run.snapshot["v3_repair"]["repair_claims"][record["patch_id"]]
    assert claim["credits"] == image_cost and runtime.latest_tasks(run)["clip"].status == "pending"


def test_patch_preserves_only_unchanged_approved_preview_gates(app_ctx, monkeypatch):
    other = image_node("other")
    other["inputs"]["prompt"] = "An unrelated landscape"
    run, version, registry = setup([image_node(gate="preview"), other],
        deliverables=[
            {"kind": "image", "node_id": "image", "output": "image"},
            {"kind": "image", "node_id": "other", "output": "image"},
        ])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "awaiting_gate"
    runtime.approve_gate(run, version.version, "image")
    assert drain_plan(run, registry) == "awaiting_result_review"
    first = reviewed_patch(run, "other")
    quote = quoted(run, first, registry)
    patch_execution.approve_patch(run, first["patch_id"], quote["quote_id"], "only", registry=registry)
    assert run.snapshot["v3_execution"]["approved_gates"] == ["image"]
    assert drain_plan(run, registry) == "awaiting_result_review"
    second = reviewed_patch(run, "image")
    quote = quoted(run, second, registry)
    patch_execution.approve_patch(run, second["patch_id"], quote["quote_id"], "only", registry=registry)
    assert run.snapshot["v3_execution"]["approved_gates"] == []
    assert drain_plan(run, registry) == "awaiting_gate"
    assert ApiTask.query.count() == 4


def test_approved_patch_uses_shared_mq_and_replay_cannot_resubmit(app_ctx):
    app_ctx.config.update(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True)
    run, _version, registry = failed_plan()
    record = reviewed_patch(run, automatic=True)
    quote = quoted(run, record, registry)
    version = patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
    assert ApiTask.query.count() == 0
    assert drain_plan(run, registry, mq=True) == "awaiting_result_review"
    provider_id, spent = ApiTask.query.one().provider_task_id, BudgetGuard.spent(run.run_id)
    replayed = patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", automatic=True, registry=registry)
    assert replayed.id == version.id and runtime.advance(run, registry) == "awaiting_result_review"
    assert ApiTask.query.count() == 1 and ApiTask.query.one().provider_task_id == provider_id
    assert BudgetGuard.spent(run.run_id) == spent


def test_pending_generation_receipt_blocks_patch_before_failure_classification(app_ctx):
    run, version, registry = failed_plan()
    record = reviewed_patch(run)
    quote = quoted(run, record, registry)
    task = runtime.latest_tasks(run)["image"]
    receipt = ToolInvocation(tool_name="generate_image", idempotency_key=policy.invocation_key(task), caller_role="production",
        budget_scope=run.run_id, status="pending", input_payload={}, estimated_cost=task.estimated_cost)
    db.session.add(receipt)
    db.session.flush()
    task.invocation_id = receipt.invocation_id
    db.session.commit()
    with pytest.raises(AppError) as error:
        patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", registry=registry)
    assert error.value.code == "RECOVERY_REQUIRED"
    assert AgentPlanVersion.query.count() == PlanNodeTask.query.count() == 1 and ApiTask.query.count() == 0


def test_rejected_worker_replay_restores_original_state_without_reverting_later_patch(app_ctx):
    run, _version, registry = failed_plan()
    first = reviewed_patch(run)
    quote = quoted(run, first, registry)
    assert patch_execution.reject_patch(run, first["patch_id"], quote["quote_id"], "only", registry=registry) == "attention"
    run.status = "understanding"
    db.session.commit()
    assert patch_execution.reject_patch(run, first["patch_id"], quote["quote_id"], "only", registry=registry) == "attention"
    second = reviewed_patch(run, prompt="A different safe scene")
    newer_quote = quoted(run, second, registry)
    patch_execution.approve_patch(run, second["patch_id"], newer_quote["quote_id"], "only", registry=registry)
    assert patch_execution.reject_patch(run, first["patch_id"], quote["quote_id"], "only", registry=registry) == "executing"
    assert versions.current_version(run).version == 2


@pytest.mark.parametrize("blocked", ["superseded", "cancelled"])
def test_approval_cannot_revive_cancelled_or_superseded_work(app_ctx, blocked):
    run, _version, registry = failed_plan()
    record = reviewed_patch(run)
    quote = quoted(run, record, registry)
    if blocked == "superseded":
        snapshot = deepcopy(run.snapshot)
        snapshot["v3_patches"][record["patch_id"]].update(status="invalid", superseded=True)
        run.snapshot = snapshot
    else:
        run.status = "cancelled"
    db.session.commit()
    with pytest.raises(AppError) as error:
        patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", registry=registry)
    assert error.value.code == {"superseded": "PATCH_SUPERSEDED", "cancelled": "INVALID_AGENT_STATE"}[blocked]
    assert AgentPlanVersion.query.count() == 1 and ToolInvocation.query.count() == 0


def test_source_replacement_between_requote_and_staging_cannot_become_approved(app_ctx, monkeypatch):
    from app.agents.workspace import write_workspace
    from tests.test_v3_workspace import brief, image_attachment, make_context
    source = image_attachment()
    run, _root, ctx = make_context(ids=[source.artifact_id], text="修复这张猫的照片")
    write_workspace("brief", "brief", brief(attachments=[{"attachment_id": source.artifact_id,
        "kind": "image", "role": "identity_ref", "description": "A cat", "reason": "Preserve identity"}]), ctx)
    node = image_node()
    node.update(model_id="wan2.7-image")
    node["inputs"].update(mode="i2i", reference_artifact_ids=[{"artifact": source.artifact_id}])
    run, version, registry = setup([node], run=run)
    runtime.begin(run, version, registry=registry)
    mark_failed(run, "image")
    record = reviewed_patch(run)
    quote = quoted(run, record, registry)
    original = patch_execution.activate_patch_locked
    def changed_before_authorization(*args, **kwargs):
        StorageService.resolve(source.file_path).write_bytes(b"replacement after quotation")
        return original(*args, **kwargs)
    monkeypatch.setattr(patch_execution, "activate_patch_locked", changed_before_authorization)
    with pytest.raises(AppError) as error:
        patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", registry=registry)
    assert error.value.code == "PATCH_QUOTE_CHANGED"
    assert AgentPlanVersion.query.count() == PlanNodeTask.query.count() == 1 and ToolInvocation.query.count() == 0
