"""Independent Phase C review edge cases using persisted Mock graph and Jobs."""

from copy import deepcopy

import pytest

from app.agent import creative_v2 as creative_module, story_graph
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ModelRegistry, ToolInvocation
from app.services.node_runner import NodeRunner
from app.skills.budget import BudgetGuard
from tests.test_agent_v2_graph import create, image
from tests.test_story_review import TEXT, act, settle, storyboard, view

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
                               AGENT_VISION_MODEL="qwen3.7-plus")


@pytest.mark.parametrize("action", ["edit_plan", "regenerate"])
def test_maximum_length_request_key_survives_version_creation(app_ctx, client, action):
    run_id, before = storyboard(client)
    payload = {"request_key": "k" * 128}
    if action == "edit_plan":
        plan = deepcopy(before["plan"])
        plan["title"] = "修改标题，保持镜头不变"
        payload.update(plan=plan, base_version=before["plan_version"])
    else:
        payload.update(target_type="keyframe", target_id="s01")
    response = act(client, run_id, action, **payload)
    assert response.status_code == 202, response.json
    row = settle(run_id)
    assert row.status == "awaiting_storyboard", row.error or row.snapshot
    after = view(client, run_id)
    assert after["plan_version"] > before["plan_version"]
    count = ToolInvocation.query.count()
    assert act(client, run_id, action, **payload).status_code == 202
    assert ToolInvocation.query.count() == count


def test_budget_exhaustion_preserves_invalid_draft_at_review(app_ctx, client):
    run_id = create(TEXT, budget=5)
    row = settle(run_id)
    assert row.status == "awaiting_storyboard", row.error or row.snapshot
    current = view(client, run_id)
    assert current["plan"] and current["plan_version"] >= 1
    assert "BUDGET_EXCEEDED" in {issue["code"] for issue in current["plan_issues"]}
    assert any(shot["motion"]["prompt"] for shot in current["plan"]["shots"])
    assert not ToolInvocation.query.filter_by(budget_scope=run_id, tool_name="generate_image").count()
    assert BudgetGuard.spent(run_id) <= 5
    assert row.snapshot["story_repair_attempted"] is True


def test_consumed_review_command_can_resume_after_pre_effect_failure(app_ctx, client, monkeypatch):
    run_id, before = storyboard(client)
    original = story_graph.validate_command
    calls = []
    def fail_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise AppError("MOCK_REVIEW_TEMPORARY", "Injected pre-effect outage", 503)
        return original(*args, **kwargs)
    monkeypatch.setattr(story_graph, "validate_command", fail_once)
    paid_before = ToolInvocation.query.filter_by(tool_name="generate_image").count()
    assert act(client, run_id, "regenerate", target_type="keyframe", target_id="s01", request_key="resumable").status_code == 202
    failed = settle(run_id)
    assert failed.status == "needs_attention"
    assert failed.error["code"] == "MOCK_REVIEW_TEMPORARY"
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == paid_before
    assert act(client, run_id, "resume").status_code == 202
    resumed = settle(run_id)
    assert resumed.status == "awaiting_storyboard", resumed.error or resumed.snapshot
    assert view(client, run_id)["previews"]["keyframes"]["s01"]["artifact_id"] != before["previews"]["keyframes"]["s01"]["artifact_id"]
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == paid_before + 1


def test_existing_reference_cannot_accept_generated_portrait_prompt(app_ctx, client, monkeypatch):
    # This test exercises a mixed existing/generated character cast. Explicitly
    # configure a capable Mock image model instead of exceeding the seed limit.
    model = ModelRegistry.query.filter_by(model_id=app_ctx.config["DEFAULT_I2I_TEST_IMAGE_MODEL"]).one()
    model.capabilities = {**model.capabilities, "reference_images": {"max": 2}}
    db.session.commit()
    original = creative_module.mock_story
    def two_characters(data):
        package = original(data)
        assert package["characters"][0]["reference"]["source"] == "attachment"
        package["characters"].append({"character_id": "companion", "name": "伙伴", "role": "帮助主角", "lock_description": "红色围巾和白色背包",
            "personality": "沉着", "reference": {"source": "generate", "artifact_ids": [], "generate_prompt": "静态伙伴定妆图，红色围巾和白色背包"}})
        for beat in package["story"]["beats"]: beat["character_ids"].append("companion")
        return package
    monkeypatch.setattr(creative_module, "mock_story", two_characters)
    run_id = create("参考这张图片的风格，制作猫咪探索城市的故事短片，约2分钟", [image()], budget=500)
    row = settle(run_id)
    assert row.status == "awaiting_characters", row.error or row.snapshot
    character = next(c for c in view(client, run_id)["story"]["characters"] if c["reference"]["source"] == "attachment")
    response = act(client, run_id, "approve_characters", edits=[{"character_id": character["character_id"], "generate_prompt": "替换角色外观"}])
    assert response.status_code == 422, response.json
    assert AgentRun.query.filter_by(run_id=run_id).one().command is None


def test_failed_mock_image_job_returns_to_character_review_and_repairs_locally(app_ctx, client, monkeypatch):
    original = NodeRunner._submit_adapter
    injected = []
    def fail_one(self, adapter, model, payload, inputs, params, job, adapter_name, operation):
        if operation == "submit_first_frame_image" and not injected:
            injected.append(job.job_id)
            raise AppError("MOCK_PAID_JOB_FAILURE", "Injected image submit failure", 503)
        return original(self, adapter, model, payload, inputs, params, job, adapter_name, operation)
    monkeypatch.setattr(NodeRunner, "_submit_adapter", fail_one)
    run_id = create(TEXT, budget=500)
    row = settle(run_id)
    assert row.status == "awaiting_characters", row.error or row.snapshot
    initial = view(client, run_id)
    cid, preview = next(iter(initial["previews"]["characters"].items()))
    assert injected and preview["status"] == "failed"
    assert act(client, run_id, "approve_characters").status_code == 409
    spent = BudgetGuard.spent(run_id)
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 1
    assert act(client, run_id, "regenerate", target_type="character", target_id=cid, request_key="retry-failed-character").status_code == 202
    row = settle(run_id)
    assert row.status == "awaiting_characters", row.error or row.snapshot
    after = view(client, run_id)
    assert after["previews"]["characters"][cid]["status"] == "success"
    assert BudgetGuard.spent(run_id) > spent
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 2
    assert not ToolInvocation.query.filter(ToolInvocation.tool_name.in_(["animate_shot", "generate_video", "produce_shot"])).count()


def test_reused_previews_are_not_reserved_again_for_title_edit(app_ctx, client):
    run_id, before = storyboard(client)
    row = AgentRun.query.filter_by(run_id=run_id).one()
    row.request = {**row.request, "budget_limit": BudgetGuard.spent(run_id) + before["estimates"]["video_credits"]}
    db.session.commit()
    plan = deepcopy(before["plan"])
    plan["title"] = "仅更新片名"
    count = ToolInvocation.query.count()
    response = act(client, run_id, "edit_plan", plan=plan, base_version=before["plan_version"], request_key="title-only-budget")
    assert response.status_code == 202, response.json
    assert settle(run_id).status == "awaiting_storyboard"
    after = view(client, run_id)
    assert after["plan_issues"] == []
    assert after["estimates"]["preview_credits"] == 0
    assert ToolInvocation.query.count() == count
    assert act(client, run_id, "approve_storyboard", plan_version=after["plan_version"]).status_code == 202
    assert settle(run_id).status == "storyboard_approved"


def test_portrait_edits_wait_for_explicit_regeneration_before_keyframes(app_ctx, client):
    run_id = create(TEXT, budget=500)
    assert settle(run_id).status == "awaiting_characters"
    before = view(client, run_id)
    cid = next(iter(before["previews"]["characters"]))
    paid_before = ToolInvocation.query.filter_by(tool_name="generate_image").count()
    response = act(client, run_id, "approve_characters", edits=[{"character_id": cid,
        "lock_description": "金色眼睛、蓝色短发、白色外套与圆形徽章", "generate_prompt": "全身静态定妆图，白色外套"}])
    assert response.status_code == 202, response.json
    row = settle(run_id)
    assert row.status == "awaiting_characters", row.error or row.snapshot
    after = view(client, run_id)
    assert after["previews"]["characters"][cid]["stale"]
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == paid_before
    assert act(client, run_id, "approve_characters").status_code == 409
    assert act(client, run_id, "regenerate", target_type="character", target_id=cid, request_key="new-character-design").status_code == 202
    assert settle(run_id).status == "awaiting_characters"
    assert act(client, run_id, "approve_characters").status_code == 202
    row = settle(run_id)
    assert row.status == "awaiting_storyboard", row.error or row.snapshot
    assert all(item["status"] == "success" for item in view(client, run_id)["previews"]["keyframes"].values())



def test_empty_motion_prompt_is_not_accepted_for_video_production(app_ctx, client):
    run_id, before = storyboard(client)
    plan = deepcopy(before["plan"])
    plan["shots"][0]["motion"]["prompt"] = ""
    response = act(client, run_id, "edit_plan", plan=plan, base_version=before["plan_version"], request_key="empty-motion")
    assert response.status_code == 202, response.json
    assert settle(run_id).status == "awaiting_storyboard"
    current = view(client, run_id)
    if current["plan"]["shots"][0]["motion"]["prompt"]:
        return  # Rewriting the explicitly cleared prompt is also valid repair.
    response = act(client, run_id, "approve_storyboard", plan_version=current["plan_version"])
    assert response.status_code == 422, response.json
    assert response.json["error"]["code"] == "INVALID_PRODUCTION_PLAN"
    assert AgentRun.query.filter_by(run_id=run_id).one().command is None


def test_saved_character_edit_replays_without_rewriting_prompts_after_catalog_change(app_ctx, client, monkeypatch):
    run_id = create(TEXT, budget=500)
    assert settle(run_id).status == "awaiting_characters"
    initial = view(client, run_id)
    cid = next(iter(initial["previews"]["characters"]))
    original = story_graph._save
    injected = []
    def save_then_fail(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("author") == "user" and not injected:
            injected.append(result.version)
            raise AppError("MOCK_AFTER_VERSION_COMMIT", "Injected checkpoint gap", 503)
        return result
    monkeypatch.setattr(story_graph, "_save", save_then_fail)
    assert act(client, run_id, "approve_characters", edits=[{"character_id": cid, "lock_description": "蓝色短发，银色围巾与白色外套"}]).status_code == 202
    row = settle(run_id)
    assert row.status == "needs_attention" and row.error["code"] == "MOCK_AFTER_VERSION_COMMIT"
    assert injected and view(client, run_id)["plan_version"] == injected[0]
    written = ToolInvocation.query.filter_by(tool_name="write_shot_prompts").count()
    # A completed version is authoritative even if model notes changed while
    # the process was down; old paid prompts must not be written a second time.
    model = ModelRegistry.query.filter_by(model_id=app_ctx.config["DEFAULT_I2I_TEST_IMAGE_MODEL"]).one()
    model.capabilities = {**model.capabilities, "pricing": {**model.capabilities["pricing"], "credits_per_unit": 2.25}}
    db.session.commit()
    assert act(client, run_id, "resume").status_code == 202
    row = settle(run_id)
    assert row.status == "awaiting_characters", row.error or row.snapshot
    assert view(client, run_id)["plan_version"] == injected[0]
    assert ToolInvocation.query.filter_by(tool_name="write_shot_prompts").count() == written
