"""V11d asset-driven offline paths; scripted calls do not prove LLM autonomy."""
from copy import deepcopy
import json
import re

import pytest

from app.agents.cards import get_catalog
from app.agents.schemas import RequirementBrief, validate_payload
from app.agents.tools import WriteInput
from app.api import AppError
from app.models import AgentDelegation, AgentPlanVersion, AgentWorkspaceItem, Job, ToolInvocation
from app.plans.blueprints.common import delivery_nodes
from app.tools import build_v3_registry
from tests.test_v3_workspace import image_attachment, make_context, next_context
from tests.v6_scenario_support import Scenario, brief, call, delegate, finish, read, upload_image, write


pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True,
                               DEFAULT_I2V_MODEL="wan2.6-i2v-flash")
BRIEFS = re.compile(r"<!-- requirement-brief-example:([a-z]+) -->\s*```json\s*(.*?)\s*```", re.S)
BLUEPRINTS = re.compile(r"<!-- blueprint-params-example:(\d+) -->\s*```json\s*(.*?)\s*```", re.S)
PLANS = re.compile(r"<!-- blueprint-default-plan:(\d+) -->\s*```json\s*(.*?)\s*```", re.S)
TEXTS = {
    "portrait": "把这张头像改成正式的证件照：纯白背景，深色西装，正面构图",
    "video": "做一段5秒的海浪拍打礁石的视频，必须用wan2.7系列模型，不要用happy-horse",
}


def parse_examples(body):
    result = {name: json.loads(raw) for name, raw in BRIEFS.findall(body)}
    assert set(result) == {"portrait", "video"}
    return result


def substitute(value, artifact_id):
    if isinstance(value, dict):
        return {key: substitute(item, artifact_id) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, artifact_id) for item in value]
    return artifact_id if value in ("REPLACE_UPLOADED_IMAGE_ID", "REPLACE_OWNED_IMAGE_ARTIFACT_ID") else value


def output_for(scenario, identity):
    for message in reversed(scenario.root.state["messages"]):
        if message.get("role") == "tool" and message.get("tool_call_id") == identity:
            output = json.loads(message["content"])
            assert not output.get("error"), output
            return output
    raise AssertionError(identity)


@pytest.mark.parametrize("case", ["portrait", "video"])
def test_actual_prompt_and_loaded_skill_examples_are_identical_and_write_valid_briefs(app_ctx, case):
    artifact = image_attachment()
    ids = [artifact.artifact_id] if case == "portrait" else []
    run, _root, ctx = make_context(ids=ids, text=TEXTS[case])
    registry = build_v3_registry()
    loaded = registry.invoke("load_skill", {"name": "intent-analysis"}, next_context(ctx))["output"]
    skill = parse_examples(loaded["body"])
    prompt = parse_examples(get_catalog().prompts["producer"])
    assert skill == prompt
    command = substitute(skill[case], artifact.artifact_id)
    checked = WriteInput.model_validate(command)
    RequirementBrief.model_validate(checked.payload)
    before = Job.query.count()
    response = registry.invoke("write_workspace", command, next_context(ctx))["output"]
    row = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key="brief", version=1).one()
    assert row.payload == response["payload"]
    assert row.payload["production_intent"] is False
    assert row.payload["constraints"]["compress_output"] is False
    assert Job.query.count() == before
    if case == "portrait":
        assert row.payload["subjects"][0]["attachment_ids"] == ids
    else:
        assert row.payload["constraints"]["model_preferences"] == ["wan2.7系列"]
        assert row.payload["constraints"]["model_exclusions"] == ["happy-horse"]


@pytest.mark.parametrize("change", ["string_subject", "string_boolean", "old_constraint", "unknown_source"])
def test_examples_do_not_introduce_ambiguous_schema_normalization(app_ctx, change):
    payload = deepcopy(parse_examples(get_catalog().prompts["producer"])["video"]["payload"])
    if change == "string_subject":
        payload["subjects"] = ["海浪与礁石"]
    elif change == "string_boolean":
        payload["production_intent"] = "false"
    elif change == "old_constraint":
        payload["constraints"]["model_family_required"] = "wan2.7"
    else:
        payload["subjects"][0]["source"] = "inferred"
    with pytest.raises(AppError) as rejected:
        validate_payload("brief", payload)
    assert rejected.value.code == "INVALID_WORKSPACE_PAYLOAD"


@pytest.mark.parametrize("case,recipe,index", [
    ("portrait", "image-edit", "0"), ("video", "single-clip", "1"),
])
def test_brief_body_drives_four_round_simple_path_without_schema_correction(app_ctx, client, case, recipe, index):
    ids = [upload_image(client)] if case == "portrait" else []
    scenario = Scenario(app_ctx, client, TEXTS[case], attachment_ids=ids)
    calls = [call("load_skill", {"name": "intent-analysis"}, "intent"),
             call("load_skill", {"name": recipe}, "recipe"),
             call("list_models", {"mode": "i2i" if ids else "i2v"})]
    if ids:
        calls.append(call("analyze_images", {"artifact_ids": ids, "focus": "确认需保留的人物身份"}))
    scenario.step("producer", calls, vision_ids=ids or None)
    understood = substitute(parse_examples(output_for(scenario, "intent")["body"])[case], ids[0] if ids else "")
    body = output_for(scenario, "recipe")["body"]
    params = json.loads(dict(BLUEPRINTS.findall(body))[index])
    draft = json.loads(dict(PLANS.findall(body))[index])
    params = substitute(params, ids[0] if ids else "")
    draft = substitute(draft, ids[0] if ids else "")
    frame = "白底、深色西装、正面证件照，保留上传人物身份" if ids else "海浪拍打礁石，海边静态首帧"
    params["plan"]["image"]["prompt"] = frame
    next(n for n in draft["nodes"] if n["id"] == "image")["inputs"]["prompt"] = frame
    if case == "video":
        params["plan"]["video"]["prompt"] = "海浪涌起拍打礁石，水花自然落回海面，固定镜头"
        next(n for n in draft["nodes"] if n["id"] == "video")["inputs"]["prompt"] = params["plan"]["video"]["prompt"]
    scenario.step("producer", [call("write_workspace", understood), call("check_plan", {"plan": draft})])
    checked = scenario.output("producer", "check_plan")
    assert checked["issues"] == []
    for key, model in checked["resolved_models"].items():
        params["plan"][key]["model_id"] = model
    scenario.step("producer", [call("instantiate_blueprint", {"name": recipe, "params": params})])
    built = scenario.output("producer", "instantiate_blueprint")
    assert built["issues"] == []
    scenario.step("producer", [call("submit_plan", {"plan_ref": built["workspace_ref"]})])
    assert scenario.root.steps == scenario.root.llm_calls == 4
    assert AgentDelegation.query.filter_by(run_id=scenario.run.run_id).count() == 1
    messages = scenario.root.state["messages"]
    names = [m["name"] for m in messages if m.get("role") == "tool"]
    assert not set(names) & {"delegate", "read_skill_resource", "read_workspace", "finish"}
    assert names.count("analyze_images") == bool(ids)
    assert all(not json.loads(m["content"]).get("error") for m in messages if m.get("role") == "tool")
    version = AgentPlanVersion.query.filter_by(run_id=scenario.run.run_id).one()
    if case == "video":
        video = next(n for n in version.plan["nodes"] if n["id"] == "video")
        assert video["model_id"] == "wan2.7-i2v" and video["params"]["duration"] == 5
    scenario.assert_review_only()


BEATS = ["清晨空站的灯亮起", "列车驶出车站", "列车穿过花田", "天空转阴",
         "前方桥梁损坏", "列车在桥前停下", "维修机械抵达", "机械修复桥梁",
         "乌云散开", "列车驶过修好的桥", "列车抵达终点", "夕阳下车站灯光渐亮"]


def complete_plot_plan():
    nodes = []
    for index, text in enumerate(BEATS):
        frame, clip = f"frame_{index}", f"clip_{index}"
        common = {"origin": {"agent": "director", "skills": ["long-form-video"]},
                  "rationale": "保持用户已给情节及顺序，只做镜头技术规划"}
        nodes.append({"id": frame, "tool": "generate_image", "model_id": None,
            "inputs": {"mode": "t2i", "prompt": text + "，二维动画静态构图"},
            "params": {"n": 1}, "gate": "preview", **deepcopy(common)})
        nodes.append({"id": clip, "tool": "animate_shot", "model_id": None,
            "inputs": {"first_frame_artifact_id": {"ref": frame + ".image"}, "prompt": text},
            "params": {"duration": 10}, **deepcopy(common)})
    extra, deliverables = delivery_nodes([{"ref": f"clip_{i}.video"} for i in range(12)],
        "story-video", "director", compress_output=False)
    for item in extra:
        item["origin"].pop("blueprint", None)
        item.pop("stage", None)
    return {"title": "列车与桥", "goal": "忠实执行用户给定的十二段完整情节",
            "nodes": nodes + extra, "deliverables": deliverables}


def test_complete_user_plot_can_reach_review_through_director_without_story_or_creative(app_ctx, client):
    text = "制作120秒短片，情节已确定，每段10秒，顺序不可改：" + "；".join(BEATS)
    scenario = Scenario(app_ctx, client, text, budget=200)
    brief_ref, source_ref = {"key": "brief", "version": 1}, {"key": "user_plot", "version": 1}
    scenario.step("producer", [write("brief", "brief", brief("video", "按完整剧情制作列车短片",
        target_duration_sec=120, duration_tolerance_sec=0)),
        write("user_plot", "note", {"text": text}),
        delegate("director", [brief_ref, source_ref], task="原情节已完整，只做技术分镜，不委派Creative。",
                 expected="PlanDraft", planning_credits=8)])
    draft = complete_plot_plan()
    plan_ref = {"key": "direct_plan", "version": 1}
    scenario.step("director", [read(source_ref), write("direct_plan", "plan_draft", draft),
                               call("check_plan", {"plan": draft})])
    assert scenario.output("director", "check_plan")["issues"] == []
    scenario.step("director", [finish(plan_ref=plan_ref, rationale="忠实采用用户情节，十二段各十秒。")])
    scenario.step("producer", [call("submit_plan", {"plan_ref": plan_ref})])
    assert {d.agent for d in AgentDelegation.query.filter_by(run_id=scenario.run.run_id)} == {"producer", "director"}
    assert AgentWorkspaceItem.query.filter_by(run_id=scenario.run.run_id, kind="story").count() == 0
    assert scenario.workspace(source_ref)["text"] == text
    version = AgentPlanVersion.query.filter_by(run_id=scenario.run.run_id).one()
    assert version.check["estimates"]["video_seconds"] == 120
    scenario.assert_review_only()


def test_complete_plot_does_not_remove_research_authority_or_copy_story_content(app_ctx, client):
    text = "完整情节：列车出发、遇断桥、修桥、抵达终点。片长120秒；车身用本周新发布品牌图案，先核实外观。"
    scenario = Scenario(app_ctx, client, text, budget=200)
    scenario.step("producer", [write("brief", "brief", brief("video", text, target_duration_sec=120,
        research_needs=[{"query": "本周新发布品牌图案", "reason": "核实影响画面的时效性外观"}])),
        write("user_plot", "note", {"text": text}),
        delegate("research", [{"key": "brief", "version": 1}, {"key": "user_plot", "version": 1}],
                 task="只核实品牌外观，不改写已确定情节。", expected="Dossier", planning_credits=3)])
    delegates = AgentDelegation.query.filter_by(run_id=scenario.run.run_id).all()
    assert {d.agent for d in delegates} == {"producer", "research"}
    assert scenario.workspace({"key": "user_plot", "version": 1})["text"] == text
    assert Job.query.count() == 0
    # Stop at admission: this proves permissions/routing remain available,
    # not that a Stub demonstrated autonomous recognition or real research.
    assert not ToolInvocation.query.filter_by(budget_scope=scenario.run.run_id, tool_name="request_preview").count()
