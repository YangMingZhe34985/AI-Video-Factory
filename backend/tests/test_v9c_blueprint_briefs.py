"""Blueprint body examples are executable authoring knowledge, not authority.

Scripted round counts prove an available short path, not real LLM latency or
autonomous quality. Every model response is Stub; production stays unapproved.
"""
import json
from pathlib import Path
import re

import pytest

from app.agents.cards import get_catalog
from app.agents.schemas import PlanDraft
from app.extensions import db
from app.models import AgentDelegation, AgentPlanVersion, AgentWorkspaceItem, Job, ToolInvocation
from app.plans.blueprints import BUILDERS
from app.plans.compiler import compile_plan
from app.plans.dry_run import dry_run
from app.tools import build_v3_registry
from tests.test_v3_blueprints import source_video  # noqa: F401 - isolated media fixture
from tests.test_v3_plan_compiler import image, make_run
from tests.test_v3_workspace import make_context, next_context
from tests.v6_scenario_support import Scenario, attachment, brief, call, upload_image, write


BACKEND = Path(__file__).resolve().parents[1]
EXAMPLES = re.compile(r"<!-- blueprint-params-example:(\d+) -->\s*```json\s*(.*?)\s*```", re.S)
DEFAULT_PLANS = re.compile(r"<!-- blueprint-default-plan:(\d+) -->\s*```json\s*(.*?)\s*```", re.S)


def examples(body):
    result = [(int(index), json.loads(raw)) for index, raw in EXAMPLES.findall(body)]
    assert result and len({index for index, _ in result}) == len(result)
    return result


def load_body(registry, ctx, name):
    loaded = registry.invoke("load_skill", {"name": name}, next_context(ctx))
    assert loaded["estimated_cost"] == 0 and loaded["invocation_id"] is None
    return loaded["output"]["body"]


def substitute(value, replacements):
    if isinstance(value, dict):
        return {key: substitute(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, replacements) for item in value]
    return replacements.get(value, value) if isinstance(value, str) else value


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_loaded_body_examples_match_resources_and_current_author_schema(app_ctx, name):
    _run, _delegation, ctx = make_context()
    registry = build_v3_registry()
    before = (Job.query.count(), ToolInvocation.query.count(), AgentWorkspaceItem.query.count())
    body = load_body(registry, ctx, name)
    resource = json.loads((BACKEND / "skills" / name / "resources/examples.json").read_text(encoding="utf-8"))
    assert "演示数据" in body and "按需" in body and "submit_plan" in body
    assert "先调用 read_skill_resource" not in body
    for index, payload in examples(body):
        # Field names, values and whole nested structures cannot drift silently.
        assert payload == resource["examples"][index]["params"]
        BUILDERS[name][0].model_validate(payload)
        placeholders = set(re.findall(r"REPLACE_[A-Z_]+", json.dumps(payload)))
        assert placeholders and placeholders <= resource["replace_before_use"].keys()
        assert not {"quote_id", "plan_version", "estimated_cost", "manifest"} & payload.keys()
    for index, raw in DEFAULT_PLANS.findall(body):
        draft = PlanDraft.model_validate(json.loads(raw)).model_dump(mode="json")
        corresponding = dict(examples(body))[int(index)]
        expected = BUILDERS[name][1](corresponding, run=_run, caller_agent="producer")["plan"]
        for node in expected["nodes"]:
            node["model_id"] = None
        assert draft["deliverables"] == expected["deliverables"]
        for actual, authoritative in zip(draft["nodes"], expected["nodes"], strict=True):
            for field in ("id", "tool", "model_id", "inputs", "params"):
                assert actual[field] == authoritative[field]
    assert (Job.query.count(), ToolInvocation.query.count(), AgentWorkspaceItem.query.count()) == before


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_body_example_builds_compiles_and_dry_runs_without_production(app_ctx, source_video, monkeypatch, name):
    own_image = image()
    ids = [source_video] if name == "video-remix" else [own_image] if name in {"image-edit", "single-clip", "video-transform"} else []
    run = make_run(deliverable="image" if name.startswith("image-") else "video", ids=ids,
                   preferences=("wan3.0系列",) if name == "video-transform" else ())
    _unused, _delegation, ctx = make_context()
    registry = build_v3_registry()
    payload = examples(load_body(registry, ctx, name))[0][1]
    payload = substitute(payload, {
        "REPLACE_DEFAULT_IMAGE_MODEL_ID": "wan2.7-image" if name in {"image-edit", "story-video"} else "wan2.6-image",
        "REPLACE_ALLOWED_VIDEO_MODEL_ID": "wan2.7-i2v",
        "REPLACE_ALLOWED_TRANSFORM_MODEL_ID": "wan3.0-video",
        "REPLACE_OWNED_IMAGE_ARTIFACT_ID": own_image,
        "REPLACE_OWNED_VIDEO_ARTIFACT_ID": source_video,
    })
    if name == "video-remix":
        # The example's 6-second original is a placeholder; use actual fixture
        # intervals rather than pretending its 5.25-second media is longer.
        payload["plan"]["shots"][0].update(source_start=0, source_end=1)
        payload["plan"]["shots"][1].update(source_start=1, source_end=2.5)
    before = (Job.query.count(), ToolInvocation.query.count(), AgentWorkspaceItem.query.count())
    built = BUILDERS[name][1](payload, run=run, caller_agent="producer")
    compiled = compile_plan(built["plan"], run, registry=registry)
    assert compiled["issues"] == [], compiled["issues"]
    with monkeypatch.context() as guard:
        guard.setattr(registry, "invoke", lambda *_a, **_kw: pytest.fail("Dry-run must not call a production tool"))
        guard.setattr(db.session, "commit", lambda: pytest.fail("Dry-run must not commit"))
        checked = dry_run(compiled, registry=registry)
    assert checked["passed"] and checked["estimated_cost"] == 0
    assert (Job.query.count(), ToolInvocation.query.count(), AgentWorkspaceItem.query.count()) == before


@pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, DEFAULT_I2V_MODEL="wan2.6-i2v-flash")
@pytest.mark.parametrize("name,index,explicit,duration", [
    ("image-create", 0, False, None), ("image-edit", 0, False, None),
    ("single-clip", 0, False, 5), ("single-clip", 1, False, 5),
    ("single-clip", 1, True, 10),
])
def test_body_driven_simple_task_reaches_review_in_four_scripted_rounds(app_ctx, client, name, index, explicit, duration):
    needs_image = name == "image-edit" or name == "single-clip" and index == 0
    identities = [upload_image(client)] if needs_image else []
    text = "生成猫咪图片" if name == "image-create" else "把上传照片中的主体改成西装照" if name == "image-edit" else "生成猫咪跳舞的视频"
    if duration:
        text += f"，时长{duration}秒"
    if explicit:
        text += "，仅使用wan2.7系列视频模型，不要HappyHorse"
    scenario = Scenario(app_ctx, client, text, attachment_ids=identities)
    initial = [call("load_skill", {"name": "plan-review"}, "contract_skill"),
        call("load_skill", {"name": name}, "blueprint_skill"),
        call("read_skill_resource", {"name": "plan-review", "path": "resources/workspace/brief.schema.json"}),
        call("list_models", {"mode": "i2v" if name == "single-clip" else "i2i" if needs_image else "t2i"})]
    if identities:
        initial.append(call("analyze_images", {"artifact_ids": identities, "focus": "识别需要保留的主体与构图"}))
    scenario.step("producer", initial, vision_ids=identities or None)
    body = scenario.output("producer", "load_skill")["body"]
    payload = dict(examples(body))[index]
    draft = json.loads(dict(DEFAULT_PLANS.findall(body))[str(index)])
    draft = substitute(draft, {"REPLACE_OWNED_IMAGE_ARTIFACT_ID": identities[0]} if identities else {})
    payload = substitute(payload, {"REPLACE_OWNED_IMAGE_ARTIFACT_ID": identities[0]} if identities else {})
    if duration:
        payload["plan"]["video"]["params"]["duration"] = duration
        next(item for item in draft["nodes"] if item["id"] == "video")["params"]["duration"] = duration
    constraints = {"model_preferences": ["wan2.7系列"] if explicit else [], "model_exclusions": ["HappyHorse"] if explicit else []}
    understood = brief("video" if duration else "image", text,
        attachments=[attachment(value, "first_frame" if name == "single-clip" else "identity_ref") for value in identities],
        constraints=constraints, **({"target_duration_sec": duration, "duration_tolerance_sec": 0} if duration else {}))
    scenario.step("producer", [write("brief", "brief", understood), call("check_plan", {"plan": draft})])
    checked = scenario.output("producer", "check_plan")
    assert checked["issues"] == [], checked["issues"]
    for key, model in checked["resolved_models"].items():
        payload["plan"][key]["model_id"] = model
    assert "REPLACE_" not in json.dumps(payload)
    scenario.step("producer", [call("instantiate_blueprint", {"name": name, "params": payload})])
    created = scenario.output("producer", "instantiate_blueprint")
    assert created["issues"] == [] and created["estimates"]["total_credits"] > 0
    scenario.step("producer", [call("submit_plan", {"plan_ref": created["workspace_ref"]})])
    assert scenario.output("producer", "submit_plan")["submitted"]
    assert scenario.root.steps == scenario.root.llm_calls == 4
    assert AgentDelegation.query.filter_by(run_id=scenario.run.run_id).count() == 1
    recorded = [item["name"] for script in scenario.responses.values() if isinstance(script, list) for item in script]
    assert recorded.count("load_skill") == 2 and recorded.count("check_plan") == 1
    assert not {"delegate", "read_workspace", "finish", "estimate_cost"} & set(recorded)
    reads = [item["arguments"] for script in scenario.responses.values() if isinstance(script, list) for item in script if item["name"] == "read_skill_resource"]
    assert reads == [{"name": "plan-review", "path": "resources/workspace/brief.schema.json"}]
    assert recorded.count("analyze_images") == bool(identities)
    version = AgentPlanVersion.query.filter_by(run_id=scenario.run.run_id).one()
    assert version.check["dry_run"]["passed"] and not version.check["issues"]
    if duration:
        video = next(item for item in version.plan["nodes"] if item["id"] == "video")
        assert video["params"]["duration"] == duration
        assert video["model_id"] == ("wan2.7-i2v" if explicit else "wan2.6-i2v-flash")
        assert version.check["estimates"]["video_seconds"] == version.check["estimates"]["generated_video_seconds"] == duration
    scenario.assert_review_only()


def test_efficiency_guidance_keeps_reviewed_strategy_and_uses_real_check_contract(app_ctx):
    prompts = get_catalog().prompts
    assert "check_plan(plan_ref)" not in prompts["director"]
    assert "check_plan({plan:完整草稿})" in prompts["director"]
    for role in ("producer", "director"):
        body = prompts[role]
        assert "已由 Claude 审定" in body
        assert "按需读取 resources/params.schema.json / resources/examples.json" in body
        assert "resolved_models" in body
        assert "不伪造 origin.blueprint" in body or "不得声称受验证 Blueprint 来源" in body
        assert "ToolRegistry" in body and "用户硬约束" in body
