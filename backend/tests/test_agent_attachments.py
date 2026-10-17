"""Agent v2 uploads use real media decoding with isolated storage and SQLite."""

import io
import os
import shutil
import subprocess

import pytest
from PIL import Image

from app.agent.attachments import attachment_for_owner, upload_attachment
from app.agent.sources import source_for_owner
from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Artifact, Job
from app.services.storage_service import StorageService
from app.services.artifact_service import ArtifactService
from app.services.job_service import JobService
from app.services.video_media_service import VideoMediaService
from app.skills.job_backed import ensure_agent_template, node_selection
from werkzeug.datastructures import FileStorage, MultiDict

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True)


def image_file(format="PNG", size=(320, 256)):
    stream = io.BytesIO()
    Image.new("RGB", size, "#4666aa").save(stream, format=format)
    stream.seek(0)
    return stream


def upload(client, stream, filename):
    return client.post("/api/agent/attachments", data={"file": (stream, filename)})


def assert_invalid(response):
    assert response.status_code == 422, response.json
    assert response.json["error"]["code"] == "INVALID_ATTACHMENT"
    assert response.json["error"]["details"]["reason"]
    assert Job.query.count() == Artifact.query.count() == ApiTask.query.count() == 0
    assert not list((StorageService.root() / "uploads").glob("*"))


@pytest.mark.parametrize("filename,format", [("photo.jpg", "JPEG"), ("photo.JPEG", "JPEG"),
                                            ("photo.png", "PNG"), ("photo.webp", "WEBP")])
def test_images_registered_with_contract_metadata(app_ctx, client, filename, format):
    response = upload(client, image_file(format), filename)
    assert response.status_code == 201, response.json
    result = response.json["data"]
    assert set(result) == {"attachment_id", "kind", "file_name", "mime_type", "size", "width", "height",
                           "duration", "preview_url"}
    assert result["kind"] == "image"
    assert result["width"] == 320 and result["height"] == 256
    assert result["duration"] is None
    assert result["size"] > 0
    assert result["mime_type"] == f"image/{'jpeg' if format == 'JPEG' else format.lower()}"
    artifact = attachment_for_owner(result["attachment_id"], "local")
    assert artifact.job.template.template_id == "agent_workspace"
    assert artifact.job.strategy == "agent_upload"
    assert artifact.job.config["agent_upload_owner"] == "local"
    assert artifact.artifact_type == "agent_attachment_image"
    assert artifact.meta["media"] == {"kind": "image", "width": 320, "height": 256, "duration": None, "fps": None}
    assert client.get(result["preview_url"]).status_code == 200
    assert ApiTask.query.count() == 0


@pytest.mark.parametrize("case", ["missing", "multiple", "wrong_field", "empty", "unsupported", "unreadable",
                                  "disguised_gif", "small_width", "small_height", "truncated"])
def test_invalid_images_leave_no_jobs_or_uploads(app_ctx, client, case):
    if case == "missing":
        response = client.post("/api/agent/attachments", data={})
    elif case == "multiple":
        response = client.post("/api/agent/attachments", data=MultiDict([
            ("file", (image_file(), "one.png")), ("file", (image_file(), "two.png"))]))
    elif case == "wrong_field":
        response = client.post("/api/agent/attachments", data={"image": (image_file(), "one.png")})
    else:
        stream, filename = {
            "empty": (io.BytesIO(), "empty.png"),
            "unsupported": (image_file(), "file.svg"),
            "unreadable": (io.BytesIO(b"not an image"), "file.png"),
            "disguised_gif": (image_file("GIF"), "file.png"),
            "small_width": (image_file(size=(255, 320)), "file.png"),
            "small_height": (image_file(size=(320, 255)), "file.png"),
            "truncated": (io.BytesIO(image_file().getvalue()[:80]), "file.png"),
        }[case]
        response = upload(client, stream, filename)
    assert_invalid(response)


def test_image_limit_checks_actual_bytes_and_cleans_invalid_upload(app_ctx, client):
    app_ctx.config["AGENT_MAX_IMAGE_MB"] = 0.001
    response = upload(client, image_file(size=(1024, 1024)), "large.png")
    assert_invalid(response)


def test_request_size_limit_uses_attachment_error_contract(app_ctx, client):
    app_ctx.config["MAX_CONTENT_LENGTH"] = 100
    response = upload(client, image_file(), "large.png")
    assert_invalid(response)


def test_png_with_corrupt_checksum_returns_validation_error(app_ctx, client):
    contents = bytearray(image_file().getvalue())
    chunk = contents.index(b"IDAT")
    length = int.from_bytes(contents[chunk - 4:chunk], "big")
    contents[chunk + 4 + length] ^= 1
    assert_invalid(upload(client, io.BytesIO(contents), "corrupt.png"))


@pytest.fixture(scope="module")
def video_file(tmp_path_factory):
    binary = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    assert binary, "Attachment media tests require FFmpeg"
    path = tmp_path_factory.mktemp("agent-attachment-media") / "source.mp4"
    subprocess.run([binary, "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
                    "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   capture_output=True, check=True, timeout=30)
    return path


@pytest.mark.parametrize("suffix", ["mp4", "mov", "mkv", "webm"])
def test_video_extensions_and_legacy_remix_metadata(app_ctx, client, video_file, suffix):
    # The local inspector identifies the container from bytes, not client MIME.
    with video_file.open("rb") as stream:
        response = upload(client, stream, f"movie.{suffix}")
    assert response.status_code == 201, response.json
    result = response.json["data"]
    assert result["kind"] == "video"
    assert result["duration"] == pytest.approx(1, abs=0.1)
    artifact = attachment_for_owner(result["attachment_id"], "local")
    assert artifact.artifact_type == "source_video"
    assert artifact.meta["media"]["kind"] == "video"
    assert artifact.meta["media"]["width"] == 320
    assert artifact.meta["media"]["fps"] == pytest.approx(10)
    assert artifact.meta["video"] == {"width": 320, "height": 180, "duration": result["duration"]}
    assert source_for_owner(result["attachment_id"], "local") == artifact
    assert ApiTask.query.count() == 0


def test_rejects_video_over_duration_limit(app_ctx, client, video_file):
    app_ctx.config["AGENT_MAX_VIDEO_SEC"] = 0.5
    with video_file.open("rb") as stream:
        response = upload(client, stream, "long.mp4")
    assert_invalid(response)


def test_invalid_video_is_rejected_and_cleaned(app_ctx, client):
    assert_invalid(upload(client, io.BytesIO(b"not video"), "broken.mp4"))


def test_unavailable_media_tool_is_an_operational_error(app_ctx, client, monkeypatch):
    def unavailable(path):
        raise AppError("MEDIA_TOOL_UNAVAILABLE", "FFmpeg is not installed", 503)
    monkeypatch.setattr(VideoMediaService, "inspect", unavailable)
    response = upload(client, io.BytesIO(b"video"), "source.mp4")
    assert response.status_code == 503
    assert response.json["error"]["code"] == "MEDIA_TOOL_UNAVAILABLE"
    assert Job.query.count() == Artifact.query.count() == 0
    assert not list((StorageService.root() / "uploads").glob("*"))


def test_attachment_lookup_rejects_other_owner_missing_file_and_non_upload(app_ctx, client):
    result = upload(client, image_file(), "photo.png").json["data"]
    artifact = attachment_for_owner(result["attachment_id"], "local")
    for artifact_id, owner in [(result["attachment_id"], "other"), ("art_missing", "local")]:
        with pytest.raises(AppError) as raised:
            attachment_for_owner(artifact_id, owner)
        assert raised.value.code == "ATTACHMENT_NOT_FOUND"
        assert raised.value.status_code == 404
    artifact.job.strategy = "default"
    db.session.commit()
    with pytest.raises(AppError, match="Attachment not found"):
        attachment_for_owner(artifact.artifact_id, "local")
    artifact.job.strategy = "agent_upload"
    db.session.commit()
    StorageService.resolve(artifact.file_path).unlink()
    with pytest.raises(AppError, match="Attachment not found"):
        attachment_for_owner(artifact.artifact_id, "local")


def test_attachment_lookup_rejects_file_outside_storage(app_ctx, client, tmp_path):
    result = upload(client, image_file(), "photo.png").json["data"]
    artifact = attachment_for_owner(result["attachment_id"], "local")
    outside = tmp_path / "outside.png"
    outside.write_bytes(image_file().getvalue())
    artifact.file_path = str(outside)
    db.session.commit()
    with pytest.raises(AppError, match="Attachment not found"):
        attachment_for_owner(artifact.artifact_id, "local")


@pytest.mark.config(AGENT_MODE_ENABLED=True, API_AUTH_REQUIRED=True,
                    JWT_SECRET_KEY="agent-attachment-test-secret-over-32-bytes")
def test_upload_records_authenticated_owner_and_requires_authentication(app_ctx, client):
    from flask_jwt_extended import create_access_token

    assert upload(client, image_file(), "photo.png").status_code == 401
    headers = {"Authorization": f"Bearer {create_access_token(identity='alice')}"}
    response = client.post("/api/agent/attachments", headers=headers,
                           data={"file": (image_file(), "photo.png")})
    assert response.status_code == 201
    artifact = attachment_for_owner(response.json["data"]["attachment_id"], "alice")
    assert artifact.job.config["agent_upload_owner"] == "alice"
    with pytest.raises(AppError) as raised:
        attachment_for_owner(artifact.artifact_id, "bob")
    assert raised.value.code == "ATTACHMENT_NOT_FOUND"


@pytest.mark.config(AGENT_MODE_ENABLED=True, API_AUTH_REQUIRED=True,
                    JWT_SECRET_KEY="agent-attachment-test-secret-over-32-bytes")
def test_attachment_urls_and_lists_enforce_ownership_but_classic_media_stays_public(app_ctx, client):
    from flask_jwt_extended import create_access_token

    alice = {"Authorization": f"Bearer {create_access_token(identity='alice')}"}
    bob = {"Authorization": f"Bearer {create_access_token(identity='bob')}"}
    response = client.post("/api/agent/attachments", headers=alice, data={"file": (image_file(), "photo.png")})
    artifact = attachment_for_owner(response.json["data"]["attachment_id"], "alice")
    for endpoint in ("preview", "download"):
        url = f"/api/artifacts/{artifact.artifact_id}/{endpoint}"
        assert client.get(url).status_code == 401
        assert client.get(url, headers=bob).status_code == 404
        assert client.get(url, headers=alice).status_code == 200
    assert client.get("/api/artifacts", headers=bob).json["data"]["artifacts"] == []
    assert len(client.get("/api/artifacts", headers=alice).json["data"]["artifacts"]) == 1
    job_url = f"/api/jobs/{artifact.job.job_id}"
    assert client.get(job_url + "/artifacts", headers=bob).status_code == 404
    assert len(client.get(job_url + "/artifacts", headers=alice).json["data"]["artifacts"]) == 1
    assert client.get(job_url, headers=bob).status_code == 404
    assert client.get(job_url, headers=alice).status_code == 200
    assert client.get(job_url + "/stream").status_code == 401
    assert client.delete(job_url, headers=bob, json={"confirm_job_id": artifact.job.job_id}).status_code == 404
    assert client.patch(job_url, headers=alice, json={"job_name": "My uploaded portrait"}).status_code == 200

    # Package artifacts attached to the private upload job inherit its owner.
    package = ArtifactService.register_artifact(artifact.job, artifact.file_path, "job_package")
    db.session.commit()
    assert client.get(f"/api/artifacts/{package.artifact_id}/download", headers=bob).status_code == 404
    assert client.get(f"/api/artifacts/{package.artifact_id}/download", headers=alice).status_code == 200

    classic = JobService.create_job({"template_id": "agent_workspace", **node_selection([])})
    classic_file = StorageService.write_mock_png(classic.job_id, ["outputs", "classic.png"])
    public = ArtifactService.register_artifact(classic, classic_file, "first_frame_image")
    db.session.commit()
    assert client.get(f"/api/artifacts/{public.artifact_id}/preview").status_code == 200
    assert client.get(f"/api/artifacts/{public.artifact_id}/download").status_code == 200
    visible = client.get("/api/artifacts", headers=bob).json["data"]["artifacts"]
    assert [item["artifact_id"] for item in visible] == [public.artifact_id]
    owned_job_id = artifact.job.job_id
    assert client.delete(job_url, headers=alice, json={"confirm_job_id": owned_job_id}).status_code == 200
    assert Job.query.filter_by(job_id=owned_job_id).first() is None
    assert client.get(f"/api/artifacts/{public.artifact_id}/preview").status_code == 200


@pytest.mark.config(AGENT_MODE_ENABLED=True, API_AUTH_REQUIRED=True,
                    JWT_SECRET_KEY="agent-attachment-test-secret-over-32-bytes")
def test_classic_import_cannot_republish_another_owners_attachment(app_ctx, client, video_file):
    from flask_jwt_extended import create_access_token

    alice = {"Authorization": f"Bearer {create_access_token(identity='alice')}"}
    bob = {"Authorization": f"Bearer {create_access_token(identity='bob')}"}
    with video_file.open("rb") as stream:
        response = client.post("/api/agent/attachments", headers=alice, data={"file": (stream, "movie.mp4")})
    artifact = attachment_for_owner(response.json["data"]["attachment_id"], "alice")
    for source in ({"initial_artifacts": {"source_video": artifact.artifact_id}},
                   {"initial_artifacts": {"reference_images": {"artifact_ids": [artifact.artifact_id]}}},
                   {"source_video_path": artifact.file_path},
                   {"source_video_path": StorageService.relative_path(artifact.file_path)}):
        result = client.post("/api/jobs", headers=bob, json={"template_id": "agent_workspace",
                                                            **node_selection([]), **source})
        assert result.status_code == 404, result.json
        assert result.json["error"]["code"] == "ATTACHMENT_NOT_FOUND"
        assert Job.query.count() == 1
    result = client.post("/api/jobs", headers=alice, json={"template_id": "agent_workspace",
        **node_selection([]), "initial_artifacts": {"source_video": artifact.artifact_id}})
    assert result.status_code == 201, result.json


@pytest.mark.parametrize("failure", ["register", "describe", "commit"])
@pytest.mark.parametrize("kind", ["image", "video"])
def test_upload_database_failure_rolls_back_job_and_removes_file(app_ctx, client, monkeypatch, failure, kind, video_file):
    ensure_agent_template()

    def fail(*args, **kwargs):
        raise RuntimeError("injected database failure")

    if failure == "register":
        monkeypatch.setattr(ArtifactService, "register_artifact", fail)
    elif failure == "describe":
        monkeypatch.setattr("app.agent.attachments.describe_attachment", fail)
    else:
        monkeypatch.setattr(db.session, "commit", fail)
    stream = image_file() if kind == "image" else io.BytesIO(video_file.read_bytes())
    response = upload(client, stream, "photo.png" if kind == "image" else "movie.mp4")
    assert response.status_code == 500
    assert Job.query.count() == Artifact.query.count() == 0
    assert not list((StorageService.root() / "uploads").glob("*"))


def test_sources_preserve_response_and_existing_v1_uploads(app_ctx, client, video_file):
    with video_file.open("rb") as stream:
        response = client.post("/api/agent/sources", data={"file": (stream, "original.mp4")})
    assert response.status_code == 201, response.json
    data = response.json["data"]
    assert set(data) == {"artifact_id", "file_name", "duration", "width", "height", "preview_url"}
    artifact = attachment_for_owner(data["artifact_id"], "local")
    assert source_for_owner(data["artifact_id"], "local") == artifact
    artifact.job.strategy = "agent_source"
    artifact.job.config = {"agent_source_owner": "legacy-owner"}
    db.session.commit()
    assert source_for_owner(data["artifact_id"], "legacy-owner") == artifact
    with pytest.raises(AppError) as raised:
        attachment_for_owner(data["artifact_id"], "legacy-owner")
    assert raised.value.code == "ATTACHMENT_NOT_FOUND"


def test_service_checks_actual_video_size_without_http_parser(app_ctx):
    app_ctx.config["MAX_CONTENT_LENGTH"] = 5
    file = FileStorage(stream=io.BytesIO(b"123456"), filename="large.mp4")
    with pytest.raises(AppError) as raised:
        upload_attachment(file, "local")
    assert raised.value.code == "INVALID_ATTACHMENT"
    assert Job.query.count() == 0
