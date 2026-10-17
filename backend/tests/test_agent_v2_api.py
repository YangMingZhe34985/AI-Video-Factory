"""v2 admission/serialization and version routing, with no paid model calls."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from app.agent.attachments import upload_attachment
from app.agent.worker import AgentWorker
from app.extensions import db
from app.models import AgentRun, Artifact, Job, ModelRegistry, ToolInvocation
from app.services.storage_service import StorageService
from tests.helpers import legacy_agent_run

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True)


def create(client, **changes):
    return client.post("/api/agent/runs", json={"text": "生成一张猫的图片", "request_key": "v2", **changes})


def attachment(owner="local"):
    stream = BytesIO()
    Image.new("RGB", (256, 256), "red").save(stream, "PNG")
    stream.seek(0)
    return upload_attachment(FileStorage(stream=stream, filename="cat.png"), owner)["attachment_id"]


@pytest.mark.parametrize("field", ["goal", "mode", "shot_count", "video_model_preference", "source_artifact_id"])
def test_legacy_fields_have_explicit_deprecation(app_ctx, client, field):
    response = create(client, **{field: None})
    assert response.status_code == 422
    assert response.json["error"]["code"] == "DEPRECATED_FIELD"
    assert response.json["error"]["details"]["fields"] == [field]
    assert AgentRun.query.count() == 0


@pytest.mark.parametrize("text", [None, "", "  ", "猫", "x" * 8001, 123],
                         ids=["missing", "empty", "spaces", "short", "long", "non-string"])
def test_text_required_before_any_work(app_ctx, client, text):
    response = create(client, text=text)
    assert response.status_code == 422
    assert response.json["error"]["code"] == "TEXT_REQUIRED"
    assert AgentRun.query.count() == Job.query.count() == ToolInvocation.query.count() == 0


def test_creation_does_not_select_models_and_replays_during_drain(app_ctx, client):
    ModelRegistry.query.update({"enabled": False})
    db.session.commit()
    first = create(client, text="  请使用未知型号生成猫的视频  ", budget_limit=3)
    assert first.status_code == 202, first.json
    data = first.json["data"]
    assert data["schema_version"] == 2 and data["status"] == "queued"
    assert data["text"] == "请使用未知型号生成猫的视频"
    assert data["summary"] == {"steps_total": 0, "steps_success": 0, "steps_failed": 0}
    assert set(data["request"]) == {"text", "attachment_ids", "budget_limit", "schema_version"}
    assert data["request_spec"] is data["plan"] is data["pending_card"] is None
    assert data["results"] == data["attachments"] == []
    app_ctx.config["AGENT_ACCEPT_NEW_RUNS"] = False
    replay = create(client, text="请使用未知型号生成猫的视频", budget_limit=3)
    assert replay.status_code == 202 and replay.json["data"]["run_id"] == data["run_id"]
    assert create(client, text="different", budget_limit=3).status_code == 409
    assert create(client, request_key="new").status_code == 503
    assert AgentRun.query.count() == 1
    assert Job.query.count() == ToolInvocation.query.count() == 0


def test_budget_defaults_and_validation(app_ctx, client):
    app_ctx.config["AGENT_DEFAULT_BUDGET"] = 17
    assert create(client).json["data"]["request"]["budget_limit"] == 17
    for index, (budget, expected) in enumerate([(0, 422), (2, 402), (501, 422), (float("inf"), 422)]):
        response = create(client, budget_limit=budget, request_key=f"budget-{index}")
        assert response.status_code == expected
    assert create(client, request_key="unknown", schema_version=2).status_code == 422


def test_attachments_require_ownership_and_unique_inventory(app_ctx, client):
    owned, other = attachment(), attachment("other")
    for ids, expected in [([other], 404), (["missing"], 404), ([owned, owned], 422),
                           ([f"missing-{index}" for index in range(9)], 422)]:
        assert create(client, attachment_ids=ids).status_code == expected
    response = create(client, attachment_ids=[owned])
    assert response.status_code == 202, response.json
    assert response.json["data"]["attachments"][0]["attachment_id"] == owned
    assert response.json["data"]["attachments"][0]["width"] == 256


@pytest.mark.parametrize("remove", ["file", "job"])
def test_completed_run_remains_readable_after_attachment_removal(app_ctx, client, remove):
    attachment_id = attachment()
    run_id = create(client, attachment_ids=[attachment_id]).json["data"]["run_id"]
    row = AgentRun.query.filter_by(run_id=run_id).one()
    row.status = "success"
    row.snapshot = {"results": [{"kind": "image", "artifact_id": "result"}]}
    db.session.commit()
    artifact = Artifact.query.filter_by(artifact_id=attachment_id).one()
    if remove == "file":
        StorageService.resolve(artifact.file_path).unlink()
    else:
        job_id = artifact.job.job_id
        assert client.delete(f"/api/jobs/{job_id}", json={"confirm_job_id": job_id}).status_code == 200
    detail = client.get(f"/api/agent/runs/{run_id}")
    listing = client.get("/api/agent/runs")
    assert detail.status_code == listing.status_code == 200
    assert detail.json["data"]["results"] == row.snapshot["results"]
    assert listing.json["data"]["items"][0]["run_id"] == run_id
    assert bool(detail.json["data"]["attachments"]) is (remove == "file")
    assert create(client, request_key="new-use", attachment_ids=[attachment_id]).status_code == 404


def test_history_attachment_metadata_does_not_expose_other_owner(app_ctx, client):
    run_id = create(client).json["data"]["run_id"]
    row = AgentRun.query.filter_by(run_id=run_id).one()
    row.request = {**row.request, "attachment_ids": [attachment("other")]}
    db.session.commit()
    assert client.get(f"/api/agent/runs/{run_id}").json["data"]["attachments"] == []


def test_v2_summary_uses_plan_steps_and_exposes_results(app_ctx, client):
    data = create(client).json["data"]
    row = AgentRun.query.filter_by(run_id=data["run_id"]).one()
    row.status = "producing"
    row.snapshot = {"request_spec": {"deliverable": "video"}, "plan": {"image": {"n": 3}, "video": {}},
                    "shots": {"image": {"status": "success", "terminal": True},
                              "video": {"status": "failed", "terminal": True}},
                    "results": [{"kind": "image", "artifact_id": "art_1"}], "pending_card": {"card_id": "old"}}
    db.session.commit()
    result = client.get(f"/api/agent/runs/{row.run_id}").json["data"]
    assert result["summary"] == {"steps_total": 2, "steps_success": 1, "steps_failed": 1}
    assert result["results"] == row.snapshot["results"]
    assert result["pending_card"] is None
    row.status = "awaiting_input"
    db.session.commit()
    assert client.get(f"/api/agent/runs/{row.run_id}").json["data"]["pending_card"]["card_id"] == "old"


def test_v1_view_remains_readable_without_v2_projection(app_ctx, client):
    row = legacy_agent_run()
    result = client.get(f"/api/agent/runs/{row.run_id}").json["data"]
    assert result["schema_version"] == 1
    assert result["summary"] == {"total": 3, "success": 0, "failed": 0, "pending": 3}
    assert all(result[key] is None for key in ("text", "attachments", "request_spec", "pending_card", "plan", "results"))
    assert create(client, request_key=row.request_key).status_code == 409


class RecordingGraph:
    def __init__(self):
        self.values, self.calls = {}, []

    def get_state(self, config):
        return SimpleNamespace(values=self.values.get(config["configurable"]["thread_id"], {}), interrupts=[])

    def invoke(self, value, config):
        self.calls.append(value)
        self.values[config["configurable"]["thread_id"]] = {**(value or {}), "status": "success"}


def test_worker_routes_versions_and_initializes_understanding(app_ctx, client):
    old = legacy_agent_run()
    new_id = create(client).json["data"]["run_id"]
    new = AgentRun.query.filter_by(run_id=new_id).one()
    new.status = "understanding"
    db.session.commit()
    v1, v2 = RecordingGraph(), RecordingGraph()
    AgentWorker(v1, v2).tick()
    assert len(v1.calls) == len(v2.calls) == 1
    assert v1.calls[0]["goal"] == old.request["goal"]
    assert v1.calls[0]["status"] == "planning"
    assert "goal" not in v2.calls[0] and "shot_count" not in v2.calls[0]
    assert v2.calls[0]["status"] == "understanding" and v2.calls[0]["results"] == []
    assert AgentRun.query.filter_by(status="success").count() == 2


def test_missing_v2_graph_cannot_execute_v1(app_ctx, client):
    run_id = create(client).json["data"]["run_id"]
    old_graph = RecordingGraph()
    AgentWorker(old_graph).advance(run_id)
    assert old_graph.calls == []
    row = AgentRun.query.filter_by(run_id=run_id).one()
    assert row.status == "needs_attention" and row.error["code"] == "AGENT_GRAPH_UNAVAILABLE"
