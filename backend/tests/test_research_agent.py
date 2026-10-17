"""B3 graph, provenance, partial failures and clarification recovery (Mock only)."""

from copy import deepcopy
from dataclasses import replace

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent import research
from app.agent.clarify import resolve_answers
from app.agent.graph_v2 import build_graph
from app.agent.research_spec import validate_dossier, validate_research_plan, validate_selection
from app.agent.worker import AgentWorker, checkpoint_path
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ApiTask, ToolInvocation
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from tests.test_agent_v2_graph import create, tick

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_VISION_MODEL="qwen3.7-plus")
TEXT = "创作一个 DeepSeek 与 ChatGPT 的 AI 拟人角色冒险故事视频，约2分钟，使用wan2.7系列，禁止happy-horse"


def run_research():
    run_id = create(TEXT, budget=500)
    return run_id, tick(run_id)


def answer(state):
    card = state["pending_card"]
    return {"action": "answer", "card_id": card["card_id"], "answers": [
        {"question_id": item["question_id"], "option_id": item["options"][-1]["option_id"]}
        for item in card["questions"]]}


def advance(run_id, registry):
    with SqliteSaver.from_conn_string(str(checkpoint_path())) as saver:
        AgentWorker(None, build_graph(saver, registry)).advance(run_id)
    db.session.expire_all()
    return AgentRun.query.filter_by(run_id=run_id).one()


def with_failure(registry, names, code):
    def fail(_data, _ctx):
        raise AppError(code, "Injected evidence failure", 503)
    # Replacing registered handlers keeps real Registry validation and ledger.
    for name in names:
        registry._specs[name] = replace(registry._specs[name], handler=fail)
    return registry


def test_story_research_dossier_choice_resume_and_no_generation(app_ctx, client):
    run_id, state = run_research()
    assert state["status"] == "awaiting_input", state
    assert state["pending_card"]["asked_by"] == "research"
    dossier = state["research_dossier"]
    assert len(dossier["entities"]) == 2
    assert all(len(item["candidates"]) == 3 for item in dossier["entities"])
    assert dossier["entities"][0]["selected_candidate_id"]
    assert dossier["entities"][1]["selected_candidate_id"] is None
    assert dossier["stats"]["web_searches"] == 1
    assert dossier["stats"]["image_searches"] == 2
    assert dossier["stats"]["references_downloaded"] == 6
    assert all(candidate["traits"] for item in dossier["entities"] for candidate in item["candidates"])
    constraints = deepcopy(state["request_spec"]["constraints"])
    calls = [(row.invocation_id, row.attempt, row.estimated_cost) for row in ToolInvocation.query.all()]
    spent = BudgetGuard.spent(run_id)
    question = state["pending_card"]["questions"][0]
    state = tick(run_id, answer(state))
    assert state["status"] == "awaiting_approval", state
    assert state["research_dossier"]["entities"][1]["selected_candidate_id"] == question["options"][-1]["option_id"]
    assert state["research_dossier"]["open_questions"] == []
    assert state["request_spec"]["constraints"] == constraints
    assert state["request_spec"]["attachments"] == []  # Generation reference binding belongs to Phase C.
    assert sum(shot["video_params"]["duration"] for shot in state["plan"]["shots"]) == 120
    assert ApiTask.query.count() == 0
    assert calls == [(row.invocation_id, row.attempt, row.estimated_cost) for row in ToolInvocation.query.order_by(ToolInvocation.id).limit(len(calls))]
    assert BudgetGuard.spent(run_id) > spent  # Only downstream Director/Creative calls were added.
    assert ToolInvocation.query.filter_by(tool_name="agent_research_synthesize").count() == 1
    view = client.get(f"/api/agent/runs/{run_id}").json["data"]
    assert view["research_dossier"] == state["research_dossier"]
    assert tick(run_id)["research_dossier"] == state["research_dossier"]


def test_ordinary_request_skips_all_research(app_ctx):
    run_id = create("生成一张猫咪的图片")
    state = tick(run_id)
    assert state["status"] == "awaiting_approval"
    assert "research_dossier" not in state
    assert not ToolInvocation.query.filter(ToolInvocation.tool_name.like("%research%"), ToolInvocation.budget_scope == run_id).count()


def test_latest_concept_web_only_keeps_short_recipe(app_ctx):
    run_id = create("用最新流行配色生成一张猫的图片")
    state = tick(run_id)
    assert state["status"] == "awaiting_approval", state
    assert state["plan"]["recipe"] == "image_create"
    assert state["research_dossier"]["topics"]
    assert state["research_dossier"]["entities"] == []
    assert ToolInvocation.query.filter_by(tool_name="image_search").count() == 0


def test_partial_search_and_fetch_failures_leave_visible_warnings(app_ctx):
    registry = with_failure(build_default_registry(), ["web_search", "download_reference"], "FETCH_FAILED")
    row = advance(create(TEXT, budget=500), registry)
    assert row.status == "awaiting_approval", row.error
    assert row.snapshot["research_dossier"]["warnings"]
    assert row.snapshot["research_dossier"]["entities"] == []
    assert row.snapshot["research_dossier"]["stats"]["image_searches"] == 2
    assert ApiTask.query.count() == 0


def test_all_search_failures_stop_with_checkpointed_diagnostics(app_ctx):
    registry = with_failure(build_default_registry(), ["web_search", "image_search"], "SEARCH_PROVIDER_UNAVAILABLE")
    run_id = create(TEXT, budget=500)
    row = advance(run_id, registry)
    assert row.status == "needs_attention"
    assert row.error["code"] == "SEARCH_PROVIDER_UNAVAILABLE"
    assert len(row.snapshot["research_warnings"]) >= 3
    before = ToolInvocation.query.count()
    row = advance(run_id, registry)
    assert row.status == "needs_attention" and ToolInvocation.query.count() == before
    assert ApiTask.query.count() == 0


def test_research_limit_before_search_side_effects(app_ctx):
    app_ctx.config["AGENT_RESEARCH_MAX_QUERIES"] = 1
    with pytest.raises(AppError) as caught:
        validate_research_plan({"web_queries": ["one", "two"]})
    assert caught.value.code == "RESEARCH_LIMIT_REACHED"
    assert ToolInvocation.query.count() == 0


@pytest.mark.parametrize("selection", [
    {"page_ids": ["https://attacker.example"]},
    {"page_ids": ["image1_1"]},
    {"images": [{"entity": "wrong", "result_ids": ["image1_1"]}]},
    {"page_ids": ["web0_1", "web0_1"]},
])
def test_selection_must_resolve_observed_ids_and_entities(app_ctx, selection):
    with pytest.raises(AppError) as caught:
        validate_selection(selection, {"research_hits": [
            {"result_id": "web0_1", "kind": "web"},
            {"result_id": "image1_1", "kind": "image", "entity": "expected"},
        ]})
    assert caught.value.code == "INVALID_RESEARCH_DOSSIER"


def test_unsourced_facts_removed_and_traits_canonical(app_ctx):
    _run_id, state = run_research()
    raw = deepcopy(state["research_dossier"])
    raw["topics"][0]["key_facts"].append({"fact": "unsupported", "source_ids": []})
    raw["entities"][0]["candidates"][0]["traits"] = ["invented trait"]
    validated = validate_dossier(raw, state)
    assert all(item["fact"] != "unsupported" for item in validated["topics"][0]["key_facts"])
    assert "invented trait" not in validated["entities"][0]["candidates"][0]["traits"]
    assert "已丢弃没有来源引用的事实。" in validated["warnings"]


@pytest.mark.parametrize("field", ["source", "reference", "selection", "question_image", "entity"])
def test_invalid_dossier_never_reaches_user_choices(app_ctx, field):
    _run_id, state = run_research()
    raw = deepcopy(state["research_dossier"])
    if field == "source":
        raw["sources"][0]["url"] = "https://attacker.example"
    elif field == "reference":
        raw["entities"][0]["candidates"][0]["reference_id"] = "foreign"
    elif field == "selection":
        raw["entities"][0]["selected_candidate_id"] = "missing"
    elif field == "question_image":
        raw["open_questions"][0]["options"][0]["image_artifact_id"] = "foreign"
    else:
        raw["entities"][0]["name"] = "wrong entity"
    with pytest.raises(AppError) as caught:
        validate_dossier(raw, state)
    assert caught.value.code == "INVALID_RESEARCH_DOSSIER"


def test_round_limit_resolves_candidates_once_without_research_repeat(app_ctx):
    app_ctx.config["AGENT_MAX_CLARIFY_ROUNDS"] = 0
    run_id = create(TEXT, budget=500)
    state = tick(run_id)
    assert state["status"] == "awaiting_approval", state
    assert all(item["selected_candidate_id"] for item in state["research_dossier"]["entities"])
    assert state["clarifications"][0]["asked"] is False
    assert state["assumptions"]
    assert ToolInvocation.query.filter_by(tool_name="agent_research_synthesize").count() == 1


def test_multiple_question_batches_use_existing_a5_round_budget(app_ctx):
    _run_id, state = run_research()
    template = state["research_dossier"]["entities"][1]
    entities = []
    for index in range(8):
        entity = deepcopy(template)
        entity["entity_id"] = f"extra_{index}"
        entity["name"] = f"Entity {index}"
        entities.append(entity)
    state["research_dossier"]["entities"] = entities
    state["pending_card"] = None
    state.update(research.resolve(state))
    for _ in range(2):
        card = state["pending_card"]
        assert len(card["questions"]) == 3
        answers = resolve_answers(card, {"card_id": card["card_id"], "answers": answer(state)["answers"]})
        state["clarifications"] = [*state.get("clarifications", []), {"card": card, "answers": answers, "asked": True}]
        state["clarify_rounds"] = state.get("clarify_rounds", 0) + 1
        state["pending_card"] = None
        state.update(research.resolve(state))
    # The remaining two are resolved by the shared A5 default policy.
    state.update(research.resolve(state))
    assert state["research_dossier"]["open_questions"] == []
    assert all(item["selected_candidate_id"] for item in state["research_dossier"]["entities"])


@pytest.mark.parametrize("word", ["漫化", "二次元娘"])
def test_original_ai_visual_examples_trigger_mock_research(app_ctx, word):
    state = tick(create(f"创作 DeepSeek 与 ChatGPT 的 AI {word}形象故事视频，约2分钟", budget=500))
    assert state["status"] == "awaiting_input"
    assert len(state["research_dossier"]["entities"]) == 2


def test_subject_research_trigger_does_not_require_research_needs():
    assert research.needs_research({"request_spec": {"research_needs": [],
        "subjects": [{"source": "needs_research"}]}})
    assert not research.needs_research({"request_spec": {"research_needs": [],
        "subjects": [{"source": "user_text"}]}})


def test_worker_tick_recovers_researching_status(app_ctx, monkeypatch):
    run_id = create("最新潮流演示")
    row = AgentRun.query.filter_by(run_id=run_id).one()
    row.status = "researching"
    db.session.commit()
    seen = []
    worker = AgentWorker(None)
    monkeypatch.setattr(worker, "advance", seen.append)
    worker.tick()
    assert seen == [run_id]
