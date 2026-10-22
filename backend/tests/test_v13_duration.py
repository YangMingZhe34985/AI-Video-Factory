"""Explicit user duration survives read-only compilation and plan revision.

These are isolated compiler/workspace tests. No model or media execution is
needed; source inspection is stubbed only in the measured-artifact case.
"""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from app.agents.schemas import DurationConstraint, PlanDraft, RequirementBrief
from app.agents.workspace import read_workspace, write_workspace
from app.api import AppError
from app.extensions import db
from app.models import AgentPlanVersion, AgentWorkspaceItem, Artifact, Job, ToolInvocation
from app.plans.compiler import compile_plan, plan_digest
from app.plans.dry_run import dry_run
from app.plans.patches import apply_patch_draft
from tests.test_v3_plan_compiler import codes, future_transform, image, node, plan, video_plan
from tests.test_v3_plan_tools import invoke, registry, save
from tests.test_v3_workspace import make_context, next_context


def duration_brief(target=120, mode="approx", **extra):
    return {"deliverable": "video", "summary": "Create the requested video", "confidence": .9,
            "target_duration_sec": target, "duration_mode": mode,
            "duration_source_text": f"{target}秒", **extra}


def duration_run(target=120, mode="approx", *, compress=False, preferences=()):
    text = "生成视频" if target is None else f"制作{'约' if mode == 'approx' else '不超过' if mode == 'at_most' else ''}{target}秒的视频"
    if preferences:
        text += "，使用" + "、".join(preferences)
    run, delegation, ctx = make_context(text=text)
    payload = ({"deliverable": "video", "summary": text, "confidence": .9} if target is None
               else duration_brief(target, mode))
    payload["constraints"] = {"compress_output": compress, "model_preferences": list(preferences)}
    write_workspace("brief", "brief", payload, ctx)
    return run, delegation, ctx


def composed(durations, *, repeats=None, compress=False, package=False):
    clips = [node(f"v{i}", "generate_video", {"mode": "t2v", "prompt": f"Scene {i}"},
                  params={"duration": seconds}) for i, seconds in enumerate(durations)]
    refs = [{"ref": f"v{i}.video"} for i in (repeats if repeats is not None else range(len(clips)))]
    nodes = [*clips, node("master", "compose_video", {"video_artifact_ids": refs, "compress_output": compress})]
    deliverables = [{"kind": "video", "node_id": "master", "output": "artifact_id"}]
    if compress:
        deliverables.append({"kind": "video", "node_id": "master", "output": "compressed_artifact_id"})
    if package:
        nodes += [node("qc", "qc_video", {"artifact_id": {"ref": "master.artifact_id"}, "video_artifact_ids": refs}),
                  node("package", "package_story", {"artifact_id": {"ref": "master.artifact_id"},
                       **({"compressed_artifact_id": {"ref": "master.compressed_artifact_id"}} if compress else {})},
                       depends_on=["qc"])]
        deliverables.append({"kind": "package", "node_id": "package", "output": "artifact_id"})
    return plan(nodes, deliverables)


def retained(seconds):
    draft = video_plan(15)
    draft["nodes"].append(node("keep", "retain_video_segment", {
        "video_artifact_id": {"ref": "clip.video"}, "source_start_sec": 0.0, "source_end_sec": seconds}))
    draft["deliverables"] = [{"kind": "video", "node_id": "keep", "output": "artifact_id"}]
    return draft


def test_vgate_120_second_request_rejects_seven_ten_second_scenes(app_ctx):
    run, _delegation, _ctx = duration_run()
    draft = composed([10] * 7)
    draft["goal"] = "A complete 120-second story"
    draft["nodes"][-1]["rationale"] = "Seven scenes add up to 120 seconds"
    original = deepcopy(draft)
    result = compile_plan(draft, run)
    issue = next(item for item in result["issues"] if item["code"] == "PLAN_DURATION_MISMATCH")
    assert issue["details"] == {"current_duration_sec": 70.0, "target_duration_sec": 120.0,
        "duration_tolerance_sec": 15.0, "mode": "approx", "minimum_duration_sec": 105.0,
        "maximum_duration_sec": 135.0}
    assert all(number in issue["message"] for number in ("70", "120", "15"))
    assert not dry_run(result)["passed"]
    assert draft == original


def test_missing_user_target_keeps_unconstrained_plan_shape(app_ctx):
    run, _delegation, _ctx = duration_run(None)
    draft = composed([10] * 7)
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert "duration_constraint" not in result["plan"]
    assert result["estimates"]["video_seconds"] == 70
    assert plan_digest(draft) == plan_digest({**draft, "duration_constraint": None})


@pytest.mark.parametrize("mode,seconds,allowed", [
    ("approx", 7.0, True), ("approx", 13.0, True), ("approx", 6.999, False), ("approx", 13.001, False),
    ("exact", 10.0, True), ("exact", 9.999, False), ("exact", 10.001, False),
    ("at_most", 1.0, True), ("at_most", 10.0, True), ("at_most", 10.001, False),
    ("exact", 10.0000005, True), ("exact", 10.000002, False),
])
def test_duration_boundaries_do_not_borrow_old_qc_tolerance(app_ctx, mode, seconds, allowed):
    run, _delegation, _ctx = duration_run(10, mode)
    result = compile_plan(retained(seconds), run)
    assert ("PLAN_DURATION_MISMATCH" not in codes(result)) is allowed
    assert codes(result) <= {"PLAN_DURATION_MISMATCH"}
    assert result["estimates"]["video_seconds"] == pytest.approx(seconds)


@pytest.mark.parametrize("target,tolerance", [(1, 3.0), (10, 3.0), (24, 3.0), (25, 3.125), (120, 15.0), (600, 75.0)])
def test_approximate_default_tolerance_is_deterministic(target, tolerance):
    parsed = RequirementBrief.model_validate(duration_brief(target))
    assert parsed.duration_tolerance_sec == tolerance
    assert RequirementBrief.model_validate(duration_brief(target, duration_tolerance_sec=tolerance)) == parsed


@pytest.mark.parametrize("field,value", [
    ("target_duration_sec", True), ("target_duration_sec", 0), ("target_duration_sec", 601),
    ("target_duration_sec", float("nan")), ("target_duration_sec", float("inf")),
    ("duration_tolerance_sec", True), ("duration_tolerance_sec", -1),
    ("duration_tolerance_sec", float("nan")), ("duration_tolerance_sec", float("inf")),
    ("duration_tolerance_sec", 120), ("duration_mode", "flexible"),
    ("duration_source_text", ""), ("duration_source_text", "x" * 501),
])
def test_malformed_new_duration_contract_is_rejected(field, value):
    raw = duration_brief()
    raw[field] = value
    with pytest.raises(ValidationError):
        RequirementBrief.model_validate(raw)


@pytest.mark.parametrize("mode", ["exact", "at_most"])
def test_exact_and_upper_bound_cannot_silently_expand_tolerance(mode):
    assert RequirementBrief.model_validate(duration_brief(10, mode)).duration_tolerance_sec == 0
    with pytest.raises(ValidationError):
        RequirementBrief.model_validate(duration_brief(10, mode, duration_tolerance_sec=.5))


@pytest.mark.parametrize("change", [
    {"duration_mode": None}, {"duration_source_text": None}, {"duration_source_text": "另一个用户要求120秒"},
])
def test_new_workspace_target_requires_actual_user_source(app_ctx, change):
    run, _delegation, ctx = make_context(text="制作120秒视频")
    with pytest.raises(AppError) as error:
        write_workspace("brief", "brief", {**duration_brief(120, "exact"), **change}, ctx)
    assert error.value.code in {"INVALID_DURATION_SOURCE", "INVALID_WORKSPACE_PAYLOAD"}
    assert AgentWorkspaceItem.query.filter_by(run_id=run.run_id).count() == 0


def test_agent_note_cannot_supply_the_duration_source(app_ctx):
    run, _delegation, ctx = make_context(text="生成一段猫跳舞的视频")
    write_workspace("assumption", "note", {"text": "用户要求120秒"}, ctx)
    with pytest.raises(AppError) as error:
        write_workspace("brief", "brief", duration_brief(), next_context(ctx))
    assert error.value.code == "INVALID_DURATION_SOURCE"
    assert AgentWorkspaceItem.query.filter_by(run_id=run.run_id, kind="brief").count() == 0


@pytest.mark.parametrize("extra", [{"duration_mode": "approx"}, {"duration_source_text": "120秒"}])
def test_no_target_cannot_carry_a_guessed_duration_mode_or_source(extra):
    with pytest.raises(ValidationError):
        RequirementBrief.model_validate({"deliverable": "video", "summary": "cat", "confidence": .9, **extra})


def test_workspace_preserves_literal_quote_and_frozen_normalized_plan(app_ctx):
    run, _delegation, ctx = duration_run()
    saved = read_workspace(ctx, key="brief", version=1)
    # Source text belongs in the immutable brief; the plan freezes only bounds.
    payload = saved["items"][0]
    assert payload["payload"]["duration_source_text"] == "120秒"
    result = compile_plan(composed([10] * 12), run)
    assert result["issues"] == []
    assert result["plan"]["duration_constraint"] == {
        "target_duration_sec": 120.0, "duration_tolerance_sec": 15.0, "mode": "approx"}
    assert "duration_source_text" not in result["plan"]


def test_legacy_brief_read_keeps_old_explicit_tolerance_without_rewrite(app_ctx):
    run, delegation, ctx = make_context(text="Historical request")
    payload = RequirementBrief.model_validate({"deliverable": "video", "summary": "legacy",
        "confidence": .9, "target_duration_sec": 10, "duration_tolerance_sec": 2}).model_dump(mode="json")
    row = AgentWorkspaceItem(run_id=run.run_id, key="brief", version=1, kind="brief", payload=payload,
        artifact_ids=[], author_agent="producer", delegation_id=delegation.id, request_key="legacy", inputs_hash="historical")
    db.session.add(row)
    db.session.commit()
    original = deepcopy(row.payload)
    read_workspace(ctx, key="brief", version=1)
    result = compile_plan(retained(12), run)
    assert result["issues"] == []
    assert result["plan"]["duration_constraint"] == {
        "target_duration_sec": 10.0, "duration_tolerance_sec": 2.0, "mode": "approx"}
    assert "PLAN_DURATION_MISMATCH" in codes(compile_plan(retained(12.01), run))
    assert row.payload == original and row.inputs_hash == "historical"
    assert "duration_mode" not in row.payload and "duration_source_text" not in row.payload


@pytest.mark.parametrize("filename,model", [("brief", RequirementBrief), ("plan_draft", PlanDraft)])
def test_skill_duration_schema_matches_actual_registry_contract(app_ctx, filename, model):
    run, _delegation, _ctx = duration_run(None)
    output = invoke(registry(), "read_skill_resource", {"name": "plan-review",
        "path": f"resources/workspace/{filename}.schema.json"}, run, "duration-schema")
    assert json.loads(output["content"]) == model.model_json_schema()


def test_repeated_composition_segment_counts_each_playback(app_ctx):
    run, _delegation, _ctx = duration_run(20, "exact")
    result = compile_plan(composed([10], repeats=[0, 0]), run)
    assert result["issues"] == []
    assert result["estimates"]["video_seconds"] == 20
    assert result["estimates"]["generated_video_seconds"] == 10


@pytest.mark.parametrize("package_only", [False, True])
def test_master_compressed_and_package_aliases_count_one_delivery(app_ctx, package_only):
    run, _delegation, _ctx = duration_run(10, "exact", compress=True)
    draft = composed([5, 5], compress=True, package=True)
    if package_only:
        draft["deliverables"] = [draft["deliverables"][-1]]
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert result["estimates"]["video_seconds"] == 10
    qc = next(item for item in result["plan"]["nodes"] if item["id"] == "qc")
    assert qc["inputs"]["duration_constraint"] == result["plan"]["duration_constraint"]


def test_independent_deliverables_are_aggregated_without_per_clip_target(app_ctx):
    run, _delegation, _ctx = duration_run(20, "exact")
    nodes = [node(f"v{i}", "generate_video", {"mode": "t2v", "prompt": "cat"}, params={"duration": 10}) for i in range(2)]
    for i in range(2):
        nodes.append(node(f"qc{i}", "qc_video", {"artifact_id": {"ref": f"v{i}.video"},
                                                "video_artifact_ids": [{"ref": f"v{i}.video"}]}))
    result = compile_plan(plan(nodes, [{"kind": "video", "node_id": f"v{i}", "output": "video"} for i in range(2)]), run)
    assert result["issues"] == []
    assert result["estimates"]["video_seconds"] == 20
    assert all("duration_constraint" not in item["inputs"] for item in result["plan"]["nodes"] if item["tool"] == "qc_video")


def test_final_qc_cannot_supply_a_weaker_user_target(app_ctx):
    run, _delegation, _ctx = duration_run(10, "exact")
    draft = composed([5, 5], package=True)
    qc = next(item for item in draft["nodes"] if item["id"] == "qc")
    qc["inputs"]["duration_constraint"] = {
        "target_duration_sec": 10.0, "duration_tolerance_sec": 3.0, "mode": "approx"}
    assert "PLAN_DURATION_CONSTRAINT_CONFLICT" in codes(compile_plan(draft, run))


def test_intermediate_reference_composition_is_not_a_second_final_delivery(app_ctx):
    run, _delegation, _ctx = duration_run(10, "exact", preferences=["wan3.0系列"])
    draft = composed([5])
    draft["nodes"].append(node("extended", "transform_video", {"operation": "extend", "prompt": "continue",
        "media": [{"type": "reference_video", "artifact_id": {"ref": "master.artifact_id"}}],
        "source_artifact_id": {"ref": "master.artifact_id"}}, model_id="wan3.0-video", params={"duration": 10, "resolution": "480P"}))
    draft["deliverables"] = [{"kind": "video", "node_id": "extended", "output": "video"}]
    result = compile_plan(draft, run)
    assert result["issues"] == []
    assert result["estimates"]["video_seconds"] == 10
    assert "duration_constraint" not in result["plan"]["nodes"][1]["inputs"]


def test_transform_uses_full_output_not_additional_or_billable_seconds(app_ctx):
    run, _delegation, _ctx = duration_run(10, "exact", preferences=["wan3.0系列"])
    result = compile_plan(future_transform(source_seconds=5, output_seconds=10), run)
    assert result["issues"] == []
    quote = result["estimates"]["nodes"][-1]
    assert quote["input_video_seconds"] == 5 and quote["output_video_seconds"] == 10
    assert result["estimates"]["video_seconds"] == 10
    assert result["estimates"]["generated_video_seconds"] == 15


def test_existing_video_uses_measured_duration_not_uploaded_claim(app_ctx, monkeypatch):
    from app.services.media_probe_service import MediaProbeService
    from app.services.storage_service import StorageService
    artifact = Artifact.query.filter_by(artifact_id=image()).one()
    path = StorageService.root() / "measured-source.mp4"
    path.write_bytes(b"stub inspected media")
    artifact.file_path, artifact.file_name = str(path), path.name
    artifact.artifact_type, artifact.mime_type = "source_video", "video/mp4"
    artifact.meta = {"media": {"kind": "video", "duration": 10}}
    db.session.commit()
    run, _delegation, ctx = make_context(text="制作10秒视频", ids=[artifact.artifact_id])
    write_workspace("brief", "brief", duration_brief(10, "exact", attachments=[{
        "attachment_id": artifact.artifact_id, "kind": "video", "role": "content_ref",
        "description": "source", "reason": "use this source"}]), ctx)
    monkeypatch.setattr(MediaProbeService, "probe", lambda *_a, **_kw: {"duration_sec": 9.0})
    draft = plan([node("master", "compose_video", {"video_artifact_ids": [{"artifact": artifact.artifact_id}]})],
                 [{"kind": "video", "node_id": "master", "output": "artifact_id"}])
    result = compile_plan(draft, run)
    assert "PLAN_DURATION_MISMATCH" in codes(result)
    assert result["estimates"]["video_seconds"] == 9


def test_unknown_final_duration_is_blocked_despite_rationale(app_ctx):
    run, _delegation, _ctx = duration_run(10, "exact")
    draft = video_plan(10)
    draft["nodes"][0]["model_id"] = "missing-model"
    draft["nodes"][0]["rationale"] = "The resulting final video is exactly ten seconds"
    result = compile_plan(draft, run)
    assert "PLAN_DURATION_UNKNOWN" in codes(result)
    assert not dry_run(result)["passed"]


@pytest.mark.parametrize("change", [
    {"target_duration_sec": 9.0}, {"duration_tolerance_sec": 1.0, "mode": "approx"}, {"mode": "at_most"},
])
def test_explicit_plan_root_must_equal_validated_brief(app_ctx, change):
    run, _delegation, _ctx = duration_run(10, "exact")
    draft = video_plan(10)
    draft["duration_constraint"] = {"target_duration_sec": 10.0, "duration_tolerance_sec": 0.0, "mode": "exact", **change}
    assert "PLAN_DURATION_CONSTRAINT_CONFLICT" in codes(compile_plan(draft, run))


def test_a_plan_cannot_invent_user_duration_without_a_brief_target(app_ctx):
    run, _delegation, _ctx = duration_run(None)
    draft = video_plan(10)
    draft["duration_constraint"] = {"target_duration_sec": 10.0, "duration_tolerance_sec": 0.0, "mode": "exact"}
    assert "PLAN_DURATION_CONSTRAINT_CONFLICT" in codes(compile_plan(draft, run))


@pytest.mark.parametrize("field,value", [("target_duration_sec", True), ("target_duration_sec", .5), ("target_duration_sec", float("inf")),
    ("duration_tolerance_sec", True), ("duration_tolerance_sec", float("nan")), ("duration_tolerance_sec", .5)])
def test_plan_duration_root_rejects_malformed_authority(field, value):
    raw = {"target_duration_sec": 10.0, "duration_tolerance_sec": 0.0, "mode": "exact", field: value}
    with pytest.raises(ValidationError):
        DurationConstraint.model_validate(raw)


def test_patch_preserves_duration_root_and_cannot_shorten_the_approved_target(app_ctx):
    run, _delegation, _ctx = duration_run(10, "exact")
    before = compile_plan(video_plan(10), run)["plan"]
    patch = {"base_version": 1, "reason": "Change the prompt", "ops": [{"op": "update_inputs", "node_id": "clip", "inputs": {"prompt": "cat waves"}}]}
    changed = apply_patch_draft(before, patch)
    assert changed["duration_constraint"] == before["duration_constraint"]
    assert compile_plan(changed, run)["issues"] == []
    changed["nodes"][0]["params"]["duration"] = 5
    assert "PLAN_DURATION_MISMATCH" in codes(compile_plan(changed, run))
    with pytest.raises(AppError) as error:
        apply_patch_draft(before, {**patch, "duration_constraint": None})
    assert error.value.code == "INVALID_PATCH"
    weakened = deepcopy(before)
    weakened["duration_constraint"] = {"target_duration_sec": 10.0, "duration_tolerance_sec": 5.0, "mode": "approx"}
    assert plan_digest(weakened) != plan_digest(before)


def test_compile_and_check_duration_never_write_or_invoke_production(app_ctx, monkeypatch):
    run, _delegation, _ctx = duration_run(120, "approx")
    value = registry()
    initial = (Job.query.count(), ToolInvocation.query.count(), AgentWorkspaceItem.query.count(), AgentPlanVersion.query.count())
    with monkeypatch.context() as guard:
        guard.setattr(db.session, "commit", lambda: pytest.fail("Compilation cannot commit"))
        guard.setattr(db.session, "flush", lambda *_a, **_kw: pytest.fail("Compilation cannot flush"))
        guard.setattr(value, "invoke", lambda *_a, **_kw: pytest.fail("Compilation cannot invoke tools"))
        result = compile_plan(composed([10] * 7), run, registry=value)
        assert "PLAN_DURATION_MISMATCH" in codes(result)
    checked = invoke(value, "check_plan", {"plan": composed([10] * 7)}, run, "check-duration")
    assert "PLAN_DURATION_MISMATCH" in codes(checked)
    assert initial == (Job.query.count(), ToolInvocation.query.count(), AgentWorkspaceItem.query.count(), AgentPlanVersion.query.count())


def test_submit_rejects_mismatch_but_valid_revised_draft_can_reach_review(app_ctx):
    run, _delegation, _ctx = duration_run(120, "approx")
    # This is the review submission API, not approval of any generation.
    run.request = {**run.request, "budget_limit": 1000}
    db.session.commit()
    value = registry()
    ref = save(run, composed([10] * 7))
    rejected = invoke(value, "submit_plan", {"plan_ref": ref}, run, "reject-duration")
    assert not rejected["submitted"] and "PLAN_DURATION_MISMATCH" in codes(rejected)
    assert AgentPlanVersion.query.count() == 0
    revised = save(run, composed([10] * 12), request_key="correct-duration")
    accepted = invoke(value, "submit_plan", {"plan_ref": revised}, run, "submit-duration")
    assert accepted["submitted"] and accepted["issues"] == []
    version = AgentPlanVersion.query.one()
    assert version.plan["duration_constraint"]["target_duration_sec"] == 120
    assert run.status == "awaiting_plan_review" and Job.query.count() == 0

