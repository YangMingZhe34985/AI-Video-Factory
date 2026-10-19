"""Image choices require explicit, current user authority across replay and Patch."""
from copy import deepcopy

import pytest

from app.agent import plan_versions as versions
from app.agents.api import RuntimeAction, admit_action
from app.agents.workspace import write_workspace
from app.api import AppError
from app.extensions import db
from app.models import AgentWorkspaceItem, ApiTask, Artifact, Job, ToolInvocation
from app.plans import choices, execution, patch_execution, policy, runtime
from app.plans.compiler import compile_plan
from app.plans.dry_run import dry_run
from app.plans.patches import patch_digest, quote_patch
from app.plans.views import public_plan
from app.services.job_run_service import JobRunService
from app.services.storage_service import StorageService
from app.tools import build_default_registry, build_v3_registry
from app.tools.budget import BudgetGuard
from app.tools.spec import ToolContext
from app.utils.ids import new_id
from tests.test_v3_plan_compiler import codes, node, plan
from tests.test_v3_workspace import brief, image_attachment, make_context
from tests.test_v4_execution import drain_plan, image_node, setup, video_node
from tests.test_v5_patch_execution import reviewed_patch

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)


def select_node(candidates, name="choice"):
    return node(name, "select_image", {"candidate_artifact_ids": candidates}, gate="choice")


def attached_choice(*, extra=False, preview=False):
    ids = [image_attachment("local").artifact_id for _ in range(3)]
    run, _root, ctx = make_context(owner="local", ids=ids, text="从三张图中选择一张")
    write_workspace("brief", "brief", brief(attachments=[{"attachment_id": key, "kind": "image",
        "role": "content_ref", "description": "candidate", "reason": "user choice"} for key in ids]), ctx)
    nodes = [select_node([{"artifact": key} for key in ids])]
    outputs = [{"kind": "image", "node_id": "choice", "output": "image"}]
    if extra:
        nodes.append(image_node("other", gate="preview" if preview else None))
        outputs.append({"kind": "image", "node_id": "other", "output": "image"})
    run, version, registry = setup(nodes, run=run, deliverables=outputs)
    return run, version, registry, ids


def ready_choice(*, extra=False, preview=False):
    run, version, registry, ids = attached_choice(extra=extra, preview=preview)
    runtime.begin(run, version, registry=registry)
    runtime.advance(run, registry)
    assert run.status == "awaiting_gate"
    return run, version, registry, ids


def choose(run, version, selected):
    proof = runtime.latest_tasks(run)["choice"].state["choice_pending"]
    return runtime.approve_gate(run, version.version, "choice", selected_artifact_id=selected,
                                choice_digest=proof["choice_digest"])


def test_selector_private_zero_cost_and_authoring_cannot_choose(app_ctx):
    run, _version, registry, ids = attached_choice()
    assert "select_image" not in build_default_registry()._specs
    spec = registry.get("select_image")
    assert spec.plan_executable and not spec.agent_visible and spec.permission == "read" and not spec.uses_ledger
    assert spec.io_types == {"inputs": {"candidate_artifact_ids": "image[]"}, "outputs": {"image": "image"}}
    draft = plan([select_node([{"artifact": key} for key in ids])], [{"kind": "image", "node_id": "choice", "output": "image"}])
    compiled = compile_plan(draft, run, registry=registry)
    assert compiled["issues"] == [] and compiled["estimates"]["total_credits"] == 0
    simulated = dry_run(compiled, registry=registry)
    assert simulated["passed"] and simulated["outputs"]["choice"] == {"image": ids[-1]}
    assert simulated["simulated_choices"] == {"choice": ids[-1]}
    for field in (None, ids[0]):
        forged = deepcopy(draft)
        forged["nodes"][0]["inputs"]["selected_artifact_id"] = field
        assert "RESERVED_INPUT" in codes(compile_plan(forged, run, registry=registry))
    with pytest.raises(AppError):
        registry.invoke("select_image", {"candidate_artifact_ids": ids, "selected_artifact_id": ids[0]},
            ToolContext(role="production", approved=True, budget_scope=run.run_id))
    assert ToolInvocation.query.count() == ApiTask.query.count() == 0


@pytest.mark.parametrize("change", ["missing_gate", "wrong_gate", "other_tool", "one", "twentyone", "duplicate", "foreign", "nested"])
def test_choice_compiler_rejects_invalid_gate_or_candidate_shape(app_ctx, change):
    run, _version, registry, ids = attached_choice()
    choice = select_node([{"artifact": key} for key in ids])
    if change == "missing_gate":
        choice.pop("gate")
    elif change == "wrong_gate":
        choice["gate"] = "preview"
    elif change == "other_tool":
        choice = image_node("choice", gate="choice")
    elif change == "one":
        choice["inputs"]["candidate_artifact_ids"] = [{"artifact": ids[0]}]
    elif change == "twentyone":
        choice["inputs"]["candidate_artifact_ids"] = [{"artifact": ids[0]}] * 21
    elif change == "duplicate":
        choice["inputs"]["candidate_artifact_ids"] = [{"artifact": ids[0]}] * 2
    elif change == "foreign":
        choice["inputs"]["candidate_artifact_ids"][0] = {"artifact": image_attachment("foreign").artifact_id}
    else:
        choice["inputs"]["candidate_artifact_ids"] = [[{"artifact": key}] for key in ids]
    compiled = compile_plan(plan([choice], [{"kind": "image", "node_id": "choice", "output": "image"}]), run, registry=registry)
    assert compiled["issues"] and not dry_run(compiled, registry=registry)["passed"]


@pytest.mark.parametrize("array", [False, True])
def test_generated_candidates_pause_then_nonfirst_choice_drives_the_video(app_ctx, monkeypatch, array):
    if array:
        first = image_node("options")
        first["params"]["n"] = 3
        nodes = [first]
        refs = {"ref": "options.images"}
    else:
        nodes = [image_node(f"option_{i}") for i in range(3)]
        for i, item in enumerate(nodes):
            item["inputs"]["prompt"] += f" variant {i}"
        refs = [{"ref": f"option_{i}.image"} for i in range(3)]
    nodes.extend([select_node(refs), video_node(source="choice")])
    run, version, registry = setup(nodes, deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry, limit=2) == "awaiting_gate"
    tasks = runtime.latest_tasks(run)
    assert tasks["choice"].status == tasks["clip"].status == "pending"
    assert tasks["choice"].inputs == {} and not tasks["choice"].invocation_id
    assert not ToolInvocation.query.filter_by(tool_name="animate_shot").first()
    shown = next(item["choice"] for item in public_plan(run)["nodes"] if item["node_id"] == "choice")
    assert shown["ready"] and shown["selected_artifact_id"] is None and len(shown["candidates"]) == 3
    selected = shown["candidates"][2]["artifact_id"]
    spent = BudgetGuard.spent(run.run_id)
    choose(run, version, selected)
    assert BudgetGuard.spent(run.run_id) == spent
    assert drain_plan(run, registry) == "awaiting_result_review"
    assert tasks["choice"].output == {"image": selected}
    assert tasks["clip"].inputs["first_frame_artifact_id"] == selected
    assert tasks["choice"].inputs["selected_artifact_id"] == selected
    assert tasks["choice"].inputs_hash == versions.inputs_hash({"tool": "select_image", "inputs": tasks["choice"].inputs,
        "sources": tasks["choice"].state["input_fingerprints"]})
    assert ToolInvocation.query.filter_by(tool_name="select_image").count() == 0
    assert version.check["estimates"]["total_credits"] == sum(item.estimated_cost for item in tasks.values())


def test_choice_action_replay_conflict_and_worker_crash_do_not_choose_twice(app_ctx, monkeypatch):
    run, version, registry, ids = ready_choice()
    proof = runtime.latest_tasks(run)["choice"].state["choice_pending"]
    body = {"action": "approve_gate", "request_key": "choose", "plan_version": version.version,
        "gate_node_id": "choice", "selected_artifact_id": ids[1], "choice_digest": proof["choice_digest"]}
    admit_action(run, RuntimeAction.model_validate(body))
    original_command = deepcopy(run.command)
    admit_action(run, RuntimeAction.model_validate(body))
    assert run.command == original_command
    with pytest.raises(AppError) as conflict:
        admit_action(run, RuntimeAction.model_validate({**body, "selected_artifact_id": ids[0]}))
    assert conflict.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    choose(run, version, ids[1])
    # Crash after user receipt, before selector invocation: no default/rebilling.
    assert choose(run, version, ids[1]) == "executing"
    original_complete = execution.complete
    with monkeypatch.context() as patch:
        patch.setattr(execution, "complete", lambda *_a, **_kw: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            runtime.advance(run, registry)
    assert runtime.latest_tasks(run)["choice"].status == "pending"
    assert runtime.advance(run, registry) == "awaiting_result_review"
    assert runtime.latest_tasks(run)["choice"].output == {"image": ids[1]}
    assert ToolInvocation.query.count() == ApiTask.query.count() == 0
    with pytest.raises(AppError):
        choose(run, version, ids[0])
    assert original_complete is execution.complete


@pytest.mark.parametrize("change", ["digest", "noncandidate", "version", "bytes", "source_order"])
def test_stale_or_forged_choice_cannot_be_admitted(app_ctx, change):
    run, version, registry, ids = ready_choice()
    task = runtime.latest_tasks(run)["choice"]
    body = {"action": "approve_gate", "request_key": "bad", "plan_version": version.version,
        "gate_node_id": "choice", "selected_artifact_id": ids[1], "choice_digest": task.state["choice_pending"]["choice_digest"]}
    if change == "digest":
        body["choice_digest"] = "0" * 64
    elif change == "noncandidate":
        body["selected_artifact_id"] = image_attachment("local").artifact_id
    elif change == "version":
        body["plan_version"] += 1
    elif change == "bytes":
        artifact = Artifact.query.filter_by(artifact_id=ids[2]).one()
        StorageService.resolve(artifact.file_path).write_bytes(b"changed-unselected-candidate")
    else:
        task.state = {**task.state, "choice_pending": {**task.state["choice_pending"], "candidates": list(reversed(ids))}}
        db.session.commit()
    with pytest.raises(AppError):
        admit_action(run, RuntimeAction.model_validate(body))
    assert run.command is None and "choice_receipts" not in run.snapshot["v3_execution"]
    assert ToolInvocation.query.count() == ApiTask.query.count() == 0


def test_upstream_preview_blocks_choice_and_independent_work_continues(app_ctx, monkeypatch):
    image = image_node(gate="preview")
    other = image_node("other")
    other["inputs"]["prompt"] += " different pose"
    selector = select_node([{"ref": "image.image"}, {"ref": "other.image"}])
    run, version, registry = setup([image, selector, other], deliverables=[{"kind": "image", "node_id": "choice", "output": "image"}])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    runtime.advance(run, registry)
    tasks = runtime.latest_tasks(run)
    assert tasks["other"].status == "success" and "choice_pending" not in tasks["choice"].state
    assert not next(item["choice"] for item in public_plan(run)["nodes"] if item["node_id"] == "choice")["ready"]
    runtime.approve_gate(run, version.version, "image")
    runtime.advance(run, registry)
    assert tasks["choice"].state["choice_pending"] and run.status == "awaiting_gate"


def test_patch_reuses_unchanged_choice_with_new_version_proof(app_ctx, monkeypatch):
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    run, version, registry, ids = ready_choice(extra=True)
    choose(run, version, ids[2])
    assert drain_plan(run, registry) == "awaiting_result_review"
    before = runtime.latest_tasks(run)["choice"]
    record = reviewed_patch(run, "other")
    quoted = quote_patch(run, record, registry=registry)["quote"]
    assert quoted["can_apply"], quoted
    assert "choice" in quoted["reused_node_ids"]
    second = patch_execution.approve_patch(run, record["patch_id"], quoted["quote_id"], "only", registry=registry)
    task = runtime.latest_tasks(run)["choice"]
    receipt = choices.receipt_for_task(run, task)
    assert receipt["plan_version"] == second.version and receipt["task_id"] == task.id != before.id
    assert receipt["inherited_from"]["task_id"] == before.id and receipt["selected_artifact_id"] == ids[2]
    assert drain_plan(run, registry) == "awaiting_result_review"


def test_patch_candidate_reorder_requires_new_selection(app_ctx):
    run, version, registry, ids = ready_choice()
    choose(run, version, ids[0])
    runtime.advance(run, registry)
    record = deepcopy(reviewed_patch(run, "choice"))
    draft = deepcopy(record["draft"])
    draft["ops"] = [{"op": "update_inputs", "node_id": "choice", "inputs": {
        "candidate_artifact_ids": [{"artifact": key} for key in reversed(ids)]}}]
    record["draft"] = draft
    record["director_review"]["draft_hash"] = patch_digest(draft)
    workspace = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key=record["patch_id"]).one()
    updated = AgentWorkspaceItem(run_id=run.run_id, key=workspace.key, version=2, kind="patch", payload=draft,
        author_agent="director", delegation_id=workspace.delegation_id, request_key=new_id("write"), inputs_hash=patch_digest(draft))
    db.session.add(updated)
    record["director_review"]["review_ref"] = {"key": workspace.key, "version": 2}
    run.snapshot = {**run.snapshot, "v3_patches": {record["patch_id"]: record}}
    db.session.commit()
    quote = quote_patch(run, record, registry=registry)["quote"]
    assert quote["can_apply"] and "choice" in quote["execute_node_ids"]
    second = patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", registry=registry)
    assert "choice" not in run.snapshot["v3_execution"].get("choice_receipts", {})
    runtime.advance(run, registry)
    assert run.status == "awaiting_gate"
    assert runtime.latest_tasks(run)["choice"].state["choice_pending"]["candidates"] == list(reversed(ids))
    choose(run, second, ids[1])
    assert runtime.advance(run, registry) == "awaiting_result_review"


def test_pending_choice_accepts_revision_feedback_without_executing(app_ctx):
    from app.agents.repair_flow import revise_plan
    run, version, registry, _ids = ready_choice()
    data = RuntimeAction(action="revise_plan", request_key="feedback", plan_version=version.version,
        gate_node_id="choice", message="三个选项都不合适，请修改候选")
    admit_action(run, data)
    result = revise_plan(run, run.command)
    flow = run.snapshot["v3_repair_flows"][result["flow_id"]]
    assert flow["trigger"]["kind"] == "gate_feedback" and flow["trigger"]["node_ids"] == ["choice"]
    assert runtime.latest_tasks(run)["choice"].status == "pending" and ToolInvocation.query.count() == 0


@pytest.mark.parametrize("stale", [False, "bytes", "missing", "mime"])
def test_choice_api_worker_revalidates_after_admission_and_consumes_definitive_refusal(app_ctx, client, stale):
    from app.agents.runtime import advance
    from app.tools.scripted_llm import ScriptedLLM
    run, version, registry, ids = ready_choice()
    scripted = ScriptedLLM({})
    app_ctx.extensions["agent_v3_scripted_llm"] = scripted
    choice = next(item["choice"] for item in public_plan(run)["nodes"] if item["node_id"] == "choice")
    body = {"action": "approve_gate", "request_key": "http-choice", "plan_version": version.version,
        "gate_node_id": "choice", "selected_artifact_id": ids[2], "choice_digest": choice["choice_digest"]}
    response = client.post(f"/api/agent/runs/{run.run_id}/actions", json=body)
    assert response.status_code == 202, response.json
    if stale:
        artifact = Artifact.query.filter_by(artifact_id=ids[0]).one()
        if stale == "missing":
            StorageService.resolve(artifact.file_path).unlink()
        elif stale == "mime":
            artifact.mime_type = "video/mp4"
            db.session.commit()
        else:
            StorageService.resolve(artifact.file_path).write_bytes(b"changed-between-admission-and-worker")
    advance(run)
    assert run.command is None and scripted.calls == []
    if stale:
        assert run.status == "awaiting_gate" and run.error["code"] == "CHOICE_CHANGED"
        assert "choice_receipts" not in run.snapshot["v3_execution"]
    else:
        assert run.status == "awaiting_result_review"
        assert client.get(f"/api/agent/runs/{run.run_id}").json["data"]["results"][0]["artifact_id"] == ids[2]
    assert ToolInvocation.query.count() == ApiTask.query.count() == 0


def test_preview_rejects_choice_fields_and_registry_rejects_changed_selection(app_ctx, monkeypatch):
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    run, version, registry, ids = ready_choice(extra=True, preview=True)
    with pytest.raises(AppError) as wrong:
        admit_action(run, RuntimeAction(action="approve_gate", request_key="wrong-preview", plan_version=version.version,
            gate_node_id="other", selected_artifact_id=None))
    assert wrong.value.code == "INVALID_CHOICE"
    choose(run, version, ids[1])
    task = runtime.latest_tasks(run)["choice"]
    node = next(item for item in version.plan["nodes"] if item["id"] == "choice")
    data, sources, digest = execution.resolve_node(run, node, version.version, {}, registry)
    task.inputs, task.inputs_hash = data, digest
    task.state = {**task.state, "resolved": True, "input_fingerprints": sources}
    task.inputs = {**task.inputs, "selected_artifact_id": ids[0]}
    task.inputs_hash = versions.inputs_hash({"tool": "select_image", "inputs": task.inputs, "sources": sources})
    db.session.commit()
    ctx = ToolContext(role="production", approved=True, budget_scope=run.run_id,
        idempotency_key=policy.invocation_key(task), plan_node_task_id=task.id)
    with pytest.raises(AppError) as denied:
        registry.invoke("select_image", task.inputs, ctx)
    assert denied.value.code == "CHOICE_CHANGED" and task.status == "pending"


def test_redone_unselected_candidate_resets_choice_and_only_preserves_old_video_lineage(app_ctx, monkeypatch):
    nodes = [image_node("a"), image_node("b")]
    nodes[1]["inputs"]["prompt"] += " blue background"
    nodes.extend([select_node([{"ref": "a.image"}, {"ref": "b.image"}]), video_node(source="choice")])
    run, first, registry = setup(nodes, deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, first, registry=registry)
    runtime.advance(run, registry)
    initial = runtime.latest_tasks(run)
    choose(run, first, initial["a"].output["image"])
    assert drain_plan(run, registry) == "awaiting_result_review"
    old_input, old_video = deepcopy(initial["clip"].inputs), deepcopy(initial["clip"].output)
    record = reviewed_patch(run, "b", prompt="A cat beside a green river")
    quote = quote_patch(run, record, registry=registry)["quote"]
    assert quote["can_apply"] and "choice" in quote["execute_node_ids"] and "clip" in quote["kept_node_ids"]
    second = patch_execution.approve_patch(run, record["patch_id"], quote["quote_id"], "only", registry=registry)
    assert "choice_receipts" not in run.snapshot["v3_execution"]
    assert runtime.advance(run, registry) == "awaiting_gate"
    current = runtime.latest_tasks(run)
    assert current["clip"].inputs == old_input and current["clip"].output == old_video
    assert current["clip"].state["source_plan_version"] == first.version
    choose(run, second, current["b"].output["image"])
    assert runtime.advance(run, registry) == "awaiting_result_review"
    assert current["choice"].output["image"] != current["clip"].inputs["first_frame_artifact_id"]
    assert current["clip"].state["retained_by_only"]
