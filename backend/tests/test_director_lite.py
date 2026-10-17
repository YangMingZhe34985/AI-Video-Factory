"""Director planning stops for hard constraints and replays without rebilling."""

import pytest

from app.agent.director_lite import director_lite, model_question, resolved_request
from app.agent.simple_plan import validate_simple_plan
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ToolInvocation
from app.services.model_service import ModelService
from app.skills.budget import BudgetGuard
from app.utils.ids import new_id
from tests.test_simple_plan import image_reference, request_spec


def make_state(spec, budget=100):
    run = AgentRun(owner_id="owner", request_key=new_id("request"), request={
        "schema_version": 2, "text": spec["summary"], "budget_limit": budget,
        "attachment_ids": [item["attachment_id"] for item in spec.get("attachments", [])],
    })
    db.session.add(run)
    db.session.commit()
    return {"run_id": run.run_id, "request_spec": spec}


def answer(state, mode, *, option="server_default", source="user", text=None):
    question = model_question(mode, "unavailable")
    return {**state, "clarifications": [{"card": {"asked_by": "director", "questions": [question]},
        "answers": {f"model_{mode}": {"source": source, "option_id": option, "text": text}}}]}


def test_image_edit_director_generates_one_step_and_replays(app_ctx):
    ref = image_reference()
    spec = request_spec("image_edit", [ref])
    spec["summary"] = "生成我的一张西装照"
    state = make_state(spec)
    result = director_lite(state)
    assert result["plan"]["image"]["mode"] == "i2i"
    assert result["plan"]["video"] is None
    assert result["plan"]["image"]["reference_attachment_ids"] == [ref["attachment_id"]]
    assert result["plan"]["estimated_cost"] == 2
    assert director_lite(state) == result
    assert ToolInvocation.query.count() == 1
    assert BudgetGuard.spent(state["run_id"]) == 1


@pytest.mark.parametrize("use_first_frame", [False, True])
def test_single_clip_chooses_only_necessary_steps(app_ctx, use_first_frame):
    ref = image_reference() if use_first_frame else None
    if ref:
        ref["role"] = "first_frame"
    spec = request_spec("single_clip", [ref] if ref else [])
    spec["target_duration_sec"] = 5
    result = director_lite(make_state(spec))
    assert bool(result["plan"]["image"]) is not use_first_frame
    assert result["plan"]["video"]["first_frame"] == ("user_attachment" if use_first_frame else "generated_image")
    assert result["plan"]["estimated_cost"] == (5 if use_first_frame else 7)


def test_missing_model_asks_without_billing_then_explicit_user_default_can_continue(app_ctx):
    state = make_state(request_spec("single_clip", preferences=["nonexistent-series"], exclusions=["HappyHorse"]))
    initial = director_lite(state)
    assert initial["plan"] is None
    assert initial["open_questions"][0]["question_id"] == "model_i2v"
    assert ToolInvocation.query.count() == 0
    confirmed = director_lite(answer(state, "i2v"))
    assert confirmed["plan"]["video"]["model_id"] == "wan2.7-i2v"
    assert confirmed["request_spec"]["constraints"]["model_preferences"] == []
    assert confirmed["request_spec"]["constraints"]["model_exclusions"] == ["HappyHorse"]
    assert ToolInvocation.query.count() == 1


@pytest.mark.parametrize("option,source", [("keep", "user"), ("server_default", "default"), ("keep", "fallback")])
def test_unresolved_model_does_not_loop_or_relax_user_requirement(app_ctx, option, source):
    state = make_state(request_spec("single_clip", preferences=["nonexistent-series"]))
    with pytest.raises(AppError) as stopped:
        director_lite(answer(state, "i2v", option=option, source=source))
    assert stopped.value.code == "MODEL_CAPABILITY_MISMATCH"
    assert ToolInvocation.query.count() == 0


def test_model_answer_retains_exclusions(app_ctx):
    state = make_state(request_spec("single_clip", preferences=["nonexistent-series"], exclusions=["wan2.7"]))
    with pytest.raises(AppError):
        resolved_request(answer(state, "i2v", option=None, text="wan2.7-i2v"))


def test_unaffordable_generation_keeps_completed_director_cost(app_ctx):
    spec = request_spec()
    spec["output_count"] = 4
    state = make_state(spec, budget=3)
    for _ in range(2):
        result = director_lite(state)
        assert result["plan"]["image"]["n"] == 4
        assert result["plan_issues"][0]["code"] == "BUDGET_EXCEEDED"
    edited = result["plan"]
    edited["image"]["n"] = 1
    checked = validate_simple_plan(edited, spec, owner_id="owner", budget_scope=state["run_id"], budget_limit=3)
    assert checked["estimated_cost"] == 2
    assert ToolInvocation.query.count() == 1
    assert ToolInvocation.query.one().status == "success"
    assert BudgetGuard.spent(state["run_id"]) == 1


def test_multiple_first_frames_use_answer_instead_of_asking_again(app_ctx):
    refs = [image_reference(), image_reference()]
    for ref in refs:
        ref["role"] = "first_frame"
    state = make_state(request_spec("single_clip", refs))
    initial = director_lite(state)
    assert initial["plan"] is None
    assert initial["open_questions"][0]["question_id"] == "first_frame"
    state["clarifications"] = [{"card": {"asked_by": "director"}, "answers": {
        "first_frame": {"source": "user", "option_id": "1", "text": None},
    }}]
    result = director_lite(state)
    assert result["open_questions"] == []
    assert result["plan"]["video"]["first_frame_attachment_id"] == refs[1]["attachment_id"]


def test_unsupported_aspect_is_preserved_as_editable_draft(app_ctx):
    spec = request_spec()
    spec["aspect_ratio"] = "4:3"
    result = director_lite(make_state(spec))
    assert result["plan"]["image"]["params"] == {"ratio": "4:3"}
    assert result["plan_issues"][0]["code"] == "INVALID_INPUT"
    assert ToolInvocation.query.count() == 1


def test_explicit_server_default_does_not_bypass_its_exclusion(app_ctx):
    state = make_state(request_spec("single_clip", preferences=["missing-series"], exclusions=["wan2.7"]))
    with pytest.raises(AppError) as stopped:
        director_lite(answer(state, "i2v"))
    assert stopped.value.code == "MODEL_CAPABILITY_MISMATCH"
    assert ToolInvocation.query.count() == 0


def test_keep_model_requirement_can_resume_after_operator_restores_model(app_ctx):
    model = ModelService.get_model("wan2.7-i2v")
    model.enabled = False
    db.session.commit()
    state = make_state(request_spec("single_clip", preferences=["wan2.7"]))
    assert director_lite(state)["open_questions"][0]["question_id"] == "model_i2v"
    confirmed = answer(state, "i2v", option="keep")
    with pytest.raises(AppError):
        director_lite(confirmed)
    assert ToolInvocation.query.count() == 0
    model.enabled = True
    db.session.commit()
    result = director_lite(confirmed)
    assert result["request_spec"]["constraints"]["model_preferences"] == ["wan2.7"]
    assert result["plan"]["video"]["model_id"] == "wan2.7-i2v"
    assert ToolInvocation.query.count() == 1
