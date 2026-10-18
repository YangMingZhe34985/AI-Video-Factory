"""Approved composition, source privacy, and free durable local recovery."""
from copy import deepcopy

from flask_jwt_extended import create_access_token
import pytest

from app.agent import plan_versions as versions
from app.agent.delivery_policy import approved_sources, resolve_delivery_artifact, resolve_source, source_hashes
from app.agent.attachments import validate_job_attachment_sources
from app.api import AppError
from app.extensions import db
from app.models import Artifact, Job, ToolInvocation
from app.services.storage_service import StorageService
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from app.skills.spec import ToolContext
from app.skills.tools import compose_video
from tests.test_story_media import private_artifact, task
from tests.test_story_previews import setup
from tests.test_video_composition import make_media

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_STORY_DELIVERY_ENABLED=True)


def delivery(*, compress=False):
    row, old, registry = setup(characters=False)
    plan = deepcopy(old.plan)
    plan["shots"] = plan["shots"][:2]
    plan["target_duration_sec"] = 2.4
    for shot in plan["shots"]:
        shot["duration_sec"] = 1.2
        shot["motion"]["params"]["duration"] = 1.2
    version = versions.create_version(row, plan, old.story_package, old.check, author="system")
    snapshot = deepcopy(row.snapshot)
    snapshot["request_spec"]["constraints"]["compress_output"] = compress
    snapshot["production"] = {"approved_version": version.version, "plan_version": version.version, "status": "videos_approved"}
    row.snapshot = snapshot
    row.status = "editing"
    db.session.commit()
    for index, shot in enumerate(version.plan["shots"]):
        media = make_media(f"source{index}.mp4", color="red" if index == 0 else "blue")
        artifact = private_artifact(row, "i2v_video", media.read_bytes())
        task(row, version, "video", shot["shot_id"], {"source": artifact.artifact_id}, artifact)
    sources = approved_sources(row, version)
    data = compose_video.ComposeVideoInput(plan_version=version.version,
        video_artifact_ids=[item[2].artifact_id for item in sources], compress_output=compress).model_dump(mode="json")
    row.snapshot = {**row.snapshot, "delivery": {"authorized": True, "plan_version": version.version,
        "approved_version": version.version, "source_artifact_ids": data["video_artifact_ids"],
        "source_sha256": source_hashes(sources), "compress_output": compress, "inputs_hash": versions.inputs_hash(data), "stage": "pending"}}
    db.session.commit()
    if "compose_video" not in registry.names():
        registry.register(compose_video.SPEC)
    return row, version, data, registry


def context(row, version, key="compose"):
    return ToolContext(role="production", approved=True, budget_scope=row.run_id,
        idempotency_key=key, delivery_version=version.version)


def invoke(row, version, data, registry):
    return registry.invoke("compose_video", data, context(row, version))


def persist_composition(row, output):
    row.snapshot = {**row.snapshot, "delivery": {**row.snapshot["delivery"], "composition": output}}
    db.session.commit()


def test_approved_composition_is_private_free_and_replayed(app_ctx, client):
    row, version, data, registry = delivery()
    before = BudgetGuard.spent(row.run_id)
    first = invoke(row, version, data, registry)
    second = invoke(row, version, data, registry)
    assert first["estimated_cost"] == 0 and second["replayed"]
    assert first["output"] == second["output"]
    assert BudgetGuard.spent(row.run_id) == before
    assert Job.query.filter_by(strategy="skill:compose_video").count() == 1
    assert ToolInvocation.query.filter_by(tool_name="compose_video").count() == 1
    persist_composition(row, first["output"])
    artifact = resolve_delivery_artifact(row, version, first["output"]["artifact_id"])
    assert artifact.job.config["agent_story_production"]["target_type"] == "delivery"
    app_ctx.config.update(API_AUTH_REQUIRED=True, JWT_SECRET_KEY="composition-test-key-long-enough-for-32-bytes")
    owner = {"Authorization": "Bearer " + create_access_token(identity=row.owner_id)}
    other = {"Authorization": "Bearer " + create_access_token(identity="bob")}
    assert client.get(first["output"]["download_url"]).status_code == 401
    assert client.get(first["output"]["download_url"], headers=other).status_code == 404
    assert client.get(first["output"]["download_url"], headers=owner).status_code == 200


@pytest.mark.parametrize("damage", ["missing", "empty", "corrupt", "compressed"])
def test_output_cache_rebuild_reuses_artifact_invocation_and_zero_cost(app_ctx, damage):
    row, version, data, registry = delivery(compress=damage == "compressed")
    first = invoke(row, version, data, registry)
    field = "compressed_artifact_id" if damage == "compressed" else "artifact_id"
    artifact = Artifact.query.filter_by(artifact_id=first["output"][field]).one()
    path = StorageService.resolve(artifact.file_path)
    if damage in {"missing", "compressed"}:
        path.unlink()
    else:
        path.write_bytes(b"" if damage == "empty" else b"corrupt")
    before = BudgetGuard.spent(row.run_id)
    repaired = invoke(row, version, data, registry)
    assert not repaired["replayed"] and path.stat().st_size > 0
    assert repaired["output"][field] == first["output"][field]
    assert repaired["invocation_id"] == first["invocation_id"]
    assert BudgetGuard.spent(row.run_id) == before
    assert Job.query.filter_by(strategy="skill:compose_video").count() == 1
    assert ToolInvocation.query.filter_by(tool_name="compose_video").one().attempt == 1


@pytest.mark.parametrize("change", ["order", "missing", "compression", "version"])
def test_input_cannot_change_approved_order_or_settings(app_ctx, change):
    row, version, data, registry = delivery()
    if change == "order":
        data["video_artifact_ids"].reverse()
    elif change == "missing":
        data["video_artifact_ids"].pop()
    elif change == "compression":
        data["compress_output"] = True
    else:
        data["plan_version"] -= 1
    with pytest.raises(AppError):
        invoke(row, version, data, registry)
    assert not ToolInvocation.query.filter_by(tool_name="compose_video").first()
    assert not Job.query.filter_by(strategy="skill:compose_video").first()


def test_public_owner_cannot_create_server_delivery_authorization(app_ctx, client, monkeypatch):
    row, version, data, registry = delivery()
    import app.skills
    monkeypatch.setattr(app.skills, "_registry", registry)
    app_ctx.config.update(API_AUTH_REQUIRED=True, JWT_SECRET_KEY="composition-test-key-long-enough-for-32-bytes")
    headers = {"Authorization": "Bearer " + create_access_token(identity=row.owner_id)}
    response = client.post("/api/skills/compose_video/invoke", headers=headers,
        json={"input": data, "role": "production", "approved": True, "budget_scope": row.run_id})
    assert response.status_code == 403, response.json
    assert response.json["error"]["code"] == "TOOL_FORBIDDEN"
    assert not ToolInvocation.query.filter_by(tool_name="compose_video").first()


@pytest.mark.parametrize("replay", [False, True])
def test_changed_source_bytes_stop_before_recomposition(app_ctx, replay):
    row, version, data, registry = delivery()
    if replay:
        invoke(row, version, data, registry)
    source = Artifact.query.filter_by(artifact_id=data["video_artifact_ids"][0]).one()
    resolve_source(source).write_bytes(make_media("changed.mp4", color="green").read_bytes())
    before = ToolInvocation.query.count()
    with pytest.raises(AppError):
        invoke(row, version, data, registry)
    assert ToolInvocation.query.count() == before


def test_old_version_and_cross_run_source_are_rejected(app_ctx):
    row, version, data, registry = delivery()
    artifact = Artifact.query.filter_by(artifact_id=data["video_artifact_ids"][0]).one()
    artifact.job.config = {**artifact.job.config, "agent_story_production": {"run_id": "other"}}
    db.session.commit()
    with pytest.raises(AppError):
        invoke(row, version, data, registry)
    versions.create_version(row, version.plan, version.story_package, version.check, author="system")
    with pytest.raises(AppError) as error:
        invoke(row, version, data, registry)
    assert error.value.code == "PLAN_VERSION_CONFLICT"
    assert not ToolInvocation.query.filter_by(tool_name="compose_video").first()


def test_original_media_is_required_even_when_compressed_proxy_exists(app_ctx):
    row, version, data, registry = delivery()
    artifact = Artifact.query.filter_by(artifact_id=data["video_artifact_ids"][0]).one()
    original = resolve_source(artifact)
    proxy = original.with_name("proxy.mp4")
    proxy.write_bytes(original.read_bytes())
    artifact.file_path = StorageService.relative_path(proxy)
    artifact.meta = {"compression": {"original_file_path": StorageService.relative_path(original)}}
    db.session.commit()
    assert resolve_source(artifact) == original
    original.unlink()
    with pytest.raises(AppError) as error:
        invoke(row, version, data, registry)
    assert error.value.code == "VIDEO_INCOMPLETE" and proxy.exists()


def test_crash_before_receipt_recovers_without_paid_or_duplicate_artifacts(app_ctx, monkeypatch):
    row, version, data, registry = delivery()
    with monkeypatch.context() as patch:
        patch.setattr(compose_video, "_finish", lambda *_a: (_ for _ in ()).throw(SystemExit("simulated crash")))
        with pytest.raises(SystemExit):
            invoke(row, version, data, registry)
    db.session.rollback()
    before = BudgetGuard.spent(row.run_id)
    result = invoke(row, version, data, registry)
    assert result["output"]["artifact_id"]
    assert Job.query.filter_by(strategy="skill:compose_video").count() == 1
    assert Artifact.query.filter_by(artifact_type="composed_video").count() == 1
    assert BudgetGuard.spent(row.run_id) == before
    assert ToolInvocation.query.filter_by(tool_name="compose_video").one().attempt == 1


def test_private_unregistered_delivery_cache_cannot_be_imported(app_ctx):
    path = StorageService.root() / "agent/delivery/unregistered.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"private cached bytes")
    with pytest.raises(AppError):
        validate_job_attachment_sources({"source_video_path": str(path)}, "bob")


def test_success_replay_still_requires_delivery_approval(app_ctx):
    row, version, data, registry = delivery()
    invoke(row, version, data, registry)
    row.snapshot = {**row.snapshot, "delivery": {**row.snapshot["delivery"], "authorized": False}}
    db.session.commit()
    with pytest.raises(AppError):
        invoke(row, version, data, registry)
    assert ToolInvocation.query.filter_by(tool_name="compose_video").count() == 1


def test_original_metadata_cannot_point_to_another_managed_directory(app_ctx):
    row, version, data, registry = delivery()
    source = Artifact.query.filter_by(artifact_id=data["video_artifact_ids"][0]).one()
    outside_job = make_media("private-other-job.mp4")
    source.meta = {"compression": {"original_file_path": StorageService.relative_path(outside_job)}}
    db.session.commit()
    with pytest.raises(AppError) as error:
        invoke(row, version, data, registry)
    assert error.value.code == "INVALID_REFERENCE"
