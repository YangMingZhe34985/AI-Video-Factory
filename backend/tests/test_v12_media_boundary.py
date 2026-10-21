"""Factory interception and state-safe mixed evaluation regressions."""
import pytest
from tests.test_v10_hybrid import media

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)


@pytest.mark.parametrize("model_id, expected_name", [
    ("wan2.7-image", "dashscope_multimodal_sync"),
    ("wan2.6-image", "dashscope_image"),
])
def test_classic_image_helper_uses_factory_and_preserves_protocol(app_ctx, monkeypatch, model_id, expected_name):
    from app import adapters
    from app.services import node_runner
    from app.services.model_service import ModelService
    model = ModelService.get_model(model_id)
    selected = []
    actual_factory = adapters.get_adapter

    def factory(name, model=None):
        selected.append((name, model))
        return actual_factory(name, model=model)

    monkeypatch.setattr(node_runner, "get_adapter", factory)
    adapter, name, payload, response = node_runner.NodeRunner()._i2i_test_image_adapter_payload(
        model, {"prompt": "Keep the primary person", "source_image": "primary.png",
                "source_images": [{"file_path": "secondary.png"}]})
    assert selected == [(expected_name, model)]
    assert name == expected_name
    assert type(adapter) is adapters.ADAPTERS[expected_name]
    assert payload["input"]["messages"][0]["content"] == [
        {"image": "primary.png"}, {"text": "Keep the primary person"}]
    assert response["provider_task_id"]
    if expected_name == "dashscope_multimodal_sync":
        assert "multimodal-generation/generation" in adapter.create_url()
        assert "enable_interleave" not in payload["parameters"]


def test_eval_factory_intercepts_wan27_local_reference_before_upload(app_ctx, monkeypatch, tmp_path):
    """Red on the former direct constructor, without contacting any provider."""
    from app import adapters
    from app.adapters.dashscope_common import DashScopeGenerationAdapter
    from app.services.model_service import ModelService
    from app.services.node_runner import NodeRunner
    from tests.test_v10_hybrid import mock_media
    uploads = []

    def forbidden_upload(*args, **kwargs):
        uploads.append("upload")
        raise AssertionError("Local evaluation references must never reach provider upload")

    app_ctx.config["MODEL_ADAPTER_MODE"] = "real"
    controller = mock_media.MediaController(tmp_path / "mock-media.jsonl")
    monkeypatch.setattr(mock_media, "CONTROLLER", controller)
    monkeypatch.setitem(adapters.ADAPTERS, "dashscope_multimodal_sync", mock_media.LocalImageAdapter)
    monkeypatch.setattr(DashScopeGenerationAdapter, "upload_local_file_get_oss_url", forbidden_upload)
    reference = tmp_path / "reference.png"
    from PIL import Image
    Image.new("RGB", (640, 360), "blue").save(reference)
    model = ModelService.get_model("wan2.7-image")
    adapter, name, payload, response = NodeRunner()._i2i_test_image_adapter_payload(
        model, {"prompt": "Keep both people", "source_image": str(reference),
                "source_images": [str(reference)]})
    assert name == "dashscope_multimodal_sync"
    assert isinstance(adapter, mock_media.LocalImageAdapter)
    assert app_ctx.config["MODEL_ADAPTER_MODE"] == "real" and adapter.use_mock
    assert uploads == []
    assert payload["inputs"]["source_images"] == [str(reference)]
    assert response["provider_task_id"]
    assert controller.summary()["mock_submissions"] == 1
    assert controller.summary()["real_media_adapter_attempts"] == 0
    assert controller.summary()["actual_real_media_http_calls"] == 0


def harness_without_io():
    from tests.test_v10_hybrid import ScenarioFailure
    from hybrid import Harness
    harness = Harness.__new__(Harness)
    calls = []
    harness.action = lambda *args, **kwargs: calls.append((args, kwargs))
    harness.version = lambda: 1
    harness.result = {"evidence": {}}
    harness.save = lambda: None
    return harness, calls, ScenarioFailure


@pytest.mark.parametrize("status", ["executing", "understanding", "awaiting_result_review", "success", "attention"])
def test_stale_success_preview_never_approved_outside_awaiting_gate(status):
    harness, calls, _ = harness_without_io()
    view = {"status": status, "nodes": [{"node_id": "cast", "gate": "preview",
            "status": "success", "gate_approved": False}]}
    assert harness.gates(view) is False
    assert calls == []


def test_manual_patch_in_attention_remains_available_to_explicit_review():
    harness, calls, _ = harness_without_io()
    view = {"status": "attention", "patches": [{"status": "awaiting_approval"}]}
    harness.observe = lambda: view
    harness.advance = lambda: pytest.fail("review must wait for the user's explicit approval")
    assert harness.drive(stop=("patch_approval",)) is view
    assert calls == []


def test_failed_command_in_attention_is_not_implicitly_retried():
    harness, calls, error_type = harness_without_io()
    view = {"status": "attention", "action_pending": True,
            "error": {"code": "AGENT_RUNTIME_FAILED"}, "nodes": []}
    harness.observe = lambda: view
    harness.advance = lambda: pytest.fail("attention must not replay an interrupted command")
    with pytest.raises(error_type, match="AGENT_RUNTIME_FAILED"):
        harness.drive()
    assert calls == []


def test_attention_reports_failed_node_before_preview_action():
    harness, calls, error_type = harness_without_io()
    view = {"status": "attention", "error": None, "nodes": [
        {"node_id": "cast_gpt", "gate": "preview", "status": "success", "gate_approved": False},
        {"node_id": "kf01", "status": "failed", "error": {
            "code": "INTERNAL_ERROR", "summary": "provider upload blocked before dispatch"}}]}
    harness.observe = lambda: view
    harness.advance = lambda: pytest.fail("attention must not keep advancing")
    with pytest.raises(error_type) as exc:
        harness.drive(max_ticks=2)
    assert "kf01" in str(exc.value) and "INTERNAL_ERROR" in str(exc.value)
    assert calls == []


def test_valid_preview_still_requires_and_uses_awaiting_gate():
    harness, calls, _ = harness_without_io()
    view = {"status": "awaiting_gate", "nodes": [{"node_id": "cast", "gate": "preview",
            "status": "success", "gate_approved": False}]}
    assert harness.gates(view) is True
    assert calls == [(("approve_gate",), {"plan_version": 1, "gate_node_id": "cast"})]


def test_wan27_reference_plan_executes_in_real_chat_mode_with_only_mock_media(app_ctx, media, monkeypatch):
    from app.adapters.dashscope_common import DashScopeGenerationAdapter
    from app.plans import runtime
    from app.services.job_run_service import JobRunService
    from tests.test_v4_execution import setup, image_node, video_node, drain_plan

    monkeypatch.setattr(DashScopeGenerationAdapter, "upload_local_file_get_oss_url",
                        lambda *args, **kwargs: pytest.fail("A local reference reached the provider upload boundary"))
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    cast = image_node("cast")
    frame = image_node("frame")
    frame.update(model_id="wan2.7-image")
    frame["inputs"]["mode"] = "i2i"
    frame["inputs"]["reference_artifact_ids"] = [{"ref": "cast.image"}]
    run, version, registry = setup([cast, frame, video_node(source="frame")],
        deliverables=[{"kind": "video", "node_id": "clip", "output": "video"}])
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    tasks = runtime.latest_tasks(run)
    assert tasks["frame"].inputs["reference_artifact_ids"] == [tasks["cast"].output["image"]]
    assert all(task.status == "success" for task in tasks.values())
    assert media.summary()["mock_images_written"] == 2
    assert media.summary()["mock_videos_written"] == 1
    assert media.summary()["real_media_adapter_attempts"] == 0
    assert media.summary()["actual_real_media_http_calls"] == 0
