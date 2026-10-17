"""Simple generation reuses Job/MQ execution, with only Mock provider calls."""
import pytest
from werkzeug.datastructures import FileStorage

from app.agent.attachments import upload_attachment
from app.agent.recovery import invoke_once
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ApiTask, Artifact, Job, ToolInvocation
from app.services.job_run_service import JobRunService
from app.skills import get_registry
from app.skills.spec import ToolContext
from tests.test_agent_attachments import image_file


def invoke(name, data, **kwargs):
    return get_registry().invoke(name, data, ToolContext(role="production", approved=True, **kwargs))


def portrait(owner="local"):
    return upload_attachment(FileStorage(stream=image_file(), filename="me.png"), owner)["attachment_id"]


def understood():
    return {"request_spec": {"deliverable": "video", "recipe_hint": "single_clip", "summary": "Animate a portrait",
                              "confidence": 1}}


@pytest.mark.parametrize("mq", [False, True])
@pytest.mark.parametrize("mode", ["t2i", "i2i"])
def test_images_deliver_every_candidate_and_charge_per_image(app_ctx, h, mq, mode):
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq)
    data = {"prompt": "A portrait in a tailored suit", "mode": mode, "n": 3}
    if mode == "i2i":
        data["reference_artifact_ids"] = [portrait()]
    result = invoke("generate_image", data, idempotency_key=f"{mode}-candidates")
    assert result["output"]["expected_outputs"] == ["artifact:first_frame_image"]
    job_id = result["output"]["job_id"]
    if mq:
        from tests.test_shared_queue import drain
        job = drain(job_id)
    else:
        job = h.wait_for_terminal(job_id)
    assert job.status == "success", job.error_summary
    outputs = Artifact.query.filter_by(job_id=job.id, artifact_type="first_frame_image").all()
    assert len(outputs) == 3
    assert len({a.file_path for a in outputs}) == 3
    from app.services.storage_service import StorageService
    assert all(StorageService.resolve(a.file_path).is_file() for a in outputs)
    task = ApiTask.query.filter_by(job_id=job.id).one()
    assert task.request_payload["parameters"]["n"] == 3
    assert ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one().estimated_cost == 6
    if mode == "i2i":
        assert task.model_id == app_ctx.config["DEFAULT_I2I_TEST_IMAGE_MODEL"]
        payload = (task.queue_data or {}).get("wire_payload") or task.request_payload
        assert any("image" in item for item in payload["input"]["messages"][0]["content"])
    replay = invoke("generate_image", data, idempotency_key=f"{mode}-candidates")
    assert replay["replayed"] and replay["output"]["job_id"] == job_id
    assert ApiTask.query.filter_by(job_id=job.id).count() == 1


def test_explicit_count_overrides_legacy_params_without_cost_drift(app_ctx, monkeypatch):
    monkeypatch.setattr(JobRunService, "start", lambda *a, **kw: {})
    for data, expected in [({"params": {"n": 2}}, 2), ({"params": {"n": 2}, "n": 1}, 1),
                           ({"params": {"n": 2}, "n": 4}, 4)]:
        result = invoke("generate_image", {"prompt": "Cat", **data})
        assert result["replayed"] is False
        invocation = ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one()
        assert invocation.estimated_cost == 2 * expected
        assert invocation.job.config["node_model_params"]["submit_first_frame_image"]["n"] == expected


def test_omitted_count_uses_frozen_catalog_default(app_ctx, monkeypatch):
    from app.services.model_service import ModelService
    monkeypatch.setattr(JobRunService, "start", lambda *a, **kw: {})
    model = ModelService.get_model(app_ctx.config["DEFAULT_IMAGE_MODEL"])
    model.default_params = {**model.default_params, "n": 3}
    db.session.commit()
    result = invoke("generate_image", {"prompt": "Cat"})
    invocation = ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one()
    assert invocation.estimated_cost == 6
    model.default_params = {**model.default_params, "n": 1}
    db.session.commit()
    assert invocation.job.config["node_model_params"]["submit_first_frame_image"]["n"] == 3


def test_multiple_references_reach_multimodal_payload_without_changing_classic_primary(app_ctx):
    from app.adapters.dashscope_multimodal_image import DashScopeMultimodalSyncAdapter
    from app.services.model_service import ModelService
    adapter = DashScopeMultimodalSyncAdapter(ModelService.get_model("wan2.7-image"))
    payload = adapter.build_payload({"prompt": "Keep both people", "source_images": ["one.png", "two.png"]}, {})
    assert payload["input"]["messages"][0]["content"][:-1] == [{"image": "one.png"}, {"image": "two.png"}]
    classic = adapter.build_payload({"prompt": "Keep primary person", "source_image": "primary.png",
                                     "source_images": [{"file_path": "other.png"}]}, {})
    assert classic["input"]["messages"][0]["content"][:-1] == [{"image": "primary.png"}]


@pytest.mark.parametrize("data", [
    {"mode": "i2i"}, {"reference_artifact_ids": ["unknown"]}, {"n": 0}, {"n": 5},
    {"mode": "i2i", "reference_artifact_ids": ["same", "same"]},
])
def test_invalid_image_input_never_launches(app_ctx, data):
    with pytest.raises(AppError) as exc:
        invoke("generate_image", {"prompt": "Cat", **data})
    assert exc.value.status_code == 422
    assert Job.query.count() == ToolInvocation.query.count() == 0


def test_i2i_model_must_support_reference_images(app_ctx):
    reference = portrait()
    with pytest.raises(AppError) as exc:
        invoke("generate_image", {"prompt": "Suit", "mode": "i2i", "reference_artifact_ids": [reference],
                                  "model_id": "wan2.6-image"})
    assert exc.value.code == "MODEL_CAPABILITY_MISMATCH"
    assert ApiTask.query.count() == 0


def test_animate_shot_shares_i2v_job_and_seconds_pricing(app_ctx, h):
    first_frame = portrait()
    for duration in (5, 15):
        result = invoke("animate_shot", {"first_frame_artifact_id": first_frame, "prompt": "The person smiles",
                                         "params": {"duration": duration}}, budget_scope=f"clip-{duration}")
        assert result["output"]["expected_outputs"] == ["artifact:i2v_video"]
        job = h.wait_for_terminal(result["output"]["job_id"])
        assert job.status == "success", job.error_summary
        assert Artifact.query.filter_by(job_id=job.id, artifact_type="i2v_video").count() == 1
        task = ApiTask.query.filter_by(job_id=job.id).one()
        assert task.request_payload["parameters"]["duration"] == duration
        invocation = ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one()
        assert invocation.estimated_cost == duration


def test_last_frame_is_reserved_and_requires_approval(app_ctx):
    data = {"prompt": "Smile", "first_frame_artifact_id": "frame", "last_frame_artifact_id": "last"}
    with pytest.raises(AppError) as exc:
        invoke("animate_shot", data)
    assert exc.value.status_code == 422
    with pytest.raises(AppError) as exc:
        get_registry().invoke("animate_shot", {"prompt": "Smile", "first_frame_artifact_id": "frame"},
                              ToolContext(role="production"))
    assert exc.value.code == "APPROVAL_REQUIRED"
    assert Job.query.count() == ToolInvocation.query.count() == 0


@pytest.mark.parametrize("tool", ["generate_image", "animate_shot"])
def test_v2_generation_references_and_replay_stay_within_run(app_ctx, monkeypatch, tool):
    monkeypatch.setattr(JobRunService, "start", lambda *a, **kw: {})
    reference = portrait("alice")
    run = AgentRun(owner_id="alice", request_key="one", request={"schema_version": 2, "text": "Portrait",
                   "attachment_ids": [], "budget_limit": 100}, snapshot=understood())
    other = AgentRun(owner_id="alice", request_key="two", request={"schema_version": 2, "text": "Portrait",
                     "attachment_ids": [reference], "budget_limit": 100}, snapshot=understood())
    db.session.add_all([run, other])
    db.session.commit()
    data = {"prompt": "Smile", **({"mode": "i2i", "reference_artifact_ids": [reference]} if tool == "generate_image"
                                  else {"first_frame_artifact_id": reference})}
    with pytest.raises(AppError) as exc:
        invoke(tool, data, budget_scope=run.run_id, idempotency_key=f"wrong-{tool}")
    assert exc.value.code == "ATTACHMENT_NOT_FOUND"
    result = invoke(tool, data, budget_scope=other.run_id, idempotency_key=f"allowed-{tool}")
    assert result["output"]["job_id"]
    with pytest.raises(AppError) as exc:
        invoke(tool, data, budget_scope=run.run_id, idempotency_key=f"allowed-{tool}")
    assert exc.value.code == "IDEMPOTENCY_KEY_CONFLICT"


@pytest.mark.config(AGENT_MODE_ENABLED=True, API_AUTH_REQUIRED=True,
                    JWT_SECRET_KEY="simple-generation-test-jwt-secret-more-than-32-bytes")
@pytest.mark.parametrize("tool", ["generate_image", "animate_shot"])
def test_new_skill_http_references_require_owner(app_ctx, client, monkeypatch, tool):
    from flask_jwt_extended import create_access_token
    monkeypatch.setattr(JobRunService, "start", lambda *a, **kw: {})
    reference = portrait("alice")
    data = {"prompt": "Smile", **({"mode": "i2i", "reference_artifact_ids": [reference]} if tool == "generate_image"
                                  else {"first_frame_artifact_id": reference})}
    payload = {"role": "production", "approved": True, "input": data}
    url = f"/api/skills/{tool}/invoke"
    assert client.post(url, json=payload).status_code == 401
    for owner, expected in [("bob", 404), ("alice", 200)]:
        response = client.post(url, json=payload, headers={"Authorization": f"Bearer {create_access_token(identity=owner)}"})
        assert response.status_code == expected, response.json
    assert ApiTask.query.count() == 0


def test_v2_may_animate_its_own_generated_image_but_not_other_run_result(app_ctx, h, monkeypatch):
    run = AgentRun(owner_id="local", request_key="own-output", request={"schema_version": 2, "text": "Cat",
                   "attachment_ids": [], "budget_limit": 100}, snapshot=understood())
    db.session.add(run)
    db.session.commit()
    result = invoke("generate_image", {"prompt": "A cat"}, budget_scope=run.run_id)
    job = h.wait_for_terminal(result["output"]["job_id"])
    frame = Artifact.query.filter_by(job_id=job.id, artifact_type="first_frame_image").one()
    monkeypatch.setattr(JobRunService, "start", lambda *a, **kw: {})
    assert invoke("animate_shot", {"first_frame_artifact_id": frame.artifact_id, "prompt": "Cat smiles"},
                  budget_scope=run.run_id)["output"]["job_id"]
    other = AgentRun(owner_id="local", request_key="not-own-output", request={"schema_version": 2, "text": "Dog",
                     "attachment_ids": [], "budget_limit": 100}, snapshot=understood())
    db.session.add(other)
    db.session.commit()
    with pytest.raises(AppError) as exc:
        invoke("animate_shot", {"first_frame_artifact_id": frame.artifact_id, "prompt": "Other story"}, budget_scope=other.run_id)
    assert exc.value.code == "ATTACHMENT_NOT_FOUND"


def test_v2_video_generation_requires_completed_understanding(app_ctx):
    run = AgentRun(owner_id="local", request_key="still-understanding", request={"schema_version": 2,
                   "text": "Use the user's selected model", "attachment_ids": [], "budget_limit": 100})
    db.session.add(run)
    db.session.commit()
    with pytest.raises(AppError) as exc:
        invoke("generate_video", {"mode": "t2v", "prompt": "A cat"}, budget_scope=run.run_id)
    assert exc.value.code == "INVALID_AGENT_STATE"
    assert Job.query.count() == ApiTask.query.count() == 0


@pytest.mark.config(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True, MQ_MAX_ATTEMPTS=2)
def test_missing_candidates_resume_original_task_without_paid_resubmission(app_ctx, monkeypatch):
    from app.adapters.mock import MockAdapter
    from app.queue.operations import reconcile
    from tests.test_shared_queue import drain
    original_submit, original_poll = MockAdapter.submit, MockAdapter.poll
    submissions = []

    def submit(adapter, payload):
        submissions.append(payload)
        return original_submit(adapter, payload)

    def incomplete(adapter, provider_id):
        return {**original_poll(adapter, provider_id), "result_urls": ["https://fixture/only-one"]}

    monkeypatch.setattr(MockAdapter, "submit", submit)
    monkeypatch.setattr(MockAdapter, "poll", incomplete)
    result = invoke("generate_image", {"prompt": "Three cat portraits", "n": 3}, budget_scope="partial-candidates")
    job = drain(result["output"]["job_id"])
    assert job.status == "failed"
    task = ApiTask.query.filter_by(job_id=job.id).one()
    assert task.queue_phase == "failed"
    assert len(submissions) == 1
    # Simulate reconciliation obtaining the full provider result, then retry only the read.
    task.response_payload = {**task.response_payload, "result_urls": [f"https://fixture/{i}" for i in range(3)]}
    db.session.commit()
    reconcile(task.api_task_id, retry=True, reason="Complete provider output recovered in offline test")
    assert drain(job.job_id).status == "success"
    assert Artifact.query.filter_by(job_id=job.id, artifact_type="first_frame_image").count() == 3
    assert len(submissions) == ApiTask.query.filter_by(job_id=job.id).count() == 1
    assert ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one().estimated_cost == 6


@pytest.mark.parametrize("name", ["generate_image", "animate_shot"])
def test_recovery_relinks_job_without_repeating_paid_call(app_ctx, monkeypatch, name):
    from app.agent import recovery
    monkeypatch.setattr(JobRunService, "start", lambda *a, **kw: {})
    monkeypatch.setattr(recovery, "recover_job", lambda job, scope: None)
    data = {"prompt": "A cat"}
    if name == "animate_shot":
        data["first_frame_artifact_id"] = portrait()
    result = invoke(name, data, budget_scope="recovery", idempotency_key=f"recover-{name}")
    invocation = ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one()
    invocation.job = None
    invocation.output_payload = None
    db.session.commit()
    recovered = invoke_once(get_registry(), name, data, ToolContext(role="production", approved=True,
        budget_scope="recovery", idempotency_key=f"recover-{name}"))
    assert recovered["output"]["job_id"] == result["output"]["job_id"]
    assert ToolInvocation.query.count() == 1
