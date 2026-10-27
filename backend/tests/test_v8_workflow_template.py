"""V8c: classic-path Plan node over Mock adapters and isolated SQLite (V.25.2–V.25.4)."""
from copy import deepcopy
import subprocess
import zipfile

import pytest
from werkzeug.datastructures import FileStorage

from app.agent import plan_versions as versions
from app.agent.attachments import upload_attachment
from app.agents.api import RuntimeAction, admit_action
from app.agents.workspace import write_workspace
from app.api import AppError
from app.extensions import db
from app.models import Job, Template
from app.plans import execution, runtime
from app.plans.compiler import compile_plan
from app.plans.dry_run import dry_run
from app.plans.workflow import created_template_id
from app.services.job_run_service import JobRunService
from app.services.prompt_service import PromptService
from app.services.storage_service import StorageService
from app.services.video_compression_service import VideoCompressionService
from app.tools import build_v3_registry
from tests.test_v3_workspace import brief, make_context
from tests.test_v4_execution import drain_plan


@pytest.fixture
def source_video(app_ctx, tmp_path):
    try:
        binary = VideoCompressionService.resolve_ffmpeg()
    except FileNotFoundError:
        pytest.skip("FFmpeg is required for a source video")
    path = tmp_path / "source.mp4"
    subprocess.run([binary, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=256x256:r=20", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True, timeout=20)
    with path.open("rb") as stream:
        return upload_attachment(FileStorage(stream=stream, filename="source.mp4"), "owner")["attachment_id"]


def classic_template():
    template = PromptService.create_template({"name": "城市夜景", "series": "default"})
    db.session.commit()
    return template


def node(**inputs):
    return {"id": "workflow", "tool": "run_workflow_template", "inputs": inputs,
            "origin": {"agent": "producer", "skills": ["production-workflow"]}, "rationale": "经典路径"}


def compile_run(inputs, deliverables, *, ids=(), extra_nodes=(), duration=None, text="反推这个视频的提示词并保存到模板", **extra):
    run, _root, ctx = make_context(ids=ids, text=text)
    uses = [{"attachment_id": key, "kind": "video", "role": "content_ref", "description": "参考视频",
             "reason": "反推提示词"} for key in ids]
    write_workspace("brief", "brief", brief(deliverable="video", production_intent=True, attachments=uses, **extra), ctx)
    draft = {"title": "经典路径", "goal": "在模板下运行经典工作流", "nodes": [node(**deepcopy(inputs)), *extra_nodes],
             "deliverables": deliverables}
    if duration:
        draft["duration_constraint"] = duration
    registry = build_v3_registry()
    return run, registry, compile_plan(draft, run, registry=registry, plan_version=1)


def approve(run, registry, checked):
    checked["dry_run"] = dry_run(checked, registry=registry)
    assert checked["dry_run"]["passed"], checked["dry_run"]
    version = versions.create_version(run, checked["plan"], {}, checked, author="system")
    run.status = "awaiting_plan_review"
    db.session.commit()
    runtime.begin(run, version, registry=registry)
    return version


def finish(run, registry, monkeypatch, *, mq=False):
    if not mq:
        monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    status = drain_plan(run, registry, mq=mq)
    task = runtime.latest_tasks(run)["workflow"]
    assert status == "awaiting_result_review", (task.status, task.error)
    assert execution.usable(run, task)
    return task


def test_reverse_prompts_creates_template_and_delivers_prompts_only(app_ctx, source_video, monkeypatch):
    inputs = {"template_target": {"series_id": "default", "new_template_name": "参考视频反推"},
              "branches": ["reverse_prompts", "rewrite_prompts"], "source_video_artifact_id": source_video,
              "package": False}
    run, registry, checked = compile_run(inputs, [{"kind": "prompts", "node_id": "workflow", "output": "prompts"}],
                                         ids=[source_video])
    assert not checked["issues"], checked["issues"]
    write = checked["template_writes"][0]
    assert write["mode"] == "new" and write["template_name"] == "参考视频反推"
    assert write["prompt_types"] == ["first_frame_image", "i2v", "t2v"]
    frozen = checked["plan"]["nodes"][0]["inputs"]
    assert set(frozen["models"]) == {"reverse_prompts", "rewrite_prompts"}
    assert checked["estimates"]["nodes"][0]["mode"] == "workflow"
    assert Template.query.filter_by(template_id=write["template_id"]).first() is None  # Compile never writes.
    approve(run, registry, checked)
    task = finish(run, registry, monkeypatch)
    template = Template.query.filter_by(template_id=created_template_id(run.run_id, "workflow")).one()
    assert template.series == "default" and template.config["agent_created"]["run_id"] == run.run_id
    assert set(task.output["prompts"]) == {"t2v", "first_frame_image", "i2v"}
    assert task.output["videos"] == [] and task.output["images"] == [] and task.output["package"] is None
    assert task.output["template"]["created"] is True
    # Classic PromptSync writes the job's prompt versions back to template level.
    assert PromptService.get_active_for_template(template, "t2v").content == task.output["prompts"]["t2v"]["content"]
    job = Job.query.filter_by(job_id=task.output["job_id"]).one()
    assert job.template_id == template.id and job.config["agent_workflow"]["branches"] == ["reverse_prompts", "rewrite_prompts"]


@pytest.mark.parametrize("mq", [False, True])
def test_prompt_testing_runs_first_frame_and_i2v_under_existing_template(app_ctx, monkeypatch, mq):
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq)
    template = classic_template()
    inputs = {"template_target": {"template_id": template.template_id}, "branches": ["first_frame_image", "i2v"],
              "prompts": {"first_frame_image": "雨夜街头，一位撑红伞的女子站在霓虹灯下。", "i2v": "女子缓缓转身，雨丝斜落。"}}
    run, registry, checked = compile_run(inputs, [{"kind": "video", "node_id": "workflow", "output": "videos"},
                                                  {"kind": "package", "node_id": "workflow", "output": "package"}])
    assert not checked["issues"], checked["issues"]
    assert checked["template_writes"][0]["mode"] == "existing"
    frozen = checked["plan"]["nodes"][0]["inputs"]
    assert set(frozen["models"]) == {"image", "i2v"} and frozen["package"] is True
    approve(run, registry, checked)
    from app.plans import workflow
    seen, original = [], workflow.validate_submit
    monkeypatch.setattr(workflow, "validate_submit", lambda *args: (seen.append(args[5]), original(*args))[1])
    task = finish(run, registry, monkeypatch, mq=mq)
    # Every provider submission is admitted against the frozen node, in both dispatch paths.
    assert {"submit_first_frame_image", "submit_i2v"} <= set(seen)
    assert len(task.output["videos"]) == 1 and len(task.output["images"]) == 1
    job = Job.query.filter_by(job_id=task.output["job_id"]).one()
    assert job.config["node_models"] == {"submit_first_frame_image": frozen["models"]["image"],
                                         "submit_i2v": frozen["models"]["i2v"]}
    package = StorageService.resolve(execution.artifact_for_run(run, task.output["package"], "package").file_path)
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    assert any(name.startswith("final/") for name in names) and "prompts/prompts.json" in names
    assert task.estimated_cost == checked["estimates"]["total_credits"]


def test_production_chain_reverses_rewrites_and_packages(app_ctx, source_video, monkeypatch):
    template = classic_template()
    inputs = {"template_target": {"template_id": template.template_id},
              "branches": ["reverse_prompts", "rewrite_prompts", "first_frame_image", "i2v"],
              "source_video_artifact_id": source_video}
    run, registry, checked = compile_run(inputs, [{"kind": "video", "node_id": "workflow", "output": "videos"},
                                                  {"kind": "package", "node_id": "workflow", "output": "package"}],
                                         ids=[source_video])
    assert not checked["issues"], checked["issues"]
    approve(run, registry, checked)
    task = finish(run, registry, monkeypatch)
    assert set(task.output["prompts"]) >= {"t2v", "first_frame_image", "i2v"}
    assert len(task.output["videos"]) == 1 and task.output["package"]


def test_i2i_test_branch_quotes_and_runs_each_sample(app_ctx, monkeypatch):
    template = classic_template()
    inputs = {"template_target": {"template_id": template.template_id}, "branches": ["i2i_test"],
              "prompts": {"i2i": "保持人物身份，换成雨夜街头背景。", "i2v": "人物缓缓抬头。"}, "i2i_test": {"mode": "single_male", "test_count": 2}}
    run, registry, checked = compile_run(inputs, [{"kind": "video", "node_id": "workflow", "output": "videos"}])
    assert not checked["issues"], checked["issues"]
    frozen = checked["plan"]["nodes"][0]["inputs"]
    assert set(frozen["models"]) == {"i2i_image", "i2i_video"}  # Supplied i2i prompt skips the rewrite node.
    from app.plans.workflow import quote
    calls = quote(frozen)["calls"]
    assert calls["submit_i2i_test_image"]["calls"] == 2 and calls["submit_i2i_test_i2v"]["calls"] == 2
    assert checked["estimates"]["total_credits"] == pytest.approx(
        sum(item["unit_cost"] * item["calls"] for item in calls.values()))
    approve(run, registry, checked)
    task = finish(run, registry, monkeypatch)
    assert len(task.output["videos"]) == 2 and len(task.output["images"]) == 2


@pytest.mark.parametrize("inputs, deliverables, code", [
    ({"branches": ["rewrite_prompts"], "prompts": {"t2v": "a"}, "template_target": {"template_id": "missing"}},
     [{"kind": "prompts", "node_id": "workflow", "output": "prompts"}], "TEMPLATE_NOT_FOUND"),
    ({"branches": ["reverse_prompts", "rewrite_prompts"], "prompts": {"t2v": "a"}}, [], "WORKFLOW_PROMPT_CONFLICT"),
    ({"branches": ["i2v"], "prompts": {"i2v": "a"}}, [], "WORKFLOW_INPUT_MISSING"),
    ({"branches": ["rewrite_prompts"]}, [], "WORKFLOW_DEPENDENCY_MISSING"),
    ({"branches": ["rewrite_prompts"], "prompts": {"t2v": "a"}}, [{"kind": "video", "node_id": "workflow", "output": "videos"}],
     "WORKFLOW_DELIVERABLE_UNAVAILABLE"),
    ({"branches": ["rewrite_prompts"], "prompts": {"t2v": "a"}}, [{"kind": "video", "node_id": "workflow", "output": "video"}],
     "INVALID_DELIVERABLE_TYPE"),
    ({"branches": ["t2v"], "prompts": {"t2v": "a"}, "models": {"i2v": "wan2.7-i2v"}}, [], "WORKFLOW_MODEL_SLOT"),
])
def test_compile_refuses_invalid_workflow_nodes(app_ctx, inputs, deliverables, code):
    template = classic_template()
    inputs.setdefault("template_target", {"template_id": template.template_id})
    run, _registry, checked = compile_run(inputs, deliverables or [{"kind": "prompts", "node_id": "workflow", "output": "prompts"}])
    assert code in {item["code"] for item in checked["issues"]}, checked["issues"]


def test_image_only_and_prompt_only_jobs_are_not_packaged(app_ctx):
    template = classic_template()
    inputs = {"template_target": {"template_id": template.template_id}, "branches": ["first_frame_image"],
              "prompts": {"first_frame_image": "雨夜街头，撑红伞的女子"}}
    _run, _registry, checked = compile_run(inputs, [{"kind": "image", "node_id": "workflow", "output": "images"}])
    assert not checked["issues"], checked["issues"]
    assert checked["plan"]["nodes"][0]["inputs"]["package"] is False  # Classic packages need a video.
    _run, _registry, checked = compile_run(inputs, [{"kind": "package", "node_id": "workflow", "output": "package"}])
    assert "WORKFLOW_DELIVERABLE_UNAVAILABLE" in {item["code"] for item in checked["issues"]}


def test_workflow_plans_are_single_node_without_duration(app_ctx):
    template = classic_template()
    inputs = {"template_target": {"template_id": template.template_id}, "branches": ["t2v"], "prompts": {"t2v": "雨夜街头"}}
    extra = {"id": "image", "tool": "generate_image", "inputs": {"prompt": "cat"}, "origin": {"agent": "producer", "skills": []},
             "rationale": "extra"}
    _run, _registry, checked = compile_run(inputs, [{"kind": "video", "node_id": "workflow", "output": "videos"}],
                                           extra_nodes=[extra], duration={"target_duration_sec": 5.0, "duration_tolerance_sec": 1.0,
                                                                          "mode": "approx"})
    codes = {item["code"] for item in checked["issues"]}
    assert {"WORKFLOW_PLAN_SHAPE", "WORKFLOW_DURATION_UNSUPPORTED"} <= codes


def test_brief_ratio_and_duration_become_branch_parameters(app_ctx):
    template = classic_template()
    inputs = {"template_target": {"template_id": template.template_id}, "branches": ["t2v"], "prompts": {"t2v": "雨夜街头"}}
    _run, _registry, checked = compile_run(inputs, [{"kind": "video", "node_id": "workflow", "output": "videos"}],
        text="用这条提示词测试一段约5秒的竖屏视频，保存到模板", aspect_ratio="9:16", target_duration_sec=5,
        duration_mode="approx", duration_source_text="约5秒")
    assert not checked["issues"], checked["issues"]
    params = checked["plan"]["nodes"][0]["inputs"]["model_params"]["t2v"]
    assert params["duration"] == 5 and (params.get("ratio") == "9:16" or "size" in params)
    assert checked["plan"].get("duration_constraint") is None
    assert checked["estimates"]["generated_video_seconds"] == 5


def test_approval_requires_template_write_confirmation(app_ctx):
    template = classic_template()
    inputs = {"template_target": {"template_id": template.template_id}, "branches": ["rewrite_prompts"], "prompts": {"t2v": "雨夜"}}
    run, registry, checked = compile_run(inputs, [{"kind": "prompts", "node_id": "workflow", "output": "prompts"}])
    checked["dry_run"] = dry_run(checked, registry=registry)
    versions.create_version(run, checked["plan"], {}, {**checked, "template_writes": checked["template_writes"]}, author="system")
    run.status = "awaiting_plan_review"
    db.session.commit()
    with pytest.raises(AppError) as error:
        admit_action(run, RuntimeAction(action="approve_plan", request_key="a1", plan_version=1))
    assert error.value.code == "TEMPLATE_WRITE_CONFIRMATION_REQUIRED"
    admit_action(run, RuntimeAction(action="approve_plan", request_key="a2", plan_version=1, confirm_template_write=True))
    assert run.command["action"] == "approve_plan" and run.command["confirm_template_write"] is True


def test_submission_rejects_changed_models_and_price(app_ctx, monkeypatch):
    template = classic_template()
    inputs = {"template_target": {"template_id": template.template_id}, "branches": ["t2v"], "prompts": {"t2v": "雨夜街头"}}
    run, registry, checked = compile_run(inputs, [{"kind": "video", "node_id": "workflow", "output": "videos"}])
    approve(run, registry, checked)
    from app.plans import policy, workflow
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: None)
    runtime.advance(run, registry)
    task = runtime.latest_tasks(run)["workflow"]
    job = Job.query.filter_by(job_id=task.job_id).one()
    from app.services.model_service import ModelService
    model = ModelService.get_model(task.inputs["models"]["t2v"])
    params = task.inputs["model_params"]["t2v"]
    good = {"prompt": "雨夜街头"}
    policy.validate_before_submit(job, model, good, params, operation="submit_t2v")
    for inputs_, params_, operation, code in [({"prompt": "改过的"}, params, "submit_t2v", "PLAN_INPUT_CHANGED"),
                                              (good, {**params, "duration": 99}, "submit_t2v", "PLAN_APPROVAL_MISMATCH"),
                                              (good, params, "submit_i2v", "PLAN_APPROVAL_MISMATCH")]:
        with pytest.raises(AppError) as error:
            policy.validate_before_submit(job, model, inputs_, params_, operation=operation)
        assert error.value.code == code
    monkeypatch.setattr("app.tools.budget.estimate_model_cost", lambda *args, **kwargs: 10_000.0)
    with pytest.raises(AppError) as error:
        workflow.validate_submit(run, task, model, good, params, "submit_t2v", None)
    assert error.value.code == "MODEL_PRICE_CHANGED"
