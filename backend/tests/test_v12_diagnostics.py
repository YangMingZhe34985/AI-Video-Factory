"""Field-specific compiler diagnostics retain strict Plan validation."""
from copy import deepcopy

import pytest
from app.plans.compiler import compile_plan
from app.plans.schemas import PlanIssue
from tests.test_v3_plan_compiler import make_run, node, plan, counts


@pytest.mark.parametrize("tool, field, expected", [
    ("generate_image", "images", "reference_artifact_ids"),
    ("generate_video", "image", "first_frame_artifact_id"),
    ("animate_shot", "media", "first_frame_artifact_id"),
    ("compose_video", "videos", "video_artifact_ids"),
])
def test_untyped_reference_names_offending_and_legal_inputs(app_ctx, tool, field, expected):
    run = make_run()
    draft = plan([node(), node("bad", tool, {field: {"ref": "image.image"}})])
    before = deepcopy(draft), counts()
    result = compile_plan(draft, run)
    issue = next(row for row in result["issues"] if row["code"] == "UNTYPED_REFERENCE")
    details = issue["details"]
    assert details["node_id"] == issue["node_id"] == "bad"
    assert details["tool"] == tool and details["fields"] == ["inputs." + field]
    assert expected in details["allowed_reference_inputs"]
    assert field not in details["allowed_reference_inputs"]
    assert "bad" not in result["validated_inputs"]
    assert draft == before[0] and counts() == before[1]
    assert PlanIssue.model_validate(issue).details == details


def test_local_parameters_point_to_inputs_without_accepting_misplaced_fields(app_ctx):
    run = make_run(deliverable="video")
    source = node("clip", "generate_video", {"mode": "t2v", "prompt": "cat"}, params={"duration": 5})
    join = node("join", "compose_video", {"video_artifact_ids": [{"ref": "clip.video"}]},
                params={"compress_output": False})
    draft = plan([source, join], [{"kind": "video", "node_id": "join", "output": "artifact_id"}])
    checked = compile_plan(draft, run)
    issue = next(row for row in checked["issues"] if row["code"] == "INVALID_NODE_MODEL")
    assert issue["details"]["fields"] == ["params"]
    assert issue["details"]["field_hints"] == [{"from": "params.compress_output", "to": "inputs.compress_output"}]
    assert "join" not in checked["validated_inputs"]
    join["inputs"]["compress_output"] = join.pop("params")["compress_output"]
    assert not compile_plan(draft, run)["issues"]


def test_reserved_model_input_and_schema_errors_get_locations(app_ctx):
    run = make_run()
    bad = node(inputs={"prompt": "cat", "model_id": "wan2.6-image"})
    issue = next(row for row in compile_plan(plan([bad]), run)["issues"] if row["code"] == "RESERVED_INPUT")
    assert issue["details"]["fields"] == ["inputs.model_id"]
    bad["inputs"] = {"prompt": "cat", "unknown_option": "SECRET_USER_TEXT"}
    issue = next(row for row in compile_plan(plan([bad]), run)["issues"] if row["code"] == "INVALID_NODE_INPUT")
    assert "inputs.unknown_option" in issue["details"]["fields"]
    assert "SECRET_USER_TEXT" not in str(issue)


def test_unknown_tool_does_not_inherit_previous_schema(app_ctx):
    draft = plan([node(), node("bad", "web_search", {"query": "secret"})])
    issue = next(row for row in compile_plan(draft, make_run())["issues"] if row["code"] == "PLAN_TOOL_FORBIDDEN")
    assert issue["details"]["tool"] == "web_search"
    assert issue["details"]["allowed_reference_inputs"] == []
    assert issue["details"]["allowed_input_fields"] == []


def test_check_plan_receipt_keeps_diagnostics_without_launching_generation(app_ctx):
    from app.models import AgentDelegation
    from app.tools import build_v3_registry
    from app.tools.spec import ToolContext
    run = make_run()
    root = AgentDelegation.query.filter_by(run_id=run.run_id, parent_id=None).one()
    ctx = ToolContext(role="producer", caller_agent="producer", delegation_id=root.id,
                      budget_scope=run.run_id, idempotency_key="diagnostic-check")
    draft = plan([node(), node("bad", "animate_shot", {"image": {"ref": "image.image"}})])
    result = build_v3_registry().invoke("check_plan", {"plan": draft}, ctx)
    issue = next(row for row in result["output"]["issues"] if row["code"] == "UNTYPED_REFERENCE")
    assert issue["details"]["allowed_reference_inputs"] == ["first_frame_artifact_id", "last_frame_artifact_id"]
    assert issue["details"]["fields"] == ["inputs.image"]


@pytest.mark.parametrize("reference", [{"ref": "image.images"}, {"ref": "image.absent"},
    {"ref": "image.image", "extra": "SECRET_REFERENCE"}])
def test_typed_reference_refusal_includes_field_without_values(app_ctx, reference):
    run = make_run(deliverable="video")
    draft = plan([node(), node("clip", "animate_shot", {"prompt": "cat", "first_frame_artifact_id": reference})],
                 [{"kind": "video", "node_id": "clip", "output": "video"}])
    before = deepcopy(draft), counts()
    checked = compile_plan(draft, run)
    located = [issue for issue in checked["issues"] if issue.get("details", {}).get("fields") == ["inputs.first_frame_artifact_id"]]
    assert located and located[0]["code"] in {"PLAN_TYPE_MISMATCH", "MISSING_PLAN_OUTPUT", "INVALID_REFERENCE"}
    assert "SECRET_REFERENCE" not in str(located[0]["details"])
    assert "clip" not in checked["validated_inputs"]
    assert draft == before[0] and counts() == before[1]


def test_out_of_scope_artifact_stays_rejected_and_is_not_echoed(app_ctx):
    from tests.test_v3_plan_compiler import image
    foreign = image("other")
    run = make_run()
    draft = plan([node(inputs={"mode": "i2i", "prompt": "cat", "reference_artifact_ids": [{"artifact": foreign}]})])
    before = deepcopy(draft), counts()
    result = compile_plan(draft, run)
    issue = next(row for row in result["issues"] if row.get("details", {}).get("fields") == ["inputs.reference_artifact_ids"])
    assert issue["code"] == "TOOL_FORBIDDEN"
    assert foreign not in str(issue["details"])
    assert not result["validated_inputs"]
    assert draft == before[0] and counts() == before[1]


@pytest.mark.parametrize("references", [[], [{"ref": "image.image"}] * 21])
def test_reference_count_is_still_rejected(app_ctx, references):
    run = make_run()
    draft = plan([node(), node("edit", inputs={"mode": "i2i", "prompt": "cat", "reference_artifact_ids": references})],
                 [{"kind": "image", "node_id": "edit", "output": "images"}])
    result = compile_plan(draft, run)
    assert any(issue["code"] == "INVALID_NODE_INPUT" and issue["node_id"] == "edit" for issue in result["issues"])
    assert "edit" not in result["validated_inputs"]


def test_server_owned_choice_is_never_suggested_as_an_authoring_field(app_ctx):
    draft = plan([node(), node("other"), node("pick", "select_image", {
        "candidate_artifact_ids": [{"ref": "image.image"}, {"ref": "other.image"}],
        "selected_artifact_id": "SECRET_SELECTED"}, gate="choice")],
        [{"kind": "image", "node_id": "pick", "output": "image"}])
    result = compile_plan(draft, make_run())
    issue = next(row for row in result["issues"] if row["code"] == "RESERVED_INPUT")
    assert issue["details"]["fields"] == ["inputs.selected_artifact_id"]
    assert issue["details"]["allowed_input_fields"] == ["candidate_artifact_ids"]
    assert issue["details"]["allowed_reference_inputs"] == ["candidate_artifact_ids"]
    assert "SECRET_SELECTED" not in str(issue["details"])
    assert "pick" not in result["validated_inputs"]


def test_parameters_reference_is_at_node_level_and_stays_rejected(app_ctx):
    result = compile_plan(plan([node(params={"size": {"ref": "image.image"}})]), make_run())
    issue = next(row for row in result["issues"] if row["code"] == "UNTYPED_REFERENCE")
    assert issue["details"]["fields"] == ["params"]
    assert not result["validated_inputs"]


def test_legacy_plan_issue_and_independent_defaults():
    raw = {"code": "INVALID_INPUT", "node_id": "shot", "message": "Invalid input"}
    first, second = PlanIssue.model_validate(raw), PlanIssue.model_validate(raw)
    assert first.details == second.details == {}
    first.details["fields"] = ["inputs.prompt"]
    assert second.details == {}


def test_details_are_bounded_and_do_not_copy_extra_payload_values():
    from app.api import AppError
    from app.plans.diagnostics import issue_details
    from app.tools import build_v3_registry
    spec = build_v3_registry().get("animate_shot")
    err = AppError("PLAN_TYPE_MISMATCH", "generic", 422,
        payload={"field": "inputs.first_frame_artifact_id", "current": "SECRET_VALUE", "expected": "PRIVATE_ID", "path": "C:/secret/file"})
    details = issue_details(err, {"id": "clip", "tool": "animate_shot"}, spec)
    assert details["fields"] == ["inputs.first_frame_artifact_id"]
    assert details["allowed_reference_inputs"] == ["first_frame_artifact_id", "last_frame_artifact_id"]
    assert "SECRET" not in str(details) and "PRIVATE" not in str(details) and "C:/secret" not in str(details)
    err.payload = {"field": "C:/secret/file", "errors": [{"loc": ["x" * 101, "secret/value", i]} for i in range(30)]}
    details = issue_details(err, {"id": "clip", "tool": "animate_shot"}, spec)
    assert len(details["fields"]) <= 8
    assert "secret" not in str(details) and "x" * 101 not in str(details)


def test_transform_reference_fields_use_real_media_paths():
    from app.api import AppError
    from app.plans.diagnostics import issue_details
    from app.tools import build_v3_registry
    spec = build_v3_registry().get("transform_video")
    details = issue_details(AppError("UNTYPED_REFERENCE", "generic", 422),
                            {"id": "transform", "tool": "transform_video"}, spec)
    assert details["allowed_reference_inputs"] == ["media[].artifact_id", "source_artifact_id"]
    assert "media" in details["allowed_input_fields"] and "prompt" in details["allowed_input_fields"]
    assert "plan_hash" not in details["allowed_input_fields"]


def test_typed_reference_existing_field_payload_is_preserved(app_ctx, monkeypatch):
    from app.api import AppError
    from app.plans import compiler
    from app.tools import build_v3_registry
    original = AppError("PLAN_TYPE_MISMATCH", "kept", 409,
        payload={"field": "inputs.media[0].artifact_id", "expected": "image"})
    def refusal(*args, **kwargs):
        raise original
    monkeypatch.setattr(compiler, "_resolve_typed", refusal)
    with pytest.raises(AppError) as caught:
        compiler._typed_inputs({"id": "clip", "tool": "animate_shot", "inputs": {
            "first_frame_artifact_id": {"ref": "image.image"}}},
            build_v3_registry().get("animate_shot"), {}, make_run(), {}, 1)
    assert caught.value is original
    assert original.status_code == 409 and original.message == "kept"
    assert original.payload == {"field": "inputs.media[0].artifact_id", "expected": "image"}


@pytest.mark.parametrize("legacy_payload", [None, "legacy", ["legacy"]])
def test_typed_reference_non_dict_payload_is_safe(monkeypatch, legacy_payload):
    from types import SimpleNamespace
    from app.api import AppError
    from app.plans import compiler
    original = AppError("PLAN_TYPE_MISMATCH", "kept", 409)
    original.payload = legacy_payload
    def refusal(*args, **kwargs):
        raise original
    monkeypatch.setattr(compiler, "_resolve_typed", refusal)
    spec = SimpleNamespace(io_types={"inputs": {"first_frame_artifact_id": "image"}})
    with pytest.raises(AppError) as caught:
        compiler._typed_inputs({"id": "clip", "tool": "animate_shot", "inputs": {
            "first_frame_artifact_id": {"ref": "image.image"}}}, spec, {}, None, {}, 1)
    assert caught.value is original
    assert original.code == "PLAN_TYPE_MISMATCH" and original.status_code == 409
    assert original.message == "kept"
    assert original.payload == {"field": "inputs.first_frame_artifact_id"}
