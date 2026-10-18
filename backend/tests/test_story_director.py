"""Director v2 uses catalog durations, server defaults and replayable decisions."""

from copy import deepcopy

import pytest

from app.agent.director_v2 import director_v2
from app.agent.production_plan import ProductionPlan, estimate_production_plan, normalized_plan
from app.api import AppError
from app.extensions import db
from app.models import ToolInvocation
from app.services.model_service import ModelService
from tests.test_director_lite import make_state, answer
from tests.test_simple_plan import request_spec


def story_state(budget=500, target=120):
    spec = request_spec("single_clip")
    spec.update(recipe_hint="story_video", target_duration_sec=target, summary="制作一部城市寻宝故事")
    state = make_state(spec, budget=budget)
    state["story_package"] = {
        "story": {"logline": "城市寻宝", "synopsis": "主人公寻找失落的声音。", "acts": [
            {"act_id": "a1", "title": "发现", "summary": "发现线索"},
            {"act_id": "a2", "title": "追寻", "summary": "前往广场"},
            {"act_id": "a3", "title": "回归", "summary": "带回声音"}],
            "beats": [{"beat_id": f"b{i}", "act_id": f"a{i}", "summary": "循着城市线索寻找声音",
                       "duration_sec": target // 3 if i < 3 else target - 2 * (target // 3),
                       "character_ids": ["hero"], "location": f"城市地点{i}", "emotion": "期待"} for i in range(1, 4)]},
        "characters": [{"character_id": "hero", "name": "小岚", "role": "主角", "lock_description": "蓝色短发，白色外套，星形发夹",
                        "personality": "好奇", "reference": {"source": "generate", "artifact_ids": [],
                        "research_entity_id": None, "generate_prompt": "蓝发白衣的年轻探险者，完整定妆照"}}],
        "style": {"visual_style": "动画", "palette": "青蓝暖橙", "lighting": "柔和光线", "camera_language": "稳定跟拍",
                  "prompt_prefix": "二维动画，细腻手绘质感。", "negative_prompt": None}, "open_questions": []}
    return state


def test_two_minute_director_preserves_duration_continuity_and_replays(app_ctx):
    state = story_state()
    result = director_v2(state)
    plan = result["plan"]
    assert ProductionPlan.model_validate(plan)
    assert sum(s["duration_sec"] for s in plan["shots"]) == 120
    assert plan["shots"][0]["transition_in"] == "start"
    assert all(s["motion"]["model_id"] == "wan2.7-i2v" for s in plan["shots"])
    assert all(s["duration_sec"] <= ModelService.get_model("wan2.7-i2v").capabilities["duration"]["max"] for s in plan["shots"])
    assert plan["estimates"] == {"preview_credits": 8, "video_credits": 120, "total_credits": 128}
    for previous, current in zip(plan["shots"], plan["shots"][1:]):
        same = previous["scene_id"] == current["scene_id"]
        assert current["transition_in"] == ("tail_frame" if same else "independent")
        assert current["depends_on"] == ([previous["shot_id"]] if same else [])
        assert current["first_frame"]["method"] == ("tail_frame" if same else "generate")
    assert director_v2(state) == result
    assert ToolInvocation.query.count() == 1


def test_cost_recomputed_from_seconds_and_server_dependency_ignores_llm(app_ctx):
    state = story_state()
    plan = director_v2(state)["plan"]
    shot = plan["shots"][1]
    shot["depends_on"] = [plan["shots"][-1]["shot_id"]]
    previous_duration = shot["duration_sec"]
    shot["duration_sec"] = 5
    shot["motion"]["params"]["duration"] = 900
    revised = normalized_plan(plan)
    assert revised["shots"][1]["depends_on"] == ["s01"]
    assert revised["shots"][1]["motion"]["params"]["duration"] == 5
    costs = estimate_production_plan(revised, state["story_package"], state["request_spec"])
    assert costs["video_credits"] == 120 - previous_duration + 5


def test_unavailable_family_asks_before_director_fee(app_ctx):
    state = story_state()
    state["request_spec"]["constraints"]["model_preferences"] = ["missing-family"]
    state["request_spec"]["constraints"]["model_exclusions"] = ["HappyHorse"]
    result = director_v2(state)
    assert result["plan"] is None
    assert result["open_questions"][0]["question_id"] == "model_i2v"
    assert ToolInvocation.query.count() == 0
    result = director_v2(answer(state, "i2v"))
    assert result["request_spec"]["constraints"]["model_exclusions"] == ["HappyHorse"]
    assert all(s["motion"]["model_id"] == "wan2.7-i2v" for s in result["plan"]["shots"])


def test_model_family_cannot_be_silently_replaced(app_ctx):
    state = story_state()
    state["request_spec"]["constraints"]["model_preferences"] = ["wan2.7"]
    state["request_spec"]["constraints"]["model_exclusions"] = ["HappyHorse"]
    result = director_v2(state)
    assert all(s["motion"]["model_id"] == "wan2.7-i2v" for s in result["plan"]["shots"])
    assert all(s["first_frame"]["model_id"] in {None, "wan2.7-image"} for s in result["plan"]["shots"])


def test_catalog_duration_limit_changes_shot_count_not_story_length(app_ctx):
    model = ModelService.get_model("wan2.7-i2v")
    model.capabilities = {**model.capabilities, "duration": {"min": 2, "max": 10, "step": 1}}
    db.session.commit()
    result = director_v2(story_state())
    assert len(result["plan"]["shots"]) == 12
    assert sum(s["duration_sec"] for s in result["plan"]["shots"]) == 120


def test_no_video_or_image_invocations_in_director(app_ctx):
    result = director_v2(story_state(budget=2))
    assert result["plan"]["estimates"]["total_credits"] > 2
    assert {row.tool_name for row in ToolInvocation.query.all()} == {"agent_director_v2"}


def test_director_repair_is_separate_idempotent_decision(app_ctx):
    state = story_state()
    state.update(director_v2(state))
    issues = [{"code": "DURATION_MISMATCH", "shot_id": None, "message": "wrong total"}]
    result = director_v2(state, issues=issues)
    assert director_v2(state, issues=issues) == result
    assert ToolInvocation.query.count() == 2


@pytest.mark.parametrize("value", [True, "15", float("nan"), float("inf"), -1])
def test_invalid_shot_duration_rejected_by_schema(app_ctx, value):
    from pydantic import ValidationError
    plan = director_v2(story_state())["plan"]
    plan["shots"][0]["duration_sec"] = value
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(plan)
