"""W3: actual private Skills/Jobs/MQ with isolated Mock providers and real media."""
from copy import deepcopy
from io import BytesIO
import os
from pathlib import Path
import subprocess
import wave

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from app.adapters.mock import MockAdapter
from app.agent.attachments import upload_attachment
from app.agent.request_spec import RequestSpec
from app.agent.transform_plan import validate_transform_plan
from app.agent import transform_policy as policy
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ApiTask, Artifact, Job, ToolInvocation
from app.services.job_run_service import JobRunService
from app.services.model_service import ModelService, WAN3_LEGACY_CAPABILITIES
from app.services.storage_service import StorageService
from app.skills import get_registry
from app.skills.budget import BudgetGuard
from app.skills.spec import ToolContext
from app.utils.ids import new_id
from tests.test_new_model_integration import complete

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True)


def upload(data, name):
    return upload_attachment(FileStorage(stream=BytesIO(data), filename=name), "local")["attachment_id"]


def prepared(tmp_path, operation="reference", multimodal=False):
    path = tmp_path / "transform-source.mp4"
    subprocess.run([os.environ["FFMPEG_BINARY"], "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=256x256:r=24:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True, timeout=30)
    source = upload(path.read_bytes(), "source.mp4")
    refs = [{"type": "reference_video", "artifact_id": source}]
    uses = [{"attachment_id": source, "kind": "video", "role": "content_ref" if operation == "reference" else "transform_source",
             "description": "A blue clip", "reason": "User input"}]
    if multimodal:
        image = BytesIO(); Image.new("RGB", (256, 256), "red").save(image, format="PNG")
        audio = BytesIO()
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(b"\0\0" * 16000)
        for data, name, kind, role, media_type in [
            (image.getvalue(), "image.png", "image", "content_ref", "reference_image"),
            (audio.getvalue(), "voice.wav", "audio", "audio_ref", "reference_audio"),
            (b"A quiet blue scene", "brief.txt", "file", "document_ref", "file"),
        ]:
            artifact_id = upload(data, name)
            refs.append({"type": media_type, "artifact_id": artifact_id})
            uses.append({"attachment_id": artifact_id, "kind": kind, "role": role, "description": name, "reason": "User input"})
    spec = RequestSpec.model_validate({"deliverable": "video", "recipe_hint": "video_transform", "summary": "Transform clip",
        "target_duration_sec": 4, "attachments": uses, "constraints": {"model_preferences": ["wan3.0"]}, "confidence": 1,
        "transform": {"operation": operation, "source_attachment_id": None if operation == "reference" else source}}).model_dump(mode="json")
    run = AgentRun(owner_id="local", request_key=new_id("test"), status="awaiting_approval",
        request={"schema_version": 2, "text": "Use wan3.0 to transform this clip", "attachment_ids": [r["artifact_id"] for r in refs],
                 "budget_limit": 100}, snapshot={"request_spec": spec})
    db.session.add(run); db.session.commit()
    plan = validate_transform_plan({"operation": operation, "title": "Transform", "model_id": "wan3.0-video",
        "prompt": "Preserve the scene and move the camera slowly", "params": {"duration": 4, "resolution": "480P", "prompt_extend": True},
        "media": refs, "source_artifact_id": None if operation == "reference" else source, "rationale": "One native generation"}, spec, run=run)
    run.snapshot = {**run.snapshot, "plan": plan}; db.session.commit()
    policy.approve(run, plan)
    run.status = "producing"; db.session.commit()
    ctx = ToolContext(role="production", approved=True, budget_scope=run.run_id, budget_limit=100,
        idempotency_key=policy.invocation_key(run.run_id, plan["plan_hash"]), transform_hash=plan["plan_hash"])
    return run, plan, ctx


def invoke(plan, ctx):
    return get_registry().invoke("transform_video", {"plan_hash": plan["plan_hash"]}, ctx)


@pytest.mark.parametrize("operation", ["reference", "edit", "extend"])
@pytest.mark.parametrize("mq", [False, True])
def test_transform_job_and_mq_bill_actual_input_plus_final_output_once(app_ctx, h, tmp_path, operation, mq):
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq)
    run, plan, ctx = prepared(tmp_path, operation, multimodal=operation == "reference")
    result = invoke(plan, ctx)
    job = complete(h, result["output"]["job_id"], mq)
    task = ApiTask.query.filter_by(job_id=job.id).one()
    assert task.model_id == "wan3.0-video"
    payload = (task.queue_data or {}).get("wire_payload") or task.request_payload
    assert [ref["type"] for ref in payload["input"]["media"]] == [ref["type"] for ref in plan["media"]]
    assert payload["parameters"]["duration"] == 4
    assert plan["cost_breakdown"]["billable_seconds"] == 6
    assert plan["estimated_cost"] == 6
    assert BudgetGuard.spent(run.run_id) == 6
    assert Artifact.query.filter_by(job_id=job.id, artifact_type="r2v_flash_video").count() == 1
    assert invoke(plan, ctx)["replayed"]
    assert ApiTask.query.filter_by(job_id=job.id).count() == 1
    assert BudgetGuard.spent(run.run_id) == 6
    assert job.config["agent_output_policy"]["compress_output"] is False


def test_public_approval_boolean_and_alternate_paid_tools_cannot_bypass_receipt(app_ctx, tmp_path):
    run, plan, ctx = prepared(tmp_path)
    ctx.transform_hash = None
    with pytest.raises(AppError, match="server"):
        invoke(plan, ctx)
    with pytest.raises(AppError) as blocked:
        get_registry().invoke("generate_video", {"mode": "t2v", "prompt": "Bypass", "model_id": "wan3.0-video"}, ctx)
    assert blocked.value.code == "UNSAFE_RETRY"
    assert ToolInvocation.query.count() == 0
    assert ApiTask.query.count() == 0


@pytest.mark.parametrize("change,code", [("price", "TRANSFORM_QUOTE_EXPIRED"), ("file", "TRANSFORM_INPUT_CHANGED")])
def test_change_after_approval_stops_before_ledger_or_job(app_ctx, tmp_path, change, code):
    run, plan, ctx = prepared(tmp_path)
    if change == "price":
        model = ModelService.get_model(plan["model_id"])
        caps = deepcopy(model.capabilities); caps["pricing"]["resolution_rates"]["480P"] = 9
        model.capabilities = caps; db.session.commit()
    else:
        artifact = Artifact.query.filter_by(artifact_id=plan["media"][0]["artifact_id"]).one()
        StorageService.resolve(artifact.file_path).write_bytes(b"replaced bytes")
    before = Job.query.count()
    with pytest.raises(AppError) as blocked:
        invoke(plan, ctx)
    assert blocked.value.code == code
    assert Job.query.count() == before and ToolInvocation.query.count() == 0


@pytest.mark.parametrize("change", ["price", "prompt", "params", "queued_media"])
def test_mq_revalidates_frozen_payload_before_provider_submit(app_ctx, tmp_path, monkeypatch, change):
    from app.queue.dispatch import dispatch_once
    from app.queue.execution import process_event
    from app.models import TaskOutbox
    app_ctx.config.update(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True)
    run, plan, ctx = prepared(tmp_path)
    result = invoke(plan, ctx)
    job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
    dispatch_once()
    task = ApiTask.query.filter_by(job_id=job.id).one()
    if change == "price":
        model = ModelService.get_model(plan["model_id"])
        caps = deepcopy(model.capabilities); caps["pricing"]["resolution_rates"]["480P"] = 9
        model.capabilities = caps
    elif change == "prompt":
        from app.services.prompt_service import PromptService
        prompt = PromptService.get_active_for_template(job.template, "r2v_flash", job_id=job.id)
        prompt.content = "Changed without approval"
    elif change == "params":
        config = deepcopy(job.config); config["node_model_params"]["submit_r2v_flash"]["duration"] = 5; job.config = config
    else:
        data = deepcopy(task.queue_data); data["inputs"]["media"] = []; task.queue_data = data
    db.session.commit()
    def forbidden(*args, **kwargs):
        pytest.fail("Changed payload reached provider")
    monkeypatch.setattr(MockAdapter, "submit", forbidden)
    event = TaskOutbox.query.filter_by(task_id=task.id, phase="submit").one()
    process_event(event.id)
    db.session.refresh(task)
    assert task.queue_phase == "failed" and task.provider_task_id is None
    assert ApiTask.query.filter_by(job_id=job.id).count() == 1


def test_private_result_and_manual_dispatch_cannot_escape_owner_or_receipt(app_ctx, h, client, tmp_path):
    run, plan, ctx = prepared(tmp_path)
    result = invoke(plan, ctx); job = complete(h, result["output"]["job_id"], False)
    for endpoint, payload in [("run-full", {}), ("run-full", {"restart": True}),
                              ("run-node", {"node_key": "submit_r2v_flash", "force": True})]:
        response = client.post(f"/api/jobs/{job.job_id}/{endpoint}", json=payload)
        assert response.status_code == 409, response.json
        assert response.json["error"]["code"] == "UNSAFE_RETRY"
    from app.agent.private_views import hidden_job_ids
    assert job.id in hidden_job_ids("other")
    assert job.id not in hidden_job_ids("local")
    from app.services.task_center_query import shared_workflow
    assert Job.query.filter(Job.id == job.id, shared_workflow()).count() == 0


def test_existing_factory_profile_upgrades_without_resetting_operator_prices(app_ctx):
    model = ModelService.get_model("wan3.0-video")
    caps = deepcopy(WAN3_LEGACY_CAPABILITIES[model.model_id])
    caps["pricing"]["credits_per_unit"] = 123
    caps["agent_selectable"] = False
    model.capabilities = caps; db.session.commit()
    ModelService.seed_defaults(); db.session.refresh(model)
    assert "video_extend" in model.capabilities["modes"]
    assert model.capabilities["pricing"]["credits_per_unit"] == 123
    assert model.capabilities["agent_selectable"] is False
    caps = deepcopy(model.capabilities); caps["modes"] = ["t2v"]
    model.capabilities = caps; db.session.commit(); ModelService.seed_defaults(); db.session.refresh(model)
    assert model.capabilities["modes"] == ["t2v"]


def test_failed_or_unknown_submit_is_not_paid_again(app_ctx, h, client, tmp_path, monkeypatch):
    from app.agent.recovery import invoke_once
    run, plan, ctx = prepared(tmp_path)
    calls = []
    def unknown(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("Provider outcome is unknown")
    monkeypatch.setattr(MockAdapter, "submit", unknown)
    result = invoke(plan, ctx)
    job = h.wait_for_terminal(result["output"]["job_id"])
    assert job.status == "failed" and len(calls) == 1
    spent = BudgetGuard.spent(run.run_id)
    for callback in (lambda: invoke(plan, ctx), lambda: invoke_once(get_registry(), "transform_video", {"plan_hash": plan["plan_hash"]}, ctx)):
        with pytest.raises(AppError):
            callback()
    assert client.post(f"/api/jobs/{job.job_id}/run-full", json={}).status_code == 409
    assert len(calls) == 1 and BudgetGuard.spent(run.run_id) == spent
    assert ToolInvocation.query.filter_by(tool_name="transform_video").one().attempt == 1


def test_receipt_replay_and_paid_poll_survive_price_or_enabled_change(app_ctx, tmp_path):
    from tests.test_shared_queue import step, drain
    app_ctx.config.update(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True)
    run, plan, ctx = prepared(tmp_path)
    result = invoke(plan, ctx)
    step()
    job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
    task = ApiTask.query.filter_by(job_id=job.id).one()
    assert task.provider_task_id
    model = ModelService.get_model(plan["model_id"])
    caps = deepcopy(model.capabilities); caps["pricing"]["resolution_rates"]["480P"] = 1000
    model.capabilities = caps; model.enabled = False; db.session.commit()
    assert policy.approve(run, plan)["plan_hash"] == plan["plan_hash"]
    assert invoke(plan, ctx)["replayed"]
    assert drain(job.job_id).status == "success"
    assert BudgetGuard.spent(run.run_id) == 6
    assert ApiTask.query.filter_by(job_id=job.id).count() == 1


def test_lost_job_link_recovers_same_queued_job_without_new_generation(app_ctx, tmp_path, monkeypatch):
    from app.agent.recovery import invoke_once
    app_ctx.config.update(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True)
    run, plan, ctx = prepared(tmp_path)
    result = invoke(plan, ctx)
    invocation = ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one()
    job_id = result["output"]["job_id"]
    invocation.job = None; invocation.output_payload = None; db.session.commit()
    replay = invoke_once(get_registry(), "transform_video", {"plan_hash": plan["plan_hash"]}, ctx)
    assert replay["output"]["job_id"] == job_id
    assert ToolInvocation.query.filter_by(tool_name="transform_video").count() == 1
    assert BudgetGuard.spent(run.run_id) == 6
    from tests.test_shared_queue import drain
    assert drain(job_id).status == "success"
    assert ApiTask.query.count() == 1


def test_legacy_r2v_classification_does_not_grant_transform_capabilities():
    from types import SimpleNamespace
    legacy = SimpleNamespace(task_type="reference_to_video", capabilities={})
    assert ModelService.supports_mode(legacy, "r2v")
    assert not any(ModelService.supports_mode(legacy, mode) for mode in ("omni_reference", "video_edit", "video_extend"))
