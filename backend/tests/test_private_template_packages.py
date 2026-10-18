"""Public template packages must never publish private Agent content."""

import io
import json
import zipfile

import pytest
from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models import AgentRun, PromptVersion
from app.services.artifact_service import ArtifactService
from app.services.prompt_sync_service import PromptSyncService
from app.services.storage_service import StorageService
from app.services.template_package_service import TemplatePackageService
from app.skills.job_backed import ensure_agent_template

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, API_AUTH_REQUIRED=True,
    JWT_SECRET_KEY="private-template-package-regression-secret-over-32-bytes")


@pytest.fixture
def headers(app_ctx):
    return {owner: {"Authorization": "Bearer " + create_access_token(identity=owner)}
            for owner in ("alice", "bob")}


def private_job(h, marker="agent_story_production", *, shared_template=True):
    template = ensure_agent_template() if shared_template else None
    run = AgentRun(owner_id="alice", request_key="private-package", request={"schema_version": 2, "goal": "Private goal"})
    db.session.add(run)
    db.session.commit()
    config = {"skill": {"budget_scope": run.run_id}}
    if marker == "agent_upload":
        config["agent_upload_owner"] = "alice"
    else:
        config[marker] = {"run_id": run.run_id}
    job = h.make_job(paths=(), template_id=template.template_id if template else "default",
        strategy="agent_upload" if marker == "agent_upload" else "skill:animate_shot",
        initial_prompts={"i2v": "ALICE_PRIVATE_MOCK_MOTION"}, job_config=config)
    path = StorageService.job_dir(job.job_id) / "private.mp4"
    path.write_bytes(b"ALICE_PRIVATE_MOCK_VIDEO")
    artifact = ArtifactService.register_artifact(job, str(path), "i2v_video")
    job.status = "success"
    db.session.commit()
    return job, artifact


def legacy_cache(template_id, body=b"ALICE_PRIVATE_MOCK_VIDEO"):
    path = TemplatePackageService.package_path(template_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("video/private.mp4", body)
        archive.writestr("package_manifest.json", json.dumps({"template_id": template_id}))
    return path


@pytest.mark.parametrize("marker", ["agent_upload", "agent_story_preview", "agent_story_production"])
@pytest.mark.parametrize("owner", ["alice", "bob"])
def test_shared_template_package_never_exports_private_jobs(app_ctx, client, headers, h, marker, owner):
    _job, artifact = private_job(h, marker)
    assert client.get(f"/api/artifacts/{artifact.artifact_id}/preview", headers=headers["bob"]).status_code == 404
    response = client.post("/api/templates/agent_workspace/package", headers=headers[owner])
    assert response.status_code == 404, response.json
    assert response.json["error"]["code"] == "TEMPLATE_PACKAGE_NOT_FOUND"
    assert not TemplatePackageService.package_path("agent_workspace").exists()


def test_private_template_numeric_alias_cannot_bypass_package_guards(app_ctx, client, headers, h):
    job, _artifact = private_job(h)
    path = legacy_cache("agent_workspace")
    assert client.post(f"/api/templates/{job.template_id}/package", headers=headers["alice"]).status_code == 404
    assert client.get(f"/api/templates/{job.template_id}/package/download").status_code == 404
    assert path.exists()


def test_existing_private_zip_is_denied_anonymously_even_after_jobs_deleted(app_ctx, client, headers, h):
    job, _artifact = private_job(h)
    path = legacy_cache("agent_workspace")
    db.session.delete(job)
    db.session.commit()
    for auth in ({}, headers["alice"], headers["bob"]):
        response = client.get("/api/templates/agent_workspace/package/download", headers=auth)
        assert response.status_code == 404
    assert path.exists()  # Revocation must not remove historical user files.


@pytest.mark.parametrize("marker", ["agent_upload", "agent_story_preview", "agent_story_production"])
def test_mixed_classic_template_cannot_publish_its_private_job_or_cached_zip(app_ctx, client, headers, h, marker):
    private_job(h, marker, shared_template=False)
    legacy_cache("default")
    assert client.post("/api/templates/default/package", headers=headers["alice"]).status_code == 404
    assert client.get("/api/templates/default/package/download").status_code == 404


def test_pure_classic_template_package_keeps_public_download(app_ctx, client, headers, h):
    job = h.make_job(paths=(), initial_prompts={"i2v": "Public classic motion"})
    path = StorageService.job_dir(job.job_id) / "public.mp4"
    path.write_bytes(b"PUBLIC_CLASSIC_VIDEO")
    ArtifactService.register_artifact(job, str(path), "i2v_video")
    db.session.commit()
    response = client.post("/api/templates/default/package", headers=headers["bob"])
    assert response.status_code == 201, response.json
    download = client.get(response.json["data"]["download_url"])
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
        videos = [name for name in archive.namelist() if name.startswith("video/")]
        assert len(videos) == 1 and archive.read(videos[0]) == b"PUBLIC_CLASSIC_VIDEO"
        assert archive.read("prompts/i2v.md").decode() == "Public classic motion"


def test_private_owner_can_still_download_job_scoped_package(app_ctx, client, headers, h):
    job, _artifact = private_job(h)
    assert client.post(f"/api/jobs/{job.job_id}/package", headers=headers["bob"]).status_code == 404
    response = client.post(f"/api/jobs/{job.job_id}/package", headers=headers["alice"])
    assert response.status_code == 201, response.json
    url = response.json["data"]["download_url"]
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers["bob"]).status_code == 404
    assert client.get(url, headers=headers["alice"]).status_code == 200


@pytest.mark.parametrize("marker", ["agent_upload", "agent_story_preview", "agent_story_production"])
def test_private_business_prompt_never_syncs_to_public_template(app_ctx, h, marker):
    job, _artifact = private_job(h, marker)
    prompt = PromptVersion.query.filter_by(job_id=job.id, prompt_type="i2v").one()
    assert prompt.content == "ALICE_PRIVATE_MOCK_MOTION"
    assert PromptSyncService.sync_job_prompt_to_template(prompt) is None
    assert not PromptVersion.query.filter_by(template_id=job.template_id, job_id=None, source="synced_from_job").count()


def test_classic_business_prompt_sync_still_works(app_ctx, h):
    job = h.make_job(paths=(), initial_prompts={"i2v": "Public classic motion"})
    prompt = PromptVersion.query.filter_by(job_id=job.id, prompt_type="i2v").one()
    synced = PromptSyncService.sync_job_prompt_to_template(prompt)
    assert synced.job_id is None and synced.content == prompt.content
    assert synced.source == "synced_from_job"


def test_private_sync_never_overwrites_existing_public_prompt(app_ctx, h):
    public_job = h.make_job(paths=(), initial_prompts={"i2v": "Public classic motion"})
    public = PromptVersion.query.filter_by(template_id=public_job.template_id,
        job_id=None, prompt_type="i2v", source="synced_from_job").one()
    private_job(h, shared_template=False)
    db.session.refresh(public)
    assert public.is_active and public.content == "Public classic motion"
    assert PromptVersion.query.filter_by(template_id=public_job.template_id,
        job_id=None, prompt_type="i2v", source="synced_from_job").count() == 1
