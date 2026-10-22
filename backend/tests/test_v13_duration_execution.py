"""Frozen duration targets at QC, result review and final approval boundaries."""
from copy import deepcopy
from types import SimpleNamespace

from flask import Flask
import pytest

from app.api import AppError
from app.plans import execution, media, runtime, runtime_duration
from app.plans.node_tools import QcInput


def constraint(target=10, mode="exact", tolerance=0):
    return {"target_duration_sec": target, "duration_tolerance_sec": tolerance, "mode": mode}


def final_plan(*, target=None, count=1):
    result = {"nodes": [{"id": f"clip{index}", "tool": "generate_video", "inputs": {}}
                        for index in range(count)],
        "deliverables": [{"kind": "video", "node_id": f"clip{index}", "output": "video"}
                         for index in range(count)]}
    if target is not None:
        result["duration_constraint"] = target
    return result


def output_stubs(monkeypatch, seconds):
    tasks = {f"clip{index}": SimpleNamespace(status="success", output={"video": f"artifact{index}"},
        artifact_ids=[f"artifact{index}"], state={"output_fingerprints": {
            f"artifact{index}": {"artifact_id": f"artifact{index}", "sha256": "approved"}}})
        for index in range(len(seconds))}
    monkeypatch.setattr(execution, "usable", lambda _run, task: task.status == "success")
    monkeypatch.setattr(execution, "artifact_for_run", lambda _run, key, _kind:
        SimpleNamespace(file_path=key, meta={"plan_output": {"duration_sec": 600}}))
    monkeypatch.setattr(execution, "fingerprint", lambda _run, key, _kind:
        {"artifact_id": key, "sha256": "approved"})
    monkeypatch.setattr(runtime_duration.StorageService, "resolve", lambda path: path)
    monkeypatch.setattr(runtime_duration.MediaProbeService, "probe", lambda path, **_kw:
        {"duration_sec": seconds[int(path.removeprefix("artifact"))]})
    return tasks


@pytest.mark.parametrize("mode,target,tolerance,actual,passed", [
    ("approx", 120, 15, 105, True), ("approx", 120, 15, 135, True),
    ("approx", 120, 15, 104.99, True), ("approx", 120, 15, 135.01, True),
    ("approx", 120, 15, 104.49, False), ("approx", 120, 15, 135.51, False),
    ("exact", 10, 0, 10, True), ("exact", 10, 0, 9.9, True), ("exact", 10, 0, 9.49, False),
    ("at_most", 10, 0, 3, True), ("at_most", 10, 0, 10.01, True), ("at_most", 10, 0, 10.51, False),
])
def test_final_media_uses_measured_duration_and_frozen_bounds(monkeypatch, mode, target, tolerance, actual, passed):
    tasks = output_stubs(monkeypatch, [actual])
    plan = final_plan(target=constraint(target, mode, tolerance))
    if passed:
        assert runtime_duration.check_delivery_duration(object(), plan, tasks, {})["current_duration_sec"] == actual
    else:
        with pytest.raises(AppError) as caught:
            runtime_duration.check_delivery_duration(object(), plan, tasks, {})
        assert caught.value.code == "PLAN_QC_FAILED"
        assert caught.value.payload["current_duration_sec"] == actual


@pytest.mark.parametrize("actual", [None, 0, -1, True, "10", float("nan"), float("inf")])
def test_unknown_or_untrusted_measured_duration_cannot_reach_review(monkeypatch, actual):
    tasks = output_stubs(monkeypatch, [actual])
    with pytest.raises(AppError) as caught:
        runtime_duration.check_delivery_duration(object(), final_plan(target=constraint()), tasks, {})
    assert caught.value.code == "PLAN_QC_FAILED"


def test_multiple_independent_deliveries_are_checked_as_one_total(monkeypatch):
    tasks = output_stubs(monkeypatch, [4, 6])
    result = runtime_duration.check_delivery_duration(object(), final_plan(target=constraint(), count=2), tasks, {})
    assert result["current_duration_sec"] == 10


@pytest.mark.parametrize("change", ["missing_task", "missing_fingerprint", "changed", "changed_during_probe"])
def test_final_measurement_requires_owned_frozen_unchanged_outputs(monkeypatch, change):
    tasks = output_stubs(monkeypatch, [10])
    if change == "missing_task":
        tasks.clear()
    elif change == "missing_fingerprint":
        tasks["clip0"].state = {}
    elif change == "changed":
        monkeypatch.setattr(execution, "fingerprint", lambda *_a: {"sha256": "changed"})
    else:
        def changed(*_a, **_kw):
            monkeypatch.setattr(execution, "fingerprint", lambda *_a: {"sha256": "changed"})
            return {"duration_sec": 10}
        monkeypatch.setattr(runtime_duration.MediaProbeService, "probe", changed)
    with pytest.raises(AppError) as caught:
        runtime_duration.check_delivery_duration(object(), final_plan(target=constraint()), tasks, {})
    assert caught.value.code == "PLAN_QC_FAILED"


def test_owned_source_master_requires_approved_source_fingerprint(monkeypatch):
    output_stubs(monkeypatch, [10])
    plan = {"duration_constraint": constraint(), "nodes": [{"id": "package", "tool": "package_story",
        "inputs": {"artifact_id": {"artifact": "artifact0"}}}],
        "deliverables": [{"kind": "package", "node_id": "package", "output": "artifact_id"}]}
    with pytest.raises(AppError, match="fingerprint"):
        runtime_duration.check_delivery_duration(object(), plan, {}, {})
    receipt = {"source_fingerprints": {"artifact0": {"artifact_id": "artifact0", "sha256": "approved"}}}
    assert runtime_duration.check_delivery_duration(object(), plan, {}, receipt)["current_duration_sec"] == 10


def test_legacy_without_constraint_never_probes(monkeypatch):
    monkeypatch.setattr(runtime_duration, "duration_targets", lambda *_a: pytest.fail("Legacy plan must remain unchanged"))
    assert runtime_duration.check_delivery_duration(object(), final_plan(), {}, {}) is None


def test_constraint_without_any_video_target_fails_closed():
    with pytest.raises(AppError) as caught:
        runtime_duration.check_delivery_duration(object(), {"duration_constraint": constraint(), "nodes": [], "deliverables": []}, {}, {})
    assert caught.value.code == "PLAN_QC_FAILED"


def test_qc_optional_constraint_preserves_legacy_serialization():
    data = {"plan_version": 1, "artifact_id": "master", "video_artifact_ids": ["clip"]}
    assert QcInput.model_validate(data).model_dump(mode="json") == data
    data.update(duration_constraint=constraint(), target_aspect_ratio="16:9", target_size="1280*720")
    assert QcInput.model_validate(data).model_dump(mode="json") == data


@pytest.mark.parametrize("mode,actual,passed", [
    ("exact", 9.9, True), ("at_most", 10.1, True), ("exact", 9.4, False), ("at_most", 10.6, False)])
def test_qc_user_target_has_separate_measurement_allowance(monkeypatch, mode, actual, passed):
    data = QcInput(plan_version=1, artifact_id="master", video_artifact_ids=["clip"],
        duration_constraint=constraint(mode=mode))
    plan = final_plan(target=constraint(mode=mode))
    qc_node = {"inputs": {"artifact_id": {"ref": "clip0.video"}}}
    monkeypatch.setattr(media.policy, "task_context", lambda *_a:
        (object(), None, SimpleNamespace(plan=plan), qc_node))
    monkeypatch.setattr(media, "_source", lambda _run, key: (SimpleNamespace(meta={
        "plan_output": {"duration_sec": 10}}), key))
    monkeypatch.setattr(media, "_duration", lambda *_a, **_kw: {"duration_sec": actual, "has_audio": False})
    monkeypatch.setattr(media, "_finish", lambda _ctx, result: result)
    result = media.qc_video(data, object())
    checks = {item["code"]: item["passed"] for item in result["checks"]}
    assert checks["TOTAL_DURATION"] is passed
    assert checks["USER_TARGET_DURATION"] is passed and result["passed"] is passed
    detail = next(item["details"] for item in result["checks"] if item["code"] == "USER_TARGET_DURATION")
    assert detail["duration_tolerance_sec"] == 0 and detail["measurement_error_sec"] == .5


def test_begin_rejects_root_duration_drift_even_when_nodes_are_unchanged(monkeypatch):
    from app.agent import plan_versions
    from app.plans import compiler
    plan = final_plan(target=constraint())
    version = SimpleNamespace(version=1, plan=plan, check={"dry_run": {"passed": True}, "estimates": {}})
    run = SimpleNamespace(status="awaiting_plan_review", snapshot={})
    changed = deepcopy(plan)
    changed["duration_constraint"] = constraint(20)
    monkeypatch.setattr(plan_versions, "require_current_version", lambda *_a: version)
    monkeypatch.setattr(compiler, "compile_plan", lambda *_a, **_kw: {"plan": changed, "issues": [], "estimates": {}})
    with pytest.raises(AppError) as caught:
        runtime.begin(run, version, registry=object())
    assert caught.value.code == "PLAN_INPUT_CHANGED" and run.status == "awaiting_plan_review"


def runtime_stubs(monkeypatch, actual=9):
    tasks = output_stubs(monkeypatch, [actual])
    plan = final_plan(target=constraint())
    version = SimpleNamespace(version=1, plan=plan)
    run = SimpleNamespace(status="executing", error=None)
    receipt = {"dag": {"order": ["clip0"], "dependencies": {"clip0": []}}}
    monkeypatch.setattr(runtime.versions, "current_version", lambda *_a: version)
    monkeypatch.setattr(runtime.versions, "require_current_version", lambda *_a: version)
    monkeypatch.setattr(runtime, "_frozen", lambda *_a: receipt)
    monkeypatch.setattr(runtime, "latest_tasks", lambda *_a: tasks)
    def update(value, *, status=None, **_changes):
        if status:
            value.status = status
        if "run_error" in _changes:
            value.error = _changes["run_error"]
        return value
    monkeypatch.setattr(runtime, "_update", update)
    return run, version, tasks


def test_short_direct_video_stops_before_review_without_invalidating_paid_output(monkeypatch):
    run, _version, tasks = runtime_stubs(monkeypatch)
    with Flask(__name__).app_context():
        assert runtime.advance(run, registry=object()) == "attention"
    assert tasks["clip0"].status == "success"
    assert run.error["code"] == "PLAN_QC_FAILED" and run.error["category"] == "qc_failed"
    assert run.error["details"]["current_duration_sec"] == 9


def test_result_approval_remeasures_and_rejects_success(monkeypatch):
    run, version, tasks = runtime_stubs(monkeypatch, actual=10)
    with Flask(__name__).app_context():
        assert runtime.advance(run, registry=object()) == "awaiting_result_review"
    monkeypatch.setattr(runtime_duration.MediaProbeService, "probe", lambda *_a, **_kw: {"duration_sec": 9})
    with pytest.raises(AppError) as caught:
        runtime.approve_results(run, version.version)
    assert caught.value.code == "PLAN_QC_FAILED" and run.status == "attention"
    assert tasks["clip0"].status == "success"


@pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)
@pytest.mark.parametrize("measured,expected_status", [
    (2, "attention"), (5, "awaiting_result_review"), (5.04, "awaiting_result_review")])
def test_mock_job_direct_video_obeys_approved_target_without_qc_node(app_ctx, monkeypatch, measured, expected_status):
    from app.agents.workspace import write_workspace
    from app.models import ApiTask, ToolInvocation
    from app.services.job_run_service import JobRunService
    from app.tools.budget import BudgetGuard
    from tests.test_v3_workspace import brief, make_context
    from tests.test_v4_execution import drain_plan, image_node, setup, video_node
    run, _root, ctx = make_context(text="生成5秒猫跳舞的视频")
    write_workspace("brief", "brief", brief(deliverable="video", target_duration_sec=5,
        duration_mode="exact", duration_source_text="5秒"), ctx)
    run, version, registry = setup([image_node(), video_node()], run=run,
        deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    probe = runtime_duration.MediaProbeService.probe
    monkeypatch.setattr(runtime_duration.MediaProbeService, "probe", lambda *args, **kwargs:
        {**probe(*args, **kwargs), "duration_sec": measured})
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == expected_status
    assert all(task.status == "success" for task in runtime.latest_tasks(run).values())
    assert ToolInvocation.query.filter_by(tool_name="qc_video").count() == 0
    spent, calls = BudgetGuard.spent(run.run_id), ApiTask.query.count()
    assert calls == 2
    if expected_status == "awaiting_result_review":
        assert runtime.approve_results(run, version.version) == "success"
    else:
        assert run.error["code"] == "PLAN_QC_FAILED"
        assert runtime.advance(run, registry) == "attention"
    assert BudgetGuard.spent(run.run_id) == spent and ApiTask.query.count() == calls


@pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)
def test_duration_attention_can_start_user_revision_without_failed_generation(app_ctx, monkeypatch):
    from app.agents import repair_flow
    from app.extensions import db
    from tests.test_v4_execution import setup
    run, version, registry = setup()
    runtime.begin(run, version, registry=registry)
    tasks = runtime.latest_tasks(run, version)
    for task in tasks.values():
        task.status = "success"
    run.status, run.error = "attention", {"code": "PLAN_QC_FAILED", "category": "qc_failed", "check": "USER_TARGET_DURATION"}
    db.session.commit()
    result = repair_flow.revise_plan(run, {"request_key": "duration-revision", "plan_version": version.version,
        "message": "请修改片段，使成片满足原有明确时长要求"})
    flow = repair_flow.active_flow(run)
    assert result["flow_id"] == flow["flow_id"] and flow["trigger"]["kind"] == "user_revision"
    assert run.status == "understanding" and all(task.status == "success" for task in tasks.values())
