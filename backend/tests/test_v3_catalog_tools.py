"""v3 planning tools use isolated SQLite, ScriptedLLM and transport stubs only."""

from io import BytesIO
import json

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from app.adapters.qwen_chat import QwenChatAdapter
from app.agent.attachments import upload_attachment
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ApiTask, Artifact, Job, ModelRegistry, ToolInvocation
from app.services.model_service import ModelService
from app.services.storage_service import StorageService
from app.services.wan3_media_service import Wan3MediaService
from app.tools import build_v3_registry
from app.tools.agent_chat import agent_chat
from app.tools.scripted_llm import ScriptedLLM
from app.tools.spec import ToolContext
from app.tools.specs import analyze_images
from app.utils.ids import new_id


pytestmark = pytest.mark.config(AGENT_VISION_MODEL="qwen3.7-plus", AGENT_PLANNER_MODEL="")


def image_attachment(owner="owner"):
    content = BytesIO()
    Image.new("RGB", (256, 256), "blue").save(content, "PNG")
    content.seek(0)
    uploaded = upload_attachment(FileStorage(stream=content, filename="portrait.png", content_type="image/png"), owner)
    return Artifact.query.filter_by(artifact_id=uploaded["attachment_id"]).one()


def make_run(ids=(), owner="owner", snapshot=None):
    row = AgentRun(owner_id=owner, request_key=new_id("request"), request={
        "schema_version": 3, "text": "制作参考图", "attachment_ids": list(ids), "budget_limit": 100,
    }, snapshot=snapshot or {})
    db.session.add(row)
    db.session.commit()
    return row


def context(row=None, **kwargs):
    row = row or make_run()
    return ToolContext(role="director", caller_agent="director", delegation_id=1, agent_step=0,
                       budget_scope=row.run_id, budget_limit=100, **kwargs)


def analyses(ids):
    return {"images": [{"artifact_id": artifact_id, "analysis": {
        "summary": "蓝色参考图片", "subjects": [], "style": "纯色", "text_in_image": "",
        "has_human_face": False, "suggested_role": "style_ref",
    }} for artifact_id in ids]}


def counts():
    return (Job.query.count(), ApiTask.query.count(), ToolInvocation.query.count(), Artifact.query.count())


def quote(registry, nodes, ctx=None):
    return registry.invoke("estimate_cost", {"nodes": nodes}, ctx or context())["output"]


def test_multi_image_mock_one_script_one_ledger_and_replay(app_ctx):
    ids = [image_attachment().artifact_id for _ in range(3)]
    row = make_run(ids)
    script = ScriptedLLM({("vision", 0): {"content": json.dumps(analyses(list(reversed(ids)))),
                                             "usage": {"prompt_tokens": 300, "completion_tokens": 50}}})
    app_ctx.extensions["agent_v3_scripted_llm"] = script
    registry = build_v3_registry()
    before = counts()
    result = registry.invoke("analyze_images", {"artifact_ids": ids, "focus": "共同风格"}, context(row))
    assert [item["artifact_id"] for item in result["output"]["images"]] == ids
    assert script.calls == [("vision", 0)]
    assert counts() == (before[0], before[1], before[2] + 1, before[3])
    assert ToolInvocation.query.one().tool_name == "analyze_images"
    assert registry.invoke("analyze_images", {"artifact_ids": ids, "focus": "共同风格"}, context(row))["replayed"] is True
    assert script.calls == [("vision", 0)]


def test_multi_image_default_example_still_uses_scripted_llm(app_ctx):
    ids = [image_attachment().artifact_id for _ in range(2)]
    row = make_run(ids)
    output = build_v3_registry().invoke("analyze_images", {"artifact_ids": ids}, context(row))["output"]
    assert all("Mock 示例结果" in item["analysis"]["summary"] for item in output["images"])
    assert app_ctx.extensions["agent_v3_scripted_llm"].calls == [("vision", 0)]


def test_requested_analysis_uses_vision_script_separate_from_agent_turn(app_ctx):
    ids = [image_attachment().artifact_id]
    row = make_run(ids)
    script = ScriptedLLM({
        ("producer", 0): {"tool_calls": [{"id": "analyze", "name": "analyze_images", "arguments": {"artifact_ids": ids}}]},
        ("vision", 0): {"content": json.dumps(analyses(ids))},
    })
    app_ctx.extensions["agent_v3_scripted_llm"] = script
    registry = build_v3_registry()

    def producer_context():
        return ToolContext(role="producer", caller_agent="producer", delegation_id=1, agent_step=0,
                           budget_scope=row.run_id, budget_limit=100)

    turn = agent_chat("producer", [{"role": "user", "content": "分析参考图"}],
                      registry.function_schemas(["analyze_images"]), ctx=producer_context(), registry=registry)
    call = turn["tool_calls"][0]
    result = registry.invoke(call["name"], call["arguments"], producer_context())
    assert result["output"]["images"][0]["artifact_id"] == ids[0]
    assert script.calls == [("producer", 0), ("vision", 0)]
    assert [item.tool_name for item in ToolInvocation.query.order_by(ToolInvocation.id)] == ["agent_llm_turn", "analyze_images"]


@pytest.mark.parametrize("ids", [[], ["a", "a"], [str(index) for index in range(9)], [""]])
def test_multi_image_input_limits_before_execution(app_ctx, ids):
    with pytest.raises(AppError) as error:
        build_v3_registry().invoke("analyze_images", {"artifact_ids": ids}, context())
    assert error.value.code == "INVALID_INPUT"
    assert ToolInvocation.query.count() == 0


@pytest.mark.parametrize("case", ["other_owner", "same_owner_other_run", "research_other_run", "not_image"])
def test_multi_image_rejects_unowned_or_nonimage_before_llm(app_ctx, case):
    artifact = image_attachment(owner="other" if case == "other_owner" else "owner")
    row = make_run([] if case == "same_owner_other_run" else [artifact.artifact_id])
    if case == "research_other_run":
        artifact.artifact_type = "agent_reference_image"
        artifact.meta = {**artifact.meta, "reference": {"run_id": "another-run"}}
    if case == "not_image":
        artifact.meta = {**artifact.meta, "media": {"kind": "video"}}
    db.session.commit()
    with pytest.raises(AppError) as error:
        build_v3_registry().invoke("analyze_images", {"artifact_ids": [artifact.artifact_id]}, context(row))
    assert error.value.code in {"ATTACHMENT_NOT_FOUND", "INVALID_ATTACHMENT"}
    assert "agent_v3_scripted_llm" not in app_ctx.extensions


def test_multi_image_accepts_only_current_run_research_image(app_ctx):
    artifact = image_attachment()
    row = make_run()
    artifact.artifact_type = "agent_reference_image"
    artifact.meta = {**artifact.meta, "reference": {"run_id": row.run_id}}
    db.session.commit()
    output = build_v3_registry().invoke("analyze_images", {"artifact_ids": [artifact.artifact_id]}, context(row))["output"]
    assert output["images"][0]["artifact_id"] == artifact.artifact_id


@pytest.mark.parametrize("case", ["missing", "duplicate", "invented", "exhausted"])
def test_multi_image_invalid_script_cannot_fake_analysis(app_ctx, case):
    ids = [image_attachment().artifact_id for _ in range(2)]
    row = make_run(ids)
    response_ids = {"missing": ids[:1], "duplicate": [ids[0], ids[0]], "invented": [ids[0], "invented"]}
    script = ScriptedLLM({"vision": []} if case == "exhausted" else {
        ("vision", 0): {"content": json.dumps(analyses(response_ids[case]))}})
    app_ctx.extensions["agent_v3_scripted_llm"] = script
    with pytest.raises(AppError) as error:
        build_v3_registry().invoke("analyze_images", {"artifact_ids": ids}, context(row))
    assert error.value.code == ("SCRIPT_EXHAUSTED" if case == "exhausted" else "TOOL_FAILED")
    assert script.calls == [("vision", 0)]
    assert ToolInvocation.query.one().status == "failed"


def test_multi_image_stub_submits_all_images_once_and_settles_tokens(app_ctx, monkeypatch):
    ids = [image_attachment().artifact_id for _ in range(3)]
    row = make_run(ids)
    model = ModelService.get_model("qwen3.7-plus")
    model.capabilities = {**model.capabilities, "pricing": {"unit": "call", "credits_per_unit": 1,
                                                          "credits_per_1k_tokens": 0.5}}
    db.session.commit()
    app_ctx.config.update(MODEL_ADAPTER_MODE="real", DASHSCOPE_API_KEY="stub-only")
    requests = []

    def request_json(self, method, url, **kwargs):
        requests.append(kwargs)
        return {"id": "stub", "choices": [{"message": {"content": json.dumps(analyses(ids))}}],
                "usage": {"prompt_tokens": 700, "completion_tokens": 100}}

    monkeypatch.setattr(QwenChatAdapter, "request_json", request_json)
    result = build_v3_registry().invoke("analyze_images", {"artifact_ids": ids}, context(row))
    assert len(requests) == 1
    assert requests[0]["no_retry"] is True
    payload = requests[0]["json"]
    assert payload["tool_choice"] == "none" and not payload.get("tools")
    image_parts = [item for item in payload["messages"][1]["content"] if item["type"] == "image_url"]
    assert len(image_parts) == 3 and all(item["image_url"]["url"].startswith("data:image/png;base64,") for item in image_parts)
    assert result["estimated_cost"] == pytest.approx(0.4)
    assert ToolInvocation.query.count() == 1


@pytest.mark.parametrize("rate", [None, 0.5])
def test_multi_image_freezes_model_and_price_during_request(app_ctx, monkeypatch, rate):
    ids = [image_attachment().artifact_id]
    row = make_run(ids)
    model = ModelService.get_model("qwen3.7-plus")
    pricing = {"unit": "call", "credits_per_unit": 1}
    if rate is not None:
        pricing["credits_per_1k_tokens"] = rate
    model.capabilities = {**model.capabilities, "pricing": pricing}
    db.session.commit()
    app_ctx.config.update(MODEL_ADAPTER_MODE="real", DASHSCOPE_API_KEY="stub-only")

    def request_json(self, method, url, **kwargs):
        assert kwargs["json"]["model"] == "qwen3.7-plus"
        model.capabilities = {**model.capabilities, "pricing": {"unit": "call", "credits_per_unit": 500,
                                                              "credits_per_1k_tokens": 500}}
        db.session.commit()
        app_ctx.config["AGENT_VISION_MODEL"] = "missing-model-after-submit"
        return {"id": "stub", "choices": [{"message": {"content": json.dumps(analyses(ids))}}],
                "usage": {"prompt_tokens": 700, "completion_tokens": 100}}

    monkeypatch.setattr(QwenChatAdapter, "request_json", request_json)
    result = build_v3_registry().invoke("analyze_images", {"artifact_ids": ids}, context(row))
    assert result["estimated_cost"] == pytest.approx(1 if rate is None else 0.4)


@pytest.mark.parametrize("case", ["provider_4xx", "malformed_tool_call"])
def test_multi_image_dispatched_failures_keep_cost_and_never_repeat(app_ctx, monkeypatch, case):
    ids = [image_attachment().artifact_id]
    row = make_run(ids)
    app_ctx.config.update(MODEL_ADAPTER_MODE="real", DASHSCOPE_API_KEY="stub-only")
    calls = []

    def request_json(self, method, url, **kwargs):
        calls.append(kwargs)
        if case == "provider_4xx":
            raise AppError("API_TASK_FAILED", "Stub provider rejected the request", 400)
        return {"id": "stub", "choices": [{"message": {"content": None, "tool_calls": [
            {"id": "bad", "type": "function", "function": {"name": "generate_video", "arguments": "{"}}
        ]}}]}

    monkeypatch.setattr(QwenChatAdapter, "request_json", request_json)
    registry = build_v3_registry()
    with pytest.raises(AppError):
        registry.invoke("analyze_images", {"artifact_ids": ids}, context(row))
    record = ToolInvocation.query.one()
    assert record.status == "failed" and record.estimated_cost == 1
    with pytest.raises(AppError) as error:
        registry.invoke("analyze_images", {"artifact_ids": ids}, context(row))
    assert error.value.code == "RETRY_LIMIT_EXCEEDED"
    assert len(calls) == 1 and calls[0]["no_retry"] is True


def test_multi_image_missing_usage_keeps_reservation_and_insufficient_budget_stops(app_ctx):
    ids = [image_attachment().artifact_id]
    row = make_run(ids)
    model = ModelService.get_model("qwen3.7-plus")
    model.capabilities = {**model.capabilities, "pricing": {"unit": "call", "credits_per_unit": 1,
                                                          "credits_per_1k_tokens": 0.5}}
    db.session.commit()
    script = ScriptedLLM({("vision", 0): {"content": json.dumps(analyses(ids)), "usage": None}})
    app_ctx.extensions["agent_v3_scripted_llm"] = script
    ctx = context(row)
    reserved = analyze_images.estimate(analyze_images.AnalyzeImagesInput(artifact_ids=ids), ctx)
    ctx.budget_limit = reserved - 0.1
    registry = build_v3_registry()
    with pytest.raises(AppError) as error:
        registry.invoke("analyze_images", {"artifact_ids": ids}, ctx)
    assert error.value.code == "BUDGET_EXCEEDED" and not script.calls
    ctx.budget_limit = reserved + 1
    result = registry.invoke("analyze_images", {"artifact_ids": ids}, ctx)
    assert result["estimated_cost"] == pytest.approx(reserved)


def test_multi_image_explicit_key_cannot_replay_across_runs(app_ctx):
    ids = [image_attachment().artifact_id]
    first, second = make_run(ids), make_run(ids)
    registry = build_v3_registry()
    registry.invoke("analyze_images", {"artifact_ids": ids}, context(first, idempotency_key="analysis-key"))
    with pytest.raises(AppError) as error:
        registry.invoke("analyze_images", {"artifact_ids": ids}, context(second, idempotency_key="analysis-key"))
    assert error.value.code == "IDEMPOTENCY_KEY_CONFLICT"


def test_list_models_filters_integrated_capabilities_and_redacts_private_settings(app_ctx):
    model = ModelService.get_model("wan3.0-video")
    model.capabilities = {**model.capabilities, "api_key": "hidden-capability",
                          "provider_capabilities": {"imaginary_mode": {"agent_enabled": True}}}
    model.default_params = {**model.default_params, "api_key": "hidden-default", "endpoint_url": "hidden-url"}
    model.parameter_schema = {**model.parameter_schema, "api_key": {"type": "string", "default": "hidden-schema"}}
    disabled = ModelService.get_model("wan3.0-video-prime")
    disabled.enabled = False
    db.session.commit()
    registry = build_v3_registry()
    before = counts()
    result = registry.invoke("list_models", {"mode": "video_edit", "family": "wan3.0"}, context())
    models = result["output"]["models"]
    assert [item["model_id"] for item in models] == ["wan3.0-video"]
    assert models[0]["integration_status"] == "integrated" and models[0]["verification_status"] == "untested"
    assert "hidden-" not in json.dumps(models) and "provider_capabilities" not in json.dumps(models)
    assert models[0]["pricing"]["billing_basis"] == "input_plus_output_seconds"
    assert registry.invoke("list_models", {"mode": "imaginary_mode"}, context())["output"]["models"] == []
    assert counts() == before and result["invocation_id"] is None


def test_estimate_fragment_uses_effective_defaults_and_has_no_side_effects(app_ctx):
    registry = build_v3_registry()
    before = counts()
    nodes = [{"node_id": "image", "model_id": "qwen-image-3.0-pro", "mode": "t2i", "params": {"n": 2}},
             {"node_id": "video", "model_id": "wan3.0-video", "mode": "t2v",
              "params": {"duration": 6, "resolution": "480P"}}]
    output = quote(registry, nodes)
    assert output["total_credits"] == 12
    assert [item["estimated_cost"] for item in output["nodes"]] == [6, 6]
    assert output["nodes"][0]["params"]["size"] == "1024*1024"
    assert output["nodes"][1]["input_video_seconds"] == 0
    assert counts() == before and output["demo"] is True


@pytest.mark.parametrize("changes", [
    {"params": {"duration": True}}, {"params": {"duration": -1}}, {"params": {"duration": 31}},
    {"params": {"resolution": "4K"}}, {"params": {"unknown": 1}}, {"input_video_seconds": 0},
    {"mode": "imaginary_mode"},
])
def test_estimate_rejects_invalid_or_client_billing_parameters(app_ctx, changes):
    with pytest.raises(AppError):
        quote(build_v3_registry(), [{"model_id": "wan3.0-video", "mode": "t2v", **changes}])
    assert ToolInvocation.query.count() == ApiTask.query.count() == 0


@pytest.mark.parametrize("change", ["disabled", "not_selectable", "provider_only", "invalid_default", "duration_step", "unknown_adapter"])
def test_estimate_validates_enabled_and_effective_generation_capabilities(app_ctx, change):
    model = ModelService.get_model("wan3.0-video")
    if change == "disabled":
        model.enabled = False
    elif change == "not_selectable":
        model.capabilities = {**model.capabilities, "agent_selectable": False}
    elif change == "provider_only":
        model.capabilities = {**model.capabilities, "modes": [], "provider_capabilities": {"t2v": True}}
    elif change == "invalid_default":
        model.default_params = {**model.default_params, "duration": -1}
    elif change == "unknown_adapter":
        model.adapter_name = "not_integrated"
    else:
        model.capabilities = {**model.capabilities, "duration": {"min": 2, "max": 30, "step": 2}}
    db.session.commit()
    with pytest.raises(AppError):
        quote(build_v3_registry(), [{"model_id": model.model_id, "mode": "t2v"}])
    assert ToolInvocation.query.count() == ApiTask.query.count() == 0


def test_estimate_missing_catalog_alias_never_seeds_or_commits_models(app_ctx):
    model = ModelService.get_model("qwen-image-3.0-pro")
    alias = model.display_name
    db.session.delete(model)
    db.session.commit()
    before = ModelRegistry.query.count()
    with pytest.raises(AppError) as error:
        quote(build_v3_registry(), [{"model_id": alias, "mode": "t2i"}])
    assert error.value.code == "MODEL_NOT_FOUND"
    assert ModelRegistry.query.count() == before


def test_estimate_honors_run_model_family_constraints(app_ctx):
    row = make_run(snapshot={"request_spec": {"deliverable": "video", "recipe_hint": "single_clip",
                    "summary": "使用Wan3系列", "constraints": {"model_preferences": ["wan3.0 系列"]}, "confidence": 1}})
    registry = build_v3_registry()
    with pytest.raises(AppError) as error:
        quote(registry, [{"model_id": "wan2.7-t2v", "mode": "t2v"}], context(row))
    assert error.value.code == "MODEL_CAPABILITY_MISMATCH"
    assert quote(registry, [{"model_id": "wan3.0-video", "mode": "t2v"}], context(row))["total_credits"] == 10


def video_reference(monkeypatch, seconds=4.25):
    artifact = image_attachment()
    path = StorageService.root() / "uploads" / (artifact.artifact_id + ".mp4")
    path.write_bytes(b"isolated-media-inspection-stub")
    artifact.file_path, artifact.file_name = str(path), path.name
    artifact.artifact_type, artifact.mime_type = "source_video", "video/mp4"
    artifact.meta = {"media": {"kind": "video", "duration": 0.01}}
    db.session.commit()
    calls = []

    def inspect(source, kind):
        calls.append((source, kind))
        assert source == path and kind == "video"
        return {"duration_sec": seconds, "width": 320, "height": 180, "fps": 10,
                "page_count": None, "mime_type": "video/mp4"}

    monkeypatch.setattr(Wan3MediaService, "inspect", inspect)
    return artifact, calls


def transform_node(artifact, duration=8):
    return {"model_id": "wan3.0-video", "mode": "video_extend", "params": {"duration": duration},
            "media": [{"type": "reference_video", "artifact_id": artifact.artifact_id}],
            "source_artifact_id": artifact.artifact_id}


def test_transform_estimate_measures_owned_video_instead_of_artifact_claim(app_ctx, monkeypatch):
    artifact, calls = video_reference(monkeypatch)
    row = make_run([artifact.artifact_id])
    before = counts()
    output = quote(build_v3_registry(), [transform_node(artifact)], context(row))
    assert output["nodes"][0]["input_video_seconds"] == 4.25
    assert output["total_credits"] == 24.5
    assert len(calls) == 1 and counts() == before


@pytest.mark.parametrize("case", ["unowned", "input_limit", "combined_limit", "not_extended", "missing_source"])
def test_transform_estimate_rejects_missing_or_invalid_media_evidence(app_ctx, monkeypatch, case):
    artifact, calls = video_reference(monkeypatch, seconds=16 if case == "input_limit" else 4.25)
    row = make_run([] if case == "unowned" else [artifact.artifact_id])
    node = transform_node(artifact, duration=27 if case == "combined_limit" else 4 if case == "not_extended" else 8)
    if case == "missing_source":
        node.pop("source_artifact_id")
    with pytest.raises(AppError):
        quote(build_v3_registry(), [node], context(row))
    assert ToolInvocation.query.count() == ApiTask.query.count() == 0
    if case in {"unowned", "missing_source"}:
        assert calls == []
