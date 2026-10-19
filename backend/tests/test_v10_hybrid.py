"""Offline tests for V10b evaluation-only media replacements and evidence helpers."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import sys

# Keep evaluation-only helpers outside the application's import tree.
script_dir = Path(__file__).resolve().parents[1] / "scripts" / "v3_eval"
if script_dir.is_dir():
    sys.path.insert(0, str(script_dir))

import mock_media
from hybrid import ScenarioFailure, require, save_json

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)


@pytest.fixture
def media(app_ctx, monkeypatch, tmp_path):
    from app import adapters
    # Track originals before the evaluation install mutates these process globals.
    for name in mock_media.MEDIA_NAMES:
        original = adapters.ADAPTERS[name]
        monkeypatch.setattr(original, "submit", original.submit)
        monkeypatch.setitem(adapters.ADAPTERS, name, original)
    monkeypatch.setattr(mock_media, "CONTROLLER", None)
    app_ctx.config["MODEL_ADAPTER_MODE"] = "real"
    return mock_media.install(tmp_path / "mock-media.jsonl")


def test_replacements_leave_real_chat_and_block_original_generation(app_ctx, media):
    from app.adapters import ADAPTERS
    from app.adapters.qwen_chat import QwenChatAdapter
    from app.adapters.dashscope_wan3 import DashScopeWan3Adapter
    assert app_ctx.config["MODEL_ADAPTER_MODE"] == "real"
    assert ADAPTERS["qwen_chat"] is QwenChatAdapter
    assert all(ADAPTERS[name] in (mock_media.LocalImageAdapter, mock_media.LocalVideoAdapter)
               for name in mock_media.MEDIA_NAMES)
    with pytest.raises(RuntimeError, match="blocked before"):
        DashScopeWan3Adapter().submit({"model": "wan3.0-video"})
    assert media.summary()["real_media_adapter_attempts"] == 1
    assert media.summary()["actual_real_media_http_calls"] == 0


def test_n_images_are_valid_distinct_and_real_mode_video_decodes(app_ctx, media, monkeypatch):
    from PIL import Image
    from app.models import Artifact
    from app.plans import runtime
    from app.services.job_run_service import JobRunService
    from app.services.media_probe_service import MediaProbeService
    from app.services.storage_service import StorageService
    from tests.test_v4_execution import setup, image_node, video_node, drain_plan
    image = image_node()
    image["params"]["n"] = 3
    run, version, registry = setup([image, video_node()], deliverables=[
        {"kind": "image", "node_id": "image", "output": "images"},
        {"kind": "video", "node_id": "clip", "output": "video"}])
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    tasks = runtime.latest_tasks(run)
    ids = tasks["image"].output["images"]
    assert len(ids) == 3 and len(set(ids)) == 3
    paths = [StorageService.resolve(Artifact.query.filter_by(artifact_id=key).one().file_path) for key in ids]
    assert len({path.read_bytes() for path in paths}) == 3
    for path in paths:
        with Image.open(path) as image:
            image.verify()
    video = Artifact.query.filter_by(artifact_id=tasks["clip"].output["video"]).one()
    probe = MediaProbeService.probe(StorageService.resolve(video.file_path), decode=True)
    assert probe["decoded"] and abs(probe["duration_sec"] - 5) < .1 and not probe["mock"]
    assert media.summary()["mock_images_written"] == 3
    assert media.summary()["mock_videos_written"] == 1
    assert media.summary()["actual_real_media_http_calls"] == 0


def test_one_shot_content_failure_uses_job_error_classification(app_ctx, media, monkeypatch):
    from app.plans import runtime
    from app.services.job_run_service import JobRunService
    from tests.test_v4_execution import setup, image_node, video_node, drain_plan
    clip = video_node()
    run, version, registry = setup([image_node(), clip], deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    media.arm(clip["model_id"], clip["inputs"]["prompt"], run_id=run.run_id, node_id="clip")
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "attention"
    failed = runtime.latest_tasks(run)["clip"]
    assert failed.error["category"] == "content_policy", failed.error
    assert media.failure is None
    assert media.summary()["content_policy_injections"] == 1
    # Same corrected/new attempt is no longer deliberately rejected.
    adapter = mock_media.LocalVideoAdapter(SimpleNamespace(model_id=clip["model_id"], provider="dashscope"))
    assert adapter.submit(adapter.build_payload({"prompt": clip["inputs"]["prompt"]}, {"duration": 5}))["status"] == "submitted"
    assert media.summary()["content_policy_injections"] == 1


def test_evidence_write_and_false_assertions_are_not_silent(tmp_path):
    path = tmp_path / "evidence.json"
    save_json(path, {"中文": [1, 2]})
    assert json.loads(path.read_text(encoding="utf-8")) == {"中文": [1, 2]}
    assert not path.with_name(path.name + ".tmp").exists()
    with pytest.raises(ScenarioFailure, match="explicit failure"):
        require(False, "explicit failure")

@pytest.mark.parametrize("automatic", [True, False])
def test_harness_drives_real_actions_with_offline_repair_director_stubs(app_ctx, media, monkeypatch, tmp_path, automatic):
    import importlib
    from dataclasses import replace
    from app.agent.worker import AgentWorker
    from app.extensions import db
    from app.models import AgentDelegation
    from app.plans.runtime import latest_tasks
    from app.services.job_run_service import JobRunService
    from langgraph.checkpoint.memory import InMemorySaver
    from tests.test_v3_runtime import call
    from tests.test_v4_execution import setup, image_node, video_node
    from hybrid import Harness, fault
    from app.agents.repair_flow import active_flow
    chat = importlib.import_module("app.tools.agent_chat")
    run, version, registry = setup([image_node(gate="preview"), video_node()], deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    run.owner_id = "local"
    root = AgentDelegation.query.filter_by(run_id=run.run_id, parent_id=None).one()
    root.status = "completed"
    root.output = {"kind": "completed", "outcome": "plan_submitted"}
    run.request = {**run.request, "_v3_runtime": True}
    db.session.commit()
    def offline_turn(data, ctx):
        from app.models import AgentRun
        current = AgentRun.query.filter_by(run_id=ctx.budget_scope).one()
        if data.role == "repair":
            task = latest_tasks(current)["clip"]
            calls = [call("propose_patch", {"draft": {"base_version": task.plan_version,
                "reason": "Use a harmless motion description", "evidence_refs": [{"task_id": task.id}],
                "ops": [{"op": "update_inputs", "node_id": "clip", "inputs": {"prompt": "A cat waves gently"}}]}})]
        else:
            assert data.role == "director"
            calls = [call("review_patch", {"patch_id": active_flow(current)["patch_id"], "verdict": "approve", "reason": "Prompt-only local repair"})]
        return {"content": None, "tool_calls": calls, "usage": {"prompt_tokens": 2, "completion_tokens": 2}, "tool_call_errors": []}
    monkeypatch.setattr(chat, "AGENT_LLM_TURN_SPEC", replace(chat.AGENT_LLM_TURN_SPEC, handler=offline_turn))
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    meter = SimpleNamespace(set_label=lambda _label: None, snapshot=lambda: {"real_calls": 0, "real_image_calls": 0, "real_video_calls": 0})
    evaluation = SimpleNamespace(app=app_ctx, WORK=tmp_path, HERE=tmp_path, METER=meter)
    harness = Harness(evaluation, AgentWorker(None, None, v3_saver=InMemorySaver()), "offline-fault", run.run_id)
    fault(harness, automatic)
    result = harness.close()
    assert result["status"] == "passed" and result["final_view"]["status"] == "success"
    assert media.summary()["content_policy_injections"] == 1
    assert {row["agent"] for row in result["ledger"] if row["tool"] == "agent_llm_turn"} == {"repair", "director"}


def _offline_harness(app_ctx, monkeypatch, tmp_path, run, name):
    from app.agent.worker import AgentWorker
    from app.extensions import db
    from app.models import AgentDelegation
    from app.services.job_run_service import JobRunService
    from langgraph.checkpoint.memory import InMemorySaver
    from hybrid import Harness
    run.owner_id = "local"
    root = AgentDelegation.query.filter_by(run_id=run.run_id, parent_id=None).one()
    root.status, root.output = "completed", {"kind": "completed", "outcome": "plan_submitted"}
    run.request = {**run.request, "_v3_runtime": True}
    db.session.commit()
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    meter = SimpleNamespace(set_label=lambda _label: None, snapshot=lambda: {"real_calls": 0, "real_image_calls": 0, "real_video_calls": 0})
    evaluation = SimpleNamespace(app=app_ctx, WORK=tmp_path, HERE=tmp_path, METER=meter)
    return Harness(evaluation, AgentWorker(None, None, v3_saver=InMemorySaver()), name, run.run_id)


def _stub_director(monkeypatch, operation):
    from dataclasses import replace
    import importlib
    from app.models import AgentRun, AgentDelegation
    from app.agents.repair_flow import active_flow
    from app.extensions import db
    from tests.test_v3_runtime import call
    chat = importlib.import_module("app.tools.agent_chat")
    def response(data, ctx):
        assert data.role == "director"
        run = AgentRun.query.filter_by(run_id=ctx.budget_scope).one()
        delegation = db.session.get(AgentDelegation, ctx.delegation_id)
        flow = active_flow(run)
        if delegation.expected == "PatchDraft":
            calls = [call("propose_patch", {"draft": {"base_version": flow["base_version"], "reason": "User explicitly requested this change",
                    "evidence_refs": [{"workspace_ref": flow["context_refs"][1]}], "ops": [operation]}})]
        else:
            calls = [call("review_patch", {"patch_id": flow["patch_id"], "verdict": "approve", "reason": "Independent bounded review"})]
        return {"content": None, "tool_calls": calls, "usage": {"prompt_tokens": 2, "completion_tokens": 2}, "tool_call_errors": []}
    monkeypatch.setattr(chat, "AGENT_LLM_TURN_SPEC", replace(chat.AGENT_LLM_TURN_SPEC, handler=response))


def test_choice_harness_reselects_without_regenerating_candidates(app_ctx, media, monkeypatch, tmp_path):
    from hybrid import choice
    from tests.test_v4_execution import setup, image_node, video_node
    from tests.test_v9_choices import select_node
    nodes = [image_node(f"option_{index}") for index in range(3)]
    for index, node in enumerate(nodes):
        node["inputs"]["prompt"] += f" style {index}"
    refs = [{"ref": f"option_{index}.image"} for index in range(3)]
    nodes.extend([select_node(refs), video_node(source="choice")])
    run, _, _ = setup(nodes, deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    harness = _offline_harness(app_ctx, monkeypatch, tmp_path, run, "offline-choice")
    _stub_director(monkeypatch, {"op": "update_inputs", "node_id": "choice", "inputs": {"candidate_artifact_ids": refs}})
    choice(harness)
    result = harness.close()
    assert result["status"] == "passed"
    assert media.summary()["mock_images_written"] == 3
    assert media.summary()["mock_videos_written"] == 2


@pytest.mark.parametrize("revise", [False, True])
def test_story_delivery_and_revision_use_real_local_compose_qc_zip(app_ctx, media, monkeypatch, tmp_path, revise):
    from hybrid import delivery, story
    from tests.test_v4_execution import setup, image_node, video_node
    nodes = []
    for index in range(3):
        image = image_node(f"frame_{index}", gate="preview")
        image["inputs"]["prompt"] += f" place {index}"
        clip = video_node(f"clip_{index}", source=f"frame_{index}")
        nodes.extend([image, clip])
    refs = [{"ref": f"clip_{index}.video"} for index in range(3)]
    nodes.extend([
        {"id": "joined", "tool": "compose_video", "inputs": {"video_artifact_ids": refs}, "rationale": "Join scenes"},
        {"id": "probe", "tool": "probe_media", "inputs": {"artifact_id": {"ref": "joined.artifact_id"}}, "rationale": "Probe"},
        {"id": "qc", "tool": "qc_video", "inputs": {"artifact_id": {"ref": "joined.artifact_id"}, "video_artifact_ids": refs}, "depends_on": ["probe"], "rationale": "QC"},
        {"id": "package", "tool": "package_story", "inputs": {"artifact_id": {"ref": "joined.artifact_id"}}, "depends_on": ["qc"], "rationale": "Package"},
    ])
    run, _, _ = setup(nodes, deliverables=[{"kind": "package", "node_id": "package", "output": "artifact_id"}])
    harness = _offline_harness(app_ctx, monkeypatch, tmp_path, run, "offline-story")
    if revise:
        _stub_director(monkeypatch, {"op": "update_inputs", "node_id": "clip_2", "inputs": {"prompt": "The cat dances gently on a rainy night"}})
        story(harness)
    else:
        delivery(harness)
    result = harness.close()
    assert result["status"] == "passed" and result["evidence"]["downloads"][0]["kind"] == "package"
    assert result["tasks"]["qc"]["output"]["passed"]
    assert media.summary()["mock_images_written"] == 3
    assert media.summary()["mock_videos_written"] == (4 if revise else 3)



def test_nonzero_safety_counters_fail_report_even_without_scenario_exception(app_ctx, media, tmp_path):
    from hybrid import Harness
    meter = SimpleNamespace(set_label=lambda _label: None, snapshot=lambda: {"real_calls": 0,
        "real_image_calls": 1, "real_video_calls": 0, "blocked_network_attempts": 1})
    evaluation = SimpleNamespace(app=app_ctx, WORK=tmp_path, HERE=tmp_path, METER=meter)
    result = Harness(evaluation, None, "offline-safety-counter", None).close()
    assert result["status"] == "failed" and not result["safety_assertions"]["passed"]
    assert "safety counter assertion" in result["failure"]["message"]


def test_timeline_order_follows_delivered_composition_not_node_declaration():
    from hybrid import ordered_video_nodes
    plan = {"nodes": [
        {"id": "clip_c", "tool": "animate_shot", "inputs": {}},
        {"id": "clip_a", "tool": "animate_shot", "inputs": {}},
        {"id": "clip_b", "tool": "animate_shot", "inputs": {}},
        {"id": "unused_join", "tool": "compose_video", "inputs": {"video_artifact_ids": [{"ref": "clip_c.video"}]}},
        {"id": "master", "tool": "compose_video", "inputs": {"video_artifact_ids": [
            {"ref": "clip_a.video"}, {"ref": "clip_b.video"}, {"ref": "clip_c.video"}]}},
        {"id": "zip", "tool": "package_story", "inputs": {"artifact_id": {"ref": "master.artifact_id"}}},
    ], "deliverables": [{"kind": "package", "node_id": "zip", "output": "artifact_id"}]}
    assert ordered_video_nodes(plan) == ["clip_a", "clip_b", "clip_c"]


def test_wrong_director_target_is_rejected_before_manual_approval_is_queued():
    from hybrid import story
    nodes = [{"id": f"clip_{index}", "tool": "animate_shot", "inputs": {}} for index in range(3)]
    class FakeHarness:
        result = {"evidence": {}}
        approved = False
        def approve_plan(self):
            pass
        def drive(self):
            return {"nodes": nodes, "plan": {"nodes": nodes, "deliverables": []}, "results": []}
        def tasks(self):
            return {}
        def generation_receipts(self):
            return set()
        def version(self):
            return 1
        def action(self, action, **body):
            assert action == "revise_plan"
        def pending_patch(self, scope):
            return {"patch_id": "wrong"}, {"automatic": {"eligible": False}, "affected_node_ids": ["clip_0"]}
        def approve_quoted_patch(self, patch, quote):
            self.approved = True
    harness = FakeHarness()
    with pytest.raises(ScenarioFailure, match="third shot"):
        story(harness)
    assert not harness.approved
