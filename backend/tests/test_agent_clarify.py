"""A5: clarification cards, answers, round limit, and the worker resume path."""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.clarify import (
    ClarifyState,
    answer_for,
    build_card,
    clarify_gate,
    queue_questions,
    resolve_answers,
)
from app.agent.worker import AgentWorker
from app.api import AppError
from app.extensions import db
from app.models import AgentRun

STYLE = {
    "question_id": "style",
    "text": "DeepSeek 的形象用哪一个？",
    "why": "所有镜头都会锁定这个外观",
    "options": [
        {"option_id": "a", "label": "鲸鱼发饰版"},
        {"option_id": "b", "label": "深海制服版"},
    ],
    "recommended_option_id": "a",
    "allow_free_text": True,
}
RATIO = {
    "question_id": "ratio",
    "text": "画幅？",
    "why": "影响构图",
    "options": [{"option_id": "v", "label": "竖屏 9:16"}, {"option_id": "h", "label": "横屏 16:9"}],
    "blocking": False,
    "default_option_id": "v",
}


def card(*questions):
    return build_card("research", list(questions)).model_dump(mode="json")


# -- schema ---------------------------------------------------------------

@pytest.mark.parametrize(
    "question",
    [
        {**RATIO, "default_option_id": None},                       # non-blocking without default
        {**STYLE, "recommended_option_id": "zzz"},                    # recommendation not an option
        {**STYLE, "options": [STYLE["options"][0]] * 2},              # duplicate option ids
        {**STYLE, "options": STYLE["options"][:1]},                   # fewer than two options
    ],
)
def test_invalid_cards_are_rejected(app_ctx, question):
    with pytest.raises(AppError) as exc:
        build_card("intake", [question])
    assert exc.value.code == "INVALID_CLARIFICATION"


def test_card_rejects_duplicate_questions_and_too_many(app_ctx):
    with pytest.raises(AppError):
        build_card("intake", [STYLE, STYLE])
    with pytest.raises(AppError):
        build_card("intake", [{**STYLE, "question_id": f"q{i}"} for i in range(4)])


# -- answers --------------------------------------------------------------

def test_resolve_option_free_text_and_defaults(app_ctx):
    c = card(STYLE, RATIO)
    resolved = resolve_answers(c, {"card_id": c["card_id"], "answers": [{"question_id": "style", "option_id": "b"}]})
    assert resolved["style"] == {**resolved["style"], "option_id": "b", "label": "深海制服版", "source": "user"}
    assert resolved["ratio"]["option_id"] == "v" and resolved["ratio"]["source"] == "default"

    free = resolve_answers(c, {"card_id": c["card_id"], "answers": [{"question_id": "style", "text": "两个都要"}]})
    assert free["style"]["text"] == "两个都要" and free["style"]["option_id"] is None


@pytest.mark.parametrize(
    ("answers", "code", "status"),
    [
        ([], "CLARIFICATION_INCOMPLETE", 409),
        ([{"question_id": "ratio", "option_id": "h"}], "CLARIFICATION_INCOMPLETE", 409),
        ([{"question_id": "style", "option_id": "nope"}], "INVALID_ANSWER", 422),
        ([{"question_id": "ratio", "text": "方形"}], "INVALID_ANSWER", 422),
        ([{"question_id": "ghost", "option_id": "a"}], "INVALID_ANSWER", 422),
        ([{"question_id": "style", "option_id": "a"}, {"question_id": "style", "option_id": "b"}], "INVALID_ANSWER", 422),
    ],
)
def test_bad_answers_are_rejected(app_ctx, answers, code, status):
    c = card(STYLE, RATIO)
    with pytest.raises(AppError) as exc:
        resolve_answers(c, {"card_id": c["card_id"], "answers": answers})
    assert (exc.value.code, exc.value.status_code) == (code, status)


def test_answers_must_target_the_pending_card(app_ctx):
    c = card(STYLE)
    with pytest.raises(AppError) as exc:
        resolve_answers(c, {"card_id": "card_other", "answers": [{"question_id": "style", "option_id": "a"}]})
    assert exc.value.code == "INVALID_ANSWER"


def test_use_defaults_skips_non_blocking_questions(app_ctx):
    c = card(RATIO)
    resolved = resolve_answers(c, {"card_id": c["card_id"], "answers": [], "use_defaults": True})
    assert resolved["ratio"]["source"] == "default"


# -- queueing and round limit --------------------------------------------

def test_queue_questions_within_and_beyond_the_round_limit(app_ctx):
    assert queue_questions({}, "intake", [], "understanding") == {}

    update = queue_questions({}, "intake", [STYLE], "planning")
    assert update["status"] == "awaiting_input"
    assert update["clarify_resume_status"] == "planning"
    assert update["pending_card"]["questions"][0]["question_id"] == "style"

    no_hint = {**STYLE, "question_id": "pose", "recommended_option_id": None}
    auto = queue_questions({"clarify_rounds": 2}, "director", [STYLE, RATIO, no_hint], "planning")
    assert "pending_card" not in auto and "status" not in auto
    answers = auto["clarifications"][0]["answers"]
    assert auto["clarifications"][0]["asked"] is False
    assert {qid: item["source"] for qid, item in answers.items()} == {
        "style": "recommended", "ratio": "default", "pose": "fallback"}
    assert len(auto["assumptions"]) == 3 and "未询问" in auto["assumptions"][0]


# -- graph + worker -------------------------------------------------------

class ClarifyTestState(ClarifyState, total=False):
    run_id: str
    asks: int
    choice: str


def build_test_graph(app, ask_times=1):
    def ctx(fn):
        def wrapped(state):
            with app.app_context():
                return fn(state)
        return wrapped

    def ask(state):
        update = queue_questions(state, "research", [{**STYLE, "question_id": f"style{state.get('asks', 0)}"}], "planning")
        return {**update, "asks": state.get("asks", 0) + 1}

    def finish(state):
        last = answer_for(state, f"style{state['asks'] - 1}")
        return {"status": "success", "choice": last["label"] or last["text"]}

    builder = StateGraph(ClarifyTestState)
    builder.add_node("ask", ctx(ask))
    builder.add_node("gate", ctx(clarify_gate))
    builder.add_node("finish", ctx(finish))
    builder.add_edge(START, "ask")
    builder.add_edge("ask", "gate")
    builder.add_conditional_edges("gate", lambda s: "ask" if s["asks"] < ask_times else "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=MemorySaver())


def start_run(graph, status_request=None):
    row = AgentRun(owner_id="local", request_key="clarify-test",
                   request=status_request or {"goal": "g", "shot_count": 1, "budget_limit": 10})
    db.session.add(row)
    db.session.commit()
    config = {"configurable": {"thread_id": row.run_id}}
    graph.invoke({"run_id": row.run_id, "status": "understanding"}, config)
    AgentWorker._save(row, graph.get_state(config).values, None)
    return row


def answer(client, run_id, card_id, **body):
    return client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "answer", "card_id": card_id, **body})


@pytest.mark.config(AGENT_MODE_ENABLED=True)
def test_answer_resumes_the_graph_through_the_worker(app_ctx, client):
    graph = build_test_graph(app_ctx)
    row = start_run(graph)
    assert row.status == "awaiting_input"
    card_id = row.snapshot["pending_card"]["card_id"]
    assert client.get(f"/api/agent/runs/{row.run_id}").json["data"]["snapshot"]["pending_card"]["card_id"] == card_id

    # Nothing happens without an answer.
    AgentWorker(graph).advance(row.run_id)
    db.session.refresh(row)
    assert row.status == "awaiting_input"

    incomplete = answer(client, row.run_id, card_id, answers=[])
    assert incomplete.status_code == 409 and incomplete.json["error"]["code"] == "CLARIFICATION_INCOMPLETE"
    invalid = answer(client, row.run_id, card_id, answers=[{"question_id": "style0", "option_id": "x"}])
    assert invalid.status_code == 422 and invalid.json["error"]["code"] == "INVALID_ANSWER"
    db.session.refresh(row)
    assert row.command is None

    ok = answer(client, row.run_id, card_id, answers=[{"question_id": "style0", "option_id": "b"}])
    assert ok.status_code == 202
    duplicate = answer(client, row.run_id, card_id, answers=[{"question_id": "style0", "option_id": "a"}])
    assert duplicate.status_code == 409

    AgentWorker(graph).advance(row.run_id)
    db.session.refresh(row)
    assert row.status == "success"
    assert row.command is None
    assert row.snapshot["choice"] == "深海制服版"
    assert row.snapshot["pending_card"] is None
    assert row.snapshot["clarify_rounds"] == 1


@pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_MAX_CLARIFY_ROUNDS=2)
def test_round_limit_turns_further_questions_into_assumptions(app_ctx, client):
    graph = build_test_graph(app_ctx, ask_times=3)
    row = start_run(graph)
    worker = AgentWorker(graph)
    for round_no in range(2):
        db.session.refresh(row)
        assert row.status == "awaiting_input"
        card_id = row.snapshot["pending_card"]["card_id"]
        assert answer(client, row.run_id, card_id, answers=[{"question_id": f"style{round_no}", "text": f"自定义{round_no}"}]).status_code == 202
        worker.advance(row.run_id)

    db.session.refresh(row)
    assert row.status == "success"
    assert row.snapshot["clarify_rounds"] == 2
    assert [record["asked"] for record in row.snapshot["clarifications"]] == [True, True, False]
    assert row.snapshot["choice"] == "鲸鱼发饰版"  # third question resolved to the recommendation
    assert len(row.snapshot["assumptions"]) == 1


@pytest.mark.config(AGENT_MODE_ENABLED=True)
def test_answer_action_validation(app_ctx, client):
    graph = build_test_graph(app_ctx)
    row = start_run(graph)
    url = f"/api/agent/runs/{row.run_id}/actions"
    assert client.post(url, json={"action": "answer"}).status_code == 422  # card_id required
    assert client.post(url, json={"action": "approve", "answers": [{"question_id": "style0", "option_id": "a"}]}).status_code == 422
    assert client.post(url, json={"action": "approve"}).status_code == 409  # wrong state

    row.status = "planning"
    db.session.commit()
    wrong_state = answer(client, row.run_id, row.snapshot["pending_card"]["card_id"],
                         answers=[{"question_id": "style0", "option_id": "a"}])
    assert wrong_state.status_code == 409 and wrong_state.json["error"]["code"] == "INVALID_AGENT_STATE"
