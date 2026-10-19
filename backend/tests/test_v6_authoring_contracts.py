"""Agent-readable authoring contracts exercise the real private compiler, offline."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.agent.research_spec import ResearchDossier
from app.agent.story_spec import StoryPackage
from app.agents.cards import get_catalog
from app.agents.schemas import CriticReview, PlanDraft, RequirementBrief
from app.api import AppError
from app.extensions import db
from app.models import AgentWorkspaceItem, Artifact, Job, ModelRegistry, ToolInvocation
from app.plans.compiler import GENERATION_TOOLS, PLAN_TOOLS, TRANSFORM_TYPES, VERSION_TOOLS, compile_plan, node_inputs, resolve_inputs
from app.plans.dry_run import dry_run
from app.plans.patch_schemas import PatchDraft
from app.tools import build_default_registry, build_v3_registry
from app.tools.registry import ToolRegistry
from tests.test_v3_plan_compiler import make_run
from tests.test_v3_workspace import make_context, next_context


WORKSPACE_MODELS = {
    "brief": RequirementBrief, "research_dossier": ResearchDossier, "story": StoryPackage,
    "plan_draft": PlanDraft, "critic_review": CriticReview, "patch": PatchDraft,
}
ROLE_KINDS = {
    "producer": ("brief", "plan_draft"), "research": ("research_dossier",),
    "creative": ("story",), "director": ("plan_draft", "patch"),
    "prompt_smith": ("plan_draft",), "critic": ("critic_review", "plan_draft"),
    "repair": ("patch", "plan_draft"),
}
EXAMPLE = "resources/examples/first-frame-delivery.plan.json"


def read_resource(registry, ctx, path):
    result = registry.invoke("read_skill_resource", {"name": "plan-review", "path": path}, next_context(ctx))
    assert result["estimated_cost"] == 0 and result["invocation_id"] is None
    assert result["output"]["name"] == "plan-review" and result["output"]["path"] == path
    return result["output"]["content"]


def read_json(registry, ctx, path):
    return json.loads(read_resource(registry, ctx, path))


def counts():
    return tuple(model.query.count() for model in (Job, Artifact, ToolInvocation, AgentWorkspaceItem, ModelRegistry))


@pytest.mark.parametrize("role", ROLE_KINDS)
def test_each_role_can_discover_and_read_its_actual_contract_without_new_authority(app_ctx, role):
    _run, delegation, ctx = make_context(role=role)
    registry = build_v3_registry()
    before = counts()
    quota = delegation.credits_limit
    card = get_catalog().cards[role]
    names_before = {row["function"]["name"] for row in registry.function_schemas(card.tools)}
    assert {"list_skills", "load_skill", "read_skill_resource"} <= names_before
    listed = registry.invoke("list_skills", {"agent": role}, next_context(ctx))
    assert "plan-review" in {item["name"] for item in listed["output"]}
    loaded = registry.invoke("load_skill", {"name": "plan-review"}, next_context(ctx))
    resources = set(loaded["output"]["resources"])
    assert "resources/README.md" in resources
    assert EXAMPLE in resources
    assert read_resource(registry, ctx, "resources/README.md")
    for kind in ROLE_KINDS[role]:
        path = f"resources/workspace/{kind}.schema.json"
        assert path in resources
        assert read_json(registry, ctx, path) == WORKSPACE_MODELS[kind].model_json_schema()
    assert names_before == {row["function"]["name"] for row in registry.function_schemas(card.tools)}
    assert not names_before & PLAN_TOOLS
    # Reading a tool's full schema is knowledge, not permission to request it.
    with pytest.raises(AppError) as denied:
        registry.invoke("generate_image", {"prompt": "A test frame"}, next_context(ctx))
    assert denied.value.code == "TOOL_FORBIDDEN"
    assert delegation.credits_limit == quota
    assert counts() == before


@pytest.mark.parametrize("kind", WORKSPACE_MODELS)
def test_workspace_schema_resource_matches_the_model_used_by_workspace_validation(app_ctx, kind):
    _run, _delegation, ctx = make_context()
    registry = build_v3_registry()
    registry.invoke("load_skill", {"name": "plan-review"}, next_context(ctx))
    schema = read_json(registry, ctx, f"resources/workspace/{kind}.schema.json")
    assert schema == WORKSPACE_MODELS[kind].model_json_schema()
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    if kind == "plan_draft":
        assert "plan_version" not in schema["properties"]
        assert "inputs" in schema["$defs"]["PlanDraftNode"]["properties"]
    if kind == "patch":
        assert {"quote_id", "patch_id", "director_review"}.isdisjoint(schema["properties"])


@pytest.mark.parametrize("name", sorted(PLAN_TOOLS))
def test_plan_tool_resources_match_private_resolved_inputs_and_named_completion_outputs(app_ctx, name):
    _run, _delegation, ctx = make_context(role="director")
    registry = build_v3_registry()
    loaded = registry.invoke("load_skill", {"name": "plan-review"}, next_context(ctx))
    declared = {Path(path).stem for path in loaded["output"]["resources"] if path.startswith("resources/tools/") and path.endswith(".json")}
    assert declared == PLAN_TOOLS
    resource = read_json(registry, ctx, f"resources/tools/{name}.json")
    spec = registry.get(name)
    assert resource["tool"] == name
    assert resource["resolved_input_schema"] == spec.input_model.model_json_schema()
    assert resource["io_types"] == spec.io_types
    authoring = resource["authoring"]
    assert set(authoring["plan_node_fields"]) == ({"model_id", "params"} if name in GENERATION_TOOLS else set())
    injected = {"plan_version"} if name in VERSION_TOOLS else {"selected_artifact_id"} if name == "select_image" else set()
    assert set(authoring["server_injected_fields"]) == injected
    forbidden = {"model_id", "params", "template_id", "plan_version"} | ({"selected_artifact_id"} if name == "select_image" else set())
    assert set(authoring["forbidden_input_fields"]) == forbidden
    for field in authoring["forbidden_input_fields"]:
        with pytest.raises(AppError) as misplaced:
            node_inputs({"tool": name, "inputs": {field: None}})
        assert misplaced.value.code == "RESERVED_INPUT"
    references = authoring["references"]
    assert set(references["existing_media"]) == {"artifact"}
    assert resolve_inputs(references["existing_media"], {}) == references["existing_media"]["artifact"]
    assert resolve_inputs(references["upstream_output"], {"node": {"output": "resolved-output"}}) == "resolved-output"
    assert spec.plan_executable and not spec.agent_visible
    with pytest.raises(AppError) as forbidden:
        registry.function_schemas([name])
    assert forbidden.value.code == "TOOL_FORBIDDEN"
    if name in {"generate_image", "animate_shot", "generate_video", "transform_video"}:
        assert "job_id" in spec.output_model.model_json_schema()["properties"]
        assert "job_id" not in resource["io_types"]["outputs"]
        assert {"model_id", "params"} <= resource["resolved_input_schema"]["properties"].keys()
    if name == "transform_video":
        assert {"operation", "media", "source_artifact_id"} <= resource["resolved_input_schema"]["properties"].keys()
        assert "plan_hash" not in resource["resolved_input_schema"]["properties"]
        assert authoring["structured_media"]["type_mapping"] == TRANSFORM_TYPES
    if name in {"compose_video", "probe_media", "qc_video", "package_story"}:
        assert "plan_version" in resource["resolved_input_schema"]["required"]


def example_and_resources():
    _run, _delegation, ctx = make_context(role="director")
    registry = build_v3_registry()
    loaded = registry.invoke("load_skill", {"name": "plan-review"}, next_context(ctx))
    assert EXAMPLE in loaded["output"]["resources"]
    draft = read_json(registry, ctx, EXAMPLE)
    PlanDraft.model_validate(draft)
    resources = {node["tool"]: read_json(registry, ctx, f"resources/tools/{node['tool']}.json") for node in draft["nodes"]}
    return draft, resources, registry


def test_documented_first_frame_delivery_compiles_and_dry_runs_without_any_handler_or_writes(app_ctx, monkeypatch):
    draft, resources, original = example_and_resources()
    run = make_run(deliverable="video")
    before = counts()
    original_draft = deepcopy(draft)
    storage = Path(app_ctx.config["STORAGE_ROOT"])
    files_before = {path.relative_to(storage) for path in storage.rglob("*")}
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("called")
        pytest.fail("Authoring compilation and dry-run must not execute tools, LLMs or writes")

    registry = ToolRegistry()
    for name in original.names():
        registry.register(replace(original.get(name), handler=forbidden, cost_fn=forbidden))
    with monkeypatch.context() as guard:
        guard.setattr(registry, "invoke", forbidden)
        guard.setattr(db.session, "commit", forbidden)
        guard.setattr(db.session, "flush", forbidden)
        result = compile_plan(draft, run, registry=registry, plan_version=3)
        assert result["issues"] == []
        checked = dry_run(result, registry=registry)
    assert checked["passed"] and checked["issues"] == []
    assert checked["estimated_cost"] == 0 and not calls
    assert counts() == before
    assert {path.relative_to(storage) for path in storage.rglob("*")} == files_before
    assert draft == original_draft
    assert result["source_artifact_ids"] == []

    nodes = {node["tool"]: node for node in result["plan"]["nodes"]}
    assert {"generate_image", "animate_shot", "compose_video", "probe_media", "qc_video", "package_story"} <= nodes.keys()
    first, clip, master, probe, qc, package = (nodes[name] for name in (
        "generate_image", "animate_shot", "compose_video", "probe_media", "qc_video", "package_story"))
    assert clip["inputs"]["first_frame_artifact_id"] == {"ref": f"{first['id']}.image"}
    assert master["inputs"]["video_artifact_ids"] == [{"ref": f"{clip['id']}.video"}]
    for node in (probe, qc, package):
        assert node["inputs"]["artifact_id"] == {"ref": f"{master['id']}.artifact_id"}
    assert qc["inputs"]["video_artifact_ids"] == [{"ref": f"{clip['id']}.video"}]
    assert qc["id"] in result["dag"]["dependencies"][package["id"]]
    assert checked["order"].index(qc["id"]) < checked["order"].index(package["id"])
    assert result["estimates"]["generated_video_seconds"] == result["estimates"]["video_seconds"] == clip["params"]["duration"]
    assert result["estimates"]["total_credits"] > 0  # estimates are not billed calls
    assert not result["validated_inputs"][master["id"]]["compress_output"]
    assert "compressed_artifact_id" not in checked["outputs"][master["id"]]

    for node in result["plan"]["nodes"]:
        resource = resources[node["tool"]]
        output = checked["outputs"][node["id"]]
        assert set(output) <= resource["io_types"]["outputs"].keys()
        assert "job_id" not in output
        inputs = resolve_inputs(node_inputs(node, plan_version=3), checked["outputs"])
        original.get(node["tool"]).input_model.model_validate(inputs)
        assert not {"model_id", "params", "plan_version", "template_id"} & node["inputs"].keys()
    assert result["validated_inputs"][clip["id"]]["first_frame_artifact_id"] == checked["outputs"][first["id"]]["image"]
    assert result["validated_inputs"][master["id"]]["video_artifact_ids"] == [checked["outputs"][clip["id"]]["video"]]
    for delivery in result["plan"]["deliverables"]:
        assert delivery["output"] in checked["outputs"][delivery["node_id"]]
    assert len(build_default_registry().names()) == 22


@pytest.mark.parametrize("mistake,code", [
    ("launch_receipt", "MISSING_PLAN_OUTPUT"), ("image_array", "PLAN_TYPE_MISMATCH"),
    ("model_inside_inputs", "RESERVED_INPUT"), ("missing_qc_control", "QC_REQUIRED"),
])
def test_documented_plan_rejects_common_authoring_mistakes_before_any_execution(app_ctx, mistake, code):
    draft, _resources, registry = example_and_resources()
    run = make_run(deliverable="video")
    nodes = {node["tool"]: node for node in draft["nodes"]}
    first, clip, package = (nodes[name] for name in ("generate_image", "animate_shot", "package_story"))
    if mistake == "launch_receipt":
        clip["inputs"]["first_frame_artifact_id"] = {"ref": f"{first['id']}.job_id"}
    elif mistake == "image_array":
        clip["inputs"]["first_frame_artifact_id"] = {"ref": f"{first['id']}.images"}
    elif mistake == "model_inside_inputs":
        clip["inputs"]["model_id"] = "wan2.7-i2v"
    else:
        package["depends_on"] = []
    before = counts()
    result = compile_plan(draft, run, registry=registry)
    assert code in {issue["code"] for issue in result["issues"]}
    checked = dry_run(result, registry=registry)
    assert not checked["passed"] and not checked["order"] and checked["estimated_cost"] == 0
    assert counts() == before
