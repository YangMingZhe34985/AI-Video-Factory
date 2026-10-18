"""Real local media verify Wan3 limits without paid calls."""
import io
import subprocess
import wave
from pathlib import Path
import pytest
from PIL import Image
from pypdf import PdfWriter
from werkzeug.datastructures import FileStorage
from app.adapters.dashscope_wan3 import DashScopeWan3Adapter
from app.agent.attachments import attachment_for_owner, upload_attachment
from app.agent.transform_media import inspect_transform_media, resolved_media, MediaReference
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, Artifact, Job
from app.services.storage_service import StorageService
from app.services.video_compression_service import VideoCompressionService
from app.services.wan3_media_service import Wan3MediaService
from tests.test_wan3_adapter import adapter
pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True)


def make_media(root, name, *, duration=1.25, size="320x240", fps=24):
    path = root / name
    if path.suffix in {".wav", ".mp3"}:
        command = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000", "-t", str(duration)]
    else:
        command = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}", "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    result = subprocess.run([VideoCompressionService.resolve_ffmpeg(), "-y", "-nostdin", "-v", "error", *command, str(path)], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return path


def upload_path(path, owner="local"):
    with path.open("rb") as stream:
        return upload_attachment(FileStorage(stream=stream, filename=path.name), owner)


def new_run(ids, owner="local", key="one", text="生成一段新视频"):
    row = AgentRun(owner_id=owner, request_key=key, request={"text": text, "attachment_ids": ids, "budget_limit": 100}, snapshot={})
    db.session.add(row)
    db.session.commit()
    return row


@pytest.mark.parametrize("name,kind", [("clip.mp4", "video"), ("clip.mov", "video"), ("sound.wav", "audio"), ("sound.mp3", "audio")])
def test_real_complete_decoded_duration(app_ctx, name, kind):
    generated = make_media(StorageService.root(), name)
    result = Wan3MediaService.inspect(generated, kind)
    assert result["duration_sec"] == pytest.approx(1.25, abs=0.02)
    if kind == "video": assert (result["width"], result["height"], result["fps"]) == (320,240,24)
    if kind == "audio":
        uploaded = upload_path(generated)
        assert uploaded["kind"] == "audio" and uploaded["duration"] == result["duration_sec"]
        assert attachment_for_owner(uploaded["attachment_id"], "local").artifact_type == "agent_attachment_audio"


@pytest.mark.parametrize("name", ["note.txt", "note.md", "note.pdf"])
def test_documents_uploaded_and_private(app_ctx, name):
    path = StorageService.root() / name
    if name.endswith("pdf"):
        writer = PdfWriter(); writer.add_blank_page(width=300, height=300); writer.write(path)
    else: path.write_text("角色参考：阳光下的猫。", encoding="utf-8")
    result = upload_path(path)
    assert result["kind"] == "file" and result["duration"] is None
    artifact = attachment_for_owner(result["attachment_id"], "local")
    assert artifact.artifact_type == "agent_attachment_document"
    assert artifact.meta["media"]["page_count"] == (1 if name.endswith("pdf") else None)
    with pytest.raises(AppError) as error: attachment_for_owner(artifact.artifact_id, "another")
    assert error.value.status_code == 404


@pytest.mark.parametrize("case", ["empty", "encoding", "nul", "badpdf", "encrypted", "pages", "office", "apple", "falsewav", "truncatedwav"])
def test_bad_uploads_leave_no_rows(app_ctx, case):
    name, raw = "note.txt", b""
    if case == "encoding": raw = b"\xff\xfe"
    if case == "nul": raw = b"valid\x00invalid"
    if case == "badpdf": name, raw = "bad.pdf", b"%PDF-1.7\nbroken"
    if case in {"encrypted", "pages"}:
        writer, output = PdfWriter(), io.BytesIO()
        for _ in range(51 if case == "pages" else 1): writer.add_blank_page(width=300, height=300)
        if case == "encrypted": writer.encrypt("secret")
        writer.write(output)
        name, raw = "document.pdf", output.getvalue()
    if case in {"office", "apple"}: name, raw = "note." + ("docx" if case == "office" else "pages"), b"unsupported"
    if case == "falsewav": name, raw = "bad.wav", b"not audio"
    if case == "truncatedwav":
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(8000); writer.writeframes(b"\0" * 32000)
        name, raw = "bad.wav", output.getvalue()[:-10000]
    with pytest.raises(AppError) as error: upload_attachment(FileStorage(stream=io.BytesIO(raw), filename=name), "local")
    assert error.value.code == "INVALID_ATTACHMENT"
    assert Job.query.count() == Artifact.query.count() == 0
    assert not list((StorageService.root() / "uploads").iterdir())


@pytest.mark.parametrize("duration,size,fps", [(0.5,"320x240",24), (15.1,"320x240",24), (1.25,"320x180",24), (1.25,"320x240",15)])
def test_video_limits_no_silent_clipping(app_ctx, duration, size, fps):
    path = make_media(StorageService.root(), "limits.mp4", duration=duration, size=size, fps=fps)
    with pytest.raises(AppError): Wan3MediaService.inspect(path, "video")


def test_manifest_actual_seconds_scope_and_drift(app_ctx):
    item = upload_path(make_media(StorageService.root(), "source.mp4"))
    run = new_run([item["attachment_id"]])
    refs = [MediaReference(type="reference_video", artifact_id=item["attachment_id"])]
    verified = inspect_transform_media(refs, run=run, operation="extend", source_artifact_id=item["attachment_id"])
    assert verified["input_video_seconds"] == verified["source_video_seconds"] == 1.25
    assert "url" not in verified["manifest"][0] and "path" not in str(verified["manifest"])
    result = resolved_media(refs, run=run, expected_manifest=verified["manifest"])
    assert Path(result[0]["url"]).is_file()
    other = new_run([], key="other")
    with pytest.raises(AppError) as error: inspect_transform_media(refs, run=other, operation="reference")
    assert error.value.status_code == 404
    Path(result[0]["url"]).write_bytes(b"changed bytes")
    with pytest.raises(AppError) as error: resolved_media(refs, run=run, expected_manifest=verified["manifest"])
    assert error.value.code == "TRANSFORM_INPUT_CHANGED"


def test_duplicate_type_source_order_and_total_seconds(app_ctx):
    a = upload_path(make_media(StorageService.root(), "a.mp4", duration=8))
    b = upload_path(make_media(StorageService.root(), "b.mp4", duration=8))
    run = new_run([a["attachment_id"], b["attachment_id"]])
    refs = [{"type": "reference_video", "artifact_id": item["attachment_id"]} for item in (a,b)]
    for invalid_refs, operation, source in [(refs,"reference",None),([refs[0]]*2,"reference",None),([refs[0]],"edit",b["attachment_id"]),([{**refs[0],"type":"reference_audio"}],"reference",None)]:
        with pytest.raises(AppError): inspect_transform_media(invalid_refs, run=run, operation=operation, source_artifact_id=source)


def test_adapter_verified_video_audio_file_and_output_limit_before_upload(app_ctx, monkeypatch):
    video = make_media(StorageService.root(), "video.mp4", duration=5)
    audio = make_media(StorageService.root(), "voice.mp3")
    document = StorageService.root() / "script.md"; document.write_text("动作参考正文", encoding="utf-8")
    value, calls = adapter(), []
    monkeypatch.setattr(DashScopeWan3Adapter, "use_mock", property(lambda _: False))
    monkeypatch.setattr(value, "upload_local_file_get_oss_url", lambda model,path: calls.append(path) or "oss://fixture/media")
    media = [{"type":kind,"url":str(path)} for kind,path in [("reference_video",video),("reference_audio",audio),("file",document)]]
    output = value.build_payload({"prompt":"把视频1延长到7秒","media":media}, {"duration":7})
    assert len(calls) == 3 and output["parameters"]["duration"] == 7
    calls.clear()
    with pytest.raises(AppError): value.build_payload({"prompt":"创作","media":media}, {"duration":26})
    assert calls == []


def test_same_identity_cache_and_replacement_decode(app_ctx, monkeypatch):
    path = make_media(StorageService.root(), "cache.mp4")
    original, calls = Wan3MediaService._inspect, []
    monkeypatch.setattr(Wan3MediaService, "_inspect", classmethod(lambda cls,p,k: calls.append(p) or original(p,k)))
    assert Wan3MediaService.inspect(path,"video") == Wan3MediaService.inspect(path,"video")
    assert len(calls) == 1
    path.write_bytes(b"invalid replaced video")
    with pytest.raises(AppError): Wan3MediaService.inspect(path,"video")
    assert len(calls) == 2


@pytest.mark.parametrize("case", ["alpha", "badpng", "small", "audio_count", "image_count", "files", "spoofed_seconds"])
def test_reference_shape_and_image_boundaries(app_ctx, case):
    path = StorageService.root() / "image.png"
    Image.new("RGBA" if case == "alpha" else "RGB", (200, 300) if case == "small" else (320, 256)).save(path)
    if case == "badpng": path.write_bytes(path.read_bytes()[:100])
    if case in {"alpha", "badpng", "small"}:
        with pytest.raises(AppError): Wan3MediaService.inspect(path, "image")
        return
    kind, count = {"audio_count": ("reference_audio",6), "image_count": ("reference_image",11),
                   "files": ("file",2), "spoofed_seconds": ("reference_video",1)}[case]
    refs = [{"type":kind,"artifact_id":f"untrusted-{i}"} for i in range(count)]
    if case == "spoofed_seconds": refs[0]["duration_sec"] = 0
    row = new_run([])
    with pytest.raises(AppError) as error: inspect_transform_media(refs,run=row,operation="reference")
    assert error.value.code == "INVALID_TRANSFORM_MEDIA"


def test_video_with_extra_track_rejected_before_estimate(app_ctx):
    source = make_media(StorageService.root(), "source.mp4")
    target = StorageService.root() / "two-tracks.mp4"
    result = subprocess.run([VideoCompressionService.resolve_ffmpeg(), "-y", "-v", "error", "-i", str(source),
        "-map", "0:v", "-map", "0:v", "-c", "copy", str(target)],capture_output=True,timeout=20)
    assert result.returncode == 0
    with pytest.raises(AppError): Wan3MediaService.inspect(target,"video")


def test_truncated_real_mp4_and_wrong_container_rejected(app_ctx):
    source = make_media(StorageService.root(), "source.mp4")
    truncated = StorageService.root() / "truncated.mp4"
    truncated.write_bytes(source.read_bytes()[:len(source.read_bytes())//2])
    with pytest.raises(AppError): Wan3MediaService.inspect(truncated,"video")
    mkv = make_media(StorageService.root(), "wrong.mkv")
    disguised = StorageService.root() / "disguised.mp4"
    disguised.write_bytes(mkv.read_bytes())
    with pytest.raises(AppError): Wan3MediaService.inspect(disguised,"video")


def test_exact_fifteen_seconds_uses_integer_pts_not_rounded_display(app_ctx):
    path = make_media(StorageService.root(), "exact-limit.mp4", duration=15, fps=24)
    assert Wan3MediaService.inspect(path,"video")["duration_sec"] == 15.0
    payload = adapter().build_payload({"prompt":"编辑视频1","media":[{"type":"reference_video","url":str(path)}]}, {"duration":15})
    assert payload["parameters"]["duration"] == 15
    with pytest.raises(AppError):
        adapter().build_payload({"prompt":"编辑视频1","media":[{"type":"reference_video","url":str(path)}]}, {"duration":16})

@pytest.mark.parametrize("suffix", ["wav", "mp3"])
def test_audio_sample_duration_at_fifteen_second_limit(app_ctx, suffix):
    path = StorageService.root() / ("exact-limit." + suffix)
    result = subprocess.run([VideoCompressionService.resolve_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=44100", "-t", "15", str(path)],capture_output=True,timeout=20)
    assert result.returncode == 0
    assert Wan3MediaService.inspect(path,"audio")["duration_sec"] == 15.0

def test_missing_pdf_dependency_is_service_error_not_bad_user_file(app_ctx, monkeypatch):
    from app.services import wan3_media_service as media
    path = StorageService.root() / "valid.pdf"
    writer = PdfWriter(); writer.add_blank_page(width=300,height=300); writer.write(path)
    monkeypatch.setattr(media,"find_spec",lambda _: None)
    with pytest.raises(AppError) as error: upload_path(path)
    assert error.value.code == "MEDIA_TOOL_UNAVAILABLE" and error.value.status_code == 503
    assert Job.query.count() == Artifact.query.count() == 0
