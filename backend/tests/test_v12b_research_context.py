"""Research run binding and actionable, evidence-free correction receipts."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest
from pydantic import ValidationError

from app.agent.recovery import invoke_once
from app.agent.research_guidance import dossier_guidance, research_needs_guidance
from app.agent.research_spec import ResearchDossier, validate_dossier
from app.agents.runtime import agent_error
from app.agents.schemas import RequirementBrief
from app.api import AppError
from app.extensions import db
from app.models import AgentWorkspaceItem, Artifact, ToolInvocation
from app.services.storage_service import StorageService
from app.tools import build_default_registry, build_v3_registry
from app.tools.spec import ToolContext
from tests.test_v3_workspace import make_context, next_context, web_dossier

TOOLS = ("fetch_page", "download_reference", "capture_reference_page")
PAGE = "https://reference.example/story"


def context(*, v3=True, role="research", owner="local", text=PAGE):
    run, delegation, ctx = make_context(owner=owner, role=role, text=text)
    run.request = {**run.request, "_v3_runtime": v3}
    db.session.commit()
    ctx.idempotency_key = None
    if not v3:
        ctx.caller_agent = ctx.delegation_id = None
        run.request = {**run.request, "schema_version": 2}
        db.session.commit()
    return run, delegation, ctx


def payload(registry, name, ctx):
    if name == "fetch_page":
        result = registry.invoke("web_search", {"query": "DeepSeek"}, ctx)["output"]
        return {"url": result["results"][0]["url"]}
    if name == "download_reference":
        result = registry.invoke("image_search", {"query": "DeepSeek"}, ctx)["output"]
        return {"image_url": result["results"][0]["image_url"], "entity": "DeepSeek"}
    return {"url": PAGE}


def artifact_for(name, result):
    key = "reference_id" if name == "download_reference" else "attachment_id"
    return Artifact.query.filter_by(artifact_id=result["output"][key]).one()


@pytest.mark.parametrize("name", TOOLS)
@pytest.mark.parametrize("v3", [True, False])
def test_registry_omitted_run_is_canonical_and_explicit_legacy_form_replays(app_ctx, name, v3):
    registry = build_v3_registry() if v3 else build_default_registry()
    role = "director" if name == "capture_reference_page" and not v3 else "research"
    run, _, ctx = context(v3=v3, role=role)
    data = payload(registry, name, ctx)
    result = registry.invoke(name, data, ctx)
    row = ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one()
    assert row.input_payload["run_id"] == run.run_id == row.budget_scope
    replay = registry.invoke(name, {**data, "run_id": run.run_id}, ctx)
    assert replay["replayed"] and replay["invocation_id"] == result["invocation_id"]
    assert registry.invoke(name, {**data, "run_id": None}, ctx)["invocation_id"] == result["invocation_id"]
    assert "run_id" not in data
    if name != "fetch_page":
        artifact = artifact_for(name, result)
        assert artifact.meta["reference"]["run_id"] == run.run_id
        assert artifact.job.config["agent_reference_run"] == run.run_id
        assert sha256(run.run_id.encode()).hexdigest()[:32] in str(StorageService.resolve(artifact.file_path))


@pytest.mark.parametrize("name", TOOLS)
def test_explicit_legacy_row_replays_through_v2_recovery_without_run_input(app_ctx, name):
    registry = build_default_registry()
    run, _, ctx = context(v3=False, role="director" if name == "capture_reference_page" else "research")
    data = payload(registry, name, ctx)
    ctx.idempotency_key = f"{run.run_id}:legacy-{name}"
    first = registry.invoke(name, {**data, "run_id": run.run_id}, ctx)
    row = ToolInvocation.query.filter_by(invocation_id=first["invocation_id"]).one()
    saved = deepcopy(row.input_payload)
    replay = invoke_once(registry, name, data, ctx)
    assert replay["invocation_id"] == first["invocation_id"] and replay["replayed"]
    assert row.input_payload == saved
    with pytest.raises(AppError) as denied:
        invoke_once(registry, name, {**data, "run_id": "forged"}, ctx)
    assert denied.value.code == "TOOL_FORBIDDEN"


@pytest.mark.parametrize("name", TOOLS)
def test_forged_explicit_run_is_rejected_before_new_receipt(app_ctx, name):
    registry = build_v3_registry()
    run, _, ctx = context()
    foreign, _, _ = context()
    data = payload(registry, name, ctx)
    before = ToolInvocation.query.count()
    for forged in (foreign.run_id, "invented-run"):
        with pytest.raises(AppError) as denied:
            registry.invoke(name, {**data, "run_id": forged}, ctx)
        assert denied.value.code == "TOOL_FORBIDDEN"
    assert ToolInvocation.query.count() == before
    assert not Artifact.query.count()


@pytest.mark.parametrize("name", TOOLS)
def test_no_current_run_never_binds_from_payload(app_ctx, name):
    registry = build_default_registry()
    role = "director" if name == "capture_reference_page" else "research"
    run, _, _ = context(v3=False, role=role)
    data = {"image_url": PAGE} if name == "download_reference" else {"url": PAGE}
    for scope in ("default", "missing"):
        with pytest.raises(AppError) as denied:
            registry.invoke(name, data, ToolContext(role=role, budget_scope=scope))
        assert denied.value.code == "AGENT_RUN_NOT_FOUND"
        with pytest.raises(AppError) as forged:
            registry.invoke(name, {**data, "run_id": run.run_id}, ToolContext(role=role, budget_scope=scope))
        assert forged.value.code == "TOOL_FORBIDDEN"
    assert not ToolInvocation.query.count()


@pytest.mark.parametrize("name", TOOLS)
def test_omission_preserves_request_owner_and_agent_delegation_checks(app_ctx, name):
    registry = build_v3_registry()
    run, delegation, ctx = context(owner="other")
    data = {"image_url": PAGE} if name == "download_reference" else {"url": PAGE}
    with app_ctx.test_request_context():
        with pytest.raises(AppError) as denied:
            registry.invoke(name, data, ctx)
        assert denied.value.code == "AGENT_RUN_NOT_FOUND"
    ctx.delegation_id = delegation.id + 10000
    with pytest.raises(AppError) as denied:
        registry.invoke(name, data, ctx)
    assert denied.value.code == "INVALID_AGENT_CONTEXT"
    assert not ToolInvocation.query.count()


@pytest.mark.parametrize("name", TOOLS)
def test_missing_run_does_not_expand_urls_or_roles(app_ctx, name):
    registry = build_default_registry()
    role = "director" if name == "capture_reference_page" else "research"
    run, _, ctx = context(v3=False, role=role, text="No supplied URL")
    data = {"image_url": PAGE} if name == "download_reference" else {"url": PAGE}
    with pytest.raises(AppError) as denied:
        registry.invoke(name, data, ctx)
    assert denied.value.code == "URL_NOT_ALLOWED"
    with pytest.raises(AppError) as forbidden:
        registry.invoke(name, data, ToolContext(role="production", budget_scope=run.run_id))
    assert forbidden.value.code == "TOOL_FORBIDDEN"
    assert not Artifact.query.count()


@pytest.mark.parametrize("name", TOOLS)
def test_model_schemas_match_optional_compatibility_field_and_reject_empty_or_wrong_type(name):
    registry = build_v3_registry()
    params = registry.function_schemas([name])[0]["function"]["parameters"]
    assert params == registry.get(name).input_model.model_json_schema()
    assert "run_id" not in params.get("required", []) and params["properties"]["run_id"]["default"] is None
    data = {"image_url": PAGE} if name == "download_reference" else {"url": PAGE}
    for invalid in ("", 123, {}, [], False):
        with pytest.raises(ValidationError):
            registry.get(name).input_model.model_validate({**data, "run_id": invalid})


def test_capture_omitted_run_replay_still_rejects_changed_snapshot(app_ctx):
    registry = build_v3_registry()
    run, _, ctx = context()
    data = {"url": PAGE}
    first = registry.invoke("capture_reference_page", data, ctx)
    artifact = artifact_for("capture_reference_page", first)
    StorageService.resolve(artifact.file_path).write_text("changed", encoding="utf-8")
    with pytest.raises(AppError) as denied:
        registry.invoke("capture_reference_page", data, ctx)
    assert denied.value.code == "TRANSFORM_INPUT_CHANGED"
    assert ToolInvocation.query.count() == 1


def failed_write(registry, ctx, kind, value):
    ctx.idempotency_key = f"{ctx.budget_scope}:write:{kind}"
    with pytest.raises(AppError) as stopped:
        registry.invoke("write_workspace", {"key": kind, "kind": kind, "payload": value}, ctx)
    assert AgentWorkspaceItem.query.count() == 0
    result = agent_error(stopped.value)
    assert isinstance(result.get("repair_guidance"), dict), result
    return stopped.value, result


def test_research_needs_schema_error_has_usable_sanitized_model_receipt(app_ctx):
    registry = build_v3_registry()
    _, _, ctx = context(role="producer")
    secret = "private-secret-that-must-not-be-echoed"
    error, reply = failed_write(registry, ctx, "brief", {"deliverable": "image", "summary": "cat",
        "confidence": 0.8, "research_needs": [secret]})
    assert error.code == "INVALID_WORKSPACE_PAYLOAD"
    guidance = reply["repair_guidance"]
    assert guidance == research_needs_guidance() and secret not in json.dumps(reply)
    corrected = {"deliverable": "image", "summary": "cat", "confidence": 0.8, **guidance["example"]}
    saved = registry.invoke("write_workspace", {"key": "brief", "kind": "brief", "payload": corrected}, next_context(ctx))
    assert saved["output"]["payload"]["research_needs"][0]["query"]
    resource = registry.invoke("read_skill_resource", guidance["schema_resource"], next_context(ctx))["output"]
    assert json.loads(resource["content"]) == RequirementBrief.model_json_schema()


@pytest.mark.parametrize("failure", ["shape", "unobserved_source", "candidate_question"])
def test_dossier_errors_expose_legal_empty_structure_without_evidence_fabrication(app_ctx, failure):
    registry = build_v3_registry()
    run, _, ctx = context()
    if failure == "shape":
        value = {"entities": ["wrong shape"]}
    elif failure == "unobserved_source":
        value = web_dossier()
    else:
        value = {"entities": [{"entity_id": "cat", "name": "cat", "description": "Unknown", "candidates": []}],
            "open_questions": [{"question_id": "appearance", "text": "Choose", "why": "Unknown identity",
                "options": [{"option_id": "upload", "label": "Upload"}, {"option_id": "text", "label": "Describe"}]}]}
    error, reply = failed_write(registry, ctx, "research_dossier", value)
    assert error.code == ("INVALID_WORKSPACE_PAYLOAD" if failure == "shape" else "INVALID_RESEARCH_DOSSIER")
    guidance = reply["repair_guidance"]
    assert guidance == dossier_guidance()
    example = guidance["example"]
    assert example["sources"] == example["entities"] == example["open_questions"] == []
    assert "http" not in json.dumps(example) and "reference_id" not in json.dumps(example)
    ResearchDossier.model_validate(example)
    validated = validate_dossier(example, {"run_id": run.run_id})
    assert not validated["sources"] and not validated["topics"]
    saved = registry.invoke("write_workspace", {"key": "empty", "kind": "research_dossier", "payload": example}, next_context(ctx))
    assert saved["output"]["payload"]["sources"] == []
    resource = registry.invoke("read_skill_resource", guidance["schema_resource"], next_context(ctx))["output"]
    assert json.loads(resource["content"]) == ResearchDossier.model_json_schema()


def test_guidance_stays_bounded_and_isolated_between_calls():
    for factory in (research_needs_guidance, dossier_guidance):
        original = factory()
        assert len(json.dumps(original, ensure_ascii=False)) <= 2000
        other = factory()
        other["example"].clear()
        assert factory() == original


def test_research_skill_explains_server_binding_and_teaching_examples(app_ctx):
    _, _, ctx = context()
    result = build_v3_registry().invoke("load_skill", {"name": "web-research"}, next_context(ctx))["output"]
    assert result["version"] == 2
    assert "默认省略 run_id" in result["body"] and "repair_guidance" in result["body"]
    assert "不是事实" in result["body"]


def test_omitted_fetch_receipt_remains_admissible_research_evidence(app_ctx):
    registry = build_v3_registry()
    run, _, ctx = context()
    search = registry.invoke("web_search", {"query": "DeepSeek"}, ctx)["output"]
    hit = search["results"][0]
    registry.invoke("fetch_page", {"url": hit["url"]}, ctx)
    source = {"source_id": hit["result_id"], "kind": "web", "url": hit["url"],
        "title": "Agent-proposed title", "site": "Mock", "retrieved_at": search["fetched_at"]}
    data = {"sources": [source], "topics": [{"topic_id": "mock", "query": "DeepSeek", "summary": "Mock 资料",
        "key_facts": [{"fact": "Mock 示例事实", "source_ids": [hit["result_id"]]}], "confidence": 0.1}]}
    saved = registry.invoke("write_workspace", {"key": "evidence", "kind": "research_dossier", "payload": data}, next_context(ctx))
    dossier = saved["output"]["payload"]
    assert dossier["sources"][0]["title"] == hit["title"]
    assert dossier["stats"]["pages_fetched"] == dossier["stats"]["web_searches"] == 1
    assert dossier["topics"][0]["key_facts"][0]["source_ids"] == [hit["result_id"]]


def test_omitted_download_recovers_existing_scoped_artifact_without_new_download(app_ctx, monkeypatch):
    registry = build_v3_registry()
    run, _, ctx = context()
    data = payload(registry, "download_reference", ctx)
    first = registry.invoke("download_reference", {**data, "run_id": run.run_id}, ctx)
    row = ToolInvocation.query.filter_by(invocation_id=first["invocation_id"]).one()
    row.status, row.output_payload = "running", None
    db.session.commit()
    monkeypatch.setattr("app.agent.search.references.fetch_resource", lambda *a, **k: pytest.fail("Must recover the existing artifact"))
    recovered = registry.invoke("download_reference", data, ctx)
    assert recovered["output"]["reference_id"] == first["output"]["reference_id"]
    assert Artifact.query.count() == 1 and row.input_payload["run_id"] == run.run_id
