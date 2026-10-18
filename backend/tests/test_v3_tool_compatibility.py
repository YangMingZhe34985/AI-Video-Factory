"""V1 namespace, public-contract and scoped-ledger compatibility checks."""

import importlib
from dataclasses import replace

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.extensions import db
from app.models import AgentRun, ToolInvocation
from app.schemas.skill_schema import InvokeSkillSchema
from app.tools import build_default_registry, build_v3_registry
from app.tools.registry import ToolRegistry, idempotency_key_for
from app.tools.spec import ToolContext, ToolSpec


LEGACY_NAMES = [
    "analyze_image", "analyze_video", "animate_shot", "capture_reference_page", "compose_video",
    "download_reference", "extract_frame", "fetch_page", "generate_image", "generate_video",
    "get_task_status", "image_search", "package_project", "package_story", "probe_media", "produce_shot",
    "qc_video", "remix_shot", "rerun_node", "rewrite_prompt", "transform_video", "web_search",
]
CORE_MODULES = ["budget", "job_backed", "model_guard", "permissions", "registry", "spec"]
MODULE_ALIASES = [(f"app.skills.{name}", f"app.tools.{name}") for name in CORE_MODULES]
MODULE_ALIASES += [("app.skills.tools", "app.tools.specs")]
MODULE_ALIASES += [(f"app.skills.tools.{name}", f"app.tools.specs.{name}") for name in LEGACY_NAMES]
PLAN_TOOLS = ["generate_image", "animate_shot", "generate_video", "transform_video", "extract_frame",
              "compose_video", "probe_media", "qc_video", "package_story"]
ASYNC_OUTPUTS = {"generate_image": {"image": "image", "images": "image[]"},
                 "animate_shot": {"video": "video"}, "generate_video": {"video": "video"},
                 "transform_video": {"video": "video"}}


@pytest.mark.parametrize("legacy,canonical", MODULE_ALIASES)
def test_every_legacy_submodule_keeps_identity_and_monkeypatch(monkeypatch, legacy, canonical):
    old_module = importlib.import_module(legacy)
    new_module = importlib.import_module(canonical)
    assert old_module is new_module
    marker = object()
    monkeypatch.setattr(f"{legacy}._compatibility_marker", marker, raising=False)
    assert new_module._compatibility_marker is marker


def test_legacy_top_level_factory_monkeypatch_changes_shared_registry(monkeypatch):
    legacy = importlib.import_module("app.skills")
    canonical = importlib.import_module("app.tools")
    marker = object()
    monkeypatch.setattr(legacy, "_registry", None)
    monkeypatch.setattr(legacy, "build_default_registry", lambda: marker)
    assert canonical.build_default_registry() is marker
    assert legacy.get_registry() is marker
    assert canonical.get_registry() is marker


def test_canonical_top_level_function_monkeypatch_is_visible_in_legacy(monkeypatch):
    legacy = importlib.import_module("app.skills")
    canonical = importlib.import_module("app.tools")
    marker = object()
    replacement = lambda: marker
    monkeypatch.setattr(canonical, "get_registry", replacement)
    assert legacy.get_registry is replacement
    assert legacy.get_registry() is marker


def test_legacy_wildcard_import_keeps_public_registry_factories():
    namespace = {}
    exec("from app.skills import *", namespace)
    canonical = importlib.import_module("app.tools")
    assert namespace["get_registry"] is canonical.get_registry
    assert namespace["build_default_registry"] is canonical.build_default_registry


def test_legacy_registry_keeps_exact_catalog_and_description_fields():
    registry = build_default_registry()
    assert registry.names() == LEGACY_NAMES
    assert len(registry.describe_all()) == 22
    expected_fields = {"name", "description", "permission", "allowed_roles", "requires_approval", "timeout_sec",
                       "max_wait_sec", "max_retries", "dedupe", "input_schema", "output_schema"}
    for description in registry.describe_all():
        assert set(description) == expected_fields
        assert description["input_schema"]["type"] == "object"
        assert description["output_schema"]["type"] == "object"


def test_v3_catalog_does_not_mutate_legacy_roles_or_descriptions():
    legacy = build_default_registry()
    before = legacy.describe_all()
    v3 = build_v3_registry()
    assert legacy.describe_all() == before == build_default_registry().describe_all()
    assert set(v3.names()) - set(LEGACY_NAMES) == {
        "analyze_images", "estimate_cost", "list_models", "list_skills", "load_skill", "read_skill_resource",
        "list_agents", "delegate", "ask_user", "read_workspace", "write_workspace", "finish",
        "check_plan", "instantiate_blueprint", "submit_plan", "request_preview", "retain_video_segment",
    }
    assert len(v3.names()) == 39
    assert "producer" in v3.get("analyze_video").allowed_roles
    assert "producer" not in legacy.get("analyze_video").allowed_roles


@pytest.mark.parametrize("name", PLAN_TOOLS)
def test_plan_io_inputs_match_handler_schema_and_outputs_are_resolvable(name):
    spec = build_default_registry().get(name)
    assert spec.plan_executable
    assert set(spec.io_types["inputs"]) <= set(spec.input_model.model_fields)
    if name in ASYNC_OUTPUTS:
        # D-032: these names are resolved from completed Job artifacts by V4,
        # rather than from the initial asynchronous launch receipt.
        assert spec.io_types["outputs"] == ASYNC_OUTPUTS[name]
        assert set(spec.output_model.model_fields) == {"job_id", "status", "expected_outputs"}
    else:
        assert set(spec.io_types["outputs"]) <= set(spec.output_model.model_fields)


@pytest.mark.parametrize("name", ["generate_image", "generate_video"])
def test_plan_reference_array_uses_the_real_artifact_input(name):
    spec = build_default_registry().get(name)
    assert spec.io_types["inputs"]["reference_artifact_ids"] == "image[]"
    assert "reference_image_ids" not in spec.io_types["inputs"]


@pytest.mark.parametrize("field", ["caller_agent", "delegation_id", "agent_step"])
def test_public_skill_schema_rejects_v3_server_context(field):
    with pytest.raises(ValidationError):
        InvokeSkillSchema.model_validate({"role": "system", "input": {}, field: "producer" if field == "caller_agent" else 1})


class LookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str


class LookupOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: str


def lookup_spec(handler):
    return ToolSpec(name="compatibility_lookup", description="Stub audited lookup", input_model=LookupInput,
                    output_model=LookupOutput, handler=handler, permission="llm",
                    allowed_roles=frozenset({"system", "producer", "research"}), agent_visible=True,
                    cost_fn=lambda _data, _ctx: 1.0)


def test_legacy_ledger_key_and_invocation_result_are_unchanged(app_ctx):
    registry = ToolRegistry()
    registry.register(lookup_spec(lambda data, _ctx: {"result": data.query}))
    data = {"query": "fact"}
    first = registry.invoke("compatibility_lookup", data, ToolContext(role="system", budget_scope="legacy"))
    assert set(first) == {"tool", "invocation_id", "status", "attempt", "estimated_cost", "replayed", "output"}
    assert first["output"] == {"result": "fact"}
    assert first["estimated_cost"] == 1.0 and first["status"] == "success" and first["attempt"] == 1
    row = ToolInvocation.query.one()
    assert row.idempotency_key == idempotency_key_for("compatibility_lookup", LookupInput(**data))
    assert row.caller_agent is None and row.delegation_id is None
    replay = registry.invoke("compatibility_lookup", data, ToolContext(role="system", budget_scope="legacy"))
    assert replay == {**first, "replayed": True}


def test_default_agent_keys_isolate_callers_and_delegations_but_replay_within_delegation(app_ctx):
    run = AgentRun(run_id="compatibility-run", owner_id="local", request_key="compatibility-run",
                   request={"schema_version": 3, "text": "Stub lookup", "budget_limit": 50})
    db.session.add(run)
    db.session.commit()
    calls = []

    def handler(data, ctx):
        calls.append((ctx.caller_agent, ctx.delegation_id))
        return {"result": data.query}

    registry = ToolRegistry()
    registry.register(lookup_spec(handler))

    def invoke(agent, delegation, step=0):
        return registry.invoke("compatibility_lookup", {"query": "same fact"},
            ToolContext(role=agent, caller_agent=agent, delegation_id=delegation, agent_step=step,
                        budget_scope=run.run_id, budget_limit=50))

    producer = invoke("producer", 1)
    research = invoke("research", 1)
    another_delegation = invoke("producer", 2)
    assert len({producer["invocation_id"], research["invocation_id"], another_delegation["invocation_id"]}) == 3
    assert invoke("producer", 1, step=1) == {**producer, "replayed": True}
    assert calls == [("producer", 1), ("research", 1), ("producer", 2)]
    rows = ToolInvocation.query.all()
    assert len(rows) == 3 and sum(row.estimated_cost for row in rows) == 3.0


@pytest.mark.config(AGENT_MODE_ENABLED=True)
def test_public_invocation_response_keeps_legacy_fields(app_ctx, client):
    row = ToolInvocation(tool_name="rewrite_prompt", idempotency_key="compat-public", caller_role="system",
                         caller_agent="producer", delegation_id=1, input_payload={}, output_payload={}, status="success")
    db.session.add(row)
    db.session.commit()
    response = client.get(f"/api/skills/invocations/{row.invocation_id}")
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert set(payload) == {"id", "invocation_id", "tool_name", "idempotency_key", "caller_role", "budget_scope",
                           "status", "attempt", "input_payload", "output_payload", "error_code", "error_message",
                           "job_id", "estimated_cost", "duration_ms", "started_at", "finished_at", "created_at",
                           "updated_at", "job_public_id"}


def test_generation_tools_cannot_be_exported_to_agents():
    from app.api import AppError

    registry = build_v3_registry()
    for name in registry.names():
        spec = registry.get(name)
        if spec.permission == "generate":
            if name == "request_preview":
                assert spec.agent_visible and not spec.plan_executable
                assert registry.function_schemas([name])[0]["function"]["name"] == name
                continue
            assert not spec.agent_visible
            with pytest.raises(AppError) as error:
                registry.function_schemas([name])
            assert error.value.code == "TOOL_FORBIDDEN"
            with pytest.raises(ValueError):
                replace(spec, agent_visible=True)
