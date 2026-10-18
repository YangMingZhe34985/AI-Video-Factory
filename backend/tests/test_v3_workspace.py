"""Workspace scope, immutable versions and crash-safe write receipts."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from PIL import Image
import pytest
from werkzeug.datastructures import FileStorage

from app.agent.attachments import upload_attachment
from app.agents.schemas import MAX_PAYLOAD_BYTES, RequirementBrief, validate_payload
from app.agents.workspace import read_workspace, resolve_workspace_ref, write_workspace
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentRun, AgentWorkspaceItem, Artifact, ToolInvocation
from app.tools.spec import ToolContext
from app.utils.ids import new_id


def make_context(*, owner="owner", ids=(), role="producer", text="生成一张猫的图片，使用 wan3 系列"):
    run = AgentRun(owner_id=owner, request_key=new_id("req"), request={
        "schema_version": 3, "text": text, "attachment_ids": list(ids), "budget_limit": 100})
    db.session.add(run)
    db.session.flush()
    delegation = AgentDelegation(run_id=run.run_id, agent=role, task=text, request_key="root", credits_limit=20)
    db.session.add(delegation)
    db.session.commit()
    ctx = ToolContext(role=role, caller_agent=role, delegation_id=delegation.id,
                      budget_scope=run.run_id, budget_limit=100, idempotency_key=new_id("write"))
    return run, delegation, ctx


def next_context(ctx):
    return ToolContext(role=ctx.role, caller_agent=ctx.caller_agent, delegation_id=ctx.delegation_id,
        budget_scope=ctx.budget_scope, budget_limit=100, idempotency_key=new_id("write"))


def image_attachment(owner="owner"):
    data = BytesIO()
    Image.new("RGB", (256, 256), "blue").save(data, "PNG")
    data.seek(0)
    value = upload_attachment(FileStorage(stream=data, filename="cat.png", content_type="image/png"), owner)
    return Artifact.query.filter_by(artifact_id=value["attachment_id"]).one()


def brief(**kwargs):
    return {"deliverable": "image", "summary": "猫的照片", "confidence": 0.9, **kwargs}


def plan():
    return {"title": "草稿", "goal": "猫的照片", "deliverables": [{"kind": "image", "node_id": "cat", "output": "image"}],
        "nodes": [{"id": "cat", "tool": "generate_image", "inputs": {"prompt": "cat"},
                   "origin": {"agent": "director", "skills": []}, "rationale": "单张图"}]}


def test_versioned_writes_are_append_only_and_refs_are_frozen(app_ctx):
    _run, _delegation, ctx = make_context()
    first = write_workspace("idea", "note", {"summary": "first"}, ctx)
    second = write_workspace("idea", "note", {"summary": "second"}, next_context(ctx))
    assert (first["version"], second["version"]) == (1, 2)
    assert read_workspace(ctx, key="idea")["items"][0]["payload"] == {"summary": "second"}
    assert resolve_workspace_ref(first["workspace_ref"], ctx)["payload"] == {"summary": "first"}
    listing = read_workspace(ctx)["items"]
    assert listing[0]["summary"] == "second" and "payload" not in listing[0]
    assert "request_key" not in second and "inputs_hash" not in second
    second["payload"]["summary"] = "mutated return"
    assert read_workspace(ctx, key="idea")["items"][0]["payload"]["summary"] == "second"


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_orm_cannot_overwrite_or_delete_workspace_history(app_ctx, operation):
    _run, _delegation, ctx = make_context()
    write_workspace("idea", "note", {"text": "original"}, ctx)
    row = AgentWorkspaceItem.query.one()
    if operation == "update":
        row.payload = {"text": "changed"}
    else:
        db.session.delete(row)
    with pytest.raises(ValueError):
        db.session.commit()
    db.session.rollback()
    assert AgentWorkspaceItem.query.one().payload == {"text": "original"}


def test_durable_write_replays_after_lost_tool_receipt(app_ctx):
    _run, _delegation, ctx = make_context()
    first = write_workspace("idea", "note", {"text": "saved before crash"}, ctx)
    db.session.remove()
    replay = write_workspace("idea", "note", {"text": "saved before crash"}, ctx)
    assert replay == first and AgentWorkspaceItem.query.count() == 1
    with pytest.raises(AppError, match="another input"):
        write_workspace("idea", "note", {"text": "changed after crash"}, ctx)
    assert AgentWorkspaceItem.query.count() == 1


@pytest.mark.parametrize("target", ["run", "delegation"])
def test_finished_work_can_replay_and_read_but_cannot_append(app_ctx, target):
    run, delegation, ctx = make_context()
    saved = write_workspace("idea", "note", {"text": "saved"}, ctx)
    if target == "run":
        run.status = "cancelled"
    else:
        delegation.status = "completed"
    db.session.commit()
    assert write_workspace("idea", "note", {"text": "saved"}, ctx) == saved
    assert read_workspace(ctx, key="idea")["items"][0] == saved
    with pytest.raises(AppError) as error:
        write_workspace("new", "note", {}, next_context(ctx))
    assert error.value.code == "AGENT_DELEGATION_FINISHED"
    assert AgentWorkspaceItem.query.count() == 1


def test_only_producer_can_author_requirement_brief(app_ctx):
    _run, _delegation, ctx = make_context(role="director")
    with pytest.raises(AppError) as error:
        write_workspace("brief", "brief", brief(), ctx)
    assert error.value.code == "TOOL_FORBIDDEN"


def test_write_key_cannot_cross_delegation_or_kind(app_ctx):
    run, _delegation, ctx = make_context()
    write_workspace("idea", "note", {}, ctx)
    other = AgentDelegation(run_id=run.run_id, agent="director", task="draft", request_key="child", credits_limit=5)
    db.session.add(other)
    db.session.commit()
    forged = ToolContext(role="director", caller_agent="director", delegation_id=other.id,
                         budget_scope=run.run_id, idempotency_key=ctx.idempotency_key)
    with pytest.raises(AppError) as error:
        write_workspace("idea", "note", {}, forged)
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(AppError) as error:
        write_workspace("idea", "clarification", {}, next_context(ctx))
    assert error.value.code == "WORKSPACE_KIND_CONFLICT"


@pytest.mark.parametrize("change", ["other_run", "role", "missing_agent", "boolean_id", "missing_key", "schema_v2"])
def test_workspace_rejects_forged_server_context(app_ctx, change):
    run, _delegation, ctx = make_context()
    if change == "other_run":
        ctx.budget_scope = make_context()[0].run_id
    elif change == "role":
        ctx.role = "director"
    elif change == "missing_agent":
        ctx.caller_agent = None
    elif change == "boolean_id":
        ctx.delegation_id = True
    elif change == "missing_key":
        ctx.idempotency_key = None
    else:
        run.request = {**run.request, "schema_version": 2}
        db.session.commit()
    with pytest.raises(AppError) as error:
        write_workspace("idea", "note", {}, ctx)
    assert error.value.code == "INVALID_AGENT_CONTEXT"
    assert AgentWorkspaceItem.query.count() == 0


def test_other_run_cannot_read_known_key_or_version(app_ctx):
    _run, _delegation, ctx = make_context()
    saved = write_workspace("secret", "note", {"text": "private"}, ctx)
    _other, _child, foreign = make_context()
    assert read_workspace(foreign) == {"items": []}
    with pytest.raises(AppError) as error:
        resolve_workspace_ref(saved["workspace_ref"], foreign)
    assert error.value.code == "WORKSPACE_ITEM_NOT_FOUND"


@pytest.mark.parametrize("ref", [{"key": "idea", "version": 0}, {"key": "idea", "version": True},
                                 {"key": "idea", "version": "1"}, {"key": "idea"},
                                 {"key": "idea", "version": 1, "run_id": "another"}])
def test_reference_requires_exact_typed_version(app_ctx, ref):
    _run, _delegation, ctx = make_context()
    with pytest.raises(AppError) as error:
        resolve_workspace_ref(ref, ctx)
    assert error.value.code == "INVALID_WORKSPACE_REFERENCE"


def test_finish_reference_requires_matching_kind(app_ctx):
    _run, _delegation, ctx = make_context()
    saved = write_workspace("idea", "note", {}, ctx)
    with pytest.raises(AppError) as error:
        resolve_workspace_ref(saved["workspace_ref"], ctx, expected_kind="story")
    assert error.value.code == "WORKSPACE_KIND_MISMATCH"


@pytest.mark.parametrize("value", [{"x": float("nan")}, {"x": float("inf")}, {"x": {1: "bad"}},
                                  {"x": (1, 2)}, {"x": object()}, []])
def test_reject_non_json_or_non_finite_payload_before_persistence(app_ctx, value):
    _run, _delegation, ctx = make_context()
    with pytest.raises(AppError) as error:
        write_workspace("idea", "note", value, ctx)
    assert error.value.code == "INVALID_WORKSPACE_PAYLOAD"
    assert AgentWorkspaceItem.query.count() == 0


def test_payload_bound_counts_utf8_bytes_and_rejects_deep_json(app_ctx):
    _run, _delegation, ctx = make_context()
    with pytest.raises(AppError) as error:
        write_workspace("idea", "note", {"text": "猫" * (MAX_PAYLOAD_BYTES // 2)}, ctx)
    assert error.value.code == "WORKSPACE_PAYLOAD_TOO_LARGE"
    deep = {}
    for _ in range(70):
        deep = {"nested": deep}
    with pytest.raises(AppError) as error:
        write_workspace("idea", "note", deep, ctx)
    assert error.value.code == "INVALID_WORKSPACE_PAYLOAD"


@pytest.mark.parametrize("kind,payload", [("brief", {}), ("story", {}), ("plan_draft", {}),
                                         ("patch", {}), ("unknown", {})])
def test_kind_validation_cannot_store_untyped_decisions(app_ctx, kind, payload):
    _run, _delegation, ctx = make_context()
    with pytest.raises(AppError):
        write_workspace("decision", kind, payload, ctx)
    assert AgentWorkspaceItem.query.count() == 0


def test_brief_has_no_fixed_recipe_and_is_never_execution_authority(app_ctx):
    run, _delegation, ctx = make_context()
    value = brief(intent_notes="修改单张图片无需委派", production_intent=False)
    saved = write_workspace("brief", "brief", value, ctx)
    assert "recipe_hint" not in saved["payload"]
    assert RequirementBrief.model_validate(saved["payload"]).deliverable == "image"
    assert run.request["text"] == "生成一张猫的图片，使用 wan3 系列"
    assert run.status == "queued" and run.snapshot == {}
    with pytest.raises(AppError):
        write_workspace("another", "brief", {**value, "recipe_hint": "image_create"}, next_context(ctx))


@pytest.mark.parametrize("extra", [{"target_duration_sec": 12}, {"production_intent": "yes"},
                                  {"constraints": {"model_preferences": ["invented-series"]}},
                                  {"constraints": {"model_exclusions": ["invented-series"]}}])
def test_brief_rejects_invalid_or_invented_constraints(app_ctx, extra):
    _run, _delegation, ctx = make_context()
    with pytest.raises(AppError):
        write_workspace("brief", "brief", brief(**extra), ctx)


def test_plan_draft_shape_does_not_compile_approve_or_execute(app_ctx):
    run, _delegation, ctx = make_context()
    saved = write_workspace("plan", "plan_draft", plan(), ctx)
    assert saved["kind"] == "plan_draft" and saved["payload"]["nodes"][0]["tool"] == "generate_image"
    assert run.status == "queued" and run.snapshot == {}
    for server_field in ("plan_version", "estimates", "experimental"):
        with pytest.raises(AppError):
            write_workspace("other", "plan_draft", {**plan(), server_field: 1}, next_context(ctx))
    assert AgentWorkspaceItem.query.count() == 1


@pytest.mark.parametrize("mutation", ["duplicate_node", "bad_id", "too_many", "bad_gate"])
def test_plan_draft_rejects_invalid_shape(mutation):
    raw = plan()
    if mutation == "duplicate_node":
        raw["nodes"] *= 2
    elif mutation == "bad_id":
        raw["nodes"][0]["id"] = "not a node"
    elif mutation == "too_many":
        raw["nodes"] = [{**raw["nodes"][0], "id": f"node_{i}"} for i in range(201)]
    else:
        raw["nodes"][0]["gate"] = "approved"
    with pytest.raises(AppError):
        validate_payload("plan_draft", raw)


def test_owned_uploaded_image_is_recorded_and_brief_covers_it(app_ctx):
    artifact = image_attachment()
    _run, _delegation, ctx = make_context(ids=[artifact.artifact_id])
    attachment = {"attachment_id": artifact.artifact_id, "kind": "image", "role": "identity_ref",
                  "description": "猫的照片", "reason": "保持外观"}
    saved = write_workspace("brief", "brief", brief(attachments=[attachment]), ctx)
    assert saved["artifact_ids"] == [artifact.artifact_id]
    with pytest.raises(AppError):
        write_workspace("missing", "brief", brief(), next_context(ctx))
    with pytest.raises(AppError):
        write_workspace("wrong", "brief", brief(attachments=[{**attachment, "kind": "video"}]), next_context(ctx))


@pytest.mark.parametrize("case", ["same_owner_unattached", "foreign_owner", "foreign_reference", "forged_id"])
def test_workspace_cannot_smuggle_foreign_artifacts(app_ctx, case):
    artifact = image_attachment("other" if case == "foreign_owner" else "owner")
    _run, _delegation, ctx = make_context(ids=[artifact.artifact_id] if case == "foreign_owner" else [])
    if case == "foreign_reference":
        artifact.artifact_type = "agent_reference_image"
        artifact.meta = {**artifact.meta, "reference": {"run_id": "another"}}
        db.session.commit()
    value = artifact.artifact_id if case != "forged_id" else "nonexistent"
    with pytest.raises(AppError):
        write_workspace("references", "note", {"nested": [{"image_artifact_id": value}]}, ctx)
    assert AgentWorkspaceItem.query.count() == 0


def test_owned_research_reference_is_accepted_only_by_its_run(app_ctx):
    artifact = image_attachment()
    run, _delegation, ctx = make_context()
    artifact.artifact_type = "agent_reference_image"
    artifact.meta = {**artifact.meta, "reference": {"run_id": run.run_id}}
    db.session.commit()
    saved = write_workspace("reference", "note", {"artifact_ids": [artifact.artifact_id]}, ctx)
    assert saved["artifact_ids"] == [artifact.artifact_id]


@pytest.mark.parametrize("case", ["valid", "forged_marker", "foreign_job", "file_missing"])
def test_generated_artifact_requires_real_matching_job_ledger(app_ctx, case):
    artifact = image_attachment()
    run, _delegation, ctx = make_context()
    job = artifact.job
    job.strategy = "skill:generate_image"
    artifact.artifact_type = "first_frame_image"
    original_scope = make_context()[0].run_id if case in {"forged_marker", "foreign_job"} else run.run_id
    ledger = ToolInvocation(tool_name="generate_image", caller_role="production", budget_scope=original_scope,
        idempotency_key=new_id("generated"), job=job, status="success")
    db.session.add(ledger)
    db.session.flush()
    job.config = {"skill": {"budget_scope": run.run_id if case == "forged_marker" else original_scope,
                            "invocation_id": ledger.invocation_id, "tool_name": "generate_image"}}
    if case == "file_missing":
        artifact.file_path = "missing.png"
    db.session.commit()
    if case == "valid":
        saved = write_workspace("generated", "note", {"artifact": artifact.artifact_id}, ctx)
        assert saved["artifact_ids"] == [artifact.artifact_id]
    else:
        with pytest.raises(AppError):
            write_workspace("generated", "note", {"artifact": artifact.artifact_id}, ctx)
        assert AgentWorkspaceItem.query.count() == 0


def receipt(run, name, inputs, output, status="success"):
    row = ToolInvocation(tool_name=name, budget_scope=run.run_id, caller_role="research",
        idempotency_key=new_id("receipt"), input_payload=inputs, output_payload=output, status=status)
    db.session.add(row)
    db.session.commit()
    return row


def dossier_source(kind="web"):
    return {"source_id": "source1", "kind": kind, "url": "https://example.org/cat", "title": "Agent title",
            "site": "example.org", "retrieved_at": "2026-10-18T00:00:00Z"}


def web_evidence(run, *, search_status="success", fetch_status="success"):
    search = receipt(run, "web_search", {"query": "cat"}, {"fetched_at": "2026-10-18T00:00:00Z", "results": [
        {"result_id": "source1", "rank": 1, "title": "Observed title", "url": "https://example.org/cat",
         "site": "example.org", "snippet": "unverified search excerpt"}]}, search_status)
    fetch = receipt(run, "fetch_page", {"run_id": run.run_id, "url": "https://example.org/cat"},
        {"url": "https://example.org/cat", "text": "Observed page body"}, fetch_status)
    return search, fetch


def web_dossier():
    return {"sources": [dossier_source()], "topics": [{"topic_id": "cats", "query": "cat", "summary": "资料",
        "key_facts": [{"fact": "页面讨论猫", "source_ids": ["source1"]}], "confidence": 0.8}]}


def test_research_uses_only_observed_sources_and_server_metadata(app_ctx):
    run, _delegation, ctx = make_context(role="research")
    web_evidence(run)
    saved = write_workspace("research", "research_dossier", web_dossier(), ctx)
    assert saved["payload"]["sources"][0]["title"] == "Observed title"
    assert saved["payload"]["stats"]["web_searches"] == 1
    assert saved["payload"]["stats"]["pages_fetched"] == 1
    assert write_workspace("research", "research_dossier", web_dossier(), ctx) == saved


@pytest.mark.parametrize("case", ["no_receipts", "foreign_run", "failed_search", "pending_fetch", "empty_fetch", "forged_url"])
def test_research_rejects_unobserved_or_unread_citations(app_ctx, case):
    run, _delegation, ctx = make_context(role="research")
    payload = web_dossier()
    evidence_run = make_context()[0] if case == "foreign_run" else run
    if case != "no_receipts":
        _search, fetch = web_evidence(evidence_run, search_status="failed" if case == "failed_search" else "success",
                                    fetch_status="pending" if case == "pending_fetch" else "success")
        if case == "empty_fetch":
            fetch.output_payload = {"url": "https://example.org/cat", "text": ""}
            db.session.commit()
    if case == "forged_url":
        payload["sources"][0]["url"] = "https://other.example/cat"
    with pytest.raises(AppError) as error:
        write_workspace("research", "research_dossier", payload, ctx)
    assert error.value.code == "INVALID_RESEARCH_DOSSIER"
    assert AgentWorkspaceItem.query.count() == 0


@pytest.mark.parametrize("case", ["valid", "missing_analysis", "wrong_entity", "different_download_url"])
def test_research_candidates_require_scoped_download_and_analysis(app_ctx, case):
    artifact = image_attachment()
    run, _delegation, ctx = make_context(role="research")
    artifact.artifact_type = "agent_reference_image"
    artifact.meta = {**artifact.meta, "reference": {"run_id": run.run_id}}
    db.session.commit()
    receipt(run, "image_search", {"query": "cat"}, {"fetched_at": "2026-10-18T00:00:00Z", "results": [
        {"result_id": "source1", "image_url": "https://example.org/cat.png", "source_page_url": "https://example.org/cat",
         "title": "Observed picture", "rank": 1}]})
    receipt(run, "download_reference", {"run_id": run.run_id, "entity": "other" if case == "wrong_entity" else "cat",
        "image_url": "https://other.example/cat.png" if case == "different_download_url" else "https://example.org/cat.png",
        "source_page_url": "https://example.org/cat"}, {"reference_id": artifact.artifact_id})
    if case != "missing_analysis":
        receipt(run, "analyze_images", {"artifact_ids": [artifact.artifact_id]}, {"images": [{
            "artifact_id": artifact.artifact_id, "analysis": {"subjects": [{"appearance": "blue cat"}], "style": "photo"}}]})
    payload = {"sources": [dossier_source("image")], "entities": [{"entity_id": "cat", "name": "cat", "description": "参考形象",
        "candidates": [{"candidate_id": "candidate1", "reference_id": artifact.artifact_id,
                        "source_id": "source1", "traits": ["invented"], "why": "参考图片"}]}]}
    if case == "valid":
        saved = write_workspace("research", "research_dossier", payload, ctx)
        assert saved["payload"]["entities"][0]["candidates"][0]["traits"] == ["blue cat", "photo"]
    else:
        with pytest.raises(AppError) as error:
            write_workspace("research", "research_dossier", payload, ctx)
        assert error.value.code == "INVALID_RESEARCH_DOSSIER"


def test_concurrent_writers_allocate_distinct_versions(app_ctx):
    _run, _delegation, ctx = make_context()
    contexts = [next_context(ctx) for _ in range(4)]
    def write(index):
        with app_ctx.app_context():
            return write_workspace("idea", "note", {"text": str(index)}, contexts[index])["version"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        versions = list(pool.map(write, range(4)))
    assert sorted(versions) == [1, 2, 3, 4]
    assert AgentWorkspaceItem.query.count() == 4
