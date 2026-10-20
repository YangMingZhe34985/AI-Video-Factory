"""Bounded draft appends, immutable receipts and authoritative final validation."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from threading import Barrier

import pytest
from pydantic import ValidationError

from app.agent.plan_versions import inputs_hash
from app.agents import runtime
from app.agents.cards import get_catalog
from app.agents.schemas import validate_payload
from app.agents.workspace import resolve_workspace_ref
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentPlanVersion, AgentRun, AgentWorkspaceItem, Job, ToolInvocation
from app.plans import tools
from app.tools.scripted_llm import ScriptedLLM
from app.tools.spec import ToolContext
from tests.test_v3_plan_compiler import make_run, node, plan
from tests.test_v3_plan_tools import context, invoke, registry, save


def draft_for(ids, present):
    return plan([node(item) for item in present],
                [{"kind": "image", "node_id": item, "output": "images"} for item in ids])


def append(run, ref, nodes, key, role="producer"):
    return invoke(registry(), "append_plan_nodes", {"plan_ref": ref, "nodes": nodes}, run, key, role)


def saved(run, ref):
    return resolve_workspace_ref(ref, context(run, "read"), expected_kind="plan_draft")["payload"]


def test_multiple_batches_keep_headers_old_versions_and_compact_hash_proofs(app_ctx):
    run = make_run()
    ref = save(run, draft_for(["image", "two", "three"], ["image"]))
    original = deepcopy(saved(run, ref))
    value = registry()
    check = invoke(value, "check_plan", {"plan_ref": ref}, run, "check-partial")
    assert check["issues"]
    assert not invoke(value, "submit_plan", {"plan_ref": ref}, run, "submit-partial")["submitted"]
    for index, node_id in enumerate(["two", "three"], start=2):
        data = {"plan_ref": ref, "nodes": [node(node_id)]}
        result = append(run, ref, data["nodes"], f"batch-{index}")
        assert set(result) == {"workspace_ref", "key", "version", "kind", "node_count", "input_hash", "payload_hash"}
        assert result["workspace_ref"] == {"key": "draft", "version": index}
        assert result["key"] == "draft" and result["version"] == index
        assert result["node_count"] == index and result["kind"] == "plan_draft"
        assert result["input_hash"] == inputs_hash(tools.AppendInput.model_validate(data).model_dump(mode="json"))
        assert result["payload_hash"] == inputs_hash(saved(run, result["workspace_ref"]))
        ref = result["workspace_ref"]
    final = saved(run, ref)
    assert {k: v for k, v in final.items() if k != "nodes"} == {k: v for k, v in original.items() if k != "nodes"}
    assert saved(run, {"key": "draft", "version": 1}) == original
    assert invoke(value, "check_plan", {"plan_ref": ref}, run, "check-final") == (
        invoke(value, "check_plan", {"plan": final}, run, "check-inline"))
    assert invoke(value, "submit_plan", {"plan_ref": ref}, run, "submit-final")["submitted"]
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 3
    assert AgentPlanVersion.query.count() == 1 and Job.query.count() == 0
    assert all(row.estimated_cost == 0 for row in ToolInvocation.query.all())


def test_check_exact_reference_is_read_only_and_old_shape_stays_compatible(app_ctx):
    run = make_run()
    draft = validate_payload("plan_draft", plan())
    ref = save(run, draft)
    before = (ToolInvocation.query.count(), AgentWorkspaceItem.query.count(), AgentPlanVersion.query.count())
    assert tools.CheckInput.model_validate({"plan": draft}).model_dump(mode="json") == {"plan": draft}
    assert tools.CheckInput.model_validate({"plan_ref": ref}).model_dump(mode="json") == {"plan_ref": ref}
    assert invoke(registry(), "check_plan", {"plan_ref": ref}, run, "check")["issues"] == []
    assert (ToolInvocation.query.count(), AgentWorkspaceItem.query.count(), AgentPlanVersion.query.count()) == before


@pytest.mark.parametrize("payload", [
    {}, {"plan": None}, {"plan_ref": None},
    {"plan": plan(), "plan_ref": {"key": "draft", "version": 1}},
    {"plan": plan(), "plan_ref": None}, {"plan": None, "plan_ref": {"key": "draft", "version": 1}},
])
def test_check_input_is_strictly_exclusive(payload):
    with pytest.raises(ValidationError):
        tools.CheckInput.model_validate(payload)


def test_check_function_schema_exposes_the_same_exclusive_non_null_inputs():
    function = registry().function_schemas(["check_plan"])[0]["function"]
    schema = function["parameters"]
    assert schema["oneOf"] == [
        {"required": ["plan"], "properties": {"plan": {"type": "object"}},
         "not": {"required": ["plan_ref"]}},
        {"required": ["plan_ref"], "properties": {"plan_ref": {"type": "object"}},
         "not": {"required": ["plan"]}},
    ]


@pytest.mark.parametrize("count", [0, 13])
def test_append_batch_size_is_bounded(count):
    with pytest.raises(ValidationError):
        tools.AppendInput.model_validate({"plan_ref": {"key": "draft", "version": 1},
                                         "nodes": [node(f"item_{i}") for i in range(count)]})


def test_full_twelve_node_batch_is_accepted(app_ctx):
    run = make_run()
    ids = ["image", *[f"extra_{index}" for index in range(12)]]
    ref = save(run, draft_for(ids, ["image"]))
    result = append(run, ref, [node(item) for item in ids[1:]], "twelve")
    assert result["node_count"] == 13
    assert invoke(registry(), "check_plan", {"plan_ref": result["workspace_ref"]}, run, "check")["issues"] == []


def test_forward_media_references_can_be_saved_before_later_batches(app_ctx):
    run = make_run()
    choice = node("choice", "select_image", {
        "candidate_artifact_ids": [{"ref": "a.image"}, {"ref": "b.image"}]}, gate="choice")
    initial = plan([choice], [{"kind": "image", "node_id": "choice", "output": "image"}])
    ref = save(run, initial)
    second = append(run, ref, [node("a")], "a")
    assert invoke(registry(), "check_plan", {"plan_ref": second["workspace_ref"]}, run, "partial")["issues"]
    third = append(run, second["workspace_ref"], [node("b")], "b")
    assert invoke(registry(), "check_plan", {"plan_ref": third["workspace_ref"]}, run, "complete")["issues"] == []


@pytest.mark.parametrize("mutation", ["duplicate", "over_200", "oversize", "foreign_artifact"])
def test_append_applies_full_structural_and_scope_guards(app_ctx, mutation):
    run = make_run()
    initial = [node(f"item_{i}") for i in range(200)] if mutation == "over_200" else [node()]
    draft = plan(initial, [{"kind": "image", "node_id": initial[0]["id"], "output": "images"}])
    ref = save(run, draft)
    added = node("image" if mutation == "duplicate" else "new")
    if mutation == "oversize":
        added["inputs"]["prompt"] = "x" * 270000
    elif mutation == "foreign_artifact":
        added["inputs"]["reference_artifact_ids"] = [{"artifact": "not-owned"}]
    with pytest.raises(AppError):
        append(run, ref, [added], "bad")
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 1
    assert not (run.snapshot or {}).get("v3_plan_tool_receipts", {}).get("bad")


@pytest.mark.parametrize("name", ["append_plan_nodes", "check_plan"])
def test_references_cannot_read_another_run_or_wrong_workspace_kind(app_ctx, name):
    source = make_run()
    foreign = save(source, plan(), key="only_in_source")
    run = make_run()
    for ref in (foreign, {"key": "brief", "version": 1}):
        args = {"plan_ref": ref}
        if name == "append_plan_nodes":
            args["nodes"] = [node("extra")]
        with pytest.raises(AppError):
            invoke(registry(), name, args, run, f"{name}-{ref['key']}")
    assert AgentWorkspaceItem.query.filter_by(run_id=run.run_id, kind="plan_draft").count() == 0


def test_stale_base_rejected_and_prior_receipt_replayed_before_latest_or_active_checks(app_ctx):
    run = make_run()
    ref = save(run, draft_for(["image", "two"], ["image"]))
    first = append(run, ref, [node("two")], "first")
    with pytest.raises(AppError) as exc:
        append(run, ref, [node("three")], "stale")
    assert exc.value.code == "PLAN_DRAFT_VERSION_CONFLICT"
    run.status = "success"
    delegation = AgentDelegation.query.filter_by(run_id=run.run_id, agent="producer").one()
    delegation.status = "completed"
    db.session.commit()
    data = tools.AppendInput(plan_ref=ref, nodes=[node("two")])
    assert tools.append_plan_nodes(data, context(run, "first")) == first
    assert tools.recover_receipt("append_plan_nodes", data.model_dump(mode="json"), context(run, "first")) == first
    with pytest.raises(AppError) as exc:
        tools.append_plan_nodes(tools.AppendInput(plan_ref=first["workspace_ref"], nodes=[node("three")]),
                                context(run, "later"))
    assert exc.value.code == "AGENT_NOT_ACTIVE"
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 2


def test_new_request_cannot_mutate_an_approved_plan_even_in_attention(app_ctx):
    run = make_run()
    ref = save(run, plan())
    run.status = "attention"
    run.snapshot = {**run.snapshot, "v3_execution": {"approved_version": 1}}
    db.session.commit()
    with pytest.raises(AppError) as exc:
        append(run, ref, [node("two")], "after-approval")
    assert exc.value.code == "PATCH_REQUIRED"


@pytest.mark.parametrize("role", ["research", "creative", "critic", "repair", "prompt_smith"])
def test_append_only_open_to_producer_and_director(app_ctx, role):
    run = make_run()
    ref = save(run, plan())
    assert "append_plan_nodes" not in get_catalog().cards[role].tools
    with pytest.raises(AppError) as exc:
        append(run, ref, [node("two")], "not-authorized", role)
    assert exc.value.code == "TOOL_FORBIDDEN"


def test_director_append_preserves_actual_author_and_conflicting_keys_reject(app_ctx):
    run = make_run()
    ref = save(run, draft_for(["image", "two"], ["image"]))
    output = append(run, ref, [node("two")], "director-batch", "director")
    item = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key="draft", version=2).one()
    assert item.author_agent == "director"
    changed = {"plan_ref": ref, "nodes": [node("other")]}
    with pytest.raises(AppError) as exc:
        tools.recover_receipt("append_plan_nodes", changed, context(run, "director-batch", "director"))
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(AppError):
        tools.recover_receipt("append_plan_nodes", {"plan_ref": ref, "nodes": [node("two")]},
                              context(run, "director-batch", "producer"))
    assert output["version"] == 2


def test_workspace_version_and_append_receipt_rollback_together(app_ctx, monkeypatch):
    run = make_run()
    ref = save(run, plan())
    ctx = context(run, "rollback")
    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit fault")))
    with pytest.raises(RuntimeError, match="commit fault"):
        tools.append_plan_nodes(tools.AppendInput(plan_ref=ref, nodes=[node("two")]), ctx)
    monkeypatch.undo()
    db.session.refresh(run)
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 1
    assert not (run.snapshot or {}).get("v3_plan_tool_receipts")


@pytest.mark.parametrize("recover_with", ["local", "startup"])
def test_commit_gap_heals_without_reexecuting_append(app_ctx, monkeypatch, recover_with):
    run = make_run()
    ref = save(run, draft_for(["image", "two"], ["image"]))
    value = registry()
    ctx = context(run, "crash")
    data = {"plan_ref": ref, "nodes": [node("two")]}
    original = value._run_handler

    class WorkerCrash(BaseException):
        pass

    def crash(spec, parsed, call_ctx):
        result = original(spec, parsed, call_ctx)
        if spec.name == "append_plan_nodes":
            raise WorkerCrash()
        return result

    monkeypatch.setattr(value, "_run_handler", crash)
    with pytest.raises(WorkerCrash):
        value.invoke("append_plan_nodes", data, ctx)
    db.session.remove()
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).one()
    if recover_with == "startup":
        run.status = "cancelled"
        db.session.commit()
        monkeypatch.setattr(runtime, "agent_chat", lambda *_a, **_kw: pytest.fail("No LLM needed for recovery"))
        runtime.advance(run)
    else:
        runtime._recover_local_receipt("append_plan_nodes", data, ctx, value)
    ledger = ToolInvocation.query.filter_by(idempotency_key="crash").one()
    assert ledger.status == "success" and ledger.output_payload["version"] == 2
    assert value.invoke("append_plan_nodes", data, ctx)["replayed"]
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 2
    assert ToolInvocation.query.filter_by(tool_name="agent_llm_turn").count() == 0


def test_two_independent_sessions_same_base_have_one_winner(app_ctx):
    run = make_run()
    ref = save(run, plan())
    ctx = context(run, "seed")
    run_id, delegation_id = run.run_id, ctx.delegation_id
    barrier = Barrier(2)
    db.session.remove()

    def worker(number):
        with app_ctx.app_context():
            try:
                local_ctx = ToolContext(role="producer", caller_agent="producer", delegation_id=delegation_id,
                    budget_scope=run_id, budget_limit=1000, idempotency_key=f"concurrent-{number}")
                barrier.wait(timeout=10)
                output = tools.append_plan_nodes(tools.AppendInput(plan_ref=ref, nodes=[node(f"extra_{number}")]), local_ctx)
                return "success", output
            except AppError as error:
                return error.code, None
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, [1, 2]))
    assert sorted(result[0] for result in results) == ["PLAN_DRAFT_VERSION_CONFLICT", "success"]
    items = AgentWorkspaceItem.query.filter_by(run_id=run_id, kind="plan_draft").order_by(AgentWorkspaceItem.version).all()
    assert len(items) == 2 and [len(item.payload["nodes"]) for item in items] == [1, 2]
    run = AgentRun.query.filter_by(run_id=run_id).one()
    assert len(run.snapshot["v3_plan_tool_receipts"]) == 1


def test_successful_append_counts_as_runtime_progress(app_ctx):
    run = make_run()
    ref = save(run, draft_for(["image", "two"], ["image"]))
    root = AgentDelegation.query.filter_by(run_id=run.run_id, agent="producer").one()
    root.state = {"messages": [{"role": "user", "content": "Continue the stored draft."}], "no_progress": 4}
    db.session.commit()
    llm = ScriptedLLM({"producer": [{"tool_calls": [{"id": "append", "name": "append_plan_nodes",
                      "arguments": {"plan_ref": ref, "nodes": [node("two")]}}]}]})
    app_ctx.extensions["agent_v3_scripted_llm"] = llm
    runtime._round(root.id, 0, registry())
    db.session.refresh(root)
    assert root.steps == 1 and root.state["no_progress"] == 0
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 2
    assert Job.query.count() == 0


def test_long_plan_policy_no_longer_forces_one_full_output(app_ctx):
    from app.agents.skill_library import get_skill_library
    catalog = get_catalog()
    assert "一次写出**完整** PlanDraft" not in catalog.prompts["director"]
    bodies = [catalog.prompts[role] for role in ("producer", "director")]
    bodies += [get_skill_library().load_skill(name)["body"] for name in ("plan-review", "long-form-video")]
    for body in bodies:
        assert "story-video" in body and "append_plan_nodes" in body
        assert "characters" in body and "目标时长" in body
        assert "不能修改" in body and "max_tokens" in body
    registry_value = registry()
    for role in ("producer", "director"):
        assert "append_plan_nodes" in catalog.cards[role].tools
    assert registry_value.get("append_plan_nodes").allowed_roles == frozenset({"producer", "director"})
    assert registry_value.get("append_plan_nodes").permission == "write"
