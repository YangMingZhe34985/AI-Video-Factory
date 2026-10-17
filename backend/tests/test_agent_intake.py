"""A4 nodes use isolated SQLite, Mock adapters and real tool-ledger semantics."""

from io import BytesIO
import json

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

import app.agent.intake as intake_module
from app.adapters.qwen_chat import QwenChatAdapter
from app.agent.attachments import upload_attachment
from app.agent.intake import analyze_attachments, intake
from app.agent import planning
from app.agent.planning import resolve_agent_model
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, Job, PromptVersion, ToolInvocation
from app.services.job_run_service import JobRunService
from app.services.video_media_service import VideoMediaService
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from app.skills.spec import ToolContext
from app.utils.ids import new_id

pytestmark = pytest.mark.config(AGENT_VISION_MODEL="qwen3.7-plus")


def make_run(text="生成 5 秒猫跳舞视频", ids=(), budget=100, owner="owner"):
    row = AgentRun(owner_id=owner, request_key=new_id("request"), request={
        "schema_version": 2, "text": text, "attachment_ids": list(ids), "budget_limit": budget,
    })
    db.session.add(row)
    db.session.commit()
    return row


def image_attachment(owner="owner"):
    content = BytesIO()
    Image.new("RGB", (256, 256), "blue").save(content, "PNG")
    content.seek(0)
    return upload_attachment(FileStorage(stream=content, filename="portrait.png", content_type="image/png"), owner)


def priced_intake():
    model = resolve_agent_model("intake")
    model.capabilities = {**model.capabilities, "pricing": {"unit": "call", "credits_per_unit": 2}}
    db.session.commit()


def valid_output():
    return {"deliverable": "video", "recipe_hint": "single_clip", "summary": "猫跳舞",
            "confidence": 0.9, "attachments": [], "open_questions": []}


def test_image_analysis_then_intake_and_replay(app_ctx):
    attachment = image_attachment()
    row = make_run("生成我的一张西装照", [attachment["attachment_id"]])
    state = {"run_id": row.run_id}
    analyzed = analyze_attachments(state)
    assert analyzed["attachments_ready"] is True
    assert analyzed["analysis_jobs"] == {}
    assert "Mock" in analyzed["attachment_analyses"][0]["description"]
    state.update(analyzed)
    result = intake(state)
    assert result["request_spec"]["recipe_hint"] == "image_edit"
    assert result["request_spec"]["attachments"][0]["role"] == "identity_ref"
    count, spent = ToolInvocation.query.count(), BudgetGuard.spent(row.run_id)
    assert analyze_attachments(state) == analyzed
    assert intake(state) == result
    assert ToolInvocation.query.count() == count == 2
    assert BudgetGuard.spent(row.run_id) == spent


@pytest.mark.parametrize("text", [None, "", "  ", "猫", "x" * 8001])
def test_empty_or_invalid_text_rejected_before_any_tool(app_ctx, text):
    row = make_run(text)
    for node in (analyze_attachments, intake):
        with pytest.raises(AppError) as error:
            node({"run_id": row.run_id})
        assert error.value.code == "TEXT_REQUIRED"
    assert ToolInvocation.query.count() == 0


def test_incomplete_attachment_analysis_cannot_start_intake(app_ctx):
    attachment = image_attachment()
    row = make_run(ids=[attachment["attachment_id"]])
    with pytest.raises(AppError) as error:
        intake({"run_id": row.run_id, "attachment_analyses": []})
    assert error.value.code == "ANALYSIS_PENDING"
    assert ToolInvocation.query.count() == 0


def test_schema_repair_is_once_billable_and_replayable(app_ctx, monkeypatch):
    priced_intake()
    row = make_run()
    calls = []

    def response(_instruction, data, *_args, **_kwargs):
        calls.append(data)
        if len(calls) == 1:
            return {**valid_output(), "attachments": [{"attachment_id": "invented", "kind": "image",
                    "role": "content_ref", "description": "unknown", "reason": "invented"}]}
        return valid_output()

    monkeypatch.setattr(intake_module, "structured_call", response)
    result = intake({"run_id": row.run_id})
    assert result["request_spec"]["recipe_hint"] == "single_clip"
    assert len(calls) == 2
    assert "cover the uploaded IDs" in calls[1].validation_feedback
    records = ToolInvocation.query.order_by(ToolInvocation.id).all()
    assert [record.status for record in records] == ["failed", "success"]
    assert BudgetGuard.spent(row.run_id) == 4
    assert intake({"run_id": row.run_id}) == result
    assert len(calls) == 2
    assert BudgetGuard.spent(row.run_id) == 4


def test_two_invalid_outputs_remain_failed_without_a_third_call(app_ctx, monkeypatch):
    priced_intake()
    row = make_run()
    calls = []

    def invalid(*_args, **_kwargs):
        calls.append(1)
        return {**valid_output(), "recipe_hint": "image_edit"}

    monkeypatch.setattr(intake_module, "structured_call", invalid)
    for _ in range(2):
        with pytest.raises(AppError) as error:
            intake({"run_id": row.run_id})
        assert error.value.code == "INVALID_REQUEST_SPEC"
        assert error.value.status_code == 422
    assert len(calls) == 2
    assert [row.status for row in ToolInvocation.query.all()] == ["failed", "failed"]
    assert BudgetGuard.spent(row.run_id) == 4


def test_schema_repair_respects_remaining_budget(app_ctx, monkeypatch):
    priced_intake()
    row = make_run(budget=2)
    calls = []

    def invalid(*_args, **_kwargs):
        calls.append(1)
        return {}

    monkeypatch.setattr(intake_module, "structured_call", invalid)
    with pytest.raises(AppError) as error:
        intake({"run_id": row.run_id})
    assert error.value.code == "BUDGET_EXCEEDED"
    assert len(calls) == 1
    assert BudgetGuard.spent(row.run_id) == 2


def test_transport_error_does_not_trigger_schema_repair(app_ctx, monkeypatch):
    row = make_run()
    calls = []

    def failed(*_args, **_kwargs):
        calls.append(1)
        raise AppError("API_TASK_FAILED", "Provider result unknown", 502)

    monkeypatch.setattr(intake_module, "structured_call", failed)
    for _ in range(2):
        with pytest.raises(AppError) as error:
            intake({"run_id": row.run_id})
        assert error.value.code == "API_TASK_FAILED"
    assert len(calls) == 1


def test_image_analysis_requires_owned_attached_image(app_ctx):
    owned = image_attachment()
    other = image_attachment("another-owner")
    run = make_run(ids=[owned["attachment_id"], other["attachment_id"]])
    registry = build_default_registry()
    with pytest.raises(AppError) as error:
        registry.invoke("analyze_image", {"attachment_id": other["attachment_id"]},
                        ToolContext(role="intake", budget_scope=run.run_id))
    assert error.value.code == "ATTACHMENT_NOT_FOUND"
    run.request = {**run.request, "attachment_ids": []}
    db.session.commit()
    with pytest.raises(AppError) as error:
        registry.invoke("analyze_image", {"attachment_id": owned["attachment_id"]},
                        ToolContext(role="intake", budget_scope=run.run_id))
    assert error.value.code == "ATTACHMENT_NOT_FOUND"
    assert BudgetGuard.spent(run.run_id) == 0
    with pytest.raises(AppError) as error:
        registry.invoke("analyze_image", {"attachment_id": owned["attachment_id"]}, ToolContext(role="production"))
    assert error.value.code == "TOOL_FORBIDDEN"


@pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_VISION_MODEL="qwen3.7-plus")
def test_image_skill_api_checks_caller_scope_and_attachment_owner(app_ctx, client):
    owned = image_attachment("local")
    foreign = image_attachment("another-owner")
    local_run = make_run(ids=[owned["attachment_id"]], owner="local")
    foreign_run = make_run(ids=[foreign["attachment_id"]], owner="another-owner")
    for scope, attachment_id in ((foreign_run.run_id, foreign["attachment_id"]),
                                 (local_run.run_id, foreign["attachment_id"])):
        response = client.post("/api/skills/analyze_image/invoke", json={
            "role": "intake", "budget_scope": scope, "input": {"attachment_id": attachment_id},
        })
        assert response.status_code == 404
    assert ToolInvocation.query.count() == 0
    response = client.post("/api/skills/analyze_image/invoke", json={
        "role": "intake", "budget_scope": local_run.run_id, "input": {"attachment_id": owned["attachment_id"]},
    })
    assert response.status_code == 200, response.json
    assert "Mock" in response.json["data"]["output"]["summary"]


def test_video_analysis_waits_without_rebilling_and_collects_prompt(app_ctx, monkeypatch):
    monkeypatch.setattr(VideoMediaService, "inspect", lambda _path: {
        "width": 640, "height": 480, "duration": 8.0, "fps": 24.0,
    })
    attachment = upload_attachment(FileStorage(stream=BytesIO(b"mock video"), filename="source.mp4"), "owner")
    monkeypatch.setattr(JobRunService, "start", lambda *_args, **_kwargs: None)
    row = make_run("保留视频开头，修改后半段", [attachment["attachment_id"]])
    state = {"run_id": row.run_id}
    first = analyze_attachments(state)
    assert first["attachments_ready"] is False
    assert first["attachment_analyses"] == []
    assert len(first["analysis_jobs"]) == 1
    spent = BudgetGuard.spent(row.run_id)
    assert analyze_attachments({**state, **first}) == first
    assert BudgetGuard.spent(row.run_id) == spent
    assert ToolInvocation.query.count() == 1
    with pytest.raises(AppError) as error:
        intake({**state, **first})
    assert error.value.code == "ANALYSIS_PENDING"

    job = Job.query.filter_by(job_id=first["analysis_jobs"][attachment["attachment_id"]]).one()
    other = make_run(owner="another-owner")
    with pytest.raises(AppError) as error:
        build_default_registry().invoke("get_task_status", {"job_id": job.job_id},
                                        ToolContext(role="intake", budget_scope=other.run_id))
    assert error.value.code == "TOOL_FORBIDDEN"
    job.status = "success"
    db.session.add(PromptVersion(template_id=job.template_id, job_id=job.id, prompt_type="t2v",
                                 version="1", title="Analysis", content="原片先出现猫，随后进入森林。"))
    db.session.commit()
    completed = analyze_attachments({**state, **first})
    assert completed["attachments_ready"] is True
    assert "森林" in completed["attachment_analyses"][0]["description"]
    result = intake({**state, **completed})
    assert result["request_spec"]["recipe_hint"] == "remix"
    assert result["request_spec"]["attachments"][0]["role"] == "remix_source"
    assert ToolInvocation.query.filter_by(tool_name="analyze_video").count() == 1


def test_failed_video_analysis_cannot_be_treated_as_description(app_ctx, monkeypatch):
    monkeypatch.setattr(VideoMediaService, "inspect", lambda _path: {
        "width": 640, "height": 480, "duration": 8.0, "fps": 24.0,
    })
    attachment = upload_attachment(FileStorage(stream=BytesIO(b"mock video"), filename="source.mp4"), "owner")
    monkeypatch.setattr(JobRunService, "start", lambda *_args, **_kwargs: None)
    row = make_run("修改视频后半段", [attachment["attachment_id"]])
    state = {"run_id": row.run_id}
    started = analyze_attachments(state)
    job = Job.query.filter_by(job_id=started["analysis_jobs"][attachment["attachment_id"]]).one()
    job.status = "success"
    db.session.commit()
    with pytest.raises(AppError) as error:
        analyze_attachments({**state, **started})
    assert error.value.code == "ANALYSIS_FAILED"
    assert ToolInvocation.query.filter_by(tool_name="agent_intake").count() == 0


def mock_completions(monkeypatch, responses):
    calls = []

    class CompletionMock(QwenChatAdapter):
        """Stub transport only; keep Qwen build/submit/response parsing real."""

        @property
        def use_mock(self):
            return False

        def _chat_completion(self, payload):
            calls.append(payload)
            response = responses[len(calls) - 1]
            if isinstance(response, Exception):
                raise response
            return {"choices": [{"message": {"content": response}}]}

    monkeypatch.setattr(planning, "get_adapter", lambda _name, model: CompletionMock(model))
    return calls


@pytest.mark.parametrize("malformed", ["plain text", "[1, 2]", '{"unfinished": }'])
def test_completed_non_object_response_gets_one_billable_repair(app_ctx, monkeypatch, malformed):
    priced_intake()
    row = make_run()
    calls = mock_completions(monkeypatch, [malformed, json.dumps(valid_output())])
    result = intake({"run_id": row.run_id})
    assert result["request_spec"]["recipe_hint"] == "single_clip"
    assert len(calls) == 2
    assert "valid JSON object" in calls[1]["messages"][1]["content"][0]["text"]
    assert [item.status for item in ToolInvocation.query.order_by(ToolInvocation.id)] == ["failed", "success"]
    assert BudgetGuard.spent(row.run_id) == 4
    assert intake({"run_id": row.run_id}) == result
    assert len(calls) == 2


def test_two_completed_malformed_responses_stop_at_two(app_ctx, monkeypatch):
    priced_intake()
    row = make_run()
    calls = mock_completions(monkeypatch, ["not JSON", "[]"])
    for _ in range(2):
        with pytest.raises(AppError) as error:
            intake({"run_id": row.run_id})
        assert error.value.code == "INVALID_REQUEST_SPEC"
    assert len(calls) == 2
    assert BudgetGuard.spent(row.run_id) == 4
    assert [item.status for item in ToolInvocation.query.all()] == ["failed", "failed"]


def test_unknown_transport_through_adapter_is_never_repaired(app_ctx, monkeypatch):
    priced_intake()
    row = make_run()
    calls = mock_completions(monkeypatch, [AppError("API_TASK_FAILED", "Transport outcome unknown", 502)])
    for _ in range(2):
        with pytest.raises(AppError) as error:
            intake({"run_id": row.run_id})
        assert error.value.code == "API_TASK_FAILED"
    assert len(calls) == 1
    assert BudgetGuard.spent(row.run_id) == 2


def test_provider_path_never_runs_mock_intent_rules(app_ctx, monkeypatch):
    row = make_run()
    mock_completions(monkeypatch, [json.dumps(valid_output())])

    def no_mock_rules(_data):
        pytest.fail("Mock intent rules must not run on the provider response path")

    monkeypatch.setattr(intake_module, "mock_request_spec", no_mock_rules)
    assert intake({"run_id": row.run_id})["request_spec"]["recipe_hint"] == "single_clip"
