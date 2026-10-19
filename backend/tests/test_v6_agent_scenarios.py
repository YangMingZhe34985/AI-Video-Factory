"""V6 scripted acceptance through real collaboration, tools and review submission.

These are offline process checks, not evidence of autonomous creative quality.
Prices, character appearances and scripted decisions are demonstration fixtures.
No test approves production, requests a preview, or calls a real model.
"""
from copy import deepcopy

import pytest

from app.extensions import db
from app.models import AgentDelegation, AgentWorkspaceItem, ToolInvocation
from app.services.job_run_service import JobRunService
from tests.v6_scenario_support import (
    Scenario, attachment, brief, call, clip_plan, delegate, finish, image_plan, read,
    upload_image, upload_video, write,
)

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)


def test_photo_edit_batches_input_understanding_without_delegation(app_ctx, client):
    identity = upload_image(client)
    style = upload_image(client, "#27394a")
    scenario = Scenario(app_ctx, client, "把第一张照片中的我改成西装照，第二张只参考蓝色服装风格。", attachment_ids=[identity, style])
    scenario.step("producer", [call("load_skill", {"name": "intent-analysis"}),
        call("analyze_images", {"artifact_ids": [identity, style], "focus": "分别识别身份照片与服装风格"})], vision_ids=[identity, style])
    scenario.step("producer", [write("brief", "brief", brief("image", "改成一张蓝色西装照", attachments=[
        attachment(identity, "identity_ref"), attachment(style, "style_ref", reason="Only use its clothing color, not its identity")]))])
    ref = scenario.blueprint("producer", "image-edit", {"plan": image_plan(refs=[identity], mode="i2i")})
    version = scenario.submit(ref)
    assert AgentDelegation.query.filter_by(run_id=scenario.run.run_id).count() == 1
    analyses = ToolInvocation.query.filter_by(budget_scope=scenario.run.run_id, tool_name="analyze_images").all()
    assert len(analyses) == 1 and analyses[0].input_payload["artifact_ids"] == [identity, style]
    assert [role for role, _step in scenario.calls].count("vision") == 1
    assert len(version.plan["nodes"]) == 1
    node = version.plan["nodes"][0]
    assert node["tool"] == "generate_image" and node["inputs"]["mode"] == "i2i"
    assert node["inputs"]["reference_artifact_ids"] == [{"artifact": identity}]
    assert "blue suit" in node["inputs"]["prompt"]
    assert version.plan["deliverables"] == [{"kind": "image", "node_id": "image", "output": "images"}]
    scenario.assert_review_only()


@pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, DEFAULT_I2V_MODEL="wan2.6-i2v-flash")
@pytest.mark.parametrize("explicit,duration", [(False, 5), (True, 5), (True, 10)])
def test_single_clip_uses_default_or_literal_family_and_explicit_seconds(app_ctx, client, explicit, duration):
    text = "生成一只猫跳舞的视频"
    if explicit:
        text += "，只用wan2.7系列视频模型"
    if duration == 10:
        text += "，长度10秒"
    scenario = Scenario(app_ctx, client, text)
    constraints = {"model_preferences": ["wan2.7系列"] if explicit else []}
    scenario.step("producer", [call("load_skill", {"name": "intent-analysis"}),
        call("list_models", {"mode": "i2v"}), write("brief", "brief", brief("video", text,
            constraints=constraints, target_duration_sec=duration, duration_tolerance_sec=0))])
    catalog = scenario.output("producer", "list_models")["models"]
    if explicit:
        model = "wan2.7-i2v"
        selected_plan = clip_plan(model, duration)
    else:
        # Ask the actual compiler to resolve unspecified models. The scripted
        # producer consumes this result; it does not guess the fixture default.
        unresolved = {"title": "猫跳舞", "goal": text,
            "deliverables": [{"kind": "video", "node_id": "video", "output": "video"}],
            "nodes": [
                {"id": "image", "tool": "generate_image", "model_id": None,
                 "inputs": {"mode": "t2i", "prompt": "A cat in a blue suit"}, "params": {"n": 1},
                 "origin": {"agent": "producer", "skills": ["single-clip"]}, "rationale": "Create one opening frame"},
                {"id": "video", "tool": "animate_shot", "model_id": None,
                 "inputs": {"first_frame_artifact_id": {"ref": "image.image"}, "prompt": "The cat dances slowly"},
                 "params": {"duration": duration}, "origin": {"agent": "producer", "skills": ["single-clip"]},
                 "rationale": "Use the server video default when the user did not choose a model"}]}
        scenario.step("producer", [call("check_plan", {"plan": unresolved})])
        resolved = scenario.output("producer", "check_plan")
        assert resolved["issues"] == [], resolved["issues"]
        model = resolved["resolved_models"]["video"]
        selected_plan = clip_plan(model, duration)
        selected_plan["image"]["model_id"] = resolved["resolved_models"]["image"]
    assert model in {entry["model_id"] for entry in catalog}
    ref = scenario.blueprint("producer", "single-clip", {"plan": selected_plan})
    version = scenario.submit(ref)
    nodes = {item["id"]: item for item in version.plan["nodes"]}
    assert len(nodes) == 2 and AgentDelegation.query.count() == 1
    assert nodes["video"]["model_id"] == model and nodes["video"]["params"]["duration"] == duration
    assert model == ("wan2.7-i2v" if explicit else "wan2.6-i2v-flash")
    assert nodes["image"]["model_id"] == "wan2.6-image"
    assert nodes["video"]["inputs"]["first_frame_artifact_id"] == {"ref": "image.image"}
    assert version.check["estimates"]["video_seconds"] == duration
    assert version.check["estimates"]["generated_video_seconds"] == duration
    quoted = {item["node_id"]: item for item in version.check["estimates"]["nodes"]}
    assert quoted["video"]["output_video_seconds"] == duration
    assert quoted["video"]["estimated_cost"] == duration  # Seeded demonstration rate: 1 credit/second.
    assert version.check["estimates"]["total_credits"] == duration + 2  # One demonstration first frame.
    scenario.assert_review_only()


def _source(hit, fetched_at, kind):
    return {"source_id": hit["result_id"], "kind": kind,
        "url": hit["url"] if kind == "web" else hit["source_page_url"], "title": hit["title"],
        "site": hit.get("site", "CineCrew Mock"), "published_at": hit.get("published_at"), "retrieved_at": fetched_at}


def _research(scenario):
    scenario.step("research", [call("load_skill", {"name": "web-research"}),
        call("web_search", {"query": "AI anime characters official or fan interpretation", "max_results": 1}),
        call("image_search", {"query": "ChatGPT anime character", "max_results": 2})])
    web = scenario.output("research", "web_search")
    images = scenario.output("research", "image_search")
    scenario.step("research", [call("fetch_page", {"run_id": scenario.run.run_id, "url": web["results"][0]["url"]}),
        *[call("download_reference", {"run_id": scenario.run.run_id, "image_url": hit["image_url"],
            "source_page_url": hit["source_page_url"], "entity": "ChatGPT"}, f"download_{index}")
          for index, hit in enumerate(images["results"])]] )
    downloads = ToolInvocation.query.filter_by(budget_scope=scenario.run.run_id, tool_name="download_reference", status="success").order_by(ToolInvocation.id).all()
    assert len(downloads) == 2
    reference_ids = [row.output_payload["reference_id"] for row in downloads]
    question = {"question_id": "cg_look", "text": "这两种演示形象，你更想采用哪一个？",
        "why": "检索出现多个同人形象，无法认定唯一标准", "blocking": True,
        "options": [{"option_id": f"candidate_{index + 1}", "label": f"形象 {index + 1}", "image_artifact_id": value}
                    for index, value in enumerate(reference_ids)]}
    dossier = {"sources": [_source(web["results"][0], web["fetched_at"], "web"),
        *[_source(hit, images["fetched_at"], "image") for hit in images["results"]]],
        "topics": [{"topic_id": "interpretation", "query": web["query"], "summary": "演示资料不能证明现实主流形象。",
            "confidence": 0.5, "key_facts": [{"fact": "当前来源为离线演示，用户需要选择形象。", "source_ids": [web["results"][0]["result_id"]]}]}],
        "entities": [{"entity_id": "cg", "name": "ChatGPT", "description": "演示同人角色", "candidates": [
            {"candidate_id": f"candidate_{index + 1}", "reference_id": value, "source_id": images["results"][index]["result_id"],
             "traits": [], "why": "用可见服饰与发饰区别候选"} for index, value in enumerate(reference_ids)]}],
        "open_questions": [question], "warnings": ["角色和受欢迎程度都是演示数据，不代表真实流行度。"]}
    scenario.step("research", [call("analyze_images", {"artifact_ids": reference_ids, "focus": "比较角色服饰和发饰"}),
        write("research", "research_dossier", dossier), finish(dossier_ref={"key": "research", "version": 1})], vision_ids=reference_ids)
    validated = scenario.workspace({"key": "research", "version": 1})
    assert validated["stats"] == {"web_searches": 1, "image_searches": 1, "pages_fetched": 1, "references_downloaded": 2}
    assert all(candidate["traits"] for candidate in validated["entities"][0]["candidates"])
    return reference_ids, question


def _story(reference_id):
    return {"story": {"logline": "AI角色找回遗失的颜色", "synopsis": "主角在档案馆发现遗失颜色，并带它回到广场分享。",
        "acts": [{"act_id": "a1", "title": "寻找", "summary": "发现遗失颜色"}, {"act_id": "a2", "title": "分享", "summary": "把颜色带回城市"}],
        "beats": [{"beat_id": f"b{index}", "act_id": "a1" if index <= 4 else "a2", "summary": f"推进故事的第{index}步",
            "duration_sec": 15, "character_ids": ["cg"], "location": "档案馆" if index <= 4 else "广场", "emotion": "好奇"}
                  for index in range(1, 9)]},
        "characters": [{"character_id": "cg", "name": "ChatGPT 演示角色", "role": "主角", "lock_description": "固定绿色几何服装与同一发饰",
            "personality": "好奇、善意", "reference": {"source": "research", "artifact_ids": [reference_id], "research_entity_id": "cg"}}],
        "style": {"visual_style": "二维动画", "palette": "绿色与金色", "lighting": "柔光", "camera_language": "稳定跟拍", "prompt_prefix": "二维动画，角色外观保持一致"}}


def _board():
    shots = []
    for index in range(1, 9):
        tail = index % 2 == 0
        shots.append({"shot_id": f"s{index:02d}", "scene_id": "archive" if index <= 4 else "square", "order": index,
            "beat_ids": [f"b{index}"], "character_ids": ["cg"], "summary": f"故事镜头 {index}", "framing": "中景",
            "duration_sec": 15.0, "transition_in": "tail_frame" if tail else "start" if index == 1 else "independent",
            "first_frame": {"method": "tail_frame"} if tail else {"method": "generate", "image_mode": "i2i", "model_id": "wan2.7-image",
                "prompt": "绿色几何服装的同一角色，保持参考图发饰与面部特征"},
            "motion": {"model_id": "wan2.7-i2v", "prompt": f"角色完成动作 {index}，镜头缓缓跟随", "params": {"duration": 15}},
            "rationale": "同场动作继承尾帧，换机位独立生成首帧"})
    return {"title": "找回颜色", "target_duration_sec": 120.0, "aspect_ratio": "16:9",
            "scenes": [{"scene_id": "archive", "location": "档案馆", "time_of_day": "上午", "summary": "发现颜色"},
                       {"scene_id": "square", "location": "广场", "time_of_day": "下午", "summary": "分享颜色"}], "shots": shots}


def test_long_story_research_choice_and_specialists_submit_real_reviewable_plan(app_ctx, client):
    text = "做一个关于ChatGPT动漫形象的两分钟原创故事，先确定形象，视频只用wan2.7系列，不压缩。"
    # Production estimate needs more than 100 demo credits; Agent planning stays at its real default of 20.
    scenario = Scenario(app_ctx, client, text, budget=200)
    brief_ref = {"key": "brief", "version": 1}
    research_ref = {"key": "research", "version": 1}
    scenario.step("producer", [call("load_skill", {"name": "delegation-policy"}), write("brief", "brief", brief("video", text,
        target_duration_sec=120, duration_tolerance_sec=0, constraints={"model_preferences": ["wan2.7系列"]},
        research_needs=[{"query": "ChatGPT动漫形象", "reason": "形象有多个同人版本"}])),
        delegate("research", [brief_ref], task="查明演示资料范围，比较两种角色形象，给出可追溯候选。", expected="Dossier")])
    reference_ids, question = _research(scenario)
    scenario.step("producer", [read(research_ref), call("ask_user", {"questions": [question]})])
    assert scenario.run.status == "awaiting_input"
    assert AgentWorkspaceItem.query.filter_by(run_id=scenario.run.run_id, kind="story").count() == 0
    card = scenario.output("producer", "ask_user")["card"]
    answer = {"action": "answer", "request_key": "choose-candidate-2", "card_id": card["card_id"],
              "answers": [{"question_id": "cg_look", "option_id": "candidate_2"}]}
    url = f"/api/agent/runs/{scenario.run.run_id}/actions"
    assert client.post(url, json=answer).status_code == 202
    assert client.post(url, json=answer).status_code == 202
    choice_ref = {"key": "clarification." + card["card_id"], "version": 1}
    selected_ref = {"key": "selected_identity", "version": 1}
    scenario.step("producer", [read(choice_ref), write("selected_identity", "note", {"candidate_id": "candidate_2", "reference_artifact_ids": [reference_ids[1]]}),
        delegate("creative", [brief_ref, research_ref, choice_ref, selected_ref], task="用确认的第二形象写120秒故事，不更改硬约束。", expected="StoryPackage")])
    story_ref = {"key": "story", "version": 1}
    scenario.step("creative", [call("load_skill", {"name": "long-form-video"}), write("story", "story", _story(reference_ids[1])), finish(story_ref=story_ref)])
    # Reserve seven of the Producer's remaining credits for four Director
    # rounds and its two useful specialists. Repeated default half-allocations
    # would starve Critic even though the unchanged 20-credit Run pool suffices.
    scenario.step("producer", [read(story_ref), delegate("director", [brief_ref, research_ref, choice_ref, story_ref],
        task="分成8个15秒镜头；连续动作串行、独立机位可并行；验证提示词与最终计划。", expected="PlanDraft", planning_credits=7)])
    original_ref = scenario.blueprint("director", "story-video", {"plan": _board(), "story": scenario.workspace(story_ref)})
    original = scenario.workspace(original_ref)
    scenario.step("director", [delegate("prompt_smith", [original_ref], task="仅优化s01的动作提示词，保持全部非提示词字段。", expected="PromptUpdates",
        prompt_scope={"plan_ref": original_ref, "node_ids": ["s01"]})])
    refined_prompt = "同一绿色服装角色轻轻推开档案门，停顿后望向发光文件，镜头平稳缓慢推进"
    scenario.step("prompt_smith", [call("load_skill", {"name": "i2v-prompt-writing"}), finish(updates=[{"node_id": "s01", "inputs_patch": {"prompt": refined_prompt}}])])
    refined = deepcopy(original)
    updates = scenario.agent("prompt_smith").output["updates"]
    for update in updates:
        next(node for node in refined["nodes"] if node["id"] == update["node_id"])["inputs"].update(update["inputs_patch"])
    final_ref = {"key": "final_story_plan", "version": 1}
    scenario.step("director", [write("final_story_plan", "plan_draft", refined), call("check_plan", {"plan": refined}),
        delegate("critic", [brief_ref, story_ref, final_ref], task="检查120秒总长、角色来源、衔接依赖、按秒费用和未批准状态。", expected="CriticReview")])
    scenario.step("critic", [call("load_skill", {"name": "plan-review"}), call("check_plan", {"plan": scenario.workspace(final_ref)}),
        write("review", "critic_review", {"verdict": "pass", "issues": []}), finish(verdict="pass", issues=[])])
    assert scenario.output("critic", "check_plan")["issues"] == []
    scenario.step("director", [read({"key": "review", "version": 1}), finish(plan_ref=final_ref, rationale="引用已确认形象，依赖与报价已校验。")])
    version = scenario.submit(final_ref)
    assert {row.agent for row in AgentDelegation.query.filter_by(run_id=scenario.run.run_id)} == {"producer", "research", "creative", "director", "prompt_smith", "critic"}
    nodes = {node["id"]: node for node in version.plan["nodes"]}
    assert len([node for node in nodes.values() if node["tool"] == "animate_shot"]) == 8
    assert nodes["s01"]["inputs"]["prompt"] == refined_prompt
    assert nodes["s02_first"]["inputs"]["video_artifact_id"] == {"ref": "s01.video"}
    assert version.check["dag"]["dependencies"]["s03_first"] == []
    for node in nodes.values():
        if node["tool"] == "generate_image":
            assert node["inputs"]["reference_artifact_ids"] == [{"artifact": reference_ids[1]}]
            assert node["gate"] == "preview"
        if node["tool"] == "animate_shot":
            assert node["model_id"] == "wan2.7-i2v" and node["params"]["duration"] == 15
    assert nodes["compose"]["inputs"]["compress_output"] is False
    assert nodes["package"]["depends_on"] == ["qc"]
    assert version.check["estimates"]["video_seconds"] == version.check["estimates"]["generated_video_seconds"] == 120
    assert sum(item["estimated_cost"] for item in version.check["estimates"]["nodes"] if item["node_id"] in {f"s{i:02d}" for i in range(1, 9)}) == 120
    assert scenario.workspace(original_ref) == original  # Prompt refinement never overwrites the source draft.
    assert version.plan["experimental"] is True  # A changed Blueprint is not silently re-certified.
    scenario.assert_review_only()


def test_remix_consumes_async_analysis_but_keeps_source_range_and_generated_time_separate(app_ctx, client, tmp_path, monkeypatch):
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    source = upload_video(client, tmp_path)
    text = "保留原片0到1秒，把原片1到2.5秒改成猫向前走的5秒片段，不压缩。"
    scenario = Scenario(app_ctx, client, text, attachment_ids=[source])
    scenario.step("producer", [call("load_skill", {"name": "video-remix"}), call("analyze_video", {"source_artifact_id": source})])
    launch = scenario.output("producer", "analyze_video")
    scenario.step("producer", [call("get_task_status", {"job_id": launch["job_id"]})])
    status = scenario.output("producer", "get_task_status")
    assert status["terminal"] is True and status["status"] == "success"
    assert status["prompts"]["t2v"]  # Dense analysis text; this is not a time-coded shot detector.
    scenario.step("producer", [write("analysis", "note", {"summary": status["prompts"]["t2v"], "job_id": launch["job_id"]}),
        write("brief", "brief", brief("video", text, attachments=[attachment(source, "remix_source", kind="video")],
            target_duration_sec=6, duration_tolerance_sec=0)), delegate("director", [{"key": "brief", "version": 1}, {"key": "analysis", "version": 1}],
            task="按用户明确区间保留与替换；原区间长1.5秒，但新生成段5秒。", expected="PlanDraft")])
    params = {"source_artifact_id": source, "plan": {"title": "局部改造", "mode": "remix", "shots": [
        {"shot_id": "keep", "action": "keep", "source_start": 0.0, "source_end": 1.0, "edit_reason": "保留原片开头"},
        {"shot_id": "replace", "action": "regenerate", "source_start": 1.0, "source_end": 2.5, "edit_reason": "只替换用户指定原区间",
         "first_frame_mode": "source", "i2v_prompt": "猫向前走，保持原片构图", "video_model_id": "wan2.7-i2v", "video_params": {"duration": 5}}]}}
    ref = scenario.blueprint("director", "video-remix", params)
    scenario.step("director", [call("check_plan", {"plan": scenario.workspace(ref)}), finish(plan_ref=ref, rationale="原区间1.5秒和新片段5秒分开表达。")])
    version = scenario.submit(ref)
    nodes = {node["id"]: node for node in version.plan["nodes"]}
    assert nodes["s001"]["tool"] == "retain_video_segment"
    assert nodes["s001"]["inputs"]["source_end_sec"] - nodes["s001"]["inputs"]["source_start_sec"] == 1
    assert nodes["s002_frame"]["inputs"]["timestamp_sec"] == 1
    assert nodes["s002"]["params"]["duration"] == 5
    assert version.check["estimates"]["video_seconds"] == 6
    assert version.check["estimates"]["generated_video_seconds"] == version.check["estimates"]["total_credits"] == 5
    assert nodes["compose"]["inputs"]["compress_output"] is False
    assert AgentDelegation.query.filter_by(run_id=scenario.run.run_id, agent="creative").count() == 0
    scenario.assert_review_only(allow_analysis=True)
