"""Planning preview permits, quotas and real local Mock/MQ execution."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentRun, AgentWorkspaceItem, ApiTask, Artifact, Job, JobNodeRun, ToolInvocation
from app.plans import preview
from app.services.job_run_service import JobRunService
from app.services.model_service import ModelService
from app.tools import build_default_registry, build_v3_registry
from app.tools.budget import BudgetGuard
from app.tools.spec import ToolContext
from app.utils.ids import new_id
from tests.test_simple_plan import image_reference, request_spec
from tests.test_v3_blueprints import make_run


DATA = {"purpose": "确认主角形象", "prompt": "蓝发白衣，角色定妆照"}


def setup_preview(*, references=(), limit=100, managed=True):
    owner = make_run(request_spec("image_create", list(references)))
    owner.status = "understanding"
    owner.request = {**owner.request, "_v3_runtime": managed, "budget_limit": limit}
    root = AgentDelegation.query.filter_by(run_id=owner.run_id).one()
    root.status = "running"
    root.credits_limit = min(20, limit)
    db.session.commit()
    return owner, root


def context(owner, root, key=None):
    return ToolContext(role=root.agent, caller_agent=root.agent, delegation_id=root.id,
        budget_scope=owner.run_id, budget_limit=owner.request["budget_limit"], agent_step=0,
        idempotency_key=key or new_id("preview_test"))


def registry():
    result = build_v3_registry()
    if preview.SPEC.name not in result.names():
        result.register(preview.SPEC)
    return result


@pytest.fixture
def paused_jobs(monkeypatch):
    calls = []
    monkeypatch.setattr(JobRunService, "_start_thread", lambda job_id, target: calls.append(job_id))
    return calls


def test_preview_is_only_agent_visible_generation_exception():
    value = registry()
    assert "request_preview" not in build_default_registry().names()
    exported = value.function_schemas(["request_preview"])[0]["function"]["parameters"]
    assert set(exported["properties"]) == {"purpose", "prompt", "reference_artifact_ids"}
    assert [spec.name for spec in value._specs.values() if spec.agent_visible and spec.permission == "generate"] == ["request_preview"]


@pytest.mark.parametrize("extra", [{"model_id": "expensive"}, {"params": {"n": 4}}, {"n": 2},
    {"plan_preview_id": "forged"}, {"approved": True}, {"reference_artifact_ids": ["a", "a"]}])
def test_caller_cannot_choose_model_cost_count_or_server_permit(app_ctx, extra):
    owner, root = setup_preview()
    with pytest.raises(AppError):
        registry().invoke("request_preview", {**DATA, **extra}, context(owner, root))
    assert ToolInvocation.query.count() == 0
    assert Job.query.count() == 0


def test_context_is_required_even_without_runtime_marker(app_ctx):
    owner, _root = setup_preview(managed=False)
    with pytest.raises(AppError):
        registry().invoke("request_preview", DATA, ToolContext(role="producer", budget_scope=owner.run_id,
            idempotency_key="public-forgery"))
    assert ToolInvocation.query.count() == 0


def test_one_ledger_one_job_frozen_single_image_and_idempotent_replay(app_ctx, paused_jobs):
    owner, root = setup_preview()
    model = ModelService.get_model("wan2.6-image")
    model.default_params = {**model.default_params, "n": 4}
    db.session.commit()
    ctx = context(owner, root, "same-preview")
    initial = registry().invoke("request_preview", DATA, ctx)
    job = Job.query.filter_by(job_id=initial["output"]["job_id"]).one()
    _run, permit = preview.validate_job(job)
    assert permit["params"]["n"] == 1
    assert initial["estimated_cost"] == 2
    assert ctx.approved is False
    replay = registry().invoke("request_preview", DATA, context(owner, root, "same-preview"))
    assert replay["replayed"] and replay["output"] == initial["output"]
    assert Job.query.count() == ToolInvocation.query.count() == len(paused_jobs) == 1
    assert BudgetGuard.spent(owner.run_id) == 2
    assert not ToolInvocation.query.filter_by(tool_name="generate_image").count()
    with pytest.raises(AppError) as conflict:
        registry().invoke("request_preview", {**DATA, "prompt": "changed"}, context(owner, root, "same-preview"))
    assert conflict.value.code == "IDEMPOTENCY_KEY_CONFLICT"


def test_run_limit_six_counts_attempts_but_replay_remains_available(app_ctx, paused_jobs):
    owner, root = setup_preview()
    value = registry()
    for index in range(6):
        value.invoke("request_preview", DATA, context(owner, root, f"preview-{index}"))
    assert len(paused_jobs) == 6
    with pytest.raises(AppError) as limited:
        value.invoke("request_preview", DATA, context(owner, root, "seventh"))
    assert limited.value.code == "PREVIEW_LIMIT_EXCEEDED"
    assert value.invoke("request_preview", DATA, context(owner, root, "preview-0"))["replayed"]
    assert len(paused_jobs) == 6 and BudgetGuard.spent(owner.run_id) == 12


def test_sixth_slot_is_serialized_across_concurrent_delegation_requests(app_ctx, paused_jobs):
    owner, root = setup_preview()
    for index in range(5):
        db.session.add(ToolInvocation(tool_name="request_preview", caller_role="producer", caller_agent="producer",
            delegation_id=root.id, budget_scope=owner.run_id, idempotency_key=f"completed-{index}",
            input_payload=DATA, status="success", estimated_cost=2))
    db.session.commit()
    run_id, delegation_id = owner.run_id, root.id
    barrier = Barrier(2)
    def concurrent(index):
        with app_ctx.app_context():
            owner = AgentRun.query.filter_by(run_id=run_id).one()
            delegation = db.session.get(AgentDelegation, delegation_id)
            barrier.wait(timeout=10)
            try:
                registry().invoke("request_preview", DATA, context(owner, delegation, f"concurrent-{index}"))
                return "accepted"
            except AppError as error:
                return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(concurrent, range(2)))
    assert sorted(results) == ["PREVIEW_LIMIT_EXCEEDED", "accepted"]
    db.session.expire_all()
    assert ToolInvocation.query.filter_by(tool_name="request_preview").filter(ToolInvocation.status != "rejected").count() == 6
    assert len(paused_jobs) == 1


@pytest.mark.parametrize("kind", ["price", "planning", "run"])
def test_price_planning_and_run_caps_prevent_job_creation(app_ctx, paused_jobs, kind):
    owner, root = setup_preview(limit=1 if kind == "run" else 100)
    if kind == "price":
        app_ctx.config["AGENT_V3_PREVIEW_MAX_CREDITS"] = 1
    elif kind == "planning":
        root.credits_limit = 1
        db.session.commit()
    with pytest.raises(AppError) as limited:
        registry().invoke("request_preview", DATA, context(owner, root))
    assert limited.value.code in {"PREVIEW_PRICE_EXCEEDED", "AGENT_PLANNING_BUDGET_EXCEEDED", "BUDGET_EXCEEDED"}
    assert Job.query.count() == len(paused_jobs) == 0
    assert BudgetGuard.spent(owner.run_id) == 0
    assert not (owner.snapshot or {}).get(preview.SNAPSHOT_KEY)


def test_foreign_or_non_image_reference_never_reserves_a_preview(app_ctx, paused_jobs):
    reference = image_reference()
    owner, root = setup_preview()
    with pytest.raises(AppError):
        registry().invoke("request_preview", {**DATA, "reference_artifact_ids": [reference["attachment_id"]]}, context(owner, root))
    assert len(paused_jobs) == ToolInvocation.query.count() == 0


def queued_preview(paused_jobs, references=()):
    owner, root = setup_preview(references=references)
    data = {**DATA, "reference_artifact_ids": [item["attachment_id"] for item in references]}
    result = registry().invoke("request_preview", data, context(owner, root))
    job = Job.query.filter_by(job_id=result["output"]["job_id"]).one()
    _owner, permit = preview.validate_job(job)
    inputs = {"prompt": DATA["prompt"], "prompt_version": permit["job_snapshot"]["prompts"]["first_frame_image"]["version"]}
    if references:
        paths = [item["path"] for item in permit["job_snapshot"]["artifacts"] if item["type"] == "reference_image"]
        inputs.update(source_image=paths[0], source_images=paths)
    return owner, root, job, permit, inputs


@pytest.mark.parametrize("mutation", ["prompt", "model", "count", "operation", "price", "cancelled", "job_config"])
def test_queued_preview_revalidates_permit_before_any_provider_post(app_ctx, paused_jobs, mutation):
    owner, _root, job, permit, inputs = queued_preview(paused_jobs)
    model = ModelService.get_model(permit["model_id"])
    params = deepcopy(permit["params"])
    operation = "submit_first_frame_image"
    if mutation == "prompt":
        inputs["prompt"] = "changed prompt"
    elif mutation == "model":
        model = ModelService.get_model("wan2.7-image")
    elif mutation == "count":
        params["n"] = 2
    elif mutation == "operation":
        operation = "submit_i2v"
    elif mutation == "price":
        model.capabilities = {**model.capabilities, "pricing": {"unit": "image", "credits_per_unit": 2.5}}
        db.session.commit()
    elif mutation == "cancelled":
        owner.status = "cancelled"
        db.session.commit()
    elif mutation == "job_config":
        job.config = {**job.config, "node_model_params": {"submit_first_frame_image": {"n": 2}}}
        db.session.commit()
    with pytest.raises(AppError):
        preview.validate_before_submit(job, model, inputs, params, operation=operation)
    assert ApiTask.query.count() == 0


def test_reference_identity_and_bytes_are_frozen(app_ctx, paused_jobs):
    from app.services.storage_service import StorageService
    reference = image_reference()
    _owner, _root, job, permit, inputs = queued_preview(paused_jobs, [reference])
    model = ModelService.get_model(permit["model_id"])
    preview.validate_before_submit(job, model, inputs, permit["params"], operation="submit_first_frame_image")
    changed = {**inputs, "source_images": ["another-image.png"]}
    with pytest.raises(AppError):
        preview.validate_before_submit(job, model, changed, permit["params"])
    artifact = Artifact.query.filter_by(artifact_id=reference["attachment_id"]).one()
    StorageService.resolve(artifact.file_path).write_bytes(b"changed")
    with pytest.raises(AppError):
        preview.validate_before_submit(job, model, inputs, permit["params"])


def test_manual_or_paid_retry_dispatch_is_rejected(app_ctx, paused_jobs):
    _owner, _root, job, _permit, _inputs = queued_preview(paused_jobs)
    with pytest.raises(AppError) as unsafe:
        JobRunService.run_inline(job.job_id)
    assert unsafe.value.code == "UNSAFE_RETRY"
    with pytest.raises(AppError):
        with preview.authorized_job_dispatch(job, "run_node", "submit_first_frame_image", force=True):
            pass
    assert ApiTask.query.count() == 0


def test_unknown_preview_submission_never_reposts(app_ctx, monkeypatch):
    owner, root = setup_preview()
    calls = []
    def unknown(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("Worker stopped after preview admission")
    monkeypatch.setattr(preview.job_backed, "launch", unknown)
    value = registry()
    for _ in range(2):
        with pytest.raises(AppError):
            value.invoke("request_preview", DATA, context(owner, root, "unknown-preview"))
    assert len(calls) == 1 and ToolInvocation.query.count() == 1
    assert BudgetGuard.spent(owner.run_id) == 2


@pytest.mark.parametrize("adapter_mode", ["mock", "real"])
def test_arbitrary_corrupt_image_is_not_the_mock_sentinel(app_ctx, paused_jobs, adapter_mode):
    from app.services.artifact_service import ArtifactService
    from app.services.storage_service import StorageService
    _owner, _root, job, _permit, _inputs = queued_preview(paused_jobs)
    path = StorageService.job_dir(job.job_id, "outputs") / "invalid.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\ntruncated")
    ArtifactService.register_artifact(job, StorageService.relative_path(path), "first_frame_image")
    job.status = "success"
    db.session.commit()
    # Only read/verify is run after this change; no model dispatch is possible.
    app_ctx.config["MODEL_ADAPTER_MODE"] = adapter_mode
    with pytest.raises(AppError) as invalid:
        preview.record_result(job)
    assert invalid.value.code == "PREVIEW_OUTPUT_INVALID"
    db.session.rollback()
    assert not AgentWorkspaceItem.query.filter_by(kind="note").count()


@pytest.mark.parametrize("mq", [False, True])
@pytest.mark.parametrize("mode", ["t2i", "i2i"])
def test_real_local_mock_preview_jobs_poll_and_write_one_workspace_result(app_ctx, h, mq, mode):
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq)
    references = [image_reference()] if mode == "i2i" else []
    owner, root = setup_preview(references=references)
    data = {**DATA, "reference_artifact_ids": [item["attachment_id"] for item in references]}
    value = registry()
    initial = value.invoke("request_preview", data, context(owner, root, "real-mock"))
    if mq:
        from tests.test_shared_queue import drain
        job = drain(initial["output"]["job_id"])
    else:
        job = h.wait_for_terminal(initial["output"]["job_id"])
    assert job.status == "success", job.error_summary
    first = value.invoke("get_task_status", {"job_id": job.job_id}, context(owner, root))
    second = value.invoke("get_task_status", {"job_id": job.job_id}, context(owner, root))
    assert first["output"]["terminal"] and second["output"]["terminal"]
    notes = AgentWorkspaceItem.query.filter_by(run_id=owner.run_id, kind="note").all()
    assert len(notes) == 1 and notes[0].payload["demo"] is True
    assert len(notes[0].artifact_ids) == 1
    assert ApiTask.query.filter_by(job_id=job.id).count() == 1
    assert ToolInvocation.query.filter_by(budget_scope=owner.run_id, tool_name="request_preview").count() == 1
    assert BudgetGuard.spent(owner.run_id) == 2
    assert value.invoke("request_preview", data, context(owner, root, "real-mock"))["replayed"]
    assert preview.record_result(job) == {"key": notes[0].key, "version": 1}


@pytest.mark.parametrize("gap", ["create", "link", "bind"])
@pytest.mark.parametrize("mode", ["t2i", "i2i"])
def test_created_preview_recovers_original_job_after_each_durable_gap(app_ctx, monkeypatch, gap, mode):
    from app.services.job_service import JobService
    references = [image_reference()] if mode == "i2i" else []
    owner, root = setup_preview(references=references)
    ctx = context(owner, root, "crashed-preview")
    data = {**DATA, "reference_artifact_ids": [item["attachment_id"] for item in references]}
    class WorkerCrash(BaseException):
        pass
    original_create = JobService.create_job
    def crashed_create(*args, **kwargs):
        original_create(*args, **kwargs)
        raise WorkerCrash()
    def crash(*args, **kwargs):
        raise WorkerCrash()
    with monkeypatch.context() as fault:
        if gap == "create":
            fault.setattr(JobService, "create_job", crashed_create)
        elif gap == "link":
            fault.setattr(preview, "bind_job", crash)
        else:
            fault.setattr(JobRunService, "start", crash)
        with pytest.raises(WorkerCrash):
            registry().invoke("request_preview", data, ctx)
    db.session.remove()
    invocation = ToolInvocation.query.filter_by(idempotency_key="crashed-preview").one()
    jobs_before = Job.query.count()
    assert ApiTask.query.count() == 0 and not invocation.output_payload
    monkeypatch.setattr(JobRunService, "start", lambda job_id, run_type, **kwargs:
        JobRunService.run_inline(job_id, run_type, **kwargs))
    recovered = preview.recover_invocation(invocation, ctx)
    assert recovered.status == "success", recovered.error_summary
    assert preview.recover_invocation(invocation, ctx).job_id == recovered.job_id
    assert Job.query.count() == jobs_before and ApiTask.query.count() == 1
    assert ToolInvocation.query.filter_by(tool_name="request_preview").count() == 1
    assert BudgetGuard.spent(owner.run_id) == 2
    assert AgentWorkspaceItem.query.filter_by(run_id=owner.run_id, kind="note").count() == 1


@pytest.mark.parametrize("mutation", ["scope", "model", "prompt", "nodes", "reference", "unknown"])
def test_unbound_recovery_never_trusts_forged_or_ambiguous_job(app_ctx, monkeypatch, mutation):
    reference = image_reference()
    owner, root = setup_preview(references=[reference])
    ctx = context(owner, root, "unbound")
    class WorkerCrash(BaseException):
        pass
    with monkeypatch.context() as fault:
        fault.setattr(preview, "bind_job", lambda *args: (_ for _ in ()).throw(WorkerCrash()))
        with pytest.raises(WorkerCrash):
            registry().invoke("request_preview", {**DATA, "reference_artifact_ids": [reference["attachment_id"]]}, ctx)
    invocation = ToolInvocation.query.filter_by(idempotency_key="unbound").one()
    job = invocation.job
    if mutation == "scope":
        other, other_root = setup_preview()
        ctx = context(other, other_root)
    elif mutation == "model":
        job.config = {**job.config, "node_models": {preview.NODES[0]: "forged-model"}}
    elif mutation == "prompt":
        from app.models import PromptVersion
        PromptVersion.query.filter_by(job_id=job.id, prompt_type="first_frame_image").one().content = "Changed"
    elif mutation == "nodes":
        job.node_overrides = {**job.node_overrides, "enabled_nodes": [*preview.NODES, "submit_t2v"]}
    elif mutation == "reference":
        from app.services.storage_service import StorageService
        source = Artifact.query.filter_by(artifact_id=reference["attachment_id"]).one()
        StorageService.resolve(source.file_path).write_bytes(b"changed")
    else:
        db.session.add(JobNodeRun(job_id=job.id, node_key=preview.NODES[0], status="running"))
    db.session.commit()
    dispatches = []
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: dispatches.append(args))
    with pytest.raises(AppError):
        preview.recover_invocation(invocation, ctx)
    db.session.rollback()
    assert not dispatches and ApiTask.query.count() == 0


def test_preview_accepted_poll_failure_recovers_without_another_post(app_ctx, monkeypatch):
    from app.services.node_runner import NodeRunner
    owner, root = setup_preview()
    monkeypatch.setattr(JobRunService, "start", lambda job_id, run_type, **kwargs:
        JobRunService.run_inline(job_id, run_type, **kwargs))
    with monkeypatch.context() as fault:
        fault.setattr(NodeRunner, "_poll_until_complete", lambda *args:
            (_ for _ in ()).throw(AppError("API_TIMEOUT", "Injected read timeout", 502)))
        registry().invoke("request_preview", DATA, context(owner, root, "poll-failure"))
    invocation = ToolInvocation.query.filter_by(idempotency_key="poll-failure").one()
    assert invocation.job.status == "failed"
    api = ApiTask.query.filter_by(job_id=invocation.job_id).one()
    provider_id = api.provider_task_id
    job = preview.recover_invocation(invocation, context(owner, root))
    assert job.status == "success", job.error_summary
    preview.record_result(job)
    assert preview.validate_job(job)[1]["read_recoveries"] == 1
    assert ApiTask.query.filter_by(job_id=job.id).count() == 1 and api.provider_task_id == provider_id
    assert BudgetGuard.spent(owner.run_id) == 2


def test_preview_read_recovery_is_bounded_and_unknown_never_reposts(app_ctx, monkeypatch):
    from app.services.node_runner import NodeRunner
    owner, root = setup_preview()
    monkeypatch.setattr(JobRunService, "start", lambda job_id, run_type, **kwargs:
        JobRunService.run_inline(job_id, run_type, **kwargs))
    monkeypatch.setattr(NodeRunner, "_poll_until_complete", lambda *args:
        (_ for _ in ()).throw(AppError("API_TIMEOUT", "Injected read timeout", 502)))
    registry().invoke("request_preview", DATA, context(owner, root, "bounded"))
    invocation = ToolInvocation.query.filter_by(idempotency_key="bounded").one()
    for _ in range(4):
        preview.recover_invocation(invocation, context(owner, root))
    assert preview.validate_job(invocation.job)[1]["read_recoveries"] == 2
    assert JobNodeRun.query.filter_by(job_id=invocation.job_id, node_key=preview.NODES[1]).count() == 3
    api = ApiTask.query.filter_by(job_id=invocation.job_id).one()
    api.provider_task_id = None
    db.session.commit()
    with pytest.raises(AppError) as unknown:
        preview.recover_invocation(invocation, context(owner, root))
    assert unknown.value.code == "RECOVERY_REQUIRED" and ApiTask.query.count() == 1


@pytest.mark.parametrize("gap", ["create", "link", "bind"])
def test_agent_pending_turn_recovers_preview_without_another_llm_turn(app_ctx, monkeypatch, gap):
    from app.agents import runtime
    from app.services.job_service import JobService
    from app.tools.scripted_llm import ScriptedLLM
    from langgraph.checkpoint.memory import InMemorySaver
    owner, root = setup_preview()
    script = ScriptedLLM({"producer": [
        [{"id": "preview", "name": "request_preview", "arguments": DATA}],
        [{"id": "finish", "name": "finish", "arguments": {"kind": "completed", "outcome": "answer", "message": "Preview ready"}}],
    ]})
    app_ctx.extensions["agent_v3_scripted_llm"] = script
    saver = InMemorySaver()
    class WorkerCrash(BaseException):
        pass
    original_create = JobService.create_job
    def crashed_create(*args, **kwargs):
        original_create(*args, **kwargs)
        raise WorkerCrash()
    def crash(*args, **kwargs):
        raise WorkerCrash()
    with monkeypatch.context() as fault:
        if gap == "create":
            fault.setattr(JobService, "create_job", crashed_create)
        elif gap == "link":
            fault.setattr(preview, "bind_job", crash)
        else:
            fault.setattr(JobRunService, "start", crash)
        with pytest.raises(WorkerCrash):
            runtime.advance(owner, saver)
    monkeypatch.setattr(JobRunService, "start", lambda job_id, run_type, **kwargs:
        JobRunService.run_inline(job_id, run_type, **kwargs))
    for _ in range(3):
        runtime.advance(owner, saver)
        if owner.status == "success":
            break
    assert owner.status == "success" and script.calls == [("producer", 0), ("producer", 1)]
    receipt = ToolInvocation.query.filter_by(tool_name="request_preview").one()
    assert receipt.output_payload["job_id"] == receipt.job.job_id and receipt.status == "success"
    assert receipt.estimated_cost == 2 and ApiTask.query.count() == 1
    assert AgentWorkspaceItem.query.filter_by(run_id=owner.run_id, kind="note").count() == 1


def test_mq_preview_download_recovery_keeps_original_provider_receipt(app_ctx):
    from tests.test_shared_queue import drain
    app_ctx.config.update(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True)
    owner, root = setup_preview()
    result = registry().invoke("request_preview", DATA, context(owner, root, "mq-read"))
    job = drain(result["output"]["job_id"])
    assert job.status == "success"
    api = ApiTask.query.filter_by(job_id=job.id).one()
    provider_id = api.provider_task_id
    job.status, job.current_node = "failed", preview.NODES[1]
    api.queue_phase, api.status = "failed", "failed"
    api.queue_data = {**api.queue_data, "failure_detail": {"stage": "download", "submission_state": "accepted", "code": "API_TIMEOUT"}}
    db.session.commit()
    invocation = ToolInvocation.query.filter_by(idempotency_key="mq-read").one()
    preview.recover_invocation(invocation, context(owner, root))
    assert api.queue_phase == "download"
    job = drain(job.job_id)
    assert job.status == "success", job.error_summary
    preview.record_result(job)
    assert preview.validate_job(job)[1]["read_recoveries"] == 1
    assert ApiTask.query.count() == 1 and api.provider_task_id == provider_id
    assert BudgetGuard.spent(owner.run_id) == 2
