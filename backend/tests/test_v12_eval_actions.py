"""Offline evaluator action admission; no real application or model execution."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.v3_eval.eval_actions import answer_defaults, default_answer_payload


def test_default_payload_matches_real_runtime_schema_and_stable_identity():
    from app.agents.api import RuntimeAction
    first = default_answer_payload("agent_123", "question_1")
    assert RuntimeAction.model_validate(first).request_key == first["request_key"]
    assert first == default_answer_payload("agent_123", "question_1")
    assert first["request_key"] != default_answer_payload("agent_123", "question_2")["request_key"]
    assert first["request_key"] != default_answer_payload("agent_456", "question_1")["request_key"]
    assert default_answer_payload("a:b", "c")["request_key"] != default_answer_payload("a", "b:c")["request_key"]
    assert 1 <= len(first["request_key"]) <= 128
    assert first["use_defaults"] is True
    assert "answers" not in first


def test_legacy_eval_answer_remains_accepted_by_legacy_schema():
    from app.agent.protocol import RunAction
    payload = default_answer_payload("legacy", "question_1", v3=False)
    assert "request_key" not in payload
    assert RunAction.model_validate(payload).action == "answer"


@pytest.mark.parametrize("run,card", [("", "c"), (None, "c"), ("r", ""), ("r", None)])
def test_default_answer_requires_both_identities(run, card):
    with pytest.raises(ValueError, match="identity"):
        default_answer_payload(run, card)


class Client:
    def __init__(self, status, body):
        self.status, self.body, self.requests = status, body, []

    def post(self, path, *, json):
        self.requests.append((path, deepcopy(json)))
        return SimpleNamespace(status_code=self.status, content_type="application/json",
                               get_json=lambda silent: deepcopy(self.body))


@pytest.mark.parametrize("status", [200, 202])
def test_default_answer_posts_exact_valid_command_once(status):
    from app.agents.api import RuntimeAction
    client, notes = Client(status, {"data": {"status": "queued"}}), []
    assert answer_defaults(client, "agent_123", "question_1", notes)
    assert len(client.requests) == 1
    path, payload = client.requests[0]
    assert path == "/api/agent/runs/agent_123/actions"
    assert RuntimeAction.model_validate(payload).use_defaults
    assert notes == [{"answered_with_defaults": status, "card_id": "question_1",
                      "accepted": True, "request_key": payload["request_key"]}]


@pytest.mark.parametrize("status", [409, 422, 500])
def test_api_error_is_preserved_and_not_retried(status):
    body = {"error": {"code": "INVALID_INPUT", "message": "Card mismatch", "details": {"field": "card_id"}}}
    client, notes = Client(status, body), []
    assert answer_defaults(client, "agent_123", "question_1", notes) is False
    assert len(client.requests) == 1
    assert notes[0]["error"] == body["error"]
    assert notes[0]["answered_with_defaults"] == status
    assert notes[0]["accepted"] is False
    body["error"]["details"]["field"] = "changed"
    assert notes[0]["error"]["details"]["field"] == "card_id"


def test_non_json_api_failure_is_explicit_without_response_body():
    client, notes = Client(502, None), []
    assert answer_defaults(client, "agent_123", "question_1", notes) is False
    assert notes[0]["error"]["code"] == "UNEXPECTED_API_RESPONSE"


def test_default_answer_never_selects_recommendation_for_blocking_card():
    from app.agents.api import RuntimeAction
    from app.agents.tools import validate_answers
    from app.api import AppError
    card = {"card_id": "question_1", "asked_by": "producer", "questions": [{
        "question_id": "choice", "text": "Choose an appearance", "why": "User decision required",
        "options": [{"option_id": "one", "label": "One"}, {"option_id": "two", "label": "Two"}],
        "blocking": True, "default_option_id": None, "recommended_option_id": "one"}]}
    payload = default_answer_payload("agent_123", card["card_id"])
    action = RuntimeAction.model_validate(payload)
    with pytest.raises(AppError) as caught:
        validate_answers(card, action.model_dump(include={"card_id", "answers", "use_defaults"}))
    assert caught.value.code == "CLARIFICATION_INCOMPLETE"
    assert caught.value.payload["missing"] == ["choice"]
    assert "answers" not in payload


@pytest.mark.parametrize("v3,status", [(True, 202), (True, 422), (False, 202)])
def test_run_case_wires_answer_helper_and_stops_on_rejection(monkeypatch, tmp_path, v3, status):
    """Execute the actual function body without the paid evaluator's import side effects."""
    from app.extensions import db
    root = Path(__file__).resolve().parents[1]
    source = root / "scripts/v3_eval/eval_v3.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_case")
    advances = []
    monkeypatch.setattr(db.session, "remove", lambda: None)
    class EvaluationClient(Client):
        def post(self, path, *, json):
            if path == "/api/agent/runs":
                return SimpleNamespace(status_code=201, json={"data": {"run_id": "agent_123"}})
            return super().post(path, json=json)

        def get(self, path):
            view = {"status": "awaiting_input", "pending_card": {"card_id": "question_1", "questions": []}}
            if status == 202 and len(advances) > 1:
                view = {"status": "awaiting_plan_review"}
            return SimpleNamespace(json={"data": view})
    client = EvaluationClient(status, {"error": {"code": "INVALID_INPUT", "message": "rejected"}})
    namespace = {"json": json, "time": SimpleNamespace(time=lambda: 0, sleep=lambda _: None),
                 "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="new-run")),
                 "METER": SimpleNamespace(set_label=lambda _: None), "HERE": tmp_path,
                 "ACTIVE": {"queued"}, "app": SimpleNamespace(config={"AGENT_V3_ENABLED": v3}),
                 "collect": lambda *args: deepcopy(args[-1]), "answer_defaults": answer_defaults}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    notes = namespace["run_case"](client, SimpleNamespace(advance=lambda run: advances.append(run)),
                                  "c3_story", {"text": "story"})
    assert len(client.requests) == 1
    assert len(advances) == (2 if status == 202 else 1)
    assert ("request_key" in client.requests[0][1]) is v3
    assert notes[-1]["accepted"] is (status == 202)
    if status != 202:
        assert notes[-1]["error"]["code"] == "INVALID_INPUT"
