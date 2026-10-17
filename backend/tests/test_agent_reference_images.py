"""Reference discovery, decoding, isolation and restart tests without network access."""

from io import BytesIO

import pytest
from PIL import Image

from app.agent.attachments import attachment_for_owner
from app.agent.recovery import invoke_once
from app.agent.search import references
from app.agent.search.base import FetchedResource
from app.agent.search.references import reference_for_run
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, Artifact, Job, ToolInvocation
from app.services.storage_service import StorageService
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from app.skills.spec import ToolContext
from app.utils.ids import new_id

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_VISION_MODEL="qwen3.7-plus")


def make_run(owner="local", text="查找 DeepSeek 与 ChatGPT 的动漫形象", budget=100):
    run = AgentRun(owner_id=owner, request_key=new_id("req"), request={
        "schema_version": 2, "text": text, "attachment_ids": [], "budget_limit": budget})
    db.session.add(run)
    db.session.commit()
    return run


def context(run, key=None):
    return ToolContext(role="research", budget_scope=run.run_id, idempotency_key=key, budget_limit=100)


def search(registry, run, query="DeepSeek"):
    return registry.invoke("image_search", {"query": query}, context(run))


def download(registry, run, url="mock://image/deepseek-1", key=None, **extra):
    return registry.invoke("download_reference", {"run_id": run.run_id, "image_url": url, **extra}, context(run, key))


def image_bytes(format="PNG", size=(320, 256)):
    stream = BytesIO()
    Image.new("RGB", size, "#2244aa").save(stream, format=format)
    return stream.getvalue()


def test_mock_candidates_and_billable_search_replay(app_ctx):
    registry, run = build_default_registry(), make_run()
    first = search(registry, run)
    second = search(registry, run, "ChatGPT")
    for result in (first, second):
        assert len(result["output"]["results"]) == 3
        assert result["output"]["provider"] == "mock"
        assert len({item["image_url"] for item in result["output"]["results"]}) == 3
        assert all(item["source_page_url"].startswith("mock://") for item in result["output"]["results"])
    assert search(registry, run)["replayed"] is True
    assert BudgetGuard.spent(run.run_id) == pytest.approx(2 * app_ctx.config["AGENT_SEARCH_COST_PER_CALL"])
    assert ToolInvocation.query.count() == 2


def test_reference_metadata_and_visual_understanding(app_ctx, monkeypatch):
    registry, run = build_default_registry(), make_run()
    search(registry, run)
    result = download(registry, run, source_page_url="mock://page/deepseek", entity="DeepSeek")["output"]
    artifact = reference_for_run(result["reference_id"], run)
    assert artifact.artifact_type == "agent_reference_image"
    assert artifact.job.strategy == "agent_upload"
    assert artifact.job.config["agent_upload_owner"] == run.owner_id
    meta = artifact.meta["reference"]
    assert set(meta) == {"source_url", "source_page_url", "entity", "provider", "sha256", "downloaded_at", "run_id"}
    assert meta["source_url"] == "mock://image/deepseek-1"
    assert meta["entity"] == "DeepSeek" and meta["provider"] == "mock"
    assert meta["run_id"] == run.run_id and meta["sha256"] == result["sha256"]
    assert result["width"] >= 256 and result["height"] >= 256
    assert result["duplicate_of"] is None
    analyzed = registry.invoke("analyze_image", {"attachment_id": artifact.artifact_id}, context(run))
    assert analyzed["output"]["subjects"]
    assert "deepseek" in str(analyzed["output"]).casefold()
    assert analyzed["output"]["suggested_role"] == "identity_ref"
    before = BudgetGuard.spent(run.run_id)
    def unexpected(*args, **kwargs):
        raise AssertionError("A completed call must not download or analyze again")
    monkeypatch.setattr(references, "fetch_resource", unexpected)
    monkeypatch.setattr("app.skills.tools.analyze_image.structured_call", unexpected)
    assert download(registry, run, source_page_url="mock://page/deepseek", entity="DeepSeek")["replayed"]
    assert registry.invoke("analyze_image", {"attachment_id": artifact.artifact_id}, context(run))["replayed"]
    assert BudgetGuard.spent(run.run_id) == before
    assert Artifact.query.count() == Job.query.count() == 1


@pytest.mark.parametrize("format,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_supported_image_formats_are_decoded(app_ctx, monkeypatch, format, mime):
    registry, run = build_default_registry(), make_run(text="https://example.com/reference")
    monkeypatch.setattr(references, "fetch_resource", lambda *a, **k: FetchedResource(
        final_url="https://example.com/reference", content_type=mime, body=image_bytes(format)))
    result = download(registry, run, "https://example.com/reference")["output"]
    artifact = reference_for_run(result["reference_id"], run)
    assert artifact.mime_type == mime
    assert (result["width"], result["height"]) == (320, 256)
    assert artifact.meta["reference"]["provider"] == "user"


@pytest.mark.parametrize("case", ["empty", "unreadable", "disguised", "truncated", "small", "wide", "large", "mime", "bomb"])
def test_invalid_reference_never_registers_artifacts(app_ctx, monkeypatch, case):
    registry, run = build_default_registry(), make_run(text="https://example.com/reference")
    body, mime = image_bytes(), "image/png"
    if case == "empty": body = b""
    if case == "unreadable": body = b"not an image"
    if case == "disguised": body = image_bytes("GIF")
    if case == "truncated": body = body[:80]
    if case == "small": body = image_bytes(size=(255, 256))
    if case == "wide": body = image_bytes(size=(8193, 256))
    if case == "large": app_ctx.config["AGENT_REFERENCE_MAX_MB"] = .0001
    if case == "mime": mime = "image/svg+xml"
    if case == "bomb": monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 50000)
    monkeypatch.setattr(references, "fetch_resource", lambda *a, **k: FetchedResource(
        final_url="https://example.com/reference", content_type=mime, body=body))
    with pytest.raises(AppError) as error:
        download(registry, run, "https://example.com/reference")
    assert error.value.code == ("CONTENT_TYPE_NOT_ALLOWED" if case == "mime" else "INVALID_REFERENCE_IMAGE")
    assert Artifact.query.count() == Job.query.count() == 0


def test_fetch_size_limit_maps_to_reference_error(app_ctx, monkeypatch):
    registry, run = build_default_registry(), make_run(text="https://example.com/reference")
    def too_large(*args, **kwargs):
        raise AppError("FETCH_FAILED", "Too large", 502, payload={"reason": "size_limit"})
    monkeypatch.setattr(references, "fetch_resource", too_large)
    with pytest.raises(AppError) as error:
        download(registry, run, "https://example.com/reference")
    assert error.value.code == "INVALID_REFERENCE_IMAGE"
    assert Artifact.query.count() == 0


def test_sha_dedup_is_run_scoped_and_url_cache_skips_fetch(app_ctx, monkeypatch):
    registry, run = build_default_registry(), make_run()
    search(registry, run)
    calls = []
    def fetch(url, *args, **kwargs):
        calls.append(url)
        return FetchedResource(final_url=url, content_type="image/png", body=image_bytes())
    monkeypatch.setattr(references, "fetch_resource", fetch)
    first = download(registry, run, key="ref-one")["output"]
    duplicate = download(registry, run, "mock://image/deepseek-2")["output"]
    assert duplicate["reference_id"] == first["reference_id"] == duplicate["duplicate_of"]
    assert download(registry, run, key="ref-one-again")["output"]["duplicate_of"] == first["reference_id"]
    assert len(calls) == 2
    other_run = make_run()
    search(registry, other_run)
    other = download(registry, other_run)["output"]
    assert other["sha256"] == first["sha256"] and other["reference_id"] != first["reference_id"]
    assert Artifact.query.count() == Job.query.count() == 2


def test_reference_rejects_cross_owner_and_cross_run_and_new_upload_admission(app_ctx, client):
    registry, run = build_default_registry(), make_run()
    search(registry, run)
    reference_id = download(registry, run)["output"]["reference_id"]
    registry.invoke("analyze_image", {"attachment_id": reference_id}, context(run, "analysis-key"))
    for other in (make_run(), make_run(owner="other")):
        with pytest.raises(AppError) as error:
            registry.invoke("analyze_image", {"attachment_id": reference_id}, context(other))
        assert error.value.code == "ATTACHMENT_NOT_FOUND"
        with pytest.raises(AppError) as error:
            registry.invoke("analyze_image", {"attachment_id": reference_id}, context(other, "analysis-key"))
        assert error.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    with pytest.raises(AppError):
        attachment_for_owner(reference_id, "local")
    response = client.post("/api/agent/runs", json={"text": "用这个参考图制作视频", "attachment_ids": [reference_id],
                                                  "request_key": "new-reference-run"})
    assert response.status_code == 404 and response.json["error"]["code"] == "ATTACHMENT_NOT_FOUND"


def test_allowlist_and_run_download_limit(app_ctx):
    registry, run = build_default_registry(), make_run()
    with pytest.raises(AppError) as error:
        download(registry, run)
    assert error.value.code == "URL_NOT_ALLOWED"
    search(registry, run)
    app_ctx.config["AGENT_MAX_REFERENCE_DOWNLOADS"] = 1
    result = download(registry, run)
    assert download(registry, run)["replayed"]
    with pytest.raises(AppError) as error:
        download(registry, run, "mock://image/deepseek-2")
    assert error.value.code == "RESEARCH_LIMIT_REACHED"
    assert Artifact.query.count() == 1
    assert result["output"]["reference_id"]


def test_pending_download_recovery_reuses_validated_cache(app_ctx, monkeypatch):
    registry, run = build_default_registry(), make_run()
    search(registry, run)
    original = references.ArtifactService.register_artifact
    class Crash(BaseException): pass
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(references.ArtifactService, "register_artifact", crash)
    with pytest.raises(Crash):
        download(registry, run, key="recover-reference")
    db.session.rollback()
    assert Artifact.query.count() == Job.query.count() == 0
    invocation = ToolInvocation.query.filter_by(idempotency_key="recover-reference").one()
    assert invocation.status == "pending"
    monkeypatch.setattr(references.ArtifactService, "register_artifact", original)
    def unexpected(*args, **kwargs):
        raise AssertionError("Recovery must use its validated download receipt")
    monkeypatch.setattr(references, "fetch_resource", unexpected)
    result = invoke_once(registry, "download_reference", {"run_id": run.run_id,
        "image_url": "mock://image/deepseek-1"}, context(run, "recover-reference"))
    assert result["output"]["reference_id"]
    assert Artifact.query.count() == Job.query.count() == 1
    assert invocation.attempt == 1 and invocation.status == "success"


def test_reference_and_success_receipt_are_committed_atomically(app_ctx, monkeypatch):
    registry, run = build_default_registry(), make_run()
    search(registry, run)
    finish = references._finish
    class Crash(BaseException): pass
    def commit_then_crash(*args, **kwargs):
        finish(*args, **kwargs)
        raise Crash()
    monkeypatch.setattr(references, "_finish", commit_then_crash)
    with pytest.raises(Crash):
        download(registry, run, key="commit-reference")
    db.session.rollback()
    invocation = ToolInvocation.query.filter_by(idempotency_key="commit-reference").one()
    assert invocation.status == "success"
    monkeypatch.setattr(references, "_finish", finish)
    assert download(registry, run, key="commit-reference")["replayed"]
    assert Artifact.query.count() == Job.query.count() == 1


def test_missing_reference_file_is_restored_from_receipt_without_new_artifact(app_ctx, monkeypatch):
    registry, run = build_default_registry(), make_run()
    search(registry, run)
    result = download(registry, run)["output"]
    artifact = reference_for_run(result["reference_id"], run)
    StorageService.resolve(artifact.file_path).unlink()
    with pytest.raises(AppError) as error:
        reference_for_run(artifact.artifact_id, run)
    assert error.value.code == "ATTACHMENT_NOT_FOUND"
    def unexpected(*args, **kwargs):
        raise AssertionError("Restoring a validated cached image must not fetch again")
    monkeypatch.setattr(references, "fetch_resource", unexpected)
    restored = download(registry, run, key="restore-reference")["output"]
    assert restored["duplicate_of"] == artifact.artifact_id
    assert reference_for_run(artifact.artifact_id, run)
    assert Artifact.query.count() == Job.query.count() == 1


@pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_VISION_MODEL="qwen3.7-plus", API_AUTH_REQUIRED=True,
                    JWT_SECRET_KEY="agent-reference-test-secret-at-least-32-bytes")
def test_private_preview_download_and_skills_api_reference_scope(app_ctx, client):
    from flask_jwt_extended import create_access_token
    registry, run = build_default_registry(), make_run(owner="alice")
    search(registry, run)
    result = download(registry, run)["output"]
    headers = {owner: {"Authorization": f"Bearer {create_access_token(identity=owner)}"} for owner in ("alice", "bob")}
    for endpoint in ("preview", "download"):
        url = f"/api/artifacts/{result['reference_id']}/{endpoint}"
        assert client.get(url).status_code == 401
        assert client.get(url, headers=headers["bob"]).status_code == 404
        assert client.get(url, headers=headers["alice"]).status_code == 200
    for other, auth, expected in ((make_run(owner="alice"), "alice", 404), (run, "bob", 404), (run, "alice", 200)):
        response = client.post("/api/skills/analyze_image/invoke", headers=headers[auth], json={
            "input": {"attachment_id": result["reference_id"]}, "role": "research", "budget_scope": other.run_id})
        assert response.status_code == expected, response.json


def test_invalid_source_link_rejected_before_fetch(app_ctx):
    registry, run = build_default_registry(), make_run()
    search(registry, run)
    with pytest.raises(AppError) as error:
        download(registry, run, source_page_url="javascript:alert(1)")
    assert error.value.code == "INVALID_INPUT"
    assert Artifact.query.count() == 0


def test_classic_import_cannot_republish_run_reference(app_ctx, client):
    from app.skills.job_backed import node_selection
    registry, run = build_default_registry(), make_run()
    search(registry, run)
    artifact = reference_for_run(download(registry, run)["output"]["reference_id"], run)
    for source in ({"initial_artifacts": {"reference_images": {"artifact_ids": [artifact.artifact_id]}}},
                   {"source_video_path": artifact.file_path}):
        response = client.post("/api/jobs", json={"template_id": "agent_workspace", **node_selection([]), **source})
        assert response.status_code == 404, response.json
        assert response.json["error"]["code"] == "ATTACHMENT_NOT_FOUND"
    assert Job.query.count() == 1


def test_image_provider_failure_and_duplicate_ids_are_rejected(app_ctx, monkeypatch):
    registry, run = build_default_registry(), make_run()
    from app.agent.search import get_search_provider
    provider = get_search_provider()
    candidates = provider.image_search("DeepSeek", max_results=3, safe=True)
    class DuplicateProvider:
        name = "broken"
        def image_search(self, *args, **kwargs):
            return [candidates[0], candidates[0]]
    monkeypatch.setattr("app.skills.tools.image_search.get_search_provider", lambda: DuplicateProvider())
    with pytest.raises(AppError) as error:
        search(registry, run)
    assert error.value.code == "SEARCH_PROVIDER_UNAVAILABLE"
    assert ToolInvocation.query.one().status == "failed"


def test_provider_result_limit_and_shared_query_quota(app_ctx):
    registry, run = build_default_registry(), make_run()
    app_ctx.config["AGENT_RESEARCH_MAX_QUERIES"] = 2
    result = registry.invoke("image_search", {"query": "DeepSeek", "max_results": 1}, context(run))
    assert len(result["output"]["results"]) == 1
    registry.invoke("web_search", {"query": "DeepSeek"}, context(run))
    with pytest.raises(AppError) as error:
        search(registry, run, "ChatGPT")
    assert error.value.code == "RESEARCH_LIMIT_REACHED"
