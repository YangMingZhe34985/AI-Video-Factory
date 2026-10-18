"""V3 video analysis and polling cannot borrow another Run's private work."""

import pytest

from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ApiTask, Artifact, Job, ToolInvocation
from app.services.job_run_service import JobRunService
from app.services.model_service import ModelService
from app.services.storage_service import StorageService
from app.tools import build_default_registry, build_v3_registry
from app.tools.budget import BudgetGuard
from app.tools.spec import ToolContext
from app.utils.ids import new_id


def make_run(ids=(), owner="owner"):
    row = AgentRun(owner_id=owner, request_key=new_id("request"), request={
        "schema_version": 3, "text": "理解此视频", "attachment_ids": list(ids), "budget_limit": 100})
    db.session.add(row)
    db.session.commit()
    return row


def context(run, role="director"):
    return ToolContext(role=role, caller_agent=role, delegation_id=1, agent_step=0,
                       budget_scope=run.run_id, budget_limit=100)


def stored_video(source_video):
    path = StorageService.root() / "inputs" / f"{new_id('source')}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source_video.read_bytes())
    return path


def upload(h, source_video, owner="owner"):
    job = h.make_job(source_video=stored_video(source_video), paths=(), strategy="agent_upload",
                     job_config={"agent_upload_owner": owner})
    artifact = Artifact.query.filter_by(job_id=job.id, artifact_type="source_video").one()
    artifact.meta = {**(artifact.meta or {}), "media": {"kind": "video"}}
    job.status = "success"
    db.session.commit()
    return artifact


def generated_job(h, source_video, run):
    job = h.make_job(source_video=stored_video(source_video), paths=(), strategy="skill:generate_video")
    invocation = ToolInvocation(tool_name="generate_video", caller_role="production", budget_scope=run.run_id,
        idempotency_key=new_id("scope"), job=job, status="success", estimated_cost=0,
        output_payload={"job_id": job.job_id})
    db.session.add(invocation)
    db.session.flush()
    job.config = {**job.config, "skill": {"invocation_id": invocation.invocation_id,
        "tool_name": invocation.tool_name, "budget_scope": run.run_id, "caller_role": "production"}}
    job.status = "success"
    artifact = Artifact.query.filter_by(job_id=job.id, artifact_type="source_video").one()
    artifact.artifact_type = "i2v_video"
    db.session.commit()
    return job, invocation, artifact


@pytest.fixture
def no_worker(monkeypatch):
    starts = []
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: starts.append(args))
    return starts


@pytest.mark.parametrize("source", ["upload", "generated"])
def test_video_analysis_accepts_only_verified_current_run_sources(app_ctx, h, source_video, no_worker, source):
    if source == "upload":
        artifact = upload(h, source_video)
        run = make_run([artifact.artifact_id])
    else:
        run = make_run()
        _job, _invocation, artifact = generated_job(h, source_video, run)
    registry = build_v3_registry()
    result = registry.invoke("analyze_video", {"source_artifact_id": artifact.artifact_id}, context(run))
    job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
    assert job.config["skill"]["budget_scope"] == run.run_id
    assert job.config["node_models"]["reverse_prompts"] == "qwen3.7-plus"
    assert len(no_worker) == 1
    poll = registry.invoke("get_task_status", {"job_id": job.job_id}, context(run))["output"]
    assert poll["job_id"] == job.job_id
    assert poll["invocation"]["invocation_id"] == result["invocation_id"]


@pytest.mark.parametrize("case", ["foreign_owner", "same_owner_not_attached", "classic", "foreign_generated", "forged_marker"])
def test_video_analysis_rejects_unowned_sources_before_dispatch(app_ctx, h, source_video, no_worker, case):
    run = make_run()
    if case in {"foreign_generated", "forged_marker"}:
        other = make_run()
        job, _invocation, artifact = generated_job(h, source_video, other)
        if case == "forged_marker":
            job.config = {**job.config, "skill": {**job.config["skill"], "budget_scope": run.run_id}}
    elif case == "classic":
        job = h.make_job(source_video=source_video, paths=())
        artifact = Artifact.query.filter_by(job_id=job.id, artifact_type="source_video").one()
    else:
        artifact = upload(h, source_video, owner="other" if case == "foreign_owner" else "owner")
        if case == "foreign_owner":
            run.request = {**run.request, "attachment_ids": [artifact.artifact_id]}
    db.session.commit()
    before = Job.query.count()
    with pytest.raises(AppError) as exc:
        build_v3_registry().invoke("analyze_video", {"source_artifact_id": artifact.artifact_id}, context(run))
    assert exc.value.code in {"ATTACHMENT_NOT_FOUND", "TOOL_FORBIDDEN"}
    assert Job.query.count() == before and ApiTask.query.count() == 0 and no_worker == []
    assert BudgetGuard.spent(run.run_id) == 0


@pytest.mark.parametrize("case", ["not_selectable", "wrong_mode", "disabled"])
def test_video_analysis_model_requires_enabled_agent_video_mode(app_ctx, h, source_video, no_worker, case):
    artifact = upload(h, source_video)
    run = make_run([artifact.artifact_id])
    model = ModelService.get_model("qwen3.7-plus")
    if case == "not_selectable":
        model.capabilities = {**model.capabilities, "agent_selectable": False}
    elif case == "wrong_mode":
        model.capabilities = {**model.capabilities, "modes": ["text", "image_understanding"]}
    else:
        model.enabled = False
    db.session.commit()
    before = Job.query.count()
    with pytest.raises(AppError) as exc:
        build_v3_registry().invoke("analyze_video", {"source_artifact_id": artifact.artifact_id}, context(run))
    assert exc.value.code in {"MODEL_CAPABILITY_MISMATCH", "INVALID_INPUT", "MODEL_DISABLED", "MODEL_NOT_FOUND"}
    assert no_worker == [] and Job.query.count() == before and ApiTask.query.count() == 0


@pytest.mark.parametrize("reference", ["job_id", "invocation_id"])
def test_status_reads_own_run_and_denies_other_run(app_ctx, h, source_video, reference):
    run, other = make_run(), make_run()
    job, invocation, _artifact = generated_job(h, source_video, run)
    raw = {reference: job.job_id if reference == "job_id" else invocation.invocation_id}
    registry = build_v3_registry()
    assert registry.invoke("get_task_status", raw, context(run))["output"]["job_id"] == job.job_id
    with pytest.raises(AppError) as exc:
        registry.invoke("get_task_status", raw, context(other))
    assert exc.value.code == "TOOL_FORBIDDEN"


@pytest.mark.parametrize("case", ["marker_scope", "ledger_scope", "ledger_job", "missing_ledger", "tool_name", "foreign_alias"])
@pytest.mark.parametrize("reference", ["job_id", "invocation_id"])
def test_status_rejects_marker_or_ledger_hijacking(app_ctx, h, source_video, case, reference):
    run, other = make_run(), make_run()
    job, invocation, _artifact = generated_job(h, source_video, run)
    if case == "marker_scope":
        job.config = {**job.config, "skill": {**job.config["skill"], "budget_scope": other.run_id}}
    elif case == "ledger_scope":
        invocation.budget_scope = other.run_id
    elif case == "ledger_job":
        invocation.job = h.make_job(paths=())
    elif case == "missing_ledger":
        job.config = {**job.config, "skill": {**job.config["skill"], "invocation_id": "missing"}}
    elif case == "tool_name":
        job.config = {**job.config, "skill": {**job.config["skill"], "tool_name": "analyze_video"}}
    else:
        # A foreign invocation pointing to this Job grants no authority.
        alias = ToolInvocation(tool_name="generate_video", caller_role="production", budget_scope=other.run_id,
            idempotency_key=new_id("alias"), job=job, status="success", estimated_cost=0)
        db.session.add(alias)
        db.session.flush()
        if reference == "job_id":
            job.config = {**job.config, "skill": {**job.config["skill"], "invocation_id": alias.invocation_id}}
        else:
            invocation = alias
    db.session.commit()
    raw = {reference: job.job_id if reference == "job_id" else invocation.invocation_id}
    before = (invocation.status, invocation.finished_at, Job.query.count(), ApiTask.query.count())
    with pytest.raises(AppError) as exc:
        build_v3_registry().invoke("get_task_status", raw, context(run))
    assert exc.value.code == "TOOL_FORBIDDEN"
    assert (invocation.status, invocation.finished_at, Job.query.count(), ApiTask.query.count()) == before


def test_v3_status_rejects_classic_jobs_but_classic_role_keeps_access(app_ctx, h):
    job = h.make_job(paths=())
    run = make_run()
    with pytest.raises(AppError) as exc:
        build_v3_registry().invoke("get_task_status", {"job_id": job.job_id}, context(run))
    assert exc.value.code == "TOOL_FORBIDDEN"
    old = build_default_registry().invoke("get_task_status", {"job_id": job.job_id}, ToolContext(role="director"))
    assert old["output"]["job_id"] == job.job_id


def test_classic_analysis_still_accepts_classic_source(app_ctx, h, source_video, no_worker):
    job = h.make_job(source_video=source_video, paths=())
    artifact = Artifact.query.filter_by(job_id=job.id, artifact_type="source_video").one()
    result = build_default_registry().invoke("analyze_video", {"source_artifact_id": artifact.artifact_id},
                                            ToolContext(role="creative"))
    assert result["output"]["job_id"] != job.job_id and len(no_worker) == 1
