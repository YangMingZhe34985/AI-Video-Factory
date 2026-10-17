"""Phase 3: real local media, mocked providers, persisted graph and classic DAG."""

import io
import json
import os
import shutil
import subprocess
import time
import zipfile
from copy import deepcopy

import pytest

from app.agent.plan_spec import PlanSpec
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ApiTask, Artifact, Job, JobNodeRun, PromptVersion, ToolInvocation
from app.services.job_run_service import JobRunService
from app.services.node_runner import NodeRunner
from app.services.storage_service import StorageService
from app.services.video_media_service import VideoMediaService
from app.skills import get_registry
from app.skills.spec import ToolContext
from tests.test_agent_mvp import action, create, detail, finish, tick

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True)


@pytest.mark.parametrize("legacy_checkpoint", [False, True])
def test_invalid_duration_draft_can_be_corrected_without_replanning(app_ctx, client, video_file, monkeypatch, legacy_checkpoint):
    import app.agent.graph as graph_module
    import app.agent.planning as planning
    original_call = planning.structured_call
    seen_goals = []

    def invalid_draft(instruction, data, schema, mock):
        if schema is PlanSpec:
            seen_goals.append(data.original_goal)
            mock["shots"][0].update(action="keep")
            mock["shots"][1].update(video_params={"duration": 2.5, "resolution": "720P"})
        return original_call(instruction, data, schema, mock)

    monkeypatch.setattr(planning, "structured_call", invalid_draft)
    original_validate = graph_module.validate_plan
    if legacy_checkpoint:
        def old_failure(*args, **kwargs):
            raise RuntimeError("Previous worker stopped before draft approval")
        monkeypatch.setattr(graph_module, "validate_plan", old_failure)
    source = upload(client, video_file)
    goal = "保留前半段，替换后半段；重生成片段5秒，使用wan2.7系列"
    run_id = create(client, mode="remix", source_artifact_id=source["artifact_id"], goal=goal, shot_count=2, budget_limit=13)
    for _ in range(100):
        tick()
        result = detail(client, run_id)
        if result["status"] in {"awaiting_approval", "needs_attention"}:
            break
        time.sleep(0.05)
    if legacy_checkpoint:
        assert result["status"] == "needs_attention"
        monkeypatch.setattr(graph_module, "validate_plan", original_validate)
        action(client, run_id, "resume")
        tick()
        result = detail(client, run_id)
    assert result["status"] == "awaiting_approval"
    assert seen_goals == [goal]
    issue = result["snapshot"]["plan_issues"][0]
    assert issue["shot_id"] == "shot_2"
    assert "duration: expected integer" in issue["errors"]
    assert result["snapshot"]["plan"]["shots"][1]["video_params"]["duration"] == 2.5
    assert ApiTask.query.count() == 0
    assert client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "approve"}).status_code == 422
    assert detail(client, run_id)["command"] is None
    plan = deepcopy(result["snapshot"]["plan"])
    plan["shots"][1]["video_params"]["duration"] = 5
    # A 1.5-second source range can generate a five-second output clip.
    action(client, run_id, "approve", plan=plan)
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery"
    assert result["snapshot"]["plan_issues"] == []
    assert result["summary"]["success"] == 2
    assert result["estimated_spent"] == 8  # analysis/planning (3) + 5 generated seconds at 1 credit/sec
    assert ApiTask.query.count() == 1
    assert ApiTask.query.one().request_payload["parameters"]["duration"] == 5
    for name in ("analyze_video", "agent_director", "agent_creative"):
        assert ToolInvocation.query.filter_by(budget_scope=run_id, tool_name=name).count() == 1
    action(client, run_id, "deliver")
    tick()
    assert detail(client, run_id)["status"] == "success"


@pytest.fixture(scope="module")
def video_file(tmp_path_factory):
    binary = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    assert binary, "Phase 3 media tests require FFmpeg on PATH or FFMPEG_BINARY"
    path = tmp_path_factory.mktemp("remix-input") / "source.mp4"
    subprocess.run([binary, "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
                   capture_output=True, check=True, timeout=30)
    return path


def upload(client, video_file, **kwargs):
    with video_file.open("rb") as stream:
        response = client.post("/api/agent/sources", data={"file": (stream, "original.mp4")}, **kwargs)
    assert response.status_code == 201, response.json
    return response.json["data"]


def planned_run(client, video_file, **kwargs):
    source = upload(client, video_file)
    run_id = create(client, mode="remix", source_artifact_id=source["artifact_id"],
                    goal="保留开场，修改后续动作，使用wan2.7系列视频模型", **kwargs)
    result = await_plan(client, run_id)
    return run_id, source, result


def await_plan(client, run_id):
    for _ in range(100):
        tick()
        result = detail(client, run_id)
        if result["status"] not in {"queued", "analyzing", "planning"}:
            assert result["status"] == "awaiting_approval", result
            return result
        time.sleep(0.05)
    pytest.fail("Analysis/planning did not finish")


def test_upload_analyze_mixed_edits_revision_lineage_and_delivery(app_ctx, client, video_file):
    run_id, source, planned = planned_run(client, video_file)
    assert source["file_name"] == "original.mp4"
    assert source["duration"] == pytest.approx(3, abs=0.1)
    assert (source["width"], source["height"]) == (320, 180)
    assert planned["estimated_spent"] == 3
    assert planned["snapshot"]["analysis"]["content"]
    assert ApiTask.query.count() == 0
    plan = deepcopy(planned["snapshot"]["plan"])
    plan["shots"][0]["action"] = "keep"
    plan["shots"][2]["first_frame_mode"] = "generate"
    plan["shots"][2]["first_frame_prompt"] = "A cat in a blue room, user-confirmed appearance change"
    action(client, run_id, "approve", plan=plan)
    generated = finish(client, run_id)
    assert generated["status"] == "awaiting_delivery", generated
    assert generated["summary"] == {"total": 3, "success": 3, "failed": 0, "pending": 0}
    assert generated["estimated_spent"] == 25  # analysis + planning + 0 + 10 + 12
    shots = generated["snapshot"]["shots"]
    original_jobs = {key: shot["job_id"] for key, shot in shots.items()}
    kept = Job.query.filter_by(job_id=original_jobs["shot_1"]).one()
    assert ApiTask.query.filter_by(job_id=kept.id).count() == 0
    clip = Artifact.query.filter_by(job_id=kept.id, artifact_type="retained_video").one()
    assert VideoMediaService.inspect(StorageService.resolve(clip.file_path))["duration"] == pytest.approx(1, abs=0.1)
    output = VideoMediaService._run([*VideoMediaService._input(StorageService.resolve(clip.file_path)),
                                     "-map", "0:a:0", "-f", "null", "-"], 30)
    assert "Audio:" in output
    source_frame_job = Job.query.filter_by(job_id=original_jobs["shot_2"]).one()
    assert ApiTask.query.filter_by(job_id=source_frame_job.id, branch_key="first_frame_image").count() == 0
    assert {task.model_id for task in ApiTask.query.filter_by(branch_key="i2v")} == {"wan2.7-i2v"}
    analysis_id = generated["snapshot"]["analysis"]["prompt_id"]
    prior_prompt = PromptVersion.query.filter_by(job_id=source_frame_job.id, prompt_type="i2v", is_active=True).one()
    assert source_frame_job.config["remix"]["prompt_lineage"]["i2v"] == analysis_id
    assert prior_prompt.parent_version and analysis_id in prior_prompt.note
    # Only shot_2 is replaced; all earlier assets and the other jobs survive.
    edited = deepcopy(generated["snapshot"]["plan"]["shots"][1])
    edited["i2v_prompt"] = "The subject turns left instead of right"
    action(client, run_id, "revise", shot=edited, request_key="edit-second-shot")
    durable_command = deepcopy(AgentRun.query.filter_by(run_id=run_id).one().command)
    revised = finish(client, run_id)
    assert revised["status"] == "awaiting_delivery", revised
    assert revised["estimated_spent"] == 35
    for key in ("shot_1", "shot_3"):
        assert revised["snapshot"]["shots"][key]["job_id"] == original_jobs[key]
    replacement = Job.query.filter_by(job_id=revised["snapshot"]["shots"]["shot_2"]["job_id"]).one()
    assert replacement.job_id != original_jobs["shot_2"]
    assert replacement.config["remix"]["prompt_lineage"]["i2v"] == prior_prompt.prompt_id
    assert revised["snapshot"]["shot_history"]["shot_2"][0]["result"]["job_id"] == source_frame_job.job_id
    assert all(StorageService.resolve(artifact.file_path).is_file() for artifact in source_frame_job.artifacts)
    count = ApiTask.query.count()
    # Lost HTTP response and a stale durable inbox must both replay the same edit.
    action(client, run_id, "revise", shot=edited, request_key="edit-second-shot")
    row = AgentRun.query.filter_by(run_id=run_id).one()
    row.command = durable_command
    db.session.commit()
    tick()
    assert ApiTask.query.count() == count
    assert detail(client, run_id)["snapshot"]["shot_revisions"]["shot_2"] == 1
    assert client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "revise", "shot": {**edited, "i2v_prompt": "different"},
                                                                 "request_key": "edit-second-shot"}).status_code == 409
    action(client, run_id, "deliver")
    tick()
    delivered = detail(client, run_id)
    assert delivered["status"] == "success", delivered
    assert len(delivered["snapshot"]["packages"]) == 3
    assert [package["job_id"] for package in delivered["snapshot"]["packages"]] == [
        revised["snapshot"]["shots"][shot["shot_id"]]["job_id"] for shot in plan["shots"]]
    for package in delivered["snapshot"]["packages"]:
        artifact = Artifact.query.filter_by(artifact_id=package["artifact_id"]).one()
        with zipfile.ZipFile(StorageService.resolve(artifact.file_path)) as archive:
            assert archive.testzip() is None
            manifest = json.loads(archive.read("package_manifest.json"))
            assert manifest["lineage"]["source_artifact_id"] == source["artifact_id"]
            assert manifest["lineage"]["analysis_prompt_id"] == analysis_id
            assert "prompts/source_analysis.md" in archive.namelist()
            assert "prompts/edit_instruction.md" in archive.namelist()
            assert any(name.startswith("final/") and name.endswith(".mp4") for name in archive.namelist())
    assert client.get(f"/api/agent/runs/{run_id}").json["data"]["snapshot"]["shot_history"]


def test_keep_only_uses_no_generation_and_only_planning_budget(app_ctx, client, video_file, monkeypatch):
    import app.agent.planning as planning
    original = planning.structured_call
    def keep(instruction, data, schema, mock):
        if schema is PlanSpec:
            for shot in mock["shots"]:
                shot["action"] = "keep"
        return original(instruction, data, schema, mock)
    monkeypatch.setattr(planning, "structured_call", keep)
    run_id, _, _ = planned_run(client, video_file, shot_count=1, budget_limit=3)
    action(client, run_id, "approve")
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert result["estimated_spent"] == 3
    assert ApiTask.query.count() == 0
    revision = deepcopy(result["snapshot"]["plan"]["shots"][0])
    revision.update(action="regenerate", i2v_prompt="move slowly")
    response = client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "revise", "shot": revision, "request_key": "over-budget"})
    assert response.status_code == 402
    assert detail(client, run_id)["command"] is None


@pytest.mark.parametrize("changes", [
    {"source_start": -1}, {"source_end": 4}, {"source_start": 2, "source_end": 1},
    {"source_start": float("nan")}, {"source_start": True}, {"action": "erase"},
    {"video_model_id": "wan2.6-i2v-flash"}, {"video_params": {"model_id": "wan2.6-i2v-flash"}},
    {"first_frame_mode": "generate", "first_frame_prompt": ""},
])
def test_invalid_edits_rejected_before_generation(app_ctx, client, video_file, changes):
    run_id, _, planned = planned_run(client, video_file, shot_count=1)
    plan = deepcopy(planned["snapshot"]["plan"])
    plan["shots"][0].update(changes)
    response = client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "approve", "plan": plan})
    assert response.status_code == 422, response.json
    assert ApiTask.query.count() == 0
    assert ToolInvocation.query.filter_by(tool_name="remix_shot").count() == 0


def test_upload_rejects_unreadable_video_and_cleans_file(app_ctx, client):
    response = client.post("/api/agent/sources", data={"file": (io.BytesIO(b"not a video"), "bad.mp4")})
    assert response.status_code == 422
    assert response.json["error"]["code"] == "INVALID_SOURCE"
    assert Job.query.count() == Artifact.query.count() == 0
    assert not list((StorageService.root() / "uploads").glob("*"))


def test_source_dimensions_ignore_codec_hex_tag_and_accept_small_video(app_ctx, client, video_file):
    source = upload(client, video_file)
    artifact = Artifact.query.filter_by(artifact_id=source["artifact_id"]).one()
    target = StorageService.root() / "small.mp4"
    VideoMediaService._run([*VideoMediaService._input(StorageService.resolve(artifact.file_path)),
                           "-vf", "scale=8:8", "-t", "1", "-c:v", "libx264", str(target)], 30)
    result = VideoMediaService.inspect(target)
    assert (result["width"], result["height"]) == (8, 8)


@pytest.mark.config(AGENT_MODE_ENABLED=True, API_AUTH_REQUIRED=True, JWT_SECRET_KEY="test-remix-auth-secret-more-than-32-bytes")
def test_source_ownership_and_required_mode(app_ctx, client, video_file):
    from flask_jwt_extended import create_access_token
    first = {"Authorization": f"Bearer {create_access_token(identity='first')}"}
    second = {"Authorization": f"Bearer {create_access_token(identity='second')}"}
    source = upload(client, video_file, headers=first)
    request = {"mode": "remix", "goal": "change motion", "request_key": "source-test", "source_artifact_id": source["artifact_id"]}
    assert client.post("/api/agent/runs", headers=second, json=request).status_code == 404
    response = client.post("/api/agent/runs", headers=first, json=request)
    assert response.status_code == 202
    assert client.post("/api/agent/runs", headers=first, json=request).json["data"]["run_id"] == response.json["data"]["run_id"]
    for invalid in [{**request, "mode": "from_scratch"}, {**request, "source_artifact_id": None},
                    {**request, "source_video_path": "C:/private.mp4"}]:
        assert client.post("/api/agent/runs", headers=first, json=invalid).status_code == 422


def test_one_failed_regeneration_keeps_source_clip_and_packages(app_ctx, client, video_file, monkeypatch):
    run_id, _, planned = planned_run(client, video_file, shot_count=2)
    plan = deepcopy(planned["snapshot"]["plan"])
    plan["shots"][0]["action"] = "keep"
    def fail(*_args):
        raise AppError("API_TASK_FAILED", "Injected video failure", 502)
    monkeypatch.setattr(NodeRunner, "_run_submit_i2v", fail)
    action(client, run_id, "approve", plan=plan)
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert result["summary"]["success"] == result["summary"]["failed"] == 1
    action(client, run_id, "deliver")
    tick()
    delivered = detail(client, run_id)
    assert delivered["status"] == "partial_success"
    assert len(delivered["snapshot"]["packages"]) == 2
    failed_package = next(item for item in delivered["snapshot"]["packages"] if item["package_status"] == "partial")
    assert failed_package["included_counts"]["images"] == 1


@pytest.mark.parametrize("tool", ["analyze_video", "remix_shot"])
def test_checkpoint_loss_replays_jobs_without_paid_resubmission(app_ctx, client, video_file, monkeypatch, tool):
    import app.agent.graph as graph
    original = graph.invoke_once
    crashed = False
    def interrupt_once(registry, name, data, ctx):
        nonlocal crashed
        result = original(registry, name, data, ctx)
        if name == tool and not crashed:
            crashed = True
            raise RuntimeError("Injected crash after job launch")
        return result
    monkeypatch.setattr(graph, "invoke_once", interrupt_once)
    source = upload(client, video_file)
    run_id = create(client, mode="remix", source_artifact_id=source["artifact_id"], shot_count=1)
    if tool == "analyze_video":
        tick()
        assert detail(client, run_id)["status"] == "needs_attention"
        action(client, run_id, "resume")
        await_plan(client, run_id)
        action(client, run_id, "approve")
    else:
        await_plan(client, run_id)
        action(client, run_id, "approve")
        tick()
        assert detail(client, run_id)["status"] == "needs_attention"
        action(client, run_id, "resume")
    result = finish(client, run_id)
    assert result["status"] == "awaiting_delivery", result
    assert ToolInvocation.query.filter_by(tool_name="analyze_video").count() == 1
    assert ToolInvocation.query.filter_by(tool_name="remix_shot").count() == 1
    assert ApiTask.query.filter_by(branch_key="i2v").count() == 1
    assert result["estimated_spent"] == 13


def test_unknown_analysis_outcome_stops_without_repeating_paid_analysis(app_ctx, client, video_file, monkeypatch):
    source = upload(client, video_file)
    run_id = create(client, mode="remix", source_artifact_id=source["artifact_id"], shot_count=1)
    original = JobRunService.start
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: {})
    tick()
    assert detail(client, run_id)["status"] == "analyzing"
    invocation = ToolInvocation.query.filter_by(tool_name="analyze_video").one()
    invocation.job.status = "running"
    db.session.add(JobNodeRun(job_id=invocation.job.id, node_key="reverse_prompts", status="running"))
    db.session.commit()
    monkeypatch.setattr(JobRunService, "start", original)
    tick()
    assert detail(client, run_id)["status"] == "needs_attention"
    assert "unknown" in detail(client, run_id)["error"]["message"]
    assert ToolInvocation.query.count() == 1
    assert ApiTask.query.count() == 0


def test_tool_cannot_swap_source_or_analysis_reference(app_ctx, client, video_file, h):
    run_id, source, planned = planned_run(client, video_file, shot_count=1)
    other_source = upload(client, video_file)
    other_analysis = get_registry().invoke("analyze_video", {"source_artifact_id": other_source["artifact_id"]},
        ToolContext(role="creative", budget_scope=run_id, budget_limit=50, idempotency_key="wrong-source-analysis"))
    h.wait_for_terminal(other_analysis["output"]["job_id"])
    other_job = Job.query.filter_by(job_id=other_analysis["output"]["job_id"]).one()
    wrong_prompt = PromptVersion.query.filter_by(job_id=other_job.id, prompt_type="t2v", is_active=True).one()
    payload = {**planned["snapshot"]["plan"]["shots"][0], "source_artifact_id": other_source["artifact_id"],
               "analysis_prompt_id": planned["snapshot"]["analysis"]["prompt_id"]}
    for index, update in enumerate([{}, {"source_artifact_id": source["artifact_id"], "analysis_prompt_id": "other-prompt"},
                                    {"source_artifact_id": source["artifact_id"], "analysis_prompt_id": wrong_prompt.prompt_id}]):
        with pytest.raises(AppError) as error:
            get_registry().invoke("remix_shot", {**payload, **update}, ToolContext(
                role="production", approved=True, budget_scope=run_id, budget_limit=50, idempotency_key=f"bad-ref-{index}"))
        assert error.value.code == "TOOL_FORBIDDEN"
    assert ApiTask.query.count() == 0
