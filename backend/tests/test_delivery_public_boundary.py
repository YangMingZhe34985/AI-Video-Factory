"""Public callers cannot impersonate the internal Editor, even after approval."""
from copy import deepcopy

import pytest
from flask_jwt_extended import create_access_token

from app.agent import plan_versions as versions
from app.agent.delivery_policy import approved_sources, source_hashes
from app.extensions import db
from app.models import ApiTask, ToolInvocation
from app.skills import build_default_registry
from tests.test_production_actions import fixture

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_STORY_DELIVERY_ENABLED=True,
    API_AUTH_REQUIRED=True, JWT_SECRET_KEY="delivery-offline-test-only-key-more-than-32-bytes")


def approved(monkeypatch):
    run, version, _registry = fixture(tail=False)
    run.owner_id = "alice"
    run.status = "videos_approved"
    sources = approved_sources(run, version)
    ids = [item[2].artifact_id for item in sources]
    payload = {"plan_version": version.version, "video_artifact_ids": ids, "compress_output": False}
    run.snapshot = {**run.snapshot, "delivery": {"authorized": True,
        "plan_version": version.version, "approved_version": version.version,
        "source_artifact_ids": ids, "source_sha256": source_hashes(sources),
        "compress_output": False, "inputs_hash": versions.inputs_hash(payload), "stage": "pending"}}
    db.session.commit()
    registry = build_default_registry()
    # Ensure HTTP reaches the same registered tools, without mutating global
    # registry state for later tests.
    monkeypatch.setattr("app.skills._registry", registry)
    return run, version, ids


def headers(owner):
    return {"Authorization": "Bearer " + create_access_token(identity=owner)}


@pytest.mark.parametrize("name", ["compose_video", "probe_media", "qc_video", "package_story"])
def test_public_skill_cannot_set_server_delivery_context(app_ctx, client, monkeypatch, name):
    run, version, ids = approved(monkeypatch)
    data = {"compose_video": {"plan_version": version.version, "video_artifact_ids": ids},
        "probe_media": {"artifact_id": ids[0]},
        "qc_video": {"plan_version": version.version, "artifact_id": ids[0], "video_artifact_ids": ids},
        "package_story": {"plan_version": version.version, "artifact_id": ids[0]}}[name]
    before = (ApiTask.query.count(), ToolInvocation.query.count(), deepcopy(run.snapshot))
    response = client.post(f"/api/skills/{name}/invoke", headers=headers("alice"), json={
        "role": "system", "approved": True, "budget_scope": run.run_id,
        "delivery_version": version.version, "input": data, "idempotency_key": "forged-editor"})
    assert response.status_code == 403, response.json
    assert response.json["error"]["code"] == "TOOL_FORBIDDEN"
    assert (ApiTask.query.count(), ToolInvocation.query.count(), run.snapshot) == before
    # An owner can request the documented action, not bypass it via Skill role.
    response = client.post(f"/api/skills/{name}/invoke", headers=headers("bob"), json={
        "role": "production", "approved": True, "budget_scope": run.run_id, "input": data})
    assert response.status_code == 404
    assert ToolInvocation.query.count() == before[1]


def test_delivery_temporary_files_cannot_be_reimported_to_public_classic_job(app_ctx, client, monkeypatch):
    from app.services.storage_service import StorageService
    run, _version, _ids = approved(monkeypatch)
    path = StorageService.root() / "agent" / "delivery" / "unregistered-cache.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"private bytes before registration")
    before = ApiTask.query.count()
    for owner in ("alice", "bob"):
        response = client.post("/api/jobs", headers=headers(owner),
            json={"template_id": "default", "source_video_path": str(path)})
        assert response.status_code == 404, response.json
    assert ApiTask.query.count() == before


def test_reused_context_rechecks_source_bytes_on_next_registry_call(app_ctx, monkeypatch):
    from app.api import AppError
    from app.skills.spec import ToolContext
    from app.services.storage_service import StorageService
    run, version, ids = approved(monkeypatch)
    registry = build_default_registry()
    data = {"plan_version": version.version, "video_artifact_ids": ids}
    ctx = ToolContext(role="production", approved=True, budget_scope=run.run_id,
        delivery_version=version.version, idempotency_key="same-context")
    result = registry.invoke("compose_video", data, ctx)
    assert result["status"] == "success"
    before = (ApiTask.query.count(), ToolInvocation.query.count())
    source = approved_sources(run, version)[0][2]
    StorageService.resolve(source.file_path).write_bytes(b"replaced approved source")
    with pytest.raises(AppError) as error:
        registry.invoke("compose_video", data, ctx)
    assert error.value.code in {"INVALID_REFERENCE", "PLAN_VERSION_CONFLICT"}
    assert (ApiTask.query.count(), ToolInvocation.query.count()) == before
