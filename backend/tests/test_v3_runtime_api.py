"""Public v3 admission, recovery commands and privacy; no real model calls."""

from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.worker import AgentWorker
from app.extensions import db
from app.models import AgentDelegation, AgentRun, AgentStep, ToolInvocation
from app.tools.scripted_llm import ScriptedLLM


pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)


def create(client, key="v3", **changes):
    response = client.post("/api/agent/runs", json={"text": "生成一只猫的故事", "request_key": key, **changes})
    assert response.status_code == 202, response.json
    return response.json["data"]


def test_rollout_replay_preserves_accepted_version_and_no_api_calls(app_ctx, client):
    first = create(client)
    assert first["schema_version"] == 3
    assert first["agents"] == first["steps"] == []
    assert first["planning_budget"] == {"limit": 20, "spent": 0}
    assert "snapshot" not in first and "request" not in first and "command" not in first
    app_ctx.config["AGENT_V3_ENABLED"] = False
    app_ctx.config["AGENT_ACCEPT_NEW_RUNS"] = False
    assert create(client)["run_id"] == first["run_id"]
    assert ToolInvocation.query.count() == AgentDelegation.query.count() == 0
    assert client.post("/api/agent/runs", json={"text": "changed", "request_key": "v3"}).status_code == 409


def test_worker_handles_v3_after_rollout_is_disabled(app_ctx, client):
    first = create(client)
    app_ctx.config["AGENT_V3_ENABLED"] = False
    worker = AgentWorker(None, None, v3_saver=InMemorySaver())
    for _ in range(5):
        worker.advance(first["run_id"])
        if AgentRun.query.filter_by(run_id=first["run_id"]).one().status == "success":
            break
    result = client.get(f'/api/agent/runs/{first["run_id"]}').json["data"]
    assert result["status"] == "success", result
    assert len(result["agents"]) == 1
    assert "Mock" in result["message"]
    assert all(row.tool_name not in {"generate_image", "animate_shot", "generate_video", "transform_video"}
               for row in ToolInvocation.query.all())
    count = ToolInvocation.query.count()
    worker.advance(first["run_id"])
    assert ToolInvocation.query.count() == count
    assert create(client)["run_id"] == first["run_id"]


def test_steps_ownership_pagination_and_raw_payload_privacy(app_ctx, client):
    item = create(client)
    worker = AgentWorker(None, None, v3_saver=InMemorySaver())
    worker.advance(item["run_id"])
    row = AgentRun.query.filter_by(run_id=item["run_id"]).one()
    row.snapshot = {**row.snapshot, "messages": [{"content": "secret raw prompt sk-private"}],
                    "raw_llm": "private model completion"}
    row.error = {"code": "RECOVERY_REQUIRED", "message": "secret raw exception sk-private"}
    for step in AgentStep.query.all():
        step.summary = "raw private model response sk-private"
    db.session.commit()
    response = client.get(f'/api/agent/runs/{row.run_id}/steps?page=1&per_page=1')
    assert response.status_code == 200
    assert len(response.json["data"]["items"]) == 1
    assert "sk-private" not in response.get_data(as_text=True)
    detail = client.get(f"/api/agent/runs/{row.run_id}")
    assert "sk-private" not in detail.get_data(as_text=True)
    assert client.get(f'/api/agent/runs/{row.run_id}/steps?page=0').status_code == 422
    row.owner_id = "someone-else"
    db.session.commit()
    assert client.get(f'/api/agent/runs/{row.run_id}/steps').status_code == 404
    assert client.get(f'/api/agent/runs/{row.run_id}').status_code == 404


def test_action_queue_replay_and_reject_cannot_launch_tools(app_ctx, client):
    item = create(client)
    url = f'/api/agent/runs/{item["run_id"]}/actions'
    assert client.post(url, json={"action": "approve_plan", "request_key": "early"}).status_code == 422
    assert client.post(url, json={"action": "reject"}).status_code == 422
    request = {"action": "reject", "request_key": "cancel-once"}
    assert client.post(url, json=request).status_code == 202
    row = AgentRun.query.filter_by(run_id=item["run_id"]).one()
    original = deepcopy(row.command)
    assert client.post(url, json=request).status_code == 202
    assert row.command == original
    assert client.post(url, json={"action": "resume", "request_key": "cancel-once"}).status_code == 409
    AgentWorker(None, None, v3_saver=InMemorySaver()).advance(row.run_id)
    db.session.refresh(row)
    assert row.status == "cancelled"
    assert ToolInvocation.query.count() == 0
    assert client.post(url, json=request).status_code == 202


def test_task_center_uses_plan_nodes_and_business_stage(app_ctx, client):
    item = create(client)
    row = AgentRun.query.filter_by(run_id=item["run_id"]).one()
    row.status = "attention"
    db.session.commit()
    from app.services.task_center_service import task_detail
    detail = task_detail("local", "agent", row.run_id, {})
    assert detail["item"]["state"] == "attention"
    assert detail["item"]["stage"] == "attention"
    assert detail["item"]["progress"] == {"unit": "plan_nodes", "completed": 0, "failed": 0, "total": 0}
    assert detail["children"] == []


def test_clarification_api_is_validated_idempotent_and_worker_resumes(app_ctx, client):
    question = {"question_id": "style", "text": "选一种画风", "why": "决定角色表现", "blocking": True,
                "options": [{"option_id": "anime", "label": "动漫"}, {"option_id": "real", "label": "写实"}],
                "recommended_option_id": "anime"}
    scripted = ScriptedLLM({"producer": [
        [{"id": "ask", "name": "ask_user", "arguments": {"questions": [question]}}],
        [{"id": "finish", "name": "finish", "arguments": {"kind": "completed", "outcome": "answer", "message": "已确认动漫风格"}}],
    ]})
    app_ctx.extensions["agent_v3_scripted_llm"] = scripted
    item = create(client)
    saver = InMemorySaver()
    worker = AgentWorker(None, None, v3_saver=saver)
    worker.advance(item["run_id"])
    row = AgentRun.query.filter_by(run_id=item["run_id"]).one()
    assert row.status == "awaiting_input"
    card = client.get(f'/api/agent/runs/{row.run_id}').json["data"]["pending_card"]
    assert card["asked_by"] == "producer"
    url = f'/api/agent/runs/{row.run_id}/actions'
    body = {"action": "answer", "request_key": "answer-once", "card_id": card["card_id"], "answers": []}
    assert client.post(url, json=body).status_code == 409
    assert row.command is None
    body["answers"] = [{"question_id": "style", "option_id": "anime"}]
    assert client.post(url, json=body).status_code == 202
    for _ in range(5):
        worker.advance(row.run_id)
        db.session.refresh(row)
        if row.status == "success":
            break
    assert row.status == "success", row.error
    calls = list(scripted.calls)
    assert client.post(url, json=body).status_code == 202
    worker.advance(row.run_id)
    assert scripted.calls == calls
    from app.models import AgentWorkspaceItem
    answers = AgentWorkspaceItem.query.filter_by(run_id=row.run_id, kind="clarification").all()
    assert len(answers) == 1


def test_worker_exception_keeps_inbox_but_requires_explicit_recovery(app_ctx, client, monkeypatch):
    item = create(client)
    row = AgentRun.query.filter_by(run_id=item["run_id"]).one()
    row.command = {"action": "answer", "command_id": "accepted-original", "card_id": "card"}
    db.session.commit()
    from app.agents import runtime
    calls = []
    def fail(run, saver=None):
        calls.append(deepcopy(run.command))
        raise RuntimeError("injected checkpoint failure")
    monkeypatch.setattr(runtime, "advance", fail)
    worker = AgentWorker(None, None, v3_saver=InMemorySaver())
    worker.tick()
    db.session.refresh(row)
    assert row.status == "attention" and row.command["command_id"] == "accepted-original"
    worker.tick()
    assert len(calls) == 1
    url = f'/api/agent/runs/{row.run_id}/actions'
    assert client.post(url, json={"action": "resume", "request_key": "recover"}).status_code == 202
    worker.tick()
    assert len(calls) == 2 and calls[0] == calls[1]


def test_sqlite_checkpointer_reopens_after_round_crash_without_rebilling(app_ctx, client, tmp_path, monkeypatch):
    from langgraph.checkpoint.sqlite import SqliteSaver
    from app.agents import runtime
    from app.models import AgentWorkspaceItem
    from app.tools.budget import BudgetGuard
    scripted = ScriptedLLM({"producer": [
        [{"id": "note", "name": "write_workspace", "arguments": {"key": "idea", "kind": "note", "payload": {"text": "猫的故事"}}}],
        [{"id": "finish", "name": "finish", "arguments": {"kind": "completed", "outcome": "answer", "message": "完成规划示例"}}],
    ]})
    app_ctx.extensions["agent_v3_scripted_llm"] = scripted
    item = create(client)
    run = AgentRun.query.filter_by(run_id=item["run_id"]).one()
    original = runtime._round
    def lose_checkpoint(*args):
        original(*args)
        raise RuntimeError("injected crash after round commit")
    monkeypatch.setattr(runtime, "_round", lose_checkpoint)
    checkpoint = str(tmp_path / "restart.sqlite")
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        with pytest.raises(RuntimeError):
            runtime.advance(run, saver=saver)
    prior_spent = BudgetGuard.spent(run.run_id)
    monkeypatch.setattr(runtime, "_round", original)
    db.session.remove()
    run = AgentRun.query.filter_by(run_id=item["run_id"]).one()
    with SqliteSaver.from_conn_string(checkpoint) as reopened:
        runtime.advance(run, saver=reopened)
        assert scripted.calls == [("producer", 0)]
        assert BudgetGuard.spent(run.run_id) == prior_spent
        assert AgentWorkspaceItem.query.filter_by(run_id=run.run_id).count() == 1
        runtime.advance(run, saver=reopened)
    assert run.status == "success"
    assert scripted.calls == [("producer", 0), ("producer", 1)]


def test_resume_restores_question_after_ask_checkpoint_failure(app_ctx, client, monkeypatch):
    from app.agents import runtime
    question = {"question_id": "style", "text": "选一种画风", "why": "决定角色表现", "blocking": True,
                "options": [{"option_id": "anime", "label": "动漫"}, {"option_id": "real", "label": "写实"}]}
    scripted = ScriptedLLM({"producer": [
        [{"id": "ask", "name": "ask_user", "arguments": {"questions": [question]}}],
        [{"id": "done", "name": "finish", "arguments": {"kind": "completed", "outcome": "answer", "message": "已确认"}}],
    ]})
    app_ctx.extensions["agent_v3_scripted_llm"] = scripted
    item = create(client)
    worker = AgentWorker(None, None, v3_saver=InMemorySaver())
    original = runtime._record
    def lose_ask_checkpoint(*args, **kwargs):
        original(*args, **kwargs)
        if args[2] == "ask":
            raise RuntimeError("crash after stored question")
    monkeypatch.setattr(runtime, "_record", lose_ask_checkpoint)
    worker.advance(item["run_id"])
    row = AgentRun.query.filter_by(run_id=item["run_id"]).one()
    assert row.status == "attention"
    monkeypatch.setattr(runtime, "_record", original)
    url = f'/api/agent/runs/{row.run_id}/actions'
    assert client.post(url, json={"action": "resume", "request_key": "recover-question"}).status_code == 202
    worker.advance(row.run_id)
    view = client.get(f'/api/agent/runs/{row.run_id}').json["data"]
    assert view["status"] == "awaiting_input" and view["pending_card"]
    assert scripted.calls == [("producer", 0)]
    assert client.post(url, json={"action": "answer", "request_key": "choose", "card_id": view["pending_card"]["card_id"],
        "answers": [{"question_id": "style", "option_id": "anime"}]}).status_code == 202
    for _ in range(5):
        worker.advance(row.run_id)
        db.session.refresh(row)
        if row.status == "success":
            break
    assert row.status == "success" and row.error is None
    assert scripted.calls == [("producer", 0), ("producer", 1)]
