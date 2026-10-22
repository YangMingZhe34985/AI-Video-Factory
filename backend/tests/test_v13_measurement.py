"""Runtime measurement error never becomes an author-controlled duration bound."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.api import AppError
from app.plans import execution, media, runtime_duration
from app.plans.duration import duration_targets, matches_duration
from app.plans.measured_duration import measured_details, segment_count
from app.plans.node_tools import QcInput


def bound(target=5, mode="exact", tolerance=0):
    return {"target_duration_sec": target, "duration_tolerance_sec": tolerance, "mode": mode}


def composed_plan(count=1, *, target=None):
    return {"nodes": [
        {"id": "clip", "tool": "generate_video", "inputs": {}},
        {"id": "master", "tool": "compose_video", "inputs": {
            "video_artifact_ids": [{"ref": "clip.video"}] * count}},
    ], "deliverables": [{"kind": "video", "node_id": "master", "output": "artifact_id"}],
        "duration_constraint": target or bound()}


def probe_outputs(monkeypatch, outputs, measured):
    tasks = {key: SimpleNamespace(status="success", output=value, state={
        "output_fingerprints": {artifact: {"sha256": artifact} for artifact in value.values()}})
        for key, value in outputs.items()}
    monkeypatch.setattr(execution, "usable", lambda _run, task: task.status == "success")
    monkeypatch.setattr(execution, "artifact_for_run", lambda _run, key, _kind:
        SimpleNamespace(file_path=key, meta={"plan_output": {"duration_sec": 600},
                                            "media": {"fps": .01}}))
    monkeypatch.setattr(execution, "fingerprint", lambda _run, key, _kind: {"sha256": key})
    monkeypatch.setattr(runtime_duration.StorageService, "resolve", lambda path: path)
    calls = []

    def probe(path, **kwargs):
        assert kwargs["decode"] is True
        calls.append(path)
        seconds, fps = measured[path]
        return {"duration_sec": seconds, "fps": fps}

    monkeypatch.setattr(runtime_duration.MediaProbeService, "probe", probe)
    return tasks, calls


def qc_result(monkeypatch, plan, actual, *, fps=25, source_count=1):
    target = plan["duration_constraint"]["target_duration_sec"]
    node = {"id": "qc", "tool": "qc_video", "inputs": {
        "artifact_id": {"ref": "master.artifact_id"}}}
    monkeypatch.setattr(media.policy, "task_context", lambda _ctx:
        (object(), None, SimpleNamespace(plan=plan), node))
    monkeypatch.setattr(media, "_source", lambda _run, key:
        (SimpleNamespace(meta={"plan_output": {"duration_sec": target / source_count}}), key))
    monkeypatch.setattr(media, "_duration", lambda _artifact, path, **_kwargs:
        {"duration_sec": actual if path == "master-artifact" else target / source_count,
         "fps": fps if path == "master-artifact" else .01, "has_audio": False})
    monkeypatch.setattr(media, "_finish", lambda _ctx, output: output)
    return media.qc_video(QcInput(plan_version=1, artifact_id="master-artifact",
        video_artifact_ids=["source-artifact"] * source_count,
        duration_constraint=plan["duration_constraint"]), object())


@pytest.mark.parametrize("constraint,actual,passed", [
    (bound(), 5.04, True), (bound(), 5.8, False),
    (bound(120, "at_most"), 120.3, True),
])
def test_user_examples_agree_at_qc_and_final_measurement(monkeypatch, constraint, actual, passed):
    plan = composed_plan(target=constraint)
    original = deepcopy(plan)
    checks = {item["code"]: item for item in qc_result(monkeypatch, plan, actual)["checks"]}
    assert checks["USER_TARGET_DURATION"]["passed"] is passed
    tasks, calls = probe_outputs(monkeypatch, {"master": {"artifact_id": "master-artifact"}},
        {"master-artifact": (actual, 25)})
    if passed:
        details = runtime_duration.check_delivery_duration(object(), plan, tasks, {})
    else:
        with pytest.raises(AppError) as caught:
            runtime_duration.check_delivery_duration(object(), plan, tasks, {})
        assert caught.value.code == "PLAN_QC_FAILED"
        details = caught.value.payload
    assert details == checks["USER_TARGET_DURATION"]["details"]
    assert details["measurement_error_sec"] == .5
    assert details["duration_tolerance_sec"] == 0
    assert calls == ["master-artifact"] and plan == original


@pytest.mark.parametrize("actual,passed", [(4.5, True), (5.5, True), (4.49999, False), (5.50001, False)])
def test_exact_runtime_edges_do_not_change_strict_bounds(actual, passed):
    constraint = bound()
    result = measured_details(actual, constraint, [(1, 25)])
    assert result["passed"] is passed
    assert result["minimum_duration_sec"] == result["maximum_duration_sec"] == 5
    assert result["effective_minimum_duration_sec"] == 4.5
    assert result["effective_maximum_duration_sec"] == 5.5
    assert constraint == bound()
    assert matches_duration(actual, constraint) is False


def test_approximate_user_tolerance_is_preserved_separately():
    constraint = bound(120, "approx", 15)
    result = measured_details(135.4, constraint, [(1, 25)])
    assert result["passed"] is True
    assert (result["minimum_duration_sec"], result["maximum_duration_sec"]) == (105, 135)
    assert result["effective_maximum_duration_sec"] == 135.5
    assert measured_details(135.6, constraint, [(1, 25)])["passed"] is False
    assert constraint == bound(120, "approx", 15)


@pytest.mark.parametrize("count,allowance", [(12, .5), (13, .52), (20, .8)])
def test_final_segment_frame_allowance_can_exceed_half_a_second(count, allowance):
    result = measured_details(5.7, bound(), [(count, 25)])
    assert result["measurement_error_sec"] == pytest.approx(allowance)
    assert result["measurement_segment_count"] == count
    assert result["passed"] is (count == 20)


@pytest.mark.parametrize("fps", [None, 0, -1, True, "25", float("nan"), float("inf")])
def test_unknown_file_fps_never_inherits_a_default_or_cached_rate(fps):
    result = measured_details(5.55, bound(), [(20, fps)])
    assert result["passed"] is False
    assert result["measurement_error_sec"] == .5
    assert result["measurement_frame_allowance_sec"] == 0
    assert result["measurement_unknown_fps_segments"] == 20


@pytest.mark.parametrize("count", [0, -1, 121, True, 1.5, "2"])
def test_invalid_approved_segment_count_fails_closed(count):
    with pytest.raises(AppError) as caught:
        measured_details(5, bound(), [(count, 25)])
    assert caught.value.code == "PLAN_QC_FAILED"


def test_missing_or_nonfinite_measurement_allowance_fails_closed():
    for observations in ([], [(120, 1e-320)]):
        with pytest.raises(AppError) as caught:
            measured_details(5, bound(), observations)
        assert caught.value.code == "PLAN_QC_FAILED"


@pytest.mark.parametrize("actual", [None, 0, -1, True, "5", float("nan"), float("inf")])
def test_technical_allowance_cannot_approve_invalid_measured_duration(actual):
    assert measured_details(actual, bound(), [(1, 25)])["passed"] is False


def test_final_compose_counts_repeats_but_not_dependencies_or_nested_sources():
    plan = composed_plan(20)
    plan["nodes"].append({"id": "outer", "tool": "compose_video", "depends_on": ["clip", "master"],
        "inputs": {"video_artifact_ids": [{"ref": "master.artifact_id"}, {"ref": "clip.video"}]}})
    original = deepcopy(plan)
    assert segment_count(plan, {"ref": "master.artifact_id"}) == 20
    assert segment_count(plan, {"ref": "master.compressed_artifact_id"}) == 20
    assert segment_count(plan, {"ref": "outer.artifact_id"}) == 2
    assert segment_count(plan, {"artifact": "existing-master"}) == 1
    assert plan == original


@pytest.mark.parametrize("tool", ["generate_video", "animate_shot", "retain_video_segment", "transform_video"])
def test_noncompose_final_outputs_are_one_segment(tool):
    plan = {"nodes": [{"id": "final", "tool": tool, "inputs": {}, "depends_on": ["noise"]}]}
    assert segment_count(plan, {"ref": "final.video"}) == 1


def test_qc_source_list_cannot_inflate_the_approved_master_allowance(monkeypatch):
    result = qc_result(monkeypatch, composed_plan(target=bound(120, "at_most")), 120.8, source_count=50)
    checks = {item["code"]: item for item in result["checks"]}
    assert checks["TOTAL_DURATION"]["passed"] is True
    assert checks["USER_TARGET_DURATION"]["passed"] is False
    assert checks["USER_TARGET_DURATION"]["details"]["measurement_segment_count"] == 1
    assert checks["USER_TARGET_DURATION"]["details"]["measurement_error_sec"] == .5
    assert result["passed"] is False


def test_multiple_final_videos_share_one_half_second_baseline(monkeypatch):
    plan = {"nodes": [{"id": name, "tool": "generate_video", "inputs": {}} for name in ("a", "b")],
        "deliverables": [{"kind": "video", "node_id": name, "output": "video"} for name in ("a", "b")],
        "duration_constraint": bound(10)}
    original = deepcopy(plan)
    tasks, calls = probe_outputs(monkeypatch, {name: {"video": name} for name in ("a", "b")},
        {"a": (5.3, 25), "b": (5.3, 25)})
    with pytest.raises(AppError) as caught:
        runtime_duration.check_delivery_duration(object(), plan, tasks, {})
    assert caught.value.code == "PLAN_QC_FAILED"
    assert caught.value.payload["measurement_error_sec"] == .5
    assert caught.value.payload["measurement_segment_count"] == 2
    assert calls == ["a", "b"] and plan == original


def test_multiple_masters_use_their_own_probed_frame_rates(monkeypatch):
    plan = {"nodes": [{"id": name, "tool": "compose_video", "inputs": {
        "video_artifact_ids": [{"artifact": "source"}] * 20}} for name in ("a", "b")],
        "deliverables": [{"kind": "video", "node_id": name, "output": "artifact_id"} for name in ("a", "b")],
        "duration_constraint": bound(10)}
    tasks, _calls = probe_outputs(monkeypatch, {name: {"artifact_id": name} for name in ("a", "b")},
        {"a": (5.7, 20), "b": (5.7, 100)})
    with pytest.raises(AppError) as caught:
        runtime_duration.check_delivery_duration(object(), plan, tasks, {})
    assert caught.value.payload["measurement_error_sec"] == pytest.approx(1.2)
    assert caught.value.payload["measurement_segment_count"] == 40


def test_package_compressed_and_master_aliases_are_measured_once(monkeypatch):
    plan = composed_plan(2, target=bound(10))
    plan["nodes"].append({"id": "package", "tool": "package_story", "inputs": {
        "artifact_id": {"ref": "master.artifact_id"}}})
    plan["deliverables"] += [
        {"kind": "video", "node_id": "master", "output": "compressed_artifact_id"},
        {"kind": "package", "node_id": "package", "output": "artifact_id"}]
    assert duration_targets(plan) == [{"ref": "master.artifact_id"}]
    tasks, calls = probe_outputs(monkeypatch, {"master": {"artifact_id": "master-artifact"}},
        {"master-artifact": (10.3, 25)})
    result = runtime_duration.check_delivery_duration(object(), plan, tasks, {})
    assert result["passed"] is True and result["current_duration_sec"] == 10.3
    assert result["measurement_segment_count"] == 2
    assert calls == ["master-artifact"]


@pytest.mark.parametrize("mode,actual", [("exact", 5.04), ("at_most", 5.3)])
def test_compiler_still_rejects_plans_that_only_fit_runtime_error(app_ctx, mode, actual):
    from app.plans.compiler import compile_plan
    from tests.test_v13_duration import duration_run, retained
    run, _delegation, _ctx = duration_run(5, mode)
    draft = retained(actual)
    original = deepcopy(draft)
    checked = compile_plan(draft, run)
    issue = next(item for item in checked["issues"] if item["code"] == "PLAN_DURATION_MISMATCH")
    assert issue["details"]["maximum_duration_sec"] == 5
    assert measured_details(actual, bound(5, mode), [(1, 25)])["passed"] is True
    assert checked["plan"]["duration_constraint"] == bound(5, mode)
    assert draft == original


@pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)
@pytest.mark.parametrize("with_qc", [False, True])
def test_mock_job_completion_and_registry_keep_measurement_allowance(app_ctx, monkeypatch, with_qc):
    from app.agents.workspace import write_workspace
    from app.models import ApiTask, ToolInvocation
    from app.plans import runtime
    from app.services.job_run_service import JobRunService
    from app.services.media_probe_service import MediaProbeService
    from app.tools.budget import BudgetGuard
    from tests.test_v3_workspace import brief, make_context
    from tests.test_v4_execution import drain_plan, image_node, setup, video_node
    run, _root, ctx = make_context(text="生成5秒猫跳舞的视频")
    write_workspace("brief", "brief", brief(deliverable="video", target_duration_sec=5,
        duration_mode="exact", duration_source_text="5秒"), ctx)
    nodes = [image_node(), video_node()]
    if with_qc:
        nodes.append({"id": "qc", "tool": "qc_video", "inputs": {
            "artifact_id": {"ref": "clip.video"}, "video_artifact_ids": [{"ref": "clip.video"}]},
            "rationale": "Check the delivered clip"})
    run, version, registry = setup(nodes, run=run,
        deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    original = deepcopy(version.plan)
    probe = MediaProbeService.probe
    monkeypatch.setattr(MediaProbeService, "probe", lambda *args, **kwargs:
        {**probe(*args, **kwargs), "duration_sec": 5.3})
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review", run.error
    tasks = runtime.latest_tasks(run)
    assert all(task.status == "success" for task in tasks.values())
    if with_qc:
        row = ToolInvocation.query.filter_by(budget_scope=run.run_id, tool_name="qc_video").one()
        for output in (row.output_payload, tasks["qc"].output):
            checked = next(item for item in output["checks"] if item["code"] == "USER_TARGET_DURATION")
            assert checked["passed"] is True
            assert checked["details"]["measurement_error_sec"] == .5
            assert checked["details"]["duration_tolerance_sec"] == 0
    spent, calls = BudgetGuard.spent(run.run_id), ApiTask.query.count()
    assert calls == 2
    assert runtime.approve_results(run, version.version) == "success"
    assert ApiTask.query.count() == calls and BudgetGuard.spent(run.run_id) == spent
    assert version.plan == original and version.plan["duration_constraint"] == bound()
