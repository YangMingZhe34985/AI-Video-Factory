"""Approved Plan DAGs execute through real Mock Jobs and the shared MQ."""
from copy import deepcopy

import pytest

from app.agent import plan_versions as versions
from app.agents.workspace import write_workspace
from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Artifact, Job, PlanNodeTask, ToolInvocation
from app.plans import execution, policy, runtime
from app.plans.compiler import compile_plan
from app.plans.dry_run import dry_run
from app.services.job_run_service import JobRunService
from app.services.storage_service import StorageService
from app.tools import build_v3_registry
from app.tools.budget import BudgetGuard
from app.tools.spec import ToolContext
from tests.test_v3_workspace import brief, make_context

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)


def image_node(name="image", *, gate=None):
    return {"id": name, "tool": "generate_image", "inputs": {"prompt": "A happy orange cat"},
            "model_id": "wan2.6-image", "params": {"n": 1}, "gate": gate,
            "origin": {"agent": "director", "skills": []}, "rationale": "Create a first frame"}


def video_node(name="clip", source="image"):
    return {"id": name, "tool": "animate_shot", "inputs": {"prompt": "The cat dances gently",
            "first_frame_artifact_id": {"ref": source + ".image"}}, "model_id": "wan2.7-i2v", "params": {"duration": 5},
            "origin": {"agent": "director", "skills": []}, "rationale": "Animate the approved image"}


def setup(nodes=None, *, run=None, deliverables=None):
    nodes = nodes or [image_node()]
    for node in nodes:
        node.setdefault("origin", {"agent": "director", "skills": []})
    if run is None:
        run, _root, ctx = make_context(text="生成一个猫的视频")
        write_workspace("brief", "brief", brief(deliverable="video"), ctx)
    registry = build_v3_registry()
    draft = {"title": "A cat", "goal": "Show a dancing cat", "nodes": deepcopy(nodes),
        "deliverables": deliverables or [{"kind": "image", "node_id": nodes[0]["id"], "output": "image"}]}
    number = (versions.current_version(run).version if versions.current_version(run) else 0) + 1
    checked = compile_plan(draft, run, registry=registry, plan_version=number)
    assert not checked["issues"], checked["issues"]
    checked["dry_run"] = dry_run(checked, registry=registry)
    assert checked["dry_run"]["passed"], checked["dry_run"]
    version = versions.create_version(run, checked["plan"], {}, checked, author="system")
    run.status = "awaiting_plan_review"
    db.session.commit()
    return run, version, registry


def drain_plan(run, registry, *, mq=False, limit=20):
    for _ in range(limit):
        status = runtime.advance(run, registry)
        if mq:
            from tests.test_shared_queue import drain
            for task in runtime.latest_tasks(run).values():
                if task.status == "running":
                    drain(task.job_id)
        if status not in runtime.ACTIVE:
            return status
    return run.status


@pytest.mark.parametrize("mq", [False, True])
def test_image_video_dag_uses_shared_jobs_and_typed_outputs(app_ctx, monkeypatch, mq):
    run, version, registry = setup([image_node(), video_node()], deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq)
    if not mq:
        monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    assert runtime.advance(run, registry) == "awaiting_plan_review"
    assert ToolInvocation.query.count() == 0
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry, mq=mq) == "awaiting_result_review", [(t.tool_name, t.error_code, t.error_message) for t in ToolInvocation.query.all()]
    tasks = runtime.latest_tasks(run)
    assert tasks["clip"].inputs["first_frame_artifact_id"] == tasks["image"].output["image"]
    assert all(execution.usable(run, task) for task in tasks.values())
    assert ApiTask.query.count() == 2
    assert ToolInvocation.query.filter_by(budget_scope=run.run_id).count() == 2
    assert BudgetGuard.spent(run.run_id) == sum(task.estimated_cost for task in tasks.values())
    spent = BudgetGuard.spent(run.run_id)
    assert runtime.approve_results(run, version.version) == "success"
    assert runtime.advance(run, registry) == "success"
    assert BudgetGuard.spent(run.run_id) == spent


def test_preview_gate_only_blocks_descendants(app_ctx, monkeypatch):
    run, version, registry = setup([image_node(gate="preview"), video_node(), image_node("other")])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert runtime.advance(run, registry) == "awaiting_gate"
    tasks = runtime.latest_tasks(run)
    assert tasks["image"].status == tasks["other"].status == "success"
    assert tasks["clip"].status == "pending"
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == 0
    runtime.approve_gate(run, version.version, "image")
    assert drain_plan(run, registry) == "awaiting_result_review"
    assert runtime.latest_tasks(run)["clip"].status == "success"


def test_terminal_preview_gate_still_requires_explicit_approval(app_ctx, monkeypatch):
    run, version, registry = setup([image_node(gate="preview")])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert runtime.advance(run, registry) == "awaiting_gate"
    with pytest.raises(AppError):
        runtime.approve_results(run, version.version)
    runtime.approve_gate(run, version.version, "image")
    assert runtime.advance(run, registry) == "awaiting_result_review"


def test_unapproved_context_cannot_invoke_generation(app_ctx):
    run, version, registry = setup()
    ctx = ToolContext(role="production", approved=True, budget_scope=run.run_id, budget_limit=100)
    with pytest.raises(AppError) as error:
        registry.invoke("generate_image", {"prompt": "cat", "model_id": "wan2.6-image"}, ctx)
    assert error.value.code == "APPROVAL_REQUIRED"
    assert ToolInvocation.query.count() == ApiTask.query.count() == 0


def test_completed_input_hash_reuses_only_valid_same_run_outputs(app_ctx, monkeypatch):
    run, version, registry = setup()
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    first = runtime.latest_tasks(run)["image"]
    original_id, cost = first.id, BudgetGuard.spent(run.run_id)
    run, second, registry = setup(run=run)
    runtime.begin(run, second, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    reused = runtime.latest_tasks(run)["image"]
    assert reused.state["reused_from"] == original_id and reused.output == first.output
    assert BudgetGuard.spent(run.run_id) == cost and ApiTask.query.count() == 1
    artifact = Artifact.query.filter_by(artifact_id=first.output["image"]).one()
    StorageService.resolve(artifact.file_path).write_bytes(b"changed bytes")
    assert not execution.usable(run, reused)
    with pytest.raises(AppError):
        runtime.approve_results(run, second.version)


def test_crash_after_tool_receipt_replays_without_second_submit(app_ctx, monkeypatch):
    run, version, registry = setup()
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    original = execution.complete
    with monkeypatch.context() as patch:
        patch.setattr(execution, "complete", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("worker lost after receipt")))
        with pytest.raises(RuntimeError):
            runtime.advance(run, registry)
    task = runtime.latest_tasks(run)["image"]
    assert task.status == "running" and task.invocation_id
    before = BudgetGuard.spent(run.run_id)
    assert drain_plan(run, registry) == "awaiting_result_review"
    assert ApiTask.query.count() == 1 and BudgetGuard.spent(run.run_id) == before


def test_unknown_receipt_never_resubmits(app_ctx, monkeypatch):
    run, version, registry = setup()
    runtime.begin(run, version, registry=registry)
    task = runtime.latest_tasks(run)["image"]
    data, sources, digest = execution.resolve_node(run, version.plan["nodes"][0], version.version, {}, registry)
    task.inputs, task.inputs_hash = data, digest
    task.state = {**task.state, "resolved": True, "input_fingerprints": sources}
    row = ToolInvocation(tool_name="generate_image", idempotency_key=policy.invocation_key(task), caller_role="production",
        budget_scope=run.run_id, status="pending", input_payload=data, estimated_cost=task.estimated_cost)
    db.session.add(row)
    db.session.commit()
    monkeypatch.setattr(JobRunService, "start", lambda *_a, **_k: pytest.fail("Unknown POST was submitted again"))
    assert runtime.advance(run, registry) == "attention"
    assert task.error["category"] == "submit_unknown"
    assert ToolInvocation.query.count() == 1 and ApiTask.query.count() == 0


def test_plan_price_increase_needs_review_and_budget_reserves_repairs(app_ctx):
    run, version, registry = setup()
    with pytest.raises(AppError) as error:
        runtime.begin(run, version, repair_budget_credits=100, registry=registry)
    assert error.value.code == "BUDGET_EXCEEDED"
    assert not runtime.latest_tasks(run)
    from app.models import ModelRegistry
    model = ModelRegistry.query.filter_by(model_id="wan2.6-image").one()
    capabilities = deepcopy(model.capabilities)
    capabilities["pricing"]["credits_per_unit"] *= 2
    model.capabilities = capabilities
    db.session.commit()
    with pytest.raises(AppError) as error:
        runtime.begin(run, version, registry=registry)
    assert error.value.code == "MODEL_PRICE_CHANGED"
    assert ToolInvocation.query.count() == 0


def test_public_job_restart_and_frozen_input_mutation_are_rejected(app_ctx, monkeypatch):
    run, version, registry = setup()
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    task = runtime.latest_tasks(run)["image"]
    job = Job.query.filter_by(job_id=task.job_id).one()
    with pytest.raises(AppError) as error:
        JobRunService.run_inline(job.job_id, "run_full", restart=True)
    assert error.value.code == "UNSAFE_RETRY"
    job.config = {**job.config, "node_model_params": {"submit_first_frame_image": {"n": 4}}}
    db.session.commit()
    with pytest.raises(AppError) as error:
        policy.validate_job(job)
    assert error.value.code == "PLAN_APPROVAL_MISMATCH"


def test_real_mock_delivery_extract_compose_qc_and_zip(app_ctx, monkeypatch):
    import zipfile
    base = [image_node(), video_node()]
    base += [{"id": "tail", "tool": "extract_frame", "inputs": {"video_artifact_id": {"ref": "clip.video"}},
        "rationale": "Extract the ending pose"},
        {"id": "joined", "tool": "compose_video", "inputs": {"video_artifact_ids": [{"ref": "clip.video"}, {"ref": "clip.video"}]},
         "rationale": "Join two clips"},
        {"id": "probe", "tool": "probe_media", "inputs": {"artifact_id": {"ref": "joined.artifact_id"}},
         "rationale": "Inspect the movie"},
        {"id": "qc", "tool": "qc_video", "inputs": {"artifact_id": {"ref": "joined.artifact_id"},
         "video_artifact_ids": [{"ref": "clip.video"}, {"ref": "clip.video"}]}, "depends_on": ["probe"], "rationale": "Check delivery structure"},
        {"id": "package", "tool": "package_story", "inputs": {"artifact_id": {"ref": "joined.artifact_id"}},
         "depends_on": ["qc"], "rationale": "Deliver originals"}]
    run, version, registry = setup(base, deliverables=[{"kind": "package", "node_id": "package", "output": "artifact_id"}])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review", [(x.node_id, x.error) for x in runtime.latest_tasks(run).values()]
    tasks = runtime.latest_tasks(run)
    assert len(tasks) == 7 and tasks["qc"].output["passed"]
    assert tasks["probe"].output["media"]["duration_sec"] == pytest.approx(10, abs=.2)
    assert tasks["joined"].output["compressed_artifact_id"] is None
    artifact = Artifact.query.filter_by(artifact_id=tasks["package"].output["artifact_id"]).one()
    with zipfile.ZipFile(StorageService.resolve(artifact.file_path)) as package:
        assert package.testzip() is None
        assert {"final/master.mp4", "sources/001.mp4", "sources/002.mp4", "manifest.json", "plan.json", "qc.json"} <= set(package.namelist())
        assert "final/compressed.mp4" not in package.namelist()
    assert ApiTask.query.count() == 2


def test_accepted_mq_poll_recovers_with_disabled_model_without_rebilling(app_ctx, monkeypatch):
    from app.adapters.mock import MockAdapter
    from app.models import ModelRegistry
    from tests.test_shared_queue import drain
    app_ctx.config.update(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True, MQ_MAX_ATTEMPTS=1)
    run, version, registry = setup()
    runtime.begin(run, version, registry=registry)
    assert runtime.advance(run, registry) == "executing"
    task = runtime.latest_tasks(run)["image"]
    original = MockAdapter.poll
    with monkeypatch.context() as patch:
        patch.setattr(MockAdapter, "poll", lambda *_: (_ for _ in ()).throw(TimeoutError("temporary poll outage")))
        assert drain(task.job_id).status == "failed"
    api = ApiTask.query.one()
    assert api.provider_task_id and api.queue_phase == "failed"
    spent, provider = BudgetGuard.spent(run.run_id), api.provider_task_id
    model = ModelRegistry.query.filter_by(model_id=api.model_id).one()
    model.enabled = False
    db.session.commit()
    assert runtime.advance(run, registry) == "executing"
    assert task.state["read_recoveries"] == 1
    assert drain(task.job_id).status == "success"
    assert runtime.advance(run, registry) == "awaiting_result_review"
    assert ApiTask.query.count() == 1 and ApiTask.query.one().provider_task_id == provider
    assert BudgetGuard.spent(run.run_id) == spent


def test_missing_completed_download_is_restored_without_new_post(app_ctx, monkeypatch):
    from tests.test_shared_queue import drain
    app_ctx.config.update(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True)
    run, version, registry = setup()
    runtime.begin(run, version, registry=registry)
    runtime.advance(run, registry)
    task = runtime.latest_tasks(run)["image"]
    assert drain(task.job_id).status == "success"
    artifact = Artifact.query.filter_by(artifact_type="first_frame_image").one()
    StorageService.resolve(artifact.file_path).unlink()
    spent = BudgetGuard.spent(run.run_id)
    assert runtime.advance(run, registry) == "executing"
    assert task.state["read_recoveries"] == 1
    assert drain(task.job_id).status == "success"
    assert runtime.advance(run, registry) == "awaiting_result_review"
    assert ApiTask.query.count() == 1 and BudgetGuard.spent(run.run_id) == spent


def test_actual_unknown_mq_post_stops_and_never_retries(app_ctx, monkeypatch):
    from app.adapters.mock import MockAdapter
    from tests.test_shared_queue import drain
    app_ctx.config.update(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True)
    calls = []
    def unknown(_self, payload):
        calls.append(payload)
        raise ConnectionError("response lost after possible acceptance")
    monkeypatch.setattr(MockAdapter, "submit", unknown)
    run, version, registry = setup()
    runtime.begin(run, version, registry=registry)
    runtime.advance(run, registry)
    task = runtime.latest_tasks(run)["image"]
    assert drain(task.job_id).status == "failed"
    assert runtime.advance(run, registry) == "attention"
    assert task.error["category"] == "submit_unknown"
    for _ in range(3):
        assert runtime.advance(run, registry) == "attention"
    assert len(calls) == 1 and ApiTask.query.one().queue_phase == "submit_unknown"


def test_independent_nodes_finish_while_one_content_failure_stops_its_branch(app_ctx, monkeypatch):
    from app.adapters.mock import MockAdapter
    from tests.test_shared_queue import drain
    app_ctx.config.update(MQ_ENABLED=True, MQ_WORKER_ACTIVE=True, AGENT_MAX_PARALLEL_SHOTS=3)
    nodes = [image_node("one"), image_node("bad"), image_node("three"), video_node(source="bad")]
    nodes[1]["inputs"]["prompt"] = "rejected test content"
    original = MockAdapter.submit
    def failure(self, payload):
        if "rejected test" in str(payload):
            raise AppError("CONTENT_POLICY_VIOLATION", "Mock provider rejection", 422,
                           payload={"code": "DataInspectionFailed"})
        return original(self, payload)
    monkeypatch.setattr(MockAdapter, "submit", failure)
    run, version, registry = setup(nodes)
    runtime.begin(run, version, registry=registry)
    assert runtime.advance(run, registry) == "executing"
    tasks = runtime.latest_tasks(run)
    assert sum(item.status == "running" for item in tasks.values()) == 3
    for item in tasks.values():
        if item.status == "running":
            drain(item.job_id)
    assert runtime.advance(run, registry) == "attention"
    assert tasks["one"].status == tasks["three"].status == "success", [(x.queue_phase, x.error_message) for x in ApiTask.query.all()]
    assert tasks["bad"].error["category"] == "content_policy"
    assert tasks["clip"].status == "pending" and ApiTask.query.count() == 3


def test_approved_upload_bytes_cannot_change_before_node_submission(app_ctx, monkeypatch):
    from tests.test_v3_workspace import image_attachment
    source = image_attachment()
    run, _root, ctx = make_context(ids=[source.artifact_id], text="修复照片")
    write_workspace("brief", "brief", brief(attachments=[{"attachment_id": source.artifact_id,
        "kind": "image", "role": "identity_ref", "description": "A cat", "reason": "Preserve identity"}]), ctx)
    node = image_node()
    node["inputs"].update(mode="i2i", reference_artifact_ids=[{"artifact": source.artifact_id}])
    node["model_id"] = "wan2.7-image"
    run, version, registry = setup([node], run=run)
    runtime.begin(run, version, registry=registry)
    StorageService.resolve(source.file_path).write_bytes(b"changed after approval")
    monkeypatch.setattr(JobRunService, "start", lambda *_a, **_k: pytest.fail("Changed approved input was submitted"))
    assert runtime.advance(run, registry) == "attention"
    assert runtime.latest_tasks(run)["image"].error["code"] == "PLAN_INPUT_CHANGED"
    assert ToolInvocation.query.count() == 0


@pytest.mark.parametrize("operation", ["reference", "edit", "extend"])
def test_future_generated_video_can_feed_wan3_with_real_media_and_full_i_plus_g(app_ctx, monkeypatch, operation):
    import subprocess
    from app.adapters.mock import MockAdapter
    from app.services.video_compression_service import VideoCompressionService
    app_ctx.config.update(DEFAULT_R2V_FLASH_MODEL="wan3.0-video", R2V_FLASH_ENABLED=True)
    duration = 10 if operation == "extend" else 5
    inputs = {"operation": operation, "prompt": "Preserve the cat and gently continue its motion",
              "media": [{"type": "reference_video", "artifact_id": {"ref": "clip.video"}}]}
    if operation != "reference":
        inputs["source_artifact_id"] = {"ref": "clip.video"}
    transform = {"id": "transform", "tool": "transform_video", "inputs": inputs,
        "model_id": "wan3.0-video", "params": {"duration": duration, "resolution": "720P"},
        "rationale": "Use a validated generated source as the complete reference"}
    run, version, registry = setup([image_node(), video_node(), transform],
        deliverables=[{"kind": "video", "node_id": "transform", "output": "video"}])
    original = MockAdapter.download_outputs
    def valid_video(self, response, output_dir):
        paths = original(self, response, output_dir)
        if self.output_kind == "video":
            seconds = duration if self.model_id == "wan3.0-video" else 5
            subprocess.run([VideoCompressionService.resolve_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                "color=c=blue:s=256x256:r=24", "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", paths[0]],
                check=True, capture_output=True, timeout=60)
        return paths
    monkeypatch.setattr(MockAdapter, "download_outputs", valid_video)
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review", [(x.node_id, x.error) for x in runtime.latest_tasks(run).values()]
    tasks = runtime.latest_tasks(run)
    transformed = tasks["transform"]
    assert transformed.state["input_video_seconds"] == 5
    assert transformed.inputs["params"]["duration"] == duration
    assert transformed.inputs["media"][0]["artifact_id"] == tasks["clip"].output["video"]
    from app.models import ModelRegistry
    from app.tools.budget import estimate_model_cost
    model = ModelRegistry.query.filter_by(model_id="wan3.0-video").one()
    assert transformed.estimated_cost == estimate_model_cost(model, transformed.inputs["params"], input_video_seconds=5)
    assert ApiTask.query.count() == 3


def test_job_link_commit_before_binding_is_resumed_without_creating_another_job(app_ctx, monkeypatch):
    run, version, registry = setup()
    runtime.begin(run, version, registry=registry)
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    original = policy.bind_job
    with monkeypatch.context() as patch:
        patch.setattr(policy, "bind_job", lambda *_a, **_k: (_ for _ in ()).throw(KeyboardInterrupt("lost before binding")))
        with pytest.raises(KeyboardInterrupt):
            runtime.advance(run, registry)
    db.session.rollback()
    assert Job.query.count() == 1 and ApiTask.query.count() == 0
    assert ToolInvocation.query.one().job_id is not None
    assert drain_plan(run, registry) == "awaiting_result_review"
    assert Job.query.count() == ApiTask.query.count() == ToolInvocation.query.count() == 1


def test_local_composition_commit_gap_reuses_original_artifact_and_zero_cost(app_ctx, monkeypatch):
    nodes = [image_node(), video_node(), {"id": "joined", "tool": "compose_video", "inputs": {
        "video_artifact_ids": [{"ref": "clip.video"}]}, "rationale": "Compose the final movie"}]
    run, version, registry = setup(nodes, deliverables=[{"kind": "video", "node_id": "joined", "output": "artifact_id"}])
    runtime.begin(run, version, registry=registry)
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    original = policy.bind_job
    def interrupted(ctx, job):
        original(ctx, job)
        if ctx.tool_name == "compose_video":
            raise KeyboardInterrupt("lost after local artifact commit")
    with monkeypatch.context() as patch:
        patch.setattr(policy, "bind_job", interrupted)
        with pytest.raises(KeyboardInterrupt):
            drain_plan(run, registry)
    db.session.rollback()
    existing = Artifact.query.filter_by(artifact_type="composed_video").one().artifact_id
    before = BudgetGuard.spent(run.run_id)
    assert drain_plan(run, registry) == "awaiting_result_review"
    task = runtime.latest_tasks(run)["joined"]
    assert task.output["artifact_id"] == existing
    assert Artifact.query.filter_by(artifact_type="composed_video").count() == 1
    assert ApiTask.query.count() == 2 and BudgetGuard.spent(run.run_id) == before


def delivery_nodes():
    return [image_node(), video_node(),
        {"id": "joined", "tool": "compose_video", "inputs": {"video_artifact_ids": [{"ref": "clip.video"}]},
         "rationale": "Compose the approved clip"},
        {"id": "qc", "tool": "qc_video", "inputs": {"artifact_id": {"ref": "joined.artifact_id"},
         "video_artifact_ids": [{"ref": "clip.video"}]}, "rationale": "Check the approved duration"},
        {"id": "package", "tool": "package_story", "inputs": {"artifact_id": {"ref": "joined.artifact_id"}},
         "depends_on": ["qc"], "rationale": "Package the checked originals"}]


def test_short_provider_video_fails_qc_against_approved_duration(app_ctx, monkeypatch):
    from pathlib import Path
    from app.adapters.mock import MockAdapter
    from app.services.video_composition_service import VideoCompositionService
    original = MockAdapter.download_outputs
    def short_video(self, response, output_dir):
        paths = original(self, response, output_dir)
        if self.output_kind == "video":
            VideoCompositionService._materialize_mock(Path(paths[0]), 2, "short provider output", 0)
        return paths
    monkeypatch.setattr(MockAdapter, "download_outputs", short_video)
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    run, version, registry = setup(delivery_nodes(), deliverables=[{"kind": "package", "node_id": "package", "output": "artifact_id"}])
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "attention"
    tasks = runtime.latest_tasks(run)
    assert tasks["clip"].status == tasks["joined"].status == "success"
    assert tasks["qc"].error["code"] == "PLAN_QC_FAILED" and tasks["package"].status == "pending"
    assert tasks["qc"].error["category"] == "qc_failed"
    assert tasks["qc"].error["submission_state"] == "not_submitted" and tasks["qc"].error["recovery_action"] == "replan"
    receipt = ToolInvocation.query.filter_by(tool_name="qc_video").one().output_payload
    checks = {item["code"]: item["passed"] for item in receipt["checks"]}
    assert checks["SOURCE_DURATION:" + tasks["clip"].output["video"]] is False
    assert checks["TOTAL_DURATION"] is False
    assert checks["MASTER_DECODE"] is True and ApiTask.query.count() == 2
    assert Artifact.query.filter_by(artifact_type="story_package").count() == 0


@pytest.mark.parametrize("changed", ["source", "master"])
def test_packaging_rechecks_qc_source_and_master_bytes(app_ctx, monkeypatch, changed):
    from app.plans import media
    original = media.package_story
    def changed_after_qc(data, ctx):
        run, _task, _version, _node = policy.task_context(ctx)
        tasks = runtime.latest_tasks(run)
        assert tasks["qc"].status == "success" and tasks["qc"].output["passed"] is True
        artifact_id = tasks["clip"].output["video"] if changed == "source" else data.artifact_id
        artifact = Artifact.query.filter_by(artifact_id=artifact_id).one()
        with StorageService.resolve(artifact.file_path).open("ab") as handle:
            handle.write(b"changed after the successful quality check")
        return original(data, ctx)
    monkeypatch.setattr(media, "package_story", changed_after_qc)
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    run, version, registry = setup(delivery_nodes(), deliverables=[{"kind": "package", "node_id": "package", "output": "artifact_id"}])
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "attention"
    task = runtime.latest_tasks(run)["package"]
    assert task.status == "failed" and task.error["code"] == "PLAN_INPUT_CHANGED"
    assert task.error["category"] == "invalid_parameters" and task.error["submission_state"] == "not_submitted"
    assert Artifact.query.filter_by(artifact_type="story_package").count() == 0
    assert not list(StorageService.root().rglob("*.zip")) and ApiTask.query.count() == 2
