"""D1/D2/D3 recovery integration with real durable tasks and offline Mock Jobs."""

from copy import deepcopy

import pytest

from app.adapters.mock import MockAdapter
from app.agent import plan_versions as versions
from app.agent import production_engine as engine
from app.agent import production_repair as repair
from app.agent.production_state import latest_tasks, usable_artifact, video_inputs
from app.agent.production_view import public_production
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, AgentShotTask, ApiTask, Job, JobNodeRun, ToolInvocation
from app.services.error_detail_service import ErrorDetailService
from app.services.job_run_service import JobRunService
from app.services.storage_service import StorageService
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from tests.test_story_media import private_artifact, task as media_task
from tests.test_story_previews import setup

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
                               AGENT_STORY_PRODUCTION_ENABLED=True)


@pytest.fixture
def inline_jobs(monkeypatch):
    monkeypatch.setattr(JobRunService, "start", lambda job_id, run_type, node_key=None, force=False, restart=False:
                        JobRunService.run_inline(job_id, run_type, node_key=node_key, force=force, restart=restart))


def prepared(count=1, allowance=60):
    run, old, registry = setup(characters=False)
    plan = deepcopy(old.plan)
    template = deepcopy(plan["shots"][0])
    plan["shots"] = []
    for index in range(count):
        shot = deepcopy(template)
        shot.update(shot_id=f"s{index + 1:02d}", order=index + 1, transition_in="independent" if index else "start",
                    depends_on=[], duration_sec=5)
        shot["motion"]["params"]["duration"] = 5
        plan["shots"].append(shot)
    plan["target_duration_sec"] = count * 5
    version = versions.create_version(run, plan, old.story_package, old.check)
    run.request = {**run.request, "budget_limit": 500}
    run.status = "producing"
    run.snapshot = {**run.snapshot, "production": {"plan_version": version.version, "approved_version": version.version,
                                                   "status": "producing", "repair_budget_credits": allowance}}
    db.session.commit()
    for shot in plan["shots"]:
        media_task(run, version, "keyframe", shot["shot_id"], {"source": shot["shot_id"]}, private_artifact(run))
    return run, version, registry


def settle(run, registry, limit=10):
    for _ in range(limit):
        status = engine.tick_production(run, registry)
        run.status = status
        db.session.commit()
        if status != "producing":
            return status
    pytest.fail(f"Production did not settle: {run.snapshot}")


def fail_submit_once(monkeypatch, code="API_TASK_FAILED", status=429, provider_code=None):
    original = MockAdapter.submit
    calls = []
    def submit(self, payload):
        calls.append(payload)
        if len(calls) == 1:
            if status is None:
                raise ConnectionError("Paid POST response was lost")
            raise AppError(code, "Injected deterministic provider rejection", status,
                           payload={"response": {"code": provider_code}} if provider_code else {})
        return original(self, payload)
    monkeypatch.setattr(MockAdapter, "submit", submit)
    return calls


def test_automatic_repair_shares_running_slot_with_unrelated_video(app_ctx, h, monkeypatch):
    app_ctx.config["AGENT_MAX_PARALLEL_SHOTS"] = 1
    run, version, registry = prepared(3)
    for index, shot in enumerate(version.plan["shots"]):
        job = h.make_job(paths=(), job_config={"skill": {"budget_scope": run.run_id}})
        job.status = "failed" if index < 2 else "running"
        node = JobNodeRun(job_id=job.id, node_key="submit_i2v", status="failed")
        db.session.add(node)
        db.session.flush()
        node.output_snapshot = {"error_detail": ErrorDetailService.build(job=job, node_run=node,
            error=AppError("API_TASK_FAILED", "429 rejected", 429))}
        data = video_inputs(run, version, shot)
        target = versions.create_task(run, version.version, "video", shot["shot_id"], data, estimated_cost=5)
        versions.update_task(run, target, status="failed" if index < 2 else "running", job_id=job.job_id)
    monkeypatch.setattr(engine, "_poll", lambda *args: None)
    launched = []
    def submit(_run, target, data, _registry):
        launched.append(target.id)
        versions.update_task(_run, target, status="running")
    monkeypatch.setattr(engine, "_submit", submit)
    engine.tick_production(run, registry)
    assert launched == []
    assert sum(task.status == "running" for task in latest_tasks(run, version).values()) == 1


def test_unknown_submission_stops_only_one_shot_and_never_replays_paid_post(app_ctx, inline_jobs, monkeypatch):
    run, version, registry = prepared(2)
    calls = fail_submit_once(monkeypatch, status=None)
    assert settle(run, registry) == "production_attention"
    tasks = latest_tasks(run, version)
    assert tasks["s01"].status == "failed" and tasks["s02"].status == "success"
    assert tasks["s01"].error["category"] == "submit_unknown"
    for _ in range(3):
        engine.tick_production(run, registry)
    assert len(calls) == 2
    assert len(versions.list_tasks(run, version.version, latest_only=False)) == 4
    assert ToolInvocation.query.filter_by(tool_name="animate_shot", budget_scope=run.run_id).count() == 2


def test_free_missing_download_preserves_paid_submission_and_repair_cost(app_ctx, inline_jobs, monkeypatch):
    run, version, registry = prepared()
    original = MockAdapter.submit
    calls = []
    monkeypatch.setattr(MockAdapter, "submit", lambda self, payload: calls.append(payload) or original(self, payload))
    assert settle(run, registry) == "awaiting_video_review", {"snapshot": run.snapshot, "tasks": [t.to_dict() for t in latest_tasks(run, version).values()]}
    old = latest_tasks(run, version)["s01"]
    api = ApiTask.query.filter_by(job_id=Job.query.filter_by(job_id=old.job_id).one().id).one()
    provider_id, invocation_id = api.provider_task_id, old.invocation_id
    artifact = usable_artifact(old)
    StorageService.resolve(artifact.file_path).unlink()
    before = BudgetGuard.spent(run.run_id)
    assert settle(run, registry) == "awaiting_video_review", {"snapshot": run.snapshot, "tasks": [t.to_dict() for t in latest_tasks(run, version).values()]}
    current = latest_tasks(run, version)["s01"]
    assert current.attempt == 2 and current.invocation_id == invocation_id and current.job_id == old.job_id
    assert len(calls) == 1 and ApiTask.query.count() == 1 and api.provider_task_id == provider_id
    assert usable_artifact(current)
    assert BudgetGuard.spent(run.run_id) == before
    estimates = public_production(run)["estimates"]
    assert estimates["repair_spent_credits"] == 0
    assert estimates["video_spent_credits"] == 5


def test_zero_byte_video_is_not_a_successful_download(app_ctx):
    run, version, registry = prepared()
    artifact = private_artifact(run, "i2v_video", b"")
    target = media_task(run, version, "video", "s01", {}, artifact)
    assert usable_artifact(target) is None


def test_paid_retry_receipt_resumes_after_crash_before_new_attempt(app_ctx, inline_jobs, monkeypatch):
    run, version, registry = prepared()
    calls = fail_submit_once(monkeypatch)
    engine.tick_production(run, registry)
    original_create = versions.create_task
    def interrupted(*args, **kwargs):
        if kwargs.get("force"):
            raise AppError("MOCK_CRASH", "after reservation before allocation", 503)
        return original_create(*args, **kwargs)
    monkeypatch.setattr(versions, "create_task", interrupted)
    with pytest.raises(AppError, match="after reservation"):
        engine.tick_production(run, registry)
    receipt = next(iter(run.snapshot["production_repairs"].values()))
    assert receipt["status"] == "claimed" and not receipt.get("replacement_task_id")
    assert len(calls) == 1
    run_id = run.run_id
    db.session.remove()
    run = AgentRun.query.filter_by(run_id=run_id).one()
    version = versions.current_version(run)
    monkeypatch.setattr(versions, "create_task", original_create)
    assert settle(run, registry) == "awaiting_video_review", {"snapshot": run.snapshot, "tasks": [t.to_dict() for t in latest_tasks(run, version).values()]}
    assert len(calls) == 2
    assert latest_tasks(run, version)["s01"].attempt == 2
    assert len(run.snapshot["production_repairs"]) == 1
    assert ToolInvocation.query.filter_by(tool_name="animate_shot", budget_scope=run.run_id).count() == 2


def test_content_rewrite_changes_only_failed_shot_and_is_not_repeated(app_ctx, inline_jobs, monkeypatch):
    run, version, registry = prepared(2)
    calls = fail_submit_once(monkeypatch, status=400, provider_code="DataInspectionFailed")
    assert settle(run, registry) == "awaiting_video_review", {"snapshot": run.snapshot, "tasks": [t.to_dict() for t in latest_tasks(run, version).values()]}
    tasks = latest_tasks(run, version)
    assert tasks["s01"].attempt == 2 and tasks["s02"].attempt == 1
    assert len(calls) == 3
    receipt = next(iter(run.snapshot["production_repairs"].values()))
    assert receipt["status"] == "completed" and receipt["category"] == "content_policy"
    assert receipt["motion_prompt"] != version.plan["shots"][0]["motion"]["prompt"]
    assert ToolInvocation.query.filter_by(tool_name="repair_motion_prompt", budget_scope=run.run_id).count() == 1
    old_spent = BudgetGuard.spent(run.run_id)
    engine.tick_production(run, registry)
    assert BudgetGuard.spent(run.run_id) == old_spent and len(calls) == 3



def test_catalog_price_increase_cannot_exceed_automatic_repair_allowance(app_ctx, inline_jobs, monkeypatch):
    from app.services.model_service import ModelService
    run, version, registry = prepared(allowance=5)
    calls = fail_submit_once(monkeypatch)
    engine.tick_production(run, registry)
    model = ModelService.get_model("wan2.7-i2v")
    model.capabilities = {**model.capabilities, "pricing": {"unit": "second", "credits_per_unit": 10}}
    db.session.commit()
    assert settle(run, registry) == "production_attention"
    receipt = next(iter(run.snapshot["production_repairs"].values()))
    assert receipt["reason"] == "REPAIR_BUDGET_EXCEEDED"
    assert receipt["estimated_cost"] == 50 and receipt["reserved_credits"] == 0
    assert latest_tasks(run, version)["s01"].attempt == 1 and len(calls) == 1



def test_paid_job_receipt_recovers_after_crash_before_task_link(app_ctx, inline_jobs, monkeypatch):
    run, version, registry = prepared()
    original_submit = MockAdapter.submit
    calls = []
    monkeypatch.setattr(MockAdapter, "submit", lambda self, payload: calls.append(payload) or original_submit(self, payload))
    original_update = versions.update_task
    crashed = []
    def interrupted(_run, target, **values):
        if target.target_type == "video" and values.get("invocation_id") and not crashed:
            crashed.append(target.id)
            raise RuntimeError("Crash after Job + ToolInvocation commit before task linkage")
        return original_update(_run, target, **values)
    monkeypatch.setattr(versions, "update_task", interrupted)
    with pytest.raises(RuntimeError, match="before task linkage"):
        engine.tick_production(run, registry)
    assert len(calls) == 1
    monkeypatch.setattr(versions, "update_task", original_update)
    run_id = run.run_id
    db.session.remove()
    run = AgentRun.query.filter_by(run_id=run_id).one()
    version = versions.current_version(run)
    assert settle(run, registry) == "awaiting_video_review"
    assert len(calls) == 1 and latest_tasks(run, version)["s01"].attempt == 1
    assert ToolInvocation.query.filter_by(tool_name="animate_shot", budget_scope=run_id).count() == 1


def test_content_repair_then_rate_limit_preserves_revised_prompt_and_two_repair_cap(app_ctx, inline_jobs, monkeypatch):
    run, version, registry = prepared()
    original = MockAdapter.submit
    calls = []
    def submitted(self, payload):
        calls.append(payload)
        if len(calls) == 1:
            raise AppError("API_TASK_FAILED", "Content rejected", 400, payload={"response": {"code": "DataInspectionFailed"}})
        if len(calls) == 2:
            raise AppError("API_TASK_FAILED", "Rate limited before submission", 429)
        return original(self, payload)
    monkeypatch.setattr(MockAdapter, "submit", submitted)
    assert settle(run, registry) == "awaiting_video_review"
    assert len(calls) == 3
    tasks = versions.list_tasks(run, version.version, latest_only=False)
    videos = [item for item in tasks if item.target_type == "video"]
    assert [item.attempt for item in videos] == [1, 2, 3]
    payloads = [ToolInvocation.query.filter_by(invocation_id=item.invocation_id).one().input_payload for item in videos]
    assert payloads[1]["prompt"] == payloads[2]["prompt"] != payloads[0]["prompt"]
    assert ToolInvocation.query.filter_by(tool_name="repair_motion_prompt", budget_scope=run.run_id).count() == 1
    assert len(run.snapshot["production_repairs"]) == 2


def test_registry_rejection_is_not_an_unknown_submission(app_ctx, inline_jobs, monkeypatch):
    from app.agent import production_actions as actions
    from app.skills import registry as registry_module
    run, version, registry = prepared(2)
    real = registry_module.BudgetGuard
    calls = []

    class RejectFirst:
        @staticmethod
        def check(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise AppError("BUDGET_EXCEEDED", "Injected budget rejection before any Job", 402)
            return real.check(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(registry_module, "BudgetGuard", RejectFirst())
    assert settle(run, registry) == "production_attention"
    tasks = latest_tasks(run, version)
    assert tasks["s02"].status == "success"
    failed = tasks["s01"]
    assert failed.status == "failed" and failed.job_id is None
    assert failed.error["category"] == "permanent"
    assert failed.error["submission_state"] == "not_submitted" and failed.error["code"] == "BUDGET_EXCEEDED"
    rejected = ToolInvocation.query.filter_by(tool_name="animate_shot", budget_scope=run.run_id, status="rejected").one()
    assert rejected.job_id is None
    # The shot stays explicitly redoable instead of being frozen as unknown.
    run.status = "production_attention"
    db.session.commit()
    offer = actions.quote(run, {"shot_id": "s01", "base_version": version.version, "operation": "redo"})
    assert offer["estimated_credits"]["only"] is not None
