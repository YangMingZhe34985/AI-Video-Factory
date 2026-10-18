"""D1 acceptance: actual Mock Jobs across durable dependency scheduling."""
from copy import deepcopy

import pytest

from app.agent import plan_versions as versions
from app.agent import preview_production as previews
from app.agent.production_engine import begin_production, tick_production
from app.agent.production_plan import normalized_plan
from app.agent.production_state import dependencies, latest_tasks, usable_artifact
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ApiTask, Job, ToolInvocation
from app.services.job_run_service import JobRunService
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from tests.test_story_previews import setup, create_keyframes

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
                               AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_MAX_PARALLEL_SHOTS=3)


def ten_shot_story(monkeypatch, *, bridge=False):
    row, old, registry = setup(characters=False)
    pattern = ["start", "tail_frame", "independent", "tail_frame", "hard_cut",
               "independent", "tail_frame", "hard_cut", "independent", "tail_frame"]
    plan = deepcopy(old.plan)
    plan["target_duration_sec"], plan["shots"], plan["scenes"] = 50, [], []
    scene = 0
    for index, transition in enumerate(pattern):
        if transition != "tail_frame":
            scene += 1
            plan["scenes"].append({"scene_id": f"scene{scene}", "location": f"城市地点{scene}",
                                   "time_of_day": "清晨", "summary": "寻访街区"})
        shot = deepcopy(old.plan["shots"][0])
        shot.update(shot_id=f"s{index + 1:02}", order=index + 1, scene_id=f"scene{scene}",
                    duration_sec=5, transition_in=transition, summary=f"镜头{index + 1}穿行城市")
        shot["motion"]["params"]["duration"] = 5
        if transition == "tail_frame":
            shot["first_frame"] = {"method": "tail_frame", "image_mode": None, "model_id": None,
                                   "prompt": "", "reference_artifact_ids": []}
        if bridge and index == 8:
            shot["transition_in"] = "keyframe_bridge"
            shot["motion"]["mode"] = "first_last_frame"
            shot["end_frame"] = deepcopy(shot["first_frame"])
        plan["shots"].append(shot)
    snapshot = deepcopy(row.snapshot)
    snapshot["request_spec"]["target_duration_sec"] = 50
    row.snapshot = snapshot
    db.session.commit()
    version = versions.create_version(row, normalized_plan(plan), old.story_package,
                                     {"issues": [], "estimates": {"video_credits": 50}}, author="user")
    with monkeypatch.context() as patch:
        patch.setattr(JobRunService, "start", JobRunService.run_inline)
        create_keyframes(row, version, registry)
    row.status = "storyboard_approved"
    db.session.commit()
    return row, version, registry


def deferred_jobs(monkeypatch, row, version):
    launched, pending = [], set()
    deps = dependencies(version)
    def start(job_id, *_args, **_kwargs):
        job = Job.query.filter_by(job_id=job_id).one()
        sid = job.config["agent_story_production"]["shot_id"]
        if deps[sid]:
            source = deps[sid][0]
            assert usable_artifact(versions.latest_task(row, version.version, "video", source))
            assert usable_artifact(versions.latest_task(row, version.version, "tail_frame", source))
        launched.append((sid, job_id))
        pending.add(job_id)
    monkeypatch.setattr(JobRunService, "start", start)
    monkeypatch.setattr(JobRunService, "is_running_in_thread", lambda job_id: job_id in pending)
    return launched, pending


def complete_pending(pending):
    for job_id in list(pending):
        from app.agent.production_policy import authorized_job_dispatch
        job = Job.query.filter_by(job_id=job_id).one()
        # This helper simulates the executor of an already-admitted dispatch.
        with authorized_job_dispatch(job, "run_full"):
            JobRunService.run_inline(job_id, "run_full")
        pending.remove(job_id)


def test_ten_shots_follow_real_dependencies_and_parallel_limit(app_ctx, monkeypatch):
    row, version, registry = ten_shot_story(monkeypatch)
    launched, pending = deferred_jobs(monkeypatch, row, version)
    assert begin_production(row, version) == "producing"
    assert tick_production(row, registry) == "producing"
    assert [sid for sid, _ in launched] == ["s01", "s03", "s05"]
    for _round in range(15):
        tasks = latest_tasks(row, version)
        assert sum(item.status == "running" for item in tasks.values()) <= 3
        complete_pending(pending)
        status = tick_production(row, registry)
        if status != "producing":
            break
    assert status == "awaiting_video_review"
    assert len(launched) == len({sid for sid, _ in launched}) == 10
    assert ApiTask.query.filter_by(branch_key="i2v").count() == 10
    assert ToolInvocation.query.filter_by(tool_name="animate_shot", budget_scope=row.run_id).count() == 10
    assert ToolInvocation.query.filter_by(tool_name="extract_frame", budget_scope=row.run_id).count() == 4
    assert len(latest_tasks(row, version)) == 10
    assert all(usable_artifact(item) for item in latest_tasks(row, version).values())
    assert sum(item.estimated_cost for item in ToolInvocation.query.filter_by(tool_name="animate_shot")) == 50


def test_restart_from_database_retains_submissions_and_completed_results(app_ctx, monkeypatch):
    row, version, registry = ten_shot_story(monkeypatch)
    launched, pending = deferred_jobs(monkeypatch, row, version)
    begin_production(row, version)
    tick_production(row, registry)
    ids = [job_id for _sid, job_id in launched]
    complete_pending(pending)
    before = BudgetGuard.spent(row.run_id)
    run_id, number = row.run_id, version.version
    db.session.remove()
    row = AgentRun.query.filter_by(run_id=run_id).one()
    version = versions.get_version(row, number)
    registry = build_default_registry()
    tick_production(row, registry)
    assert [job_id for _sid, job_id in launched[:3]] == ids
    assert len(launched) == 6
    assert len({job_id for _sid, job_id in launched}) == 6
    assert BudgetGuard.spent(row.run_id) == before + 15
    for job_id in ids:
        job = Job.query.filter_by(job_id=job_id).one()
        assert ApiTask.query.filter_by(job_id=job.id).count() == 1
    for _round in range(15):
        complete_pending(pending)
        if tick_production(row, registry) != "producing":
            break
    count, spent = ToolInvocation.query.count(), BudgetGuard.spent(row.run_id)
    assert tick_production(row, registry) == "awaiting_video_review"
    assert ToolInvocation.query.count() == count and BudgetGuard.spent(row.run_id) == spent
    assert len(launched) == 10


@pytest.mark.parametrize("mq", [False, True])
def test_mq_and_thread_paths_share_jobs_ledger_and_tail_inputs(app_ctx, monkeypatch, mq):
    row, version, registry = ten_shot_story(monkeypatch)
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq)
    if not mq:
        monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    begin_production(row, version)
    for _round in range(20):
        status = tick_production(row, registry)
        if status != "producing":
            break
        if mq:
            from tests.test_shared_queue import drain
            for item in latest_tasks(row, version).values():
                if item.status == "running":
                    assert drain(item.job_id).status == "success"
    assert status == "awaiting_video_review"
    rows = ToolInvocation.query.filter_by(budget_scope=row.run_id, tool_name="animate_shot").all()
    assert len(rows) == 10 and sum(item.estimated_cost for item in rows) == 50
    for item in latest_tasks(row, version).values():
        assert item.status == "success" and usable_artifact(item)
        job = Job.query.filter_by(job_id=item.job_id).one()
        api = ApiTask.query.filter_by(job_id=job.id).one()
        assert api.model_id == "wan2.7-i2v"
        assert api.request_payload["parameters"]["duration"] == 5
    chained = versions.latest_task(row, version.version, "video", "s02")
    invoice = ToolInvocation.query.filter_by(invocation_id=chained.invocation_id).one()
    tail = versions.latest_task(row, version.version, "tail_frame", "s01")
    assert invoice.input_payload["first_frame_artifact_id"] == tail.artifact_ids[0]


def test_no_submission_before_explicit_start_and_disabled_flag_blocks(app_ctx, monkeypatch):
    row, version, registry = ten_shot_story(monkeypatch)
    with pytest.raises(AppError) as error:
        tick_production(row, registry)
    assert error.value.code == "PRODUCTION_DISABLED"
    app_ctx.config["AGENT_STORY_PRODUCTION_ENABLED"] = False
    with pytest.raises(AppError) as error:
        begin_production(row, version)
    assert error.value.code == "PRODUCTION_DISABLED"
    assert ToolInvocation.query.filter_by(tool_name="animate_shot").count() == 0


def test_approved_first_last_frames_do_not_wait_for_unrelated_video(app_ctx, monkeypatch):
    app_ctx.config.update(AGENT_ENABLE_KEYFRAME_BRIDGE=True, AGENT_MAX_PARALLEL_SHOTS=10)
    row, version, registry = ten_shot_story(monkeypatch, bridge=True)
    launched, pending = deferred_jobs(monkeypatch, row, version)
    begin_production(row, version)
    assert tick_production(row, registry) == "producing"
    assert [sid for sid, _ in launched] == ["s01", "s03", "s05", "s06", "s08", "s09"]
    item = versions.latest_task(row, version.version, "video", "s09")
    invoice = ToolInvocation.query.filter_by(invocation_id=item.invocation_id).one()
    end = versions.latest_task(row, version.version, "end_frame", "s09")
    assert invoice.input_payload["last_frame_artifact_id"] == end.artifact_ids[0]
    complete_pending(pending)
    for _round in range(10):
        status = tick_production(row, registry)
        if status != "producing":
            break
        complete_pending(pending)
    assert status == "awaiting_video_review"
