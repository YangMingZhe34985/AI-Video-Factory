"""Late candidate drift and nested-choice lineage remain execution barriers."""
from copy import deepcopy

import pytest

from app.extensions import db
from app.models import Artifact, ToolInvocation
from app.api import AppError
from app.plans import choices, execution, patch_execution, runtime
from app.plans.patches import quote_patch
from app.services.job_run_service import JobRunService
from app.services.storage_service import StorageService
from tests.test_v4_execution import drain_plan, image_node, setup, video_node
from tests.test_v5_patch_execution import reviewed_patch
from tests.test_v9_choices import attached_choice, choose, select_node

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)


def test_unselected_file_drift_after_selection_stops_delayed_paid_descendant(app_ctx, monkeypatch):
    run, _draft, registry, ids = attached_choice()
    nodes = [select_node([{"artifact": key} for key in ids]), image_node("review", gate="preview"),
        {**video_node(source="choice"), "depends_on": ["review"]}]
    run, version, registry = setup(nodes, run=run, deliverables=[{"kind": "video", "node_id": "clip", "output": "video"},
        {"kind": "image", "node_id": "review", "output": "image"}])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    runtime.advance(run, registry)
    choose(run, version, ids[0])
    assert runtime.advance(run, registry) == "awaiting_gate"
    task = runtime.latest_tasks(run)["choice"]
    assert execution.usable(run, task)
    unselected = Artifact.query.filter_by(artifact_id=ids[2]).one()
    StorageService.resolve(unselected.file_path).write_bytes(b"unselected-candidate-changed")
    assert not execution.usable(run, task)
    runtime.approve_gate(run, version.version, "review")
    assert runtime.advance(run, registry) == "attention"
    assert runtime.latest_tasks(run)["clip"].error["code"] == "PLAN_INPUT_CHANGED"
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == 0


def test_nested_choices_rebind_only_verified_unchanged_approval_chains(app_ctx, monkeypatch):
    run, _draft, registry, ids = attached_choice()
    first = select_node([{"artifact": ids[0]}, {"artifact": ids[1]}])
    second = select_node([{"ref": "choice.image"}, {"artifact": ids[2]}], name="final_choice")
    # Author order need not be topological, including during Patch activation.
    run, version, registry = setup([second, image_node("other"), first], run=run, deliverables=[
        {"kind": "image", "node_id": "final_choice", "output": "image"},
        {"kind": "image", "node_id": "other", "output": "image"}])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    runtime.advance(run, registry)
    assert "choice_pending" not in runtime.latest_tasks(run)["final_choice"].state
    choose(run, version, ids[1])
    runtime.advance(run, registry)
    proof = runtime.latest_tasks(run)["final_choice"].state["choice_pending"]
    runtime.approve_gate(run, version.version, "final_choice", selected_artifact_id=ids[1], choice_digest=proof["choice_digest"])
    assert drain_plan(run, registry) == "awaiting_result_review"
    record = reviewed_patch(run, "other")
    quote = quote_patch(run, record, registry=registry)["quote"]
    assert quote["can_apply"], quote
    assert {"choice", "final_choice"} <= set(quote["reused_node_ids"])
    next_version = patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", registry=registry)
    tasks = runtime.latest_tasks(run)
    for key in ("choice", "final_choice"):
        receipt = choices.receipt_for_task(run, tasks[key])
        assert receipt["plan_version"] == next_version.version and receipt["selected_artifact_id"] == ids[1]
        assert execution.usable(run, tasks[key])
    assert drain_plan(run, registry) == "awaiting_result_review"
    # Altering a historical user approval cannot manufacture current authority.
    snapshot = deepcopy(run.snapshot)
    snapshot["v3_execution_history"][str(version.version)]["choice_receipts"]["choice"]["selected_artifact_id"] = ids[0]
    run.snapshot = snapshot
    db.session.commit()
    assert not execution.usable(run, tasks["choice"])
    assert not execution.usable(run, tasks["final_choice"])


@pytest.mark.parametrize("field", ["inputs", "input_fingerprints"])
def test_changed_source_payload_cannot_hide_behind_unchanged_inputs_hash(app_ctx, monkeypatch, field):
    first, second = image_node("a"), image_node("b")
    second["inputs"]["prompt"] += " blue background"
    selector = select_node([{"ref": "a.image"}, {"ref": "b.image"}])
    run, version, registry = setup([first, second, selector], deliverables=[
        {"kind": "image", "node_id": "choice", "output": "image"}])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert runtime.advance(run, registry) == "awaiting_gate"
    tasks = runtime.latest_tasks(run)
    source, choice = tasks["a"], tasks["choice"]
    old_hash = source.inputs_hash
    proof = deepcopy(choice.state["choice_pending"])
    if field == "inputs":
        source.inputs = {**source.inputs, "prompt": "An altered stored request"}
    else:
        source.state = {**source.state, "input_fingerprints": {"changed": {"sha256": "changed"}}}
    db.session.commit()
    assert source.inputs_hash == old_hash
    with pytest.raises(AppError) as refused:
        runtime.approve_gate(run, version.version, "choice", selected_artifact_id=source.output["image"],
                            choice_digest=proof["choice_digest"])
    assert refused.value.code == "CHOICE_CHANGED"
    assert "choice_receipts" not in run.snapshot["v3_execution"] and choice.status == "pending"
