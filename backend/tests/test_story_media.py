"""Phase D media, approved model pinning and private-output recovery (Mock only)."""
from copy import deepcopy
from pathlib import Path
import subprocess

from flask_jwt_extended import create_access_token
from PIL import Image
import pytest

from app.agent import plan_versions as versions
from app.agent.production_policy import invocation_key
from app.agent.recovery import invoke_once
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, AgentShotTask, ApiTask, Artifact, Job, ModelRegistry, ToolInvocation
from app.services.artifact_service import ArtifactService
from app.services.job_run_service import JobRunService
from app.services.job_service import JobService
from app.services.model_service import ModelService
from app.services.storage_service import StorageService, MOCK_PNG_BYTES
from app.services.video_compression_service import VideoCompressionService
from app.services.video_media_service import VideoMediaService
from app.skills import get_registry, job_backed
from app.skills.budget import BudgetGuard
from app.skills.spec import ToolContext
from app.skills.tools.animate_shot import AnimateShotInput
from app.skills.tools.extract_frame import ExtractFrameInput, MOCK_VIDEO_BYTES
from tests.test_story_previews import setup

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
                               AGENT_STORY_PRODUCTION_ENABLED=True)


def private_artifact(row, kind="first_frame_image", body=MOCK_PNG_BYTES):
    template = job_backed.ensure_agent_template()
    job = JobService.create_job({"template_id": template.template_id, "strategy": "skill:fixture",
        **job_backed.node_selection([]), "job_config": {"skill": {"budget_scope": row.run_id},
        "agent_story_production": {"run_id": row.run_id}}})
    path = StorageService.job_dir(job.job_id) / ("test.mp4" if "video" in kind else "test.png")
    path.write_bytes(body)
    artifact = ArtifactService.register_artifact(job, str(path), kind)
    job.status = "success"
    db.session.commit()
    return artifact


def task(row, version, kind, target, data, artifact=None):
    result = AgentShotTask(run_id=row.run_id, plan_version=version.version, target_type=kind,
        target_id=target, inputs_hash=versions.inputs_hash(data), status="success" if artifact else "pending",
        artifact_ids=[artifact.artifact_id] if artifact else [])
    db.session.add(result)
    db.session.commit()
    return result


def context(row, item=None, key="extract"):
    return ToolContext(role="production", approved=True, budget_scope=row.run_id,
        budget_limit=row.request["budget_limit"], shot_task_id=item.id if item else None,
        idempotency_key=invocation_key(item) if item else key)


def production(override=False, bridge=False):
    row, version, _registry = setup(characters=False)
    plan = deepcopy(version.plan)
    if override:
        source = ModelService.get_model("wan2.7-i2v")
        model = ModelRegistry(model_id="review-i2v", display_name="review", provider=source.provider,
            task_type=source.task_type, adapter_name=source.adapter_name, enabled=True,
            capabilities={**deepcopy(source.capabilities), "pricing": {"unit": "second", "credits_per_unit": 3}},
            default_params=deepcopy(source.default_params), parameter_schema=deepcopy(source.parameter_schema))
        db.session.add(model)
        row.snapshot = {**row.snapshot, "story_model_overrides": {"s01:motion": model.model_id}}
        plan["shots"][0]["motion"]["model_id"] = model.model_id
        db.session.commit()
    if bridge:
        plan["shots"][0]["motion"]["mode"] = "first_last_frame"
        plan["shots"][0]["end_frame"] = deepcopy(plan["shots"][0]["first_frame"])
    if override or bridge:
        version = versions.create_version(row, plan, version.story_package, version.check, author="user")
    row.snapshot = {**row.snapshot, "production": {"approved_version": version.version,
                                                  "plan_version": version.version, "status": "producing"}}
    db.session.commit()
    shot = version.plan["shots"][0]
    frame = private_artifact(row)
    task(row, version, "keyframe", "s01", {"source": "first"}, frame)
    last = private_artifact(row) if bridge else None
    if last:
        task(row, version, "end_frame", "s01", {"source": "last"}, last)
    data = AnimateShotInput(first_frame_artifact_id=frame.artifact_id,
        last_frame_artifact_id=last.artifact_id if last else None, model_id=shot["motion"]["model_id"],
        prompt=shot["motion"]["prompt"], params=shot["motion"]["params"]).model_dump(mode="json")
    item = task(row, version, "video", "s01", data)
    return row, version, data, item


@pytest.mark.parametrize("mq", [False, True])
def test_bridge_reaches_shared_i2v_payload_in_inline_and_mq(app_ctx, h, mq):
    app_ctx.config.update(AGENT_ENABLE_KEYFRAME_BRIDGE=True, MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq)
    row, version, data, item = production(bridge=True)
    output = get_registry().invoke("animate_shot", data, context(row, item))
    if mq:
        from tests.test_shared_queue import drain
        job = drain(output["output"]["job_id"])
    else:
        job = h.wait_for_terminal(output["output"]["job_id"])
    assert job.status == "success", job.error_summary
    api = ApiTask.query.filter_by(job_id=job.id).one()
    payload = (api.queue_data or {}).get("wire_payload") or api.request_payload
    assert [media["type"] for media in payload["input"]["media"]] == ["first_frame", "last_frame"]
    assert output["estimated_cost"] == data["params"]["duration"]
    assert job.config["agent_story_production"]["task_id"] == item.id
    assert Artifact.query.filter_by(job_id=job.id, artifact_type="i2v_video").count() == 1


def test_review_model_is_priced_pinned_and_recovered_without_default_reversion(app_ctx, monkeypatch):
    row, version, data, item = production(override=True)
    monkeypatch.setattr(JobRunService, "start", lambda *_a, **_kw: None)
    result = get_registry().invoke("animate_shot", data, context(row, item))
    job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
    assert result["estimated_cost"] == 3 * data["params"]["duration"]
    assert job.config["node_models"]["submit_i2v"] == "review-i2v"
    from app.agent.model_policy import validate_job_policy
    validate_job_policy(job)
    assert get_registry().invoke("animate_shot", data, context(row, item))["replayed"]
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == 1
    changed = deepcopy(row.snapshot)
    changed["request_spec"].setdefault("constraints", {})["model_exclusions"] = ["review"]
    row.snapshot = changed
    db.session.commit()
    with pytest.raises(AppError):
        validate_job_policy(job)


@pytest.mark.parametrize("field", ["prompt", "params", "model_id", "first_frame_artifact_id"])
def test_task_input_tampering_never_charges(app_ctx, field):
    row, version, data, item = production()
    data[field] = {"duration": 10} if field == "params" else "tampered"
    before = BudgetGuard.spent(row.run_id)
    with pytest.raises(AppError) as error:
        get_registry().invoke("animate_shot", data, context(row, item))
    assert error.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert BudgetGuard.spent(row.run_id) == before
    assert not ApiTask.query.first()


def test_unapproved_or_old_plan_cannot_submit(app_ctx):
    row, version, data, item = production()
    row.snapshot = {**row.snapshot, "production": {"plan_version": version.version}}
    db.session.commit()
    with pytest.raises(AppError) as error:
        get_registry().invoke("animate_shot", data, context(row, item))
    assert error.value.code == "PLAN_VERSION_CONFLICT"
    assert not ApiTask.query.first()


@pytest.mark.parametrize("reason", ["flag", "capability", "old_model"])
def test_bridge_requirements_reject_before_billing(app_ctx, reason):
    app_ctx.config["AGENT_ENABLE_KEYFRAME_BRIDGE"] = reason != "flag"
    row, version, data, item = production(bridge=True)
    if reason == "capability":
        model = ModelService.get_model("wan2.7-i2v")
        model.capabilities = {**model.capabilities, "modes": ["i2v"]}
        db.session.commit()
    if reason == "old_model":
        data["model_id"] = "wan2.6-i2v"
    before = BudgetGuard.spent(row.run_id)
    with pytest.raises(AppError):
        get_registry().invoke("animate_shot", data, context(row))
    assert BudgetGuard.spent(row.run_id) == before
    assert not ApiTask.query.first()


def test_free_extraction_replay_and_interrupted_receipt_reuse_one_artifact(app_ctx):
    row, version, _registry = setup(characters=False)
    video = private_artifact(row, "i2v_video", MOCK_VIDEO_BYTES)
    data = ExtractFrameInput(video_artifact_id=video.artifact_id).model_dump(mode="json")
    first = get_registry().invoke("extract_frame", data, context(row))
    assert first["estimated_cost"] == 0
    artifact = Artifact.query.filter_by(artifact_id=first["output"]["artifact_id"]).one()
    with Image.open(StorageService.resolve(artifact.file_path)) as frame:
        frame.verify()
    replay = get_registry().invoke("extract_frame", data, context(row))
    assert replay["replayed"] and replay["output"] == first["output"]
    invocation = ToolInvocation.query.filter_by(invocation_id=first["invocation_id"]).one()
    invocation.status, invocation.output_payload = "pending", {}
    db.session.commit()
    recovered = invoke_once(get_registry(), "extract_frame", data, context(row))
    assert recovered["output"] == first["output"]
    assert Artifact.query.filter_by(artifact_type="tail_frame_image").count() == 1
    assert not ApiTask.query.first()


def test_extract_rejects_wrong_source_and_cross_run_replay(app_ctx):
    row, version, _registry = setup(characters=False)
    image = private_artifact(row)
    with pytest.raises(AppError) as error:
        get_registry().invoke("extract_frame", {"video_artifact_id": image.artifact_id}, context(row))
    assert error.value.code == "INVALID_INPUT"
    video = private_artifact(row, "i2v_video", MOCK_VIDEO_BYTES)
    data = {"video_artifact_id": video.artifact_id}
    result = get_registry().invoke("extract_frame", data, context(row))
    other = AgentRun(owner_id=row.owner_id, request_key="other", request=deepcopy(row.request), snapshot=deepcopy(row.snapshot))
    db.session.add(other)
    db.session.commit()
    with pytest.raises(AppError) as error:
        get_registry().invoke("extract_frame", data, context(other))
    assert error.value.code == "ATTACHMENT_NOT_FOUND"
    with pytest.raises(AppError) as error:
        get_registry().invoke("extract_frame", {**data, "position": "first"}, context(row))
    assert error.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert ToolInvocation.query.filter_by(tool_name="extract_frame").count() == 1


def test_private_video_and_tail_are_not_republished_by_another_user(app_ctx, client):
    app_ctx.config.update(API_AUTH_REQUIRED=True, JWT_SECRET_KEY="story-media-secret-with-at-least-thirty-two-characters")
    row, version, _registry = setup(characters=False)
    row.owner_id = "alice"
    db.session.commit()
    video = private_artifact(row, "i2v_video", MOCK_VIDEO_BYTES)
    result = get_registry().invoke("extract_frame", {"video_artifact_id": video.artifact_id}, context(row))
    for identity, expected in [("alice", 200), ("bob", 404)]:
        headers = {"Authorization": f"Bearer {create_access_token(identity=identity)}"}
        for artifact_id in [video.artifact_id, result["output"]["artifact_id"]]:
            assert client.get(f"/api/artifacts/{artifact_id}/preview", headers=headers).status_code == expected
        listing = client.get("/api/artifacts", headers=headers).json["data"]["artifacts"]
        assert (video.artifact_id in {a["artifact_id"] for a in listing}) is (identity == "alice")
    headers = {"Authorization": f"Bearer {create_access_token(identity='bob')}"}
    response = client.post("/api/jobs", json={"template_id": job_backed.AGENT_TEMPLATE_ID,
        "initial_artifacts": {"first_frame_image": result["output"]["artifact_id"]}}, headers=headers)
    assert response.status_code == 404


def test_real_ffmpeg_tail_extract_returns_last_decoded_frame(app_ctx):
    binary = VideoCompressionService.resolve_ffmpeg()
    source = StorageService.root() / "two-colours.mp4"
    subprocess.run([binary, "-nostdin", "-hide_banner", "-y", "-f", "lavfi", "-i", "color=red:s=64x64:d=0.5:r=10",
        "-f", "lavfi", "-i", "color=blue:s=64x64:d=0.5:r=10", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
    first, last = StorageService.root() / "first.png", StorageService.root() / "last.png"
    VideoMediaService.extract_frame(source, first, position="first")
    VideoMediaService.extract_frame(source, last, position="last")
    with Image.open(first) as image:
        red, _green, blue = image.convert("RGB").getpixel((20, 20))
        assert red > blue + 150
    with Image.open(last) as image:
        red, _green, blue = image.convert("RGB").getpixel((20, 20))
        assert blue > red + 150
    with pytest.raises(AppError):
        VideoMediaService.extract_frame(source, last, position="first", timestamp_sec=2)


@pytest.mark.parametrize("invalid", [False, True])
def test_only_reserved_repair_receipt_may_change_motion(app_ctx, monkeypatch, invalid):
    row, version, data, previous = production()
    previous.status = "failed"
    revised = {**data, "prompt": "人物在花园平静漫步，镜头缓慢跟拍。"}
    replacement = AgentShotTask(run_id=row.run_id, plan_version=version.version, target_type="video", target_id="s01",
        attempt=2, inputs_hash=versions.inputs_hash(revised), status="pending", artifact_ids=[])
    db.session.add(replacement)
    db.session.flush()
    row.snapshot = {**row.snapshot, "production_repairs": {str(previous.id): {
        "failed_task_id": previous.id, "shot_id": "s01", "plan_version": version.version,
        "action": "rewrite_prompt", "category": "content_policy", "status": "running",
        "reserved_credits": 0 if invalid else 10, "motion_prompt": revised["prompt"], "replacement_task_id": replacement.id}}}
    db.session.commit()
    monkeypatch.setattr(JobRunService, "start", lambda *_a, **_kw: None)
    if invalid:
        with pytest.raises(AppError) as error:
            get_registry().invoke("animate_shot", revised, context(row, replacement))
        assert error.value.code == "MODEL_PREFERENCE_VIOLATION"
    else:
        result = get_registry().invoke("animate_shot", revised, context(row, replacement))
        job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
        from app.agent.model_policy import validate_job_policy
        validate_job_policy(job)
        assert job.config["agent_story_production"]["motion_prompt"] == revised["prompt"]


@pytest.mark.parametrize("corruption", [None, b"", MOCK_PNG_BYTES])
def test_missing_extracted_file_restores_original_artifact_without_model_call(app_ctx, corruption):
    row, version, _registry = setup(characters=False)
    video = private_artifact(row, "i2v_video", MOCK_VIDEO_BYTES)
    data = {"video_artifact_id": video.artifact_id}
    result = get_registry().invoke("extract_frame", data, context(row))
    artifact = Artifact.query.filter_by(artifact_id=result["output"]["artifact_id"]).one()
    path = StorageService.resolve(artifact.file_path)
    if corruption is None:
        path.unlink()
    else:
        path.write_bytes(corruption)
    before = BudgetGuard.spent(row.run_id)
    restored = invoke_once(get_registry(), "extract_frame", data, context(row))
    assert restored["output"] == result["output"]
    with Image.open(path) as frame:
        frame.verify()
    assert BudgetGuard.spent(row.run_id) == before
    assert ToolInvocation.query.filter_by(tool_name="extract_frame").count() == 1
    assert Artifact.query.filter_by(artifact_type="tail_frame_image").count() == 1
    assert not ApiTask.query.first()


@pytest.mark.parametrize("changed", ["prompt", "frame", "params"])
def test_frozen_job_input_cannot_drift_before_submission(app_ctx, monkeypatch, changed):
    row, version, data, item = production()
    monkeypatch.setattr(JobRunService, "start", lambda *_a, **_kw: None)
    result = get_registry().invoke("animate_shot", data, context(row, item))
    job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
    if changed == "prompt":
        from app.services.prompt_service import PromptService
        prompt = PromptService.get_active_for_template(job.template, "i2v", job_id=job.id)
        prompt.content = "Unapproved motion"
    elif changed == "frame":
        artifact = ArtifactService.latest_for_job(job, "first_frame_image")
        artifact.meta = {**artifact.meta, "source_artifact_id": "not-approved"}
    else:
        config = deepcopy(job.config)
        config["node_model_params"]["submit_i2v"]["duration"] += 1
        job.config = config
    db.session.commit()
    from app.agent.model_policy import validate_job_policy
    with pytest.raises(AppError) as error:
        validate_job_policy(job)
    assert error.value.code == "MODEL_PREFERENCE_VIOLATION"
    assert not ApiTask.query.first()


@pytest.mark.parametrize("revised", [False, True])
def test_retry_receipt_inherits_only_authorized_motion_lineage(app_ctx, monkeypatch, revised):
    row, version, data, original = production()
    original.status = "failed"
    prior, receipts = original, {}
    if revised:
        data["prompt"] = "人物漫步在安静的城市，镜头轻轻前移。"
        prior = AgentShotTask(run_id=row.run_id, plan_version=version.version, target_type="video", target_id="s01",
            attempt=2, inputs_hash=versions.inputs_hash(data), status="failed", artifact_ids=[])
        db.session.add(prior)
        db.session.flush()
        receipts[str(original.id)] = {"failed_task_id": original.id, "shot_id": "s01", "plan_version": version.version,
            "action": "rewrite_prompt", "category": "content_policy", "status": "failed", "reserved_credits": 10,
            "motion_prompt": data["prompt"], "replacement_task_id": prior.id}
    replacement = AgentShotTask(run_id=row.run_id, plan_version=version.version, target_type="video", target_id="s01",
        attempt=prior.attempt + 1, inputs_hash=versions.inputs_hash(data), status="pending", artifact_ids=[])
    db.session.add(replacement)
    db.session.flush()
    receipts[str(prior.id)] = {"failed_task_id": prior.id, "shot_id": "s01", "plan_version": version.version,
        "action": "retry_submit", "category": "transient", "status": "running", "reserved_credits": 5,
        "replacement_task_id": replacement.id}
    row.snapshot = {**row.snapshot, "production_repairs": receipts}
    db.session.commit()
    monkeypatch.setattr(JobRunService, "start", lambda *_a, **_kw: None)
    result = get_registry().invoke("animate_shot", data, context(row, replacement))
    from app.agent.model_policy import validate_job_policy
    job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
    validate_job_policy(job)
    assert job.config["agent_story_production"]["motion_prompt"] == data["prompt"]



def test_registry_cannot_bypass_production_repair_with_failed_key(app_ctx, monkeypatch):
    row, version, data, item = production()
    monkeypatch.setattr(JobRunService, "start", lambda *_a, **_kw: None)
    result = get_registry().invoke("animate_shot", data, context(row, item))
    invoice = ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one()
    invoice.status, invoice.job.status, item.status = "failed", "failed", "failed"
    db.session.commit()
    spent = BudgetGuard.spent(row.run_id)
    with pytest.raises(AppError) as error:
        get_registry().invoke("animate_shot", data, context(row, item))
    assert error.value.code == "UNSAFE_RETRY"
    assert invoice.attempt == 1 and BudgetGuard.spent(row.run_id) == spent
    assert not ApiTask.query.first()
