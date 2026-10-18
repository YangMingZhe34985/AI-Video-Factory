"""Phase C previews use only Mock image Jobs, durable receipts and isolated data."""

from copy import deepcopy
from dataclasses import replace
import time

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import update

from app.agent import plan_versions as versions
from app.agent import preview_production as previews
from app.agent.director_v2 import director_v2
from app.api import AppError
from app.extensions import db
from app.models import AgentPlanVersion, AgentRun, AgentShotTask, ApiTask, Artifact, Job, ToolInvocation
from app.services.artifact_service import ArtifactService
from app.services.job_run_service import JobRunService
from app.services.storage_service import StorageService
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from app.skills.spec import ToolContext
from tests.test_story_director import story_state

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
                               AGENT_VISION_MODEL="qwen3.7-plus")


def setup(characters=True):
    state = story_state(target=15)
    if not characters:
        state["story_package"]["characters"] = []
        for beat in state["story_package"]["story"]["beats"]:
            beat["character_ids"] = []
    result = director_v2(state)
    row = AgentRun.query.filter_by(run_id=state["run_id"]).one()
    row.snapshot = {"request_spec": state["request_spec"]}
    db.session.commit()
    plan = result["plan"]
    for shot in plan["shots"]:
        shot["first_frame"]["prompt"] = "手绘风格，静态画面：" + shot["summary"]
        shot["motion"]["prompt"] = "镜头缓慢前推"
    version = versions.create_version(row, plan, state["story_package"], {"issues": [], "estimates": plan["estimates"]})
    return row, version, build_default_registry()


def finish(row, version, registry):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        report = previews.poll_previews(row, version, registry)
        if report["complete"]:
            return report
        time.sleep(.05)
    raise AssertionError("Preview tasks did not finish")


def create_characters(row, version, registry):
    targets = previews.targets_for(version, "characters")
    previews.prepare_previews(row, version, targets=targets)
    previews.launch_previews(row, version, targets, registry)
    assert finish(row, version, registry) == {"complete": True, "failed": False}
    plan, story = previews.bind_character_references(row, version)
    return versions.create_version(row, plan, story, version.check, author="system")


def create_keyframes(row, version, registry):
    targets = previews.targets_for(version, "keyframes")
    previews.prepare_previews(row, version)
    previews.launch_previews(row, version, targets, registry)
    assert finish(row, version, registry) == {"complete": True, "failed": False}
    return previews.preview_view(row, version)


def test_generated_character_binds_all_keyframes_and_only_images_are_submitted(app_ctx):
    row, version, registry = setup()
    assert previews.preview_cost(row, version, previews.targets_for(version, "characters")) == 2
    with pytest.raises(AppError) as error:
        previews.planned_inputs(row, version, "keyframe", "s01")
    assert error.value.code == "PREVIEW_INCOMPLETE"
    version = create_characters(row, version, registry)
    character_id = version.story_package["characters"][0]["reference"]["artifact_ids"][0]
    assert all(character_id in shot["first_frame"]["reference_artifact_ids"] for shot in version.plan["shots"])
    view = create_keyframes(row, version, registry)
    assert all(item["status"] == "success" for item in view["keyframes"].values())
    assert view["characters"]["hero"]["artifact_id"] == character_id
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 4
    assert BudgetGuard.spent(row.run_id) == 9
    assert all(task.model_id in {"wan2.6-image", "wan2.7-image"} for task in ApiTask.query.all())
    assert all(job.config.get("agent_story_preview") for job in Job.query.filter(Job.strategy.like("skill:%")).all())
    assert previews.preview_cost(row, version, previews.targets_for(version)) == 0


def test_launch_replay_and_reopened_session_do_not_repeat_image_charges(app_ctx):
    row, version, registry = setup(characters=False)
    targets = previews.targets_for(version)
    previews.prepare_previews(row, version)
    previews.launch_previews(row, version, targets, registry)
    run_id, number = row.run_id, version.version
    db.session.remove()
    row = AgentRun.query.filter_by(run_id=run_id).one()
    version = versions.get_version(row, number)
    previews.launch_previews(row, version, targets, registry)
    assert finish(row, version, registry)["complete"]
    count = ToolInvocation.query.count()
    previews.prepare_previews(row, version)
    previews.launch_previews(row, version, targets, registry)
    assert ToolInvocation.query.count() == count == 4
    assert AgentShotTask.query.count() == 3


@pytest.mark.parametrize("entry", ["poll", "launch_replay", "recover"])
def test_finished_preview_is_not_recovered_from_a_stale_running_snapshot(app_ctx, monkeypatch, entry):
    row, version, registry = setup(characters=False)
    target = [("keyframe", "s01")]
    starts = []

    def start_inline(job_id, *args, **kwargs):
        starts.append(job_id)
        return JobRunService.run_inline(job_id, *args, **kwargs)

    monkeypatch.setattr(JobRunService, "start", start_inline)
    previews.prepare_previews(row, version, targets=target)
    previews.launch_previews(row, version, target, registry)
    task = versions.latest_task(row, version.version, *target[0])
    job = Job.query.filter_by(job_id=task.job_id).one()
    assert job.status == "success"
    assert ApiTask.query.filter_by(job_id=job.id).count() == 1
    job.status = "running"
    db.session.commit()
    completed = []

    def finish_before_liveness_check(job_id):
        if not completed:
            # The worker commits completion after recovery loaded a running
            # Job, but before it notices that the worker thread has exited.
            with db.engine.begin() as connection:
                connection.execute(update(Job).where(Job.id == job.id).values(status="success"))
            completed.append(job_id)
        return False

    monkeypatch.setattr(JobRunService, "is_running_in_thread", finish_before_liveness_check)
    if entry == "launch_replay":
        previews.launch_previews(row, version, target, registry)
    elif entry == "recover":
        previews.recover_job(job, row.run_id)
        assert not db.session().in_transaction()
    assert previews.poll_previews(row, version, registry) == {"complete": True, "failed": False}
    assert completed == starts == [job.job_id]
    assert ApiTask.query.filter_by(job_id=job.id).count() == 1
    assert Artifact.query.filter_by(job_id=job.id, artifact_type="first_frame_image").count() == 1
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 1
    assert BudgetGuard.spent(row.run_id) == 3


def test_preview_job_is_private_before_background_worker_starts(app_ctx, monkeypatch):
    row, version, registry = setup(characters=False)
    captured = []
    def capture(job_id, *_args, **_kwargs):
        captured.append(deepcopy(Job.query.filter_by(job_id=job_id).one().config))
    monkeypatch.setattr(JobRunService, "start", capture)
    targets = previews.targets_for(version)
    previews.prepare_previews(row, version)
    previews.launch_previews(row, version, targets, registry)
    assert len(captured) == 3
    assert all(item["agent_story_preview"]["run_id"] == row.run_id for item in captured)
    assert all(item["skill"]["budget_scope"] == row.run_id for item in captured)


def test_edit_marks_only_changed_keyframe_stale_without_submitting_jobs(app_ctx):
    row, version, registry = setup(characters=False)
    original = create_keyframes(row, version, registry)
    count, cost = ToolInvocation.query.count(), BudgetGuard.spent(row.run_id)
    plan = deepcopy(version.plan)
    plan["shots"][0]["first_frame"]["prompt"] += "，改为暮色"
    edited = versions.create_version(row, plan, version.story_package, version.check, author="user", base_version=version.version)
    previews.prepare_previews(row, edited)
    view = previews.preview_view(row, edited)
    assert view["keyframes"]["s01"]["stale"] is True
    assert view["keyframes"]["s01"]["artifact_id"] == original["keyframes"]["s01"]["artifact_id"]
    assert all(not item["stale"] for key, item in view["keyframes"].items() if key != "s01")
    previews.launch_previews(row, edited, previews.targets_for(edited), registry)
    assert ToolInvocation.query.count() == count
    assert BudgetGuard.spent(row.run_id) == cost


def test_forced_local_redo_reuses_other_outputs_and_preserves_original(app_ctx):
    row, version, registry = setup(characters=False)
    original = create_keyframes(row, version, registry)
    count = ToolInvocation.query.count()
    redo = versions.create_version(row, version.plan, version.story_package, version.check, author="user")
    target = [("keyframe", "s01")]
    previews.prepare_previews(row, redo, force_targets=target)
    previews.launch_previews(row, redo, target, registry)
    assert finish(row, redo, registry)["complete"]
    current = previews.preview_view(row, redo)
    assert current["keyframes"]["s01"]["artifact_id"] != original["keyframes"]["s01"]["artifact_id"]
    assert current["keyframes"]["s02"]["artifact_id"] == original["keyframes"]["s02"]["artifact_id"]
    assert previews.preview_view(row, version) == original
    assert ToolInvocation.query.count() == count + 1
    previews.prepare_previews(row, redo, force_targets=target)
    previews.launch_previews(row, redo, target, registry)
    assert ToolInvocation.query.count() == count + 1


def test_character_redo_invalidates_dependent_frames_only_after_rebinding(app_ctx):
    row, version, registry = setup()
    version = create_characters(row, version, registry)
    original = create_keyframes(row, version, registry)
    redo = versions.create_version(row, version.plan, version.story_package, version.check, author="user")
    targets = [("character", "hero")]
    previews.prepare_previews(row, redo, force_targets=targets)
    previews.launch_previews(row, redo, targets, registry)
    assert finish(row, redo, registry)["complete"]
    plan, story = previews.bind_character_references(row, redo)
    updated = versions.create_version(row, plan, story, redo.check, author="system")
    previews.prepare_previews(row, updated)
    view = previews.preview_view(row, updated)
    assert all(item["stale"] for item in view["keyframes"].values())
    assert view["characters"]["hero"]["artifact_id"] != original["characters"]["hero"]["artifact_id"]
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 5


def test_budget_check_rejects_batch_before_first_image(app_ctx):
    row, version, registry = setup(characters=False)
    row.request = {**row.request, "budget_limit": 5}
    db.session.commit()
    previews.prepare_previews(row, version)
    with pytest.raises(AppError) as error:
        previews.launch_previews(row, version, previews.targets_for(version), registry)
    assert error.value.code == "BUDGET_EXCEEDED"
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 0


def test_one_submission_failure_keeps_other_previews_successful(app_ctx, monkeypatch):
    row, version, registry = setup(characters=False)
    targets = previews.targets_for(version)
    previews.prepare_previews(row, version)
    original = registry.get("generate_image")
    def fail_one(data, ctx):
        task = db.session.get(AgentShotTask, ctx.preview_task_id)
        if task.target_id == "s02":
            raise AppError("MOCK_SUBMIT_FAILURE", "Injected local failure after ledger admission", 503)
        return original.handler(data, ctx)
    monkeypatch.setitem(registry._specs, "generate_image", replace(original, handler=fail_one))
    previews.launch_previews(row, version, targets, registry)
    assert finish(row, version, registry) == {"complete": True, "failed": True}
    view = previews.preview_view(row, version)
    assert [view["keyframes"][key]["status"] for key in ("s01", "s02", "s03")] == ["success", "failed", "success"]
    previews.launch_previews(row, version, targets, registry)
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 3
    assert ToolInvocation.query.filter_by(tool_name="generate_image", status="failed").count() == 1
    assert BudgetGuard.spent(row.run_id) == 7


@pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True, API_AUTH_REQUIRED=True,
                    JWT_SECRET_KEY="phase-c-preview-owner-secret-over-32-bytes")
def test_preview_urls_job_routes_lists_and_packages_are_owner_protected(app_ctx, client, h):
    row, version, registry = setup(characters=False)
    view = create_keyframes(row, version, registry)
    own = {"Authorization": "Bearer " + create_access_token(identity="owner")}
    other = {"Authorization": "Bearer " + create_access_token(identity="other")}
    artifact_id = view["keyframes"]["s01"]["artifact_id"]
    artifact = Artifact.query.filter_by(artifact_id=artifact_id).one()
    for endpoint in ("preview", "download"):
        url = f"/api/artifacts/{artifact_id}/{endpoint}"
        assert client.get(url).status_code == 401
        assert client.get(url, headers=other).status_code == 404
        assert client.get(url, headers=own).status_code == 200
    for suffix in ("", "/artifacts", "/stream"):
        assert client.get(f"/api/jobs/{artifact.job.job_id}{suffix}", headers=other).status_code == 404
    assert client.post(f"/api/jobs/{artifact.job.job_id}/package", headers=other).status_code == 404
    package = client.post(f"/api/jobs/{artifact.job.job_id}/package", headers=own)
    assert package.status_code == 400
    assert package.json["error"]["code"] == "NO_PACKABLE_CONTENT"
    # Image-only previews are not a Phase C delivery package; any package
    # artifact attached later still inherits the private Job's owner.
    package_artifact = ArtifactService.register_artifact(artifact.job, artifact.file_path, "job_package")
    db.session.commit()
    url = f"/api/artifacts/{package_artifact.artifact_id}/download"
    assert client.get(url, headers=other).status_code == 404
    assert client.get(url, headers=own).status_code == 200
    for source in ({"initial_artifacts": {"first_frame_image": artifact_id}},
                   {"source_video_path": artifact.file_path}):
        result = client.post("/api/jobs", headers=other, json={"template_id": "agent_workspace", **source})
        assert result.status_code == 404
    result = client.post("/api/skills/generate_image/invoke", headers=other, json={
        "role": "production", "approved": True, "budget_scope": "unrelated", "budget_limit": 100,
        "input": {"mode": "i2i", "prompt": "copy", "reference_artifact_ids": [artifact_id]}})
    assert result.status_code == 404
    assert not client.get("/api/artifacts", headers=other).json["data"]["artifacts"]
    assert client.get("/api/artifacts", headers=own).json["data"]["artifacts"]
    classic = h.make_job(paths=())
    file = StorageService.write_mock_png(classic.job_id, ["outputs", "public.png"])
    public = ArtifactService.register_artifact(classic, file, "first_frame_image")
    db.session.commit()
    assert client.get(f"/api/artifacts/{public.artifact_id}/preview").status_code == 200


def test_research_reference_reaches_i2i_and_other_run_is_rejected(app_ctx):
    from tests.test_story_creative import with_research
    from app.skills.job_backed import resolve_artifact
    row, version, registry = setup()
    research_state = {}
    reference_id = with_research(row, research_state)[0]
    story, plan = deepcopy(version.story_package), deepcopy(version.plan)
    story["characters"][0]["reference"] = {"source": "research", "artifact_ids": [reference_id],
        "research_entity_id": "e1", "generate_prompt": None}
    for shot in plan["shots"]:
        shot["first_frame"]["reference_artifact_ids"] = [reference_id]
    version = versions.create_version(row, plan, story, version.check, author="system")
    assert not previews.targets_for(version, "characters")
    view = create_keyframes(row, version, registry)
    assert view["characters"]["hero"]["artifact_id"] == reference_id
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 3
    other, _, _ = setup(characters=False)
    with pytest.raises(AppError) as error:
        resolve_artifact(reference_id, image_only=True, ctx=ToolContext(role="production", budget_scope=other.run_id))
    assert error.value.code == "ATTACHMENT_NOT_FOUND"


def test_user_first_frame_is_immediately_ready_without_image_charge(app_ctx):
    from tests.test_story_creative import attachment
    row, version, registry = setup(characters=False)
    artifact_id = attachment(owner=row.owner_id)
    row.request = {**row.request, "attachment_ids": [artifact_id]}
    db.session.commit()
    plan = deepcopy(version.plan)
    plan["shots"][0]["first_frame"] = {"method": "user_image", "image_mode": None,
        "model_id": None, "prompt": "", "reference_artifact_ids": [artifact_id]}
    version = versions.create_version(row, plan, version.story_package, version.check, author="user")
    view = create_keyframes(row, version, registry)
    assert view["keyframes"]["s01"]["artifact_id"] == artifact_id
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count() == 2
    assert view["keyframes"]["s01"]["estimated_cost"] == 0


def test_deleted_preview_becomes_stale_without_paid_resubmission(app_ctx):
    row, version, registry = setup(characters=False)
    view = create_keyframes(row, version, registry)
    artifact = Artifact.query.filter_by(artifact_id=view["keyframes"]["s01"]["artifact_id"]).one()
    StorageService.resolve(artifact.file_path).unlink()
    count = ToolInvocation.query.count()
    assert previews.preview_view(row, version)["keyframes"]["s01"]["stale"]
    changed = versions.create_version(row, version.plan, version.story_package, version.check, author="user")
    previews.prepare_previews(row, changed)
    assert versions.latest_task(row, changed.version, "keyframe", "s01").status == "stale"
    previews.launch_previews(row, changed, previews.targets_for(changed), registry)
    assert ToolInvocation.query.count() == count


def test_edit_quote_reuses_unchanged_images_but_redo_quote_is_billable(app_ctx):
    row, version, registry = setup(characters=False)
    assert previews.remaining_preview_cost(row, version.plan, version.story_package) == 6
    create_keyframes(row, version, registry)
    assert previews.remaining_preview_cost(row, version.plan, version.story_package) == 0
    target = [("keyframe", "s01")]
    assert previews.preview_cost(row, version, target) == 0
    assert previews.preview_cost(row, version, target, force=True) == 2
    plan = deepcopy(version.plan)
    plan["shots"][0]["motion"]["prompt"] += "，加快移动"
    plan["shots"][0]["duration_sec"] += 1
    assert previews.remaining_preview_cost(row, plan, version.story_package) == 0
    plan["shots"][0]["first_frame"]["prompt"] += "，改为夜景"
    assert previews.remaining_preview_cost(row, plan, version.story_package) == 2
    assert AgentPlanVersion.query.count() == 1


def test_initial_quote_includes_unbound_character_and_uses_plan_aspect(app_ctx):
    row, version, registry = setup()
    assert previews.remaining_preview_cost(row, version.plan, version.story_package) == 8
    data = previews.planned_inputs(row, version, "character", "hero")
    assert data["params"].get("ratio") == "16:9" or data["params"].get("size") in {"1280*720", "1536*864", "1920*1080"}
    view = previews.preview_view(row, version)
    assert view["keyframes"]["s01"]["estimated_cost"] == 2
    assert view["keyframes"]["s01"]["error"]["code"] == "PREVIEW_INCOMPLETE"


def test_invalid_draft_quote_omits_unpriceable_images_without_blocking_edit(app_ctx):
    row, version, registry = setup(characters=False)
    plan = deepcopy(version.plan)
    plan["shots"][0]["first_frame"]["model_id"] = "missing-image-model"
    assert previews.remaining_preview_cost(row, plan, version.story_package) == 4
    plan["shots"][1]["first_frame"]["image_mode"] = None
    assert previews.remaining_preview_cost(row, plan, version.story_package) == 2
    assert AgentShotTask.query.count() == 0
