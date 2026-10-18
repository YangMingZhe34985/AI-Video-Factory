"""Contract-aligned policy assets and tool boundaries; no creative-quality claim."""

import json
from pathlib import Path
import re

import pytest
import yaml

from app.agents.cards import get_catalog
from app.agents.schemas import PlanDraft, validate_payload
from app.agents.skill_library import get_skill_library
from app.agents.tools import FinishInput, PromptUpdate, WriteInput
from app.models import AgentWorkspaceItem, Job, ToolInvocation
from app.plans.blueprints import BUILDERS, VERSION
from app.tools import build_default_registry, build_v3_registry
from tests.test_v3_workspace import make_context, next_context


BACKEND = Path(__file__).resolve().parents[1]
ROLES = ("producer", "research", "creative", "director", "prompt_smith", "critic", "repair")
PRODUCTION_TOOLS = {"generate_image", "animate_shot", "generate_video", "transform_video",
                    "retain_video_segment", "extract_frame", "compose_video", "probe_media", "qc_video", "package_story"}


@pytest.mark.parametrize("role", ROLES)
def test_formal_cards_keep_generation_private_and_role_authority_narrow(app_ctx, role):
    registry = build_v3_registry()
    card = get_catalog().cards[role]
    exposed = {item["function"]["name"] for item in registry.function_schemas(card.tools)}
    assert not exposed & PRODUCTION_TOOLS
    assert "agent_llm_turn" not in exposed
    assert {name for name in exposed if registry.get(name).permission == "generate"} == (
        {"request_preview"} if role in {"producer", "director"} else set())
    assert ("submit_plan" in exposed) == (role == "producer")
    assert ("propose_patch" in exposed) == (role in {"repair", "director"})
    assert ("review_patch" in exposed) == (role == "director")
    assert 0 < card.limits.planning_credits <= 20
    assert "finish" in exposed
    assert all(registry.get(name).agent_visible for name in exposed)


@pytest.mark.parametrize("role", ["producer", "director", "research", "repair"])
def test_async_analysis_or_preview_roles_can_observe_existing_jobs(app_ctx, role):
    card = get_catalog().cards[role]
    assert "get_task_status" in card.tools
    schema = next(item["function"] for item in build_v3_registry().function_schemas(card.tools)
                  if item["function"]["name"] == "get_task_status")
    assert set(schema["parameters"]["properties"]) == {"job_id", "invocation_id"}


def test_repairs_and_prompt_editors_have_no_authority_to_expand_execution(app_ctx):
    catalog = get_catalog()
    repair = catalog.cards["repair"]
    prompt = catalog.cards["prompt_smith"]
    assert not repair.can_delegate_to and not prompt.can_delegate_to
    assert not {"delegate", "ask_user", "write_workspace", "request_preview", "review_patch"} & set(repair.tools)
    assert not {"delegate", "check_plan", "estimate_cost", "request_preview", "propose_patch", "review_patch"} & set(prompt.tools)
    assert catalog.cards["creative"].can_delegate_to == ["research"]
    assert not {"list_models", "estimate_cost", "analyze_images", "analyze_video"} & set(catalog.cards["creative"].tools)
    assert "analyze_images" not in catalog.cards["critic"].tools
    assert len(build_default_registry().names()) == 22


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_blueprint_contract_and_examples_are_readable_through_registry(app_ctx, name):
    _run, _delegation, ctx = make_context()
    registry = build_v3_registry()
    before = (ToolInvocation.query.count(), Job.query.count(), AgentWorkspaceItem.query.count())
    loaded = registry.invoke("load_skill", {"name": name}, next_context(ctx))
    assert {"resources/params.schema.json", "resources/examples.json"} <= set(loaded["output"]["resources"])
    assert loaded["output"]["version"] == VERSION
    schema_result = registry.invoke("read_skill_resource", {
        "name": name, "path": "resources/params.schema.json"}, next_context(ctx))
    examples_result = registry.invoke("read_skill_resource", {
        "name": name, "path": "resources/examples.json"}, next_context(ctx))
    schema = json.loads(schema_result["output"]["content"])
    metadata = yaml.safe_load((BACKEND / "skills" / name / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1])
    assert schema == metadata["blueprint"]["params_schema"] == BUILDERS[name][0].model_json_schema()
    examples = json.loads(examples_result["output"]["content"])
    assert examples["demo"] is True and examples["warning"]
    placeholders = examples["replace_before_use"]
    assert placeholders and all(value.startswith("REPLACE_") for value in placeholders)
    for example in examples["examples"]:
        # Check shape only: placeholders deliberately never become scoped artifacts.
        BUILDERS[name][0].model_validate(example["params"])
        used = set(re.findall(r"REPLACE_[A-Z_]+", json.dumps(example["params"])))
        assert used <= placeholders.keys()
        assert used
        assert not {"quote_id", "manifest", "cost_breakdown", "estimated_cost", "plan_version"} & example["params"].keys()
    assert (ToolInvocation.query.count(), Job.query.count(), AgentWorkspaceItem.query.count()) == before
    assert all(result["estimated_cost"] == 0 and result["invocation_id"] is None
               for result in (loaded, schema_result, examples_result))


@pytest.mark.parametrize("role", ["producer", "director", "prompt_smith", "critic"])
def test_embedded_policy_json_examples_match_actual_input_contracts(app_ctx, role):
    body = get_catalog().prompts[role]
    examples = [json.loads(block) for block in re.findall(r"```json\s*(.*?)\s*```", body, re.S)]
    assert examples
    for value in examples:
        if role == "producer":
            command = WriteInput.model_validate(value)
            validate_payload(command.kind, command.payload)
        elif role == "director":
            plan = PlanDraft.model_validate(value)
            assert all(node.model_id is None for node in plan.nodes)
        else:
            command = FinishInput.model_validate(value)
            assert command.kind == "completed"
            if role == "prompt_smith":
                for item in command.updates:
                    checked = PromptUpdate.model_validate(item)
                    assert set(checked.inputs_patch.model_dump()) == {"prompt"}
            else:
                validate_payload("critic_review", {"verdict": command.verdict, "issues": command.issues})


def test_pending_human_audits_are_not_claimed_complete(app_ctx):
    catalog = get_catalog()
    library = get_skill_library()
    for role in ("producer", "director"):
        assert "待 Claude 审定" in catalog.prompts[role]
    for name in ("intent-analysis", "delegation-policy", "long-form-video", "character-consistency"):
        assert "待 Claude 审定" in library.load_skill(name)["body"]
