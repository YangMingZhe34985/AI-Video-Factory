"""Registry captures page bytes once with Run/owner scope and SSRF checks."""
import pytest
from app.agent.attachments import attachment_for_owner, require_upload_job_owner, validate_job_attachment_sources
from app.agent.transform_media import inspect_transform_media, resolved_media
from app.api import AppError
from app.extensions import db
from app.models import Artifact, Job, ToolInvocation
from app.services.artifact_service import ArtifactService
from app.services.job_service import JobService
from app.services.storage_service import StorageService
from app.skills import build_default_registry
from app.skills.job_backed import ensure_agent_template, node_selection
from app.skills.spec import ToolContext
from app.skills.tools import capture_reference_page as capture
from tests.test_wan3_media import new_run
from tests.test_research_fetch import network, Response


def invoke(row, url, **kwargs):
    return build_default_registry().invoke("capture_reference_page", {"run_id":row.run_id,"url":url},
        ToolContext(role=kwargs.pop("role", "director"), budget_scope=kwargs.pop("scope", row.run_id), **kwargs))


def test_mock_capture_replay_owned_manifest_and_cache_loss_stops(app_ctx, monkeypatch):
    url = "https://reference.example/story"
    row = new_run([], text="参考此网页 " + url)
    monkeypatch.setattr(capture, "fetch_resource", lambda *a, **kw: pytest.fail("Mock must never fetch a page"))
    result = invoke(row, url)
    output = result["output"]
    artifact = attachment_for_owner(output["attachment_id"], "local", run_id=row.run_id)
    assert "Mock" in output["description"] and artifact.artifact_type == "agent_reference_document"
    assert artifact.meta["media"]["kind"] == "file"
    path = StorageService.resolve(artifact.file_path)
    assert "Mock" in path.read_text(encoding="utf-8")
    assert invoke(row,url)["replayed"] and ToolInvocation.query.count() == 1
    refs = [{"type":"file","artifact_id":artifact.artifact_id}]
    verified = inspect_transform_media(refs,run=row,operation="reference")
    assert verified["manifest"][0]["source_url"] == url
    assert resolved_media(refs,run=row,expected_manifest=verified["manifest"])[0]["type"] == "file"
    with pytest.raises(AppError): attachment_for_owner(artifact.artifact_id,"local")
    with pytest.raises(AppError): attachment_for_owner(artifact.artifact_id,"other",run_id=row.run_id)
    other = new_run([],key="other")
    with pytest.raises(AppError): inspect_transform_media(refs,run=other,operation="reference")
    path.unlink()
    with pytest.raises(AppError) as error: invoke(row,url)
    assert error.value.status_code == 409 and ToolInvocation.query.count() == 1
    with pytest.raises(AppError): invoke(row,url,idempotency_key="new-key-after-loss")
    assert Job.query.count() == 1


def test_capture_altered_snapshot_not_replaced(app_ctx):
    url = "https://reference.example/story"
    row = new_run([], text=url)
    artifact_id = invoke(row,url)["output"]["attachment_id"]
    artifact = Artifact.query.filter_by(artifact_id=artifact_id).one()
    StorageService.resolve(artifact.file_path).write_text("changed",encoding="utf-8")
    with pytest.raises(AppError) as error: invoke(row,url)
    assert error.value.status_code == 409
    assert Artifact.query.count() == 1


def test_original_user_url_scope_and_role_required(app_ctx):
    url = "https://reference.example/story"
    row = new_run([],text=url)
    for requested, kwargs in [("https://other.example/",{}),(url,{"scope":"another-run"}),(url,{"role":"production"}),
                               ("file:///private",{}),("mock://reference",{}),("https://user:password@example.com",{})]:
        with pytest.raises(AppError): invoke(row,requested,**kwargs)
    assert ToolInvocation.query.count() == Job.query.count() == 0


def test_real_capture_uses_bounded_pinned_fetch_and_strips_scripts(app_ctx, monkeypatch):
    url = "https://reference.example/story"
    row = new_run([],text=url)
    calls,_ = network(app_ctx,monkeypatch,[Response(body=b"<html><script>do evil</script><style>hidden</style><p>Creative reference</p></html>",headers={"Content-Type":"text/html"})])
    artifact_id = invoke(row,url)["output"]["attachment_id"]
    artifact = Artifact.query.filter_by(artifact_id=artifact_id).one()
    assert StorageService.resolve(artifact.file_path).read_text(encoding="utf-8") == "Creative reference"
    assert calls[0].address == "93.184.216.34"
    assert calls[0].options["server_hostname"] == "reference.example"
    assert artifact.meta["reference"]["mock"] is False


@pytest.mark.parametrize("case",["private","redirect","empty","oversize","binary"])
def test_capture_fetch_rejects_invalid_resources(app_ctx,monkeypatch,case):
    url = "https://reference.example/"
    row = new_run([],text=url)
    responses, addresses = [Response()], None
    if case == "private": addresses = {"reference.example":["127.0.0.1"]}; responses=[]
    if case == "redirect": responses=[Response(status=302,headers={"Location":"http://127.0.0.1/private"})]
    if case == "empty": responses=[Response(body=b"<script>only script</script>",headers={"Content-Type":"text/html"})]
    if case == "oversize": responses=[Response(body=b"x"*100)]; app_ctx.config["AGENT_FETCH_MAX_BYTES"]=50
    if case == "binary": responses=[Response(body=b"binary",headers={"Content-Type":"application/octet-stream"})]
    calls,_ = network(app_ctx,monkeypatch,responses,addresses)
    with pytest.raises(AppError): invoke(row,url)
    assert Artifact.query.count() == Job.query.count() == 0
    assert all(connection.closed for connection in calls)


def test_private_snapshot_cannot_be_copied_into_classic_job(app_ctx):
    url="https://reference.example/"
    row=new_run([],text=url)
    artifact=Artifact.query.filter_by(artifact_id=invoke(row,url)["output"]["attachment_id"]).one()
    for payload in ({"initial_artifacts":{"reference":artifact.artifact_id}}, {"source_video_path":artifact.file_path}):
        with pytest.raises(AppError): validate_job_attachment_sources(payload,"local")


def test_transform_private_outputs_require_matching_owner_and_budget_scope(app_ctx):
    row=new_run([])
    template=ensure_agent_template()
    job=JobService.create_job({"template_id":template.template_id,"strategy":"agent_skill", **node_selection([]),
        "job_config":{"agent_transform":{"run_id":row.run_id},"skill":{"budget_scope":row.run_id}}},commit=False)
    path=StorageService.job_dir(job.job_id)/"private.mp4"; path.write_bytes(b"private fixture")
    artifact=ArtifactService.register_artifact(job,str(path),"video"); db.session.commit()
    require_upload_job_owner(job,"local")
    with pytest.raises(AppError): require_upload_job_owner(job,"other")
    with pytest.raises(AppError): validate_job_attachment_sources({"source_video_path":str(path)},"other")
    with pytest.raises(AppError): validate_job_attachment_sources({"initial_artifacts":{"video":artifact.artifact_id}},"other")
    job.config={**job.config,"skill":{"budget_scope":"other"}}
    with pytest.raises(AppError): require_upload_job_owner(job,"local")
