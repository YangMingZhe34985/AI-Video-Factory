"""Research checkpoint recovery and multi-round choices retain security boundaries."""

from collections import Counter
from copy import deepcopy

import pytest

import app.agent.intake as intake_module
from app.agent.search import references
from app.extensions import db
from app.models import AgentRun, ToolInvocation
from app.skills import build_default_registry
from tests.test_agent_v2_graph import create
from tests.test_research_agent import advance, answer
from tests.test_research_injection import TEXT, assert_no_generation, evidence_rows, no_connections

pytestmark = pytest.mark.config(
    AGENT_MODE_ENABLED=True, AGENT_VISION_MODEL="qwen3.7-plus",
    AGENT_RESEARCH_MODEL="qwen3.7-plus",
)


class WorkerStopped(BaseException):
    pass


def test_graph_restart_reuses_download_receipt_without_research_or_download_repeat(app_ctx, client, monkeypatch):
    write = references._atomic_write
    fetch = references.fetch_resource
    downloads = Counter()
    stopped = False
    def count_download(url, *args, **kwargs):
        downloads[url] += 1
        return fetch(url, *args, **kwargs)
    def crash_after_receipt(path, body):
        nonlocal stopped
        write(path, body)
        if path.suffix == ".json" and not stopped:
            stopped = True
            raise WorkerStopped("Crash after durable bytes, before artifact/ledger commit")
    monkeypatch.setattr(references, "fetch_resource", count_download)
    monkeypatch.setattr(references, "_atomic_write", crash_after_receipt)
    run_id = create(TEXT, budget=500)
    with pytest.raises(WorkerStopped):
        advance(run_id, build_default_registry())
    db.session.rollback()
    pending = ToolInvocation.query.filter_by(budget_scope=run_id, tool_name="download_reference").one()
    assert pending.status == "pending"
    first_url = pending.input_payload["image_url"]
    assert downloads[first_url] == 1
    searches = [(row.invocation_id, row.attempt, row.estimated_cost)
                for row in ToolInvocation.query.filter(
                    ToolInvocation.budget_scope == run_id,
                    ToolInvocation.tool_name.in_(["web_search", "image_search"]))]
    row = advance(run_id, build_default_registry())
    assert row.status == "awaiting_input", row.error
    assert downloads[first_url] == 1 and len(downloads) == 6
    assert all(count == 1 for count in downloads.values())
    assert searches == [(item.invocation_id, item.attempt, item.estimated_cost)
                        for item in ToolInvocation.query.filter(
                            ToolInvocation.budget_scope == run_id,
                            ToolInvocation.tool_name.in_(["web_search", "image_search"]))]
    pending = ToolInvocation.query.filter_by(invocation_id=pending.invocation_id).one()
    assert pending.status == "success" and pending.attempt == 1
    before = evidence_rows(run_id)
    assert client.post(f"/api/agent/runs/{run_id}/actions", json=answer(row.snapshot)).status_code == 202
    row = advance(run_id, build_default_registry())
    assert row.status == "awaiting_approval", row.error
    assert evidence_rows(run_id) == before
    assert row.request["budget_limit"] == row.snapshot["budget_limit"] == 500
    assert_no_generation()


def test_two_actual_clarification_checkpoints_never_repeat_research_or_accept_url_answers(app_ctx, client, monkeypatch):
    original = intake_module.mock_request_spec
    def four_entities(data):
        spec = original(data)
        spec["subjects"] = [{"name": name, "description": "需要查证的演示角色",
                             "source": "needs_research", "attachment_ids": []}
                            for name in ("Alpha", "Beta", "Gamma", "Delta")]
        return spec
    monkeypatch.setattr(intake_module, "mock_request_spec", four_entities)
    run_id = create("用最新四位角色生成5秒视频，使用wan2.7系列，禁止happy-horse", budget=500)
    row = advance(run_id, build_default_registry())
    assert row.status == "awaiting_input", row.error
    frozen = deepcopy(row.snapshot["request_spec"])
    before = evidence_rows(run_id)
    counts = []
    selected = {}
    for _ in range(2):
        state = row.snapshot
        card = state["pending_card"]
        counts.append(len(card["questions"]))
        question = card["questions"][0]
        invalid = {"action": "answer", "card_id": card["card_id"], "answers": [
            {"question_id": question["question_id"], "text": "http://127.0.0.1/private"}]}
        refused = client.post(f"/api/agent/runs/{run_id}/actions", json=invalid)
        assert refused.status_code == 422
        assert refused.json["error"]["code"] == "INVALID_ANSWER"
        assert AgentRun.query.filter_by(run_id=run_id).one().command is None
        submission = answer(state)
        selected.update({item["question_id"]: item["option_id"] for item in submission["answers"]})
        assert client.post(f"/api/agent/runs/{run_id}/actions", json=submission).status_code == 202
        row = advance(run_id, build_default_registry())
        assert evidence_rows(run_id) == before
        assert row.snapshot["request_spec"] == frozen
        assert_no_generation()
    assert counts == [3, 1]
    assert row.status == "awaiting_approval", row.error
    assert row.snapshot["clarify_rounds"] == 2
    assert all(entity["selected_candidate_id"] == selected[f"entity_{entity['entity_id']}"]
               for entity in row.snapshot["research_dossier"]["entities"])
    assert row.snapshot["research_dossier"]["open_questions"] == []
    assert row.request["budget_limit"] == row.snapshot["budget_limit"] == 500
