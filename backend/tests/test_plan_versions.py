"""C2 persistence and concurrent editing against isolated SQLite only."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.agent import plan_versions as versions
from app.api import AppError
from app.extensions import db
from app.models import AgentPlanVersion, AgentRun, AgentShotTask, Artifact, ToolInvocation
from app.services.schema_service import SchemaService
from app.utils.ids import new_id
from tests.test_migrations import MIGRATIONS_DIR, _empty_app

PLAN = {"recipe": "story_video", "title": "Story", "shots": [
    {"shot_id": "s01", "character_ids": ["c01"], "summary": "Before", "end_frame": {"prompt": "End"}},
    {"shot_id": "s02", "character_ids": [], "summary": "Other"}]}
STORY = {"characters": [{"character_id": "c01", "lock_description": "Blue hair"}]}
CHECK = {"issues": [], "estimates": {"preview_credits": 3, "video_credits": 20, "total_credits": 23}}
INPUTS = {"prompt": "Blue hair portrait", "model_id": "wan2.7-image", "params": {}, "reference_artifact_ids": []}


def run(owner="local"):
    row = AgentRun(owner_id=owner, request_key=new_id("test"), request={"schema_version": 2, "attachment_ids": []})
    db.session.add(row)
    db.session.commit()
    return row


def save(row, **kwargs):
    return versions.create_version(row, PLAN, STORY, CHECK, **kwargs)


def artifact(row, h):
    job = h.make_job(paths=(), job_config={"skill": {"budget_scope": row.run_id}})
    output = Artifact(job=job, file_path="test.png", file_name="test.png", artifact_type="first_frame_image")
    db.session.add(output)
    db.session.commit()
    return output


def test_immutable_snapshots_and_current_version_survive_restart(app_ctx):
    row = run()
    plan, story, check = deepcopy(PLAN), deepcopy(STORY), deepcopy(CHECK)
    first = versions.create_version(row, plan, story, check)
    plan["shots"][0]["summary"] = "Mutated input"
    story["characters"][0]["lock_description"] = "Changed"
    check["issues"].append({"code": "INVALID"})
    assert first.plan["shots"][0]["summary"] == "Before"
    exported = first.to_dict()
    exported["plan"]["shots"][0]["summary"] = "Mutated output"
    assert first.plan["shots"][0]["summary"] == "Before"
    second = save(row, author="user", base_version=1)
    assert (first.version, second.version, second.parent_version) == (1, 2, 1)
    row_id = row.run_id
    db.session.remove()
    row = AgentRun.query.filter_by(run_id=row_id).one()
    assert row.snapshot["plan_version"] == 2
    assert versions.current_version(row).version == 2
    first = versions.get_version(row, 1)
    assert first.story_package == STORY
    first.plan = {"changed": True}
    with pytest.raises(ValueError, match="immutable"):
        db.session.commit()
    db.session.rollback()
    assert versions.get_version(row, 1).plan["title"] == "Story"


def test_operation_replay_keeps_latest_pointer_and_rejects_changed_content(app_ctx):
    row = run()
    first = save(row, operation_key="initial")
    save(row, author="user", base_version=1, operation_key="edit1")
    assert save(row, operation_key="initial").id == first.id
    assert versions.current_version(row).version == row.snapshot["plan_version"] == 2
    with pytest.raises(AppError) as error:
        versions.create_version(row, {**PLAN, "title": "Other"}, STORY, CHECK, operation_key="initial")
    assert error.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert AgentPlanVersion.query.count() == 2


def test_version_conflict_keeps_existing_plan(app_ctx):
    row = run()
    save(row)
    with pytest.raises(AppError) as error:
        save(row, author="user", base_version=0)
    assert error.value.code == "PLAN_VERSION_CONFLICT"
    assert error.value.payload["current_version"] == 1
    assert AgentPlanVersion.query.count() == 1
    with pytest.raises(AppError):
        versions.require_current_version(row, 2)
    assert versions.require_current_version(row, 1).version == 1


@pytest.mark.parametrize("optimistic", [True, False])
def test_simultaneous_edits_are_atomic(app, optimistic):
    with app.app_context():
        row = run()
        save(row)
        run_id = row.run_id
    barrier = Barrier(2)

    def edit():
        with app.app_context():
            row = AgentRun.query.filter_by(run_id=run_id).one()
            barrier.wait(timeout=10)
            try:
                return save(row, author="user", base_version=1 if optimistic else None).version
            except AppError as error:
                return error.code
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = sorted(map(str, pool.map(lambda _: edit(), range(2))))
    assert result == (["2", "PLAN_VERSION_CONFLICT"] if optimistic else ["2", "3"])
    with app.app_context():
        assert AgentPlanVersion.query.count() == (2 if optimistic else 3)


def test_version_and_task_lookups_are_run_scoped(app_ctx):
    first, other = run(), run()
    save(first)
    with pytest.raises(AppError) as error:
        versions.get_version(other, 1)
    assert error.value.code == "PLAN_VERSION_NOT_FOUND"
    assert versions.current_version(other) is None
    save(other)
    task = versions.create_task(first, 1, "keyframe", "s01", INPUTS)
    with pytest.raises(AppError) as error:
        versions.update_task(other, task, status="running")
    assert error.value.code == "INVALID_REFERENCE"
    assert versions.latest_task(other, 1, "keyframe", "s01") is None


def test_task_resume_and_forced_retry_preserve_attempts(app_ctx, h):
    row = run()
    save(row)
    first = versions.create_task(row, 1, "keyframe", "s01", INPUTS, estimated_cost=2.5)
    assert versions.create_task(row, 1, "keyframe", "s01", INPUTS).id == first.id
    versions.update_task(row, first, status="failed", error={"code": "MOCK_FAILURE"})
    assert versions.create_task(row, 1, "keyframe", "s01", INPUTS).id == first.id
    second = versions.create_task(row, 1, "keyframe", "s01", INPUTS, force=True)
    assert second.attempt == 2
    output = artifact(row, h)
    versions.update_task(row, second, status="success", artifact_ids=[output.artifact_id], job_id=output.job.job_id)
    assert versions.latest_task(row, 1, "keyframe", "s01").id == second.id
    assert len(versions.list_tasks(row, 1)) == 1
    assert len(versions.list_tasks(row, 1, latest_only=False)) == 2
    assert first.error == {"code": "MOCK_FAILURE"}
    with pytest.raises(AppError, match="terminal"):
        versions.update_task(row, first, status="running")


def test_matching_success_reused_across_versions_but_not_runs(app_ctx, h):
    row = run()
    save(row)
    output = artifact(row, h)
    first = versions.create_task(row, 1, "keyframe", "s01", INPUTS)
    versions.update_task(row, first, status="success", artifact_ids=[output.artifact_id])
    save(row)
    reused = versions.create_task(row, 2, "keyframe", "s01", INPUTS)
    assert reused.id != first.id
    assert reused.status == "success" and reused.artifact_ids == first.artifact_ids
    other = run()
    save(other)
    assert versions.create_task(other, 1, "keyframe", "s01", INPUTS).status == "pending"
    assert AgentShotTask.query.count() == 3


def test_hash_covers_generation_inputs_and_changes_need_version(app_ctx):
    row = run()
    save(row)
    versions.create_task(row, 1, "keyframe", "s01", INPUTS)
    assert versions.inputs_hash(dict(reversed(list(INPUTS.items())))) == versions.inputs_hash(INPUTS)
    for field, value in (("prompt", "other"), ("model_id", "other"), ("params", {"size": "new"}),
                         ("reference_artifact_ids", ["ref"])):
        changed = {**INPUTS, field: value}
        assert versions.inputs_hash(changed) != versions.inputs_hash(INPUTS)
        with pytest.raises(AppError) as error:
            versions.create_task(row, 1, "keyframe", "s01", changed)
        assert error.value.code == "PLAN_VERSION_CONFLICT"
    assert AgentShotTask.query.count() == 1


def test_character_redo_only_marks_dependent_previews_stale(app_ctx, h):
    row = run()
    save(row)
    output = artifact(row, h)
    for kind, target in (("character", "c01"), ("keyframe", "s01"), ("end_frame", "s01"), ("keyframe", "s02")):
        task = versions.create_task(row, 1, kind, target, INPUTS)
        versions.update_task(row, task, status="success", artifact_ids=[output.artifact_id])
    changed = versions.invalidate_character_keyframes(row, 1, "c01")
    assert {(item.target_type, item.target_id) for item in changed} == {("keyframe", "s01"), ("end_frame", "s01")}
    assert versions.latest_task(row, 1, "keyframe", "s02").status == "success"
    assert versions.latest_task(row, 1, "character", "c01").status == "success"
    assert all(item.artifact_ids == [output.artifact_id] for item in changed)
    assert AgentShotTask.query.count() == 4 and ToolInvocation.query.count() == 0
    with pytest.raises(AppError, match="terminal"):
        versions.update_task(row, changed[0], status="success")


def test_expected_hash_invalidates_only_changed_attempt(app_ctx):
    row = run()
    save(row)
    for target in ("s01", "s02"):
        versions.create_task(row, 1, "keyframe", target, INPUTS)
    changed = versions.mark_stale(row, 1, expected_hashes={
        ("keyframe", "s01"): "changed", ("keyframe", "s02"): versions.inputs_hash(INPUTS)})
    assert [item.target_id for item in changed] == ["s01"]
    assert versions.latest_task(row, 1, "keyframe", "s02").status == "pending"


@pytest.mark.parametrize("kind,target", [("invalid_target", "s01"), ("character", "missing"),
    ("end_frame", "s02"), ("video", "missing"), ("tail_frame", "missing")])
def test_unknown_targets_rejected(app_ctx, kind, target):
    row = run()
    save(row)
    with pytest.raises(AppError):
        versions.create_task(row, 1, kind, target, INPUTS)
    assert AgentShotTask.query.count() == 0


@pytest.mark.parametrize("kind,inputs", [
    ("video", {"first_frame_artifact_id": "frame", "last_frame_artifact_id": None,
               "prompt": "Approved motion", "model_id": "wan2.7-i2v", "params": {"duration": 5}}),
    ("tail_frame", {"video_artifact_id": "video", "position": "last", "timestamp_sec": None}),
])
def test_production_target_types_are_persisted_for_existing_shots(app_ctx, kind, inputs):
    row = run()
    save(row)
    task = versions.create_task(row, 1, kind, "s01", inputs)
    assert task.target_type == kind and task.target_id == "s01" and task.status == "pending"
    assert versions.latest_task(row, 1, kind, "s01").id == task.id
    assert versions.create_task(row, 1, kind, "s01", inputs).id == task.id
    assert AgentShotTask.query.count() == 1 and ToolInvocation.query.count() == 0


def test_cross_run_artifact_job_and_invocation_rejected(app_ctx, h):
    row, other = run(), run()
    save(row)
    output = artifact(other, h)
    ledger = ToolInvocation(tool_name="generate_image", caller_role="production", idempotency_key="foreign",
                            budget_scope=other.run_id, job_id=output.job.id)
    db.session.add(ledger)
    db.session.commit()
    task = versions.create_task(row, 1, "keyframe", "s01", INPUTS)
    for values in ({"artifact_ids": [output.artifact_id]}, {"job_id": output.job.job_id},
                   {"invocation_id": ledger.invocation_id}):
        with pytest.raises(AppError) as error:
            versions.update_task(row, task, **values)
        assert error.value.code == "INVALID_REFERENCE"
    assert task.status == "pending" and task.artifact_ids == []


def test_empty_success_and_nonfinite_cost_rejected(app_ctx):
    row = run()
    save(row)
    task = versions.create_task(row, 1, "keyframe", "s01", INPUTS)
    with pytest.raises(AppError):
        versions.update_task(row, task, status="success")
    for cost in (-1, float("nan"), float("inf"), True):
        with pytest.raises(AppError):
            versions.create_task(row, 1, "keyframe", "s02", INPUTS, estimated_cost=cost)
    with pytest.raises(AppError):
        versions.inputs_hash({"param": float("nan")})


def test_repeatable_migration_repair_and_downgrade(tmp_path):
    app = _empty_app(tmp_path)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
        upgrade(directory=MIGRATIONS_DIR)
        assert inspect(db.engine).has_table("agent_plan_versions")
        assert inspect(db.engine).has_table("agent_shot_tasks")
        uniques = inspect(db.engine).get_unique_constraints("agent_shot_tasks")
        assert any(item["column_names"] == ["run_id", "plan_version", "target_type", "target_id", "attempt"] for item in uniques)
        downgrade(directory=MIGRATIONS_DIR, revision="20261018_001")
        assert not inspect(db.engine).has_table("agent_shot_tasks")
        assert {"agent_plan_versions", "agent_shot_tasks"} <= set(SchemaService.ensure_compatible_schema())
        assert not {"agent_plan_versions", "agent_shot_tasks"} & set(SchemaService.ensure_compatible_schema())
        db.session.remove()
        upgrade(directory=MIGRATIONS_DIR)
        assert db.session.execute(text("SELECT version_num FROM alembic_version")).scalar() == "20261018_004"
        db.session.remove()
        db.engine.dispose()


def test_completed_attempt_never_overwrites_previous_artifact(app_ctx, h):
    row = run()
    save(row)
    first, replacement = artifact(row, h), artifact(row, h)
    task = versions.create_task(row, 1, "keyframe", "s01", INPUTS)
    versions.update_task(row, task, status="success", artifact_ids=[first.artifact_id])
    with pytest.raises(AppError, match="immutable"):
        versions.update_task(row, task, artifact_ids=[replacement.artifact_id])
    assert task.artifact_ids == [first.artifact_id]
    versions.mark_stale(row, 1, target_type="keyframe", target_ids={"s01"})
    assert task.artifact_ids == [first.artifact_id]
