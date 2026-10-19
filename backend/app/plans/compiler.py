"""Read-only, typed Plan IR compiler. Nothing here authorizes execution."""

from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
import math
import re

from flask import current_app
from pydantic import ValidationError

from app.adapters import ADAPTERS
from app.agent.model_selection import TRANSFORM_MODES, validate_generation_model
from app.agent.production_plan import select_plan_model
from app.agents.schemas import PlanDraft, RequirementBrief, finite_json
from app.agents.workspace import require_artifact
from app.api import AppError
from app.extensions import db
from app.models import AgentWorkspaceItem
from app.plans.schemas import PlanEstimates
from app.services.model_service import ModelService
from app.services.storage_service import StorageService
from app.tools.budget import estimate_model_cost
from app.tools.spec import ToolContext
from app.tools.specs.list_models import public_pricing

PLAN_TOOLS = frozenset({"generate_image", "animate_shot", "generate_video", "transform_video",
    "extract_frame", "retain_video_segment", "compose_video", "probe_media", "qc_video", "package_story", "select_image"})
GENERATION_TOOLS = frozenset({"generate_image", "animate_shot", "generate_video", "transform_video"})
VERSION_TOOLS = frozenset({"compose_video", "probe_media", "qc_video", "package_story"})
MEDIA_TYPES = frozenset({"image", "video", "audio", "document", "package"})
TRANSFORM_TYPES = {"reference_image": "image", "reference_video": "video", "reference_audio": "audio", "file": "document"}
_REF = re.compile(r"^([a-z0-9_]{1,40})\.([A-Za-z0-9_]{1,80})$")


def authoring_plan(raw):
    """Remove only compiler-owned envelope fields from a stored ExecutionPlan."""
    value = deepcopy(raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw)
    if isinstance(value, dict):
        for name in ("plan_version", "estimates", "experimental"):
            value.pop(name, None)
    return value


def plan_digest(raw):
    value = PlanDraft.model_validate(authoring_plan(raw)).model_dump(mode="json")
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def request_spec_for_run(run):
    """Project a validated brief into the existing model-policy-only schema."""
    row = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, kind="brief").order_by(AgentWorkspaceItem.id.desc()).first()
    if row is None:
        raise AppError("BRIEF_REQUIRED", "A validated requirement brief is required before compiling a plan", 422)
    brief = RequirementBrief.model_validate(row.payload)
    return {"deliverable": brief.deliverable, "recipe_hint": "image_create" if brief.deliverable == "image" else "single_clip",
            "summary": brief.summary, "confidence": brief.confidence, "constraints": brief.constraints.model_dump(mode="json")}


def node_inputs(node, *, plan_version=1):
    """Build the exact tool payload while retaining unresolved typed references."""
    value = deepcopy(node.model_dump(mode="json") if hasattr(node, "model_dump") else node)
    inputs = deepcopy(value.get("inputs") or {})
    if set(inputs) & {"model_id", "params", "template_id", "plan_version"}:
        raise AppError("RESERVED_INPUT", "Model, parameters, template and version cannot be supplied inside inputs", 422)
    if value["tool"] == "select_image" and "selected_artifact_id" in inputs:
        raise AppError("RESERVED_INPUT", "Only a user choice can supply the selected image", 422)
    if value["tool"] in GENERATION_TOOLS:
        inputs.update(model_id=value.get("model_id"), params=deepcopy(value.get("params") or {}))
    elif value.get("model_id") is not None or value.get("params"):
        raise AppError("INVALID_NODE_MODEL", "Local tools do not accept a generation model or parameters", 422)
    if value["tool"] in VERSION_TOOLS:
        inputs["plan_version"] = plan_version
    return inputs


def resolve_inputs(value, outputs):
    """Resolve strict reference objects without flattening array-valued outputs."""
    if isinstance(value, list):
        return [resolve_inputs(item, outputs) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    if "artifact" in value:
        if set(value) != {"artifact"} or not isinstance(value["artifact"], str) or not value["artifact"]:
            raise AppError("INVALID_REFERENCE", "Artifact references must contain one non-empty ID", 422)
        return value["artifact"]
    if "ref" in value:
        match = _REF.fullmatch(value["ref"]) if isinstance(value["ref"], str) else None
        if set(value) != {"ref"} or match is None:
            raise AppError("INVALID_REFERENCE", "References must have the form node.output", 422)
        node, field = match.groups()
        if node not in outputs or field not in outputs[node] or outputs[node][field] is None:
            raise AppError("MISSING_PLAN_OUTPUT", "A referenced node output is unavailable", 422)
        return deepcopy(outputs[node][field])
    return {key: resolve_inputs(item, outputs) for key, item in value.items()}


def _refs(value):
    if isinstance(value, list):
        for item in value:
            yield from _refs(item)
    elif isinstance(value, dict):
        if "ref" in value:
            match = _REF.fullmatch(value["ref"]) if isinstance(value["ref"], str) else None
            if set(value) != {"ref"} or match is None:
                raise AppError("INVALID_REFERENCE", "References must be pure node.output objects", 422)
            yield match.groups()
        elif "artifact" in value:
            if set(value) != {"artifact"} or not isinstance(value["artifact"], str) or not value["artifact"]:
                raise AppError("INVALID_REFERENCE", "Artifact references must be pure ID objects", 422)
        else:
            for item in value.values():
                yield from _refs(item)


def _has_reference(value):
    if isinstance(value, list):
        return any(_has_reference(item) for item in value)
    return isinstance(value, dict) and (bool(set(value) & {"ref", "artifact"}) or any(_has_reference(item) for item in value.values()))


def _seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise AppError("UNKNOWN_MEDIA_DURATION", "A verified positive video duration is required", 422)
    return float(value)


def _artifact_info(artifact_id, run, cache):
    if artifact_id in cache:
        return cache[artifact_id]
    ctx = ToolContext(role="production", budget_scope=run.run_id)
    artifact = require_artifact(artifact_id, ctx, run=run)
    mime = artifact.mime_type or ""
    kind = next((name for name in ("image", "video", "audio") if mime.startswith(name + "/")), None)
    if artifact.artifact_type in {"agent_attachment_document", "agent_reference_document"}:
        kind = "document"
    if artifact.artifact_type == "story_package":
        kind = "package"
    if kind is None:
        raise AppError("INVALID_ARTIFACT_TYPE", "Artifact has no supported Plan media type", 422)
    result = {"type": kind, "artifact_id": artifact_id}
    if kind in {"video", "audio"}:
        from app.services.media_probe_service import MediaProbeService
        from app.services.wan3_media_service import Wan3MediaService
        path = StorageService.resolve(artifact.file_path)
        if kind == "audio":
            result["duration_sec"] = _seconds(Wan3MediaService.inspect(path, "audio")["duration_sec"])
        else:
            # Mock sentinel bytes do not prove a duration. Their completed plan
            # task or upload metadata must supply the server-owned bound.
            media = (artifact.meta or {}).get("media") or {}
            bound = media.get("duration_sec", media.get("duration"))
            if bound is None:
                marker = (artifact.meta or {}).get("plan_output") or {}
                bound = marker.get("duration_sec")
            measured = MediaProbeService.probe(path, decode=False, mock_duration_sec=bound)
            result["duration_sec"] = _seconds(measured["duration_sec"])
    cache[artifact_id] = result
    return result


def _placeholder(node, field, metadata):
    kind = metadata["type"]
    if kind.endswith("[]"):
        return [f"plan_{node}_{field}_{index}" for index in range(metadata.get("count", 1))]
    if kind == "json":
        return {} if field not in {"checks", "warnings"} else []
    return f"plan_{node}_{field}"


def _resolve_typed(value, expected, output_metadata, run, cache):
    """Return schema placeholder and its trusted media descriptor(s)."""
    if isinstance(value, dict) and "ref" in value:
        refs = list(_refs(value))
        node, field = refs[0]
        metadata = output_metadata.get(node, {}).get(field)
        if metadata is None:
            raise AppError("MISSING_PLAN_OUTPUT", "Referenced output does not exist or is optional and unavailable", 422)
        if metadata["type"] != expected:
            raise AppError("PLAN_TYPE_MISMATCH", f"Expected {expected}, received {metadata['type']}", 422)
        metas = metadata.get("items") if expected.endswith("[]") else metadata
        if expected.endswith("[]") and metas is None:
            metas = [{"type": expected[:-2]} for _ in range(metadata.get("count", 1))]
        return _placeholder(node, field, metadata), deepcopy(metas)
    if expected.endswith("[]"):
        if not isinstance(value, list):
            raise AppError("PLAN_TYPE_MISMATCH", f"Expected a {expected} array", 422)
        resolved = [_resolve_typed(item, expected[:-2], output_metadata, run, cache) for item in value]
        return [item[0] for item in resolved], [item[1] for item in resolved]
    if expected in MEDIA_TYPES:
        if isinstance(value, dict):
            if set(value) != {"artifact"}:
                raise AppError("INVALID_REFERENCE", "Media values require artifact or node output references", 422)
            value = resolve_inputs(value, {})
        if not isinstance(value, str) or not value:
            raise AppError("PLAN_TYPE_MISMATCH", "Media input must contain an artifact ID", 422)
        metadata = _artifact_info(value, run, cache)
        if metadata["type"] != expected:
            raise AppError("PLAN_TYPE_MISMATCH", f"Expected {expected}, received {metadata['type']}", 422)
        return value, deepcopy(metadata)
    if _has_reference(value):
        raise AppError("INVALID_REFERENCE", "References are not allowed inside an untyped literal", 422)
    return deepcopy(value), {"type": expected}


def _typed_inputs(node, spec, outputs, run, cache, plan_version):
    payload = node_inputs(node, plan_version=plan_version)
    metadata = {}
    declared = spec.io_types.get("inputs", {})
    for field, value in list(payload.items()):
        if node["tool"] == "transform_video" and field == "media":
            if not isinstance(value, list) or not 1 <= len(value) <= 20:
                raise AppError("INVALID_TRANSFORM_MEDIA", "Transform requires 1 to 20 ordered media references", 422)
            resolved, items = [], []
            for item in value:
                if not isinstance(item, dict) or set(item) != {"type", "artifact_id"} or item["type"] not in TRANSFORM_TYPES:
                    raise AppError("INVALID_TRANSFORM_MEDIA", "Invalid transform media reference", 422)
                artifact, info = _resolve_typed(item["artifact_id"], TRANSFORM_TYPES[item["type"]], outputs, run, cache)
                resolved.append({"type": item["type"], "artifact_id": artifact})
                items.append({**info, "reference_type": item["type"], "resolved_id": artifact})
            payload[field], metadata[field] = resolved, items
        elif node["tool"] == "transform_video" and field == "source_artifact_id" and value is not None:
            payload[field], metadata[field] = _resolve_typed(value, "video", outputs, run, cache)
        elif field in declared and value is not None:
            payload[field], metadata[field] = _resolve_typed(value, declared[field], outputs, run, cache)
        elif _has_reference(value):
            raise AppError("UNTYPED_REFERENCE", "Only declared typed inputs may contain references", 422)
    return payload, metadata


def _transform_seconds(payload, input_metadata, model, params):
    from app.adapters.dashscope_wan3 import MODEL_IDS
    from app.services.wan3_media_service import Wan3MediaService
    if model.provider != "dashscope" or model.adapter_name != "dashscope_wan3" or model.model_id not in MODEL_IDS:
        raise AppError("MODEL_CAPABILITY_MISMATCH", "Transform requires the integrated Wan 3 protocol", 422)
    items = input_metadata["media"]
    counts = {kind: sum(item["reference_type"] == kind for item in items) for kind in TRANSFORM_TYPES}
    if any(counts[kind] > limit for kind, limit in {"reference_image": 10, "reference_video": 5, "reference_audio": 5, "file": 1}.items()):
        raise AppError("INVALID_TRANSFORM_MEDIA", "Transform media exceeds per-type limits", 422)
    if len({item["resolved_id"] for item in items}) != len(items):
        raise AppError("INVALID_TRANSFORM_MEDIA", "Transform media cannot repeat", 422)
    if counts["file"] and params.get("prompt_extend") is not True:
        raise AppError("INVALID_TRANSFORM_MEDIA", "Document references require prompt_extend=true", 422)
    # Existing media receives the full Wan3 format/dimension/size inspection.
    # Future data can only be bounded here; runtime must inspect the actual file.
    from app.models import Artifact
    for item in items:
        if item.get("artifact_id"):
            artifact = Artifact.query.filter_by(artifact_id=item["artifact_id"]).one()
            inspected = Wan3MediaService.inspect(StorageService.resolve(artifact.file_path),
                "file" if item["type"] == "document" else item["type"])
            if item["type"] in {"video", "audio"}:
                item["duration_sec"] = _seconds(inspected["duration_sec"])
    incoming = sum(_seconds(item.get("duration_sec")) for item in items if item["type"] == "video")
    audio = sum(_seconds(item.get("duration_sec")) for item in items if item["type"] == "audio")
    if incoming > 15 or audio > 15 or incoming + params["duration"] > 30:
        raise AppError("INVALID_TRANSFORM_DURATION", "Reference video/audio and input-plus-output duration exceed Wan3 limits", 422)
    videos = [item for item in items if item["type"] == "video"]
    operation = payload["operation"]
    if operation in {"edit", "extend"}:
        if not videos or payload.get("source_artifact_id") != videos[0]["resolved_id"]:
            raise AppError("INVALID_TRANSFORM_SOURCE", "Editing/extension requires its source as the first video reference", 422)
        if operation == "extend" and params["duration"] <= videos[0]["duration_sec"]:
            raise AppError("INVALID_TRANSFORM_DURATION", "Extended output must be longer than its full source", 422)
    elif payload.get("source_artifact_id") is not None:
        raise AppError("INVALID_TRANSFORM_SOURCE", "Reference generation does not choose a primary source", 422)
    pricing = (model.capabilities or {}).get("pricing") or {}
    if pricing.get("unit") != "second" or pricing.get("billing_basis") != "input_plus_output_seconds":
        raise AppError("INVALID_TRANSFORM_PRICING", "Transform pricing must include input and output seconds", 422)
    return incoming


def _generation(node, payload, input_metadata, request_spec, run):
    tool = node["tool"]
    if tool == "animate_shot":
        mode = "i2v"
        count = 1 + int(bool(payload.get("last_frame_artifact_id")))
    elif tool == "transform_video":
        mode = {"reference": "omni_reference", "edit": "video_edit", "extend": "video_extend"}.get(payload.get("operation"))
        if mode is None:
            raise AppError("INVALID_INPUT", "Unsupported transform operation", 422)
        count = sum(item["reference_type"] == "reference_image" for item in input_metadata["media"])
    else:
        mode = payload.get("mode", "t2i" if tool == "generate_image" else None)
        count = (len(payload.get("reference_artifact_ids") or []) if mode != "i2v" else int(bool(payload.get("first_frame_artifact_id"))))
    model_id = ModelService.canonical_model_id(node.get("model_id")) if node.get("model_id") else None
    model = select_plan_model(request_spec, mode, model_id, run=run)
    if model.adapter_name not in ADAPTERS:
        raise AppError("MODEL_CAPABILITY_MISMATCH", "Model adapter is not integrated", 422)
    params = deepcopy(node["params"])
    if tool == "generate_image" and payload.get("n") is not None:
        params["n"] = payload["n"]
    params = validate_generation_model(model, mode, params, reference_count=count)
    if tool != "generate_image" and params.get("n_outputs", 1) != 1:
        raise AppError("INVALID_OUTPUT_COUNT", "Each video node must produce exactly one video", 422)
    if tool == "animate_shot":
        from app.tools.specs.animate_shot import AnimateShotInput, validate_bridge
        validate_bridge(AnimateShotInput.model_validate({**payload, "params": params, "model_id": model.model_id}), model)
    if mode == "i2v" and count != (2 if tool == "animate_shot" and payload.get("last_frame_artifact_id") else 1):
        raise AppError("INVALID_REFERENCE_COUNT", "Image-to-video requires one first frame or an enabled frame pair", 422)
    incoming = _transform_seconds(payload, input_metadata, model, params) if mode in TRANSFORM_MODES else 0.0
    node["model_id"], node["params"] = model.model_id, params
    if tool == "generate_image":
        node["inputs"].pop("n", None)
    return {"node_id": node["id"], "model_id": model.model_id, "mode": mode,
        "estimated_cost": estimate_model_cost(model, params, input_video_seconds=incoming),
        "input_video_seconds": incoming, "output_video_seconds": 0.0 if tool == "generate_image" else params["duration"],
        "pricing": public_pricing(model)}


def _output_metadata(node, spec, payload, inputs, estimate):
    result = {field: {"type": kind} for field, kind in spec.io_types["outputs"].items()}
    if node["tool"] == "generate_image":
        count = node["params"].get("n", 1)
        result["images"].update(count=count, items=[{"type": "image"} for _ in range(count)])
    elif node["tool"] in {"animate_shot", "generate_video", "transform_video"}:
        result["video"]["duration_sec"] = estimate["output_video_seconds"]
    elif node["tool"] == "compose_video":
        duration = sum(_seconds(item.get("duration_sec")) for item in inputs["video_artifact_ids"])
        result["artifact_id"]["duration_sec"] = duration
        if payload.get("compress_output"):
            result["compressed_artifact_id"]["duration_sec"] = duration
        else:
            result.pop("compressed_artifact_id", None)
    elif node["tool"] == "retain_video_segment":
        start, end = payload["source_start_sec"], payload["source_end_sec"]
        if end <= start or end > _seconds(inputs["video_artifact_id"].get("duration_sec")):
            raise AppError("INVALID_SOURCE_RANGE", "Retained segment must lie inside the complete source video", 422)
        result["artifact_id"]["duration_sec"] = end - start
    elif node["tool"] == "extract_frame" and payload.get("timestamp_sec") is not None:
        if payload["timestamp_sec"] > _seconds(inputs["video_artifact_id"].get("duration_sec")):
            raise AppError("INVALID_SOURCE_RANGE", "Frame timestamp exceeds the source video", 422)
    return result


def _provenance(plan, run):
    if any(node["origin"].get("blueprint") is None for node in plan["nodes"]):
        return False
    digest = plan_digest(plan)
    receipts = (run.snapshot or {}).get("v3_blueprint_receipts", [])
    if isinstance(receipts, dict):
        receipts = list(receipts.values())
    for receipt in receipts:
        if (isinstance(receipt, dict) and digest in {receipt.get("raw_hash"), receipt.get("normalized_hash")}
                and all(node["origin"]["blueprint"] == {"name": receipt.get("name"), "version": receipt.get("version")} for node in plan["nodes"])):
            return True
    return False


def _issue_message(error):
    """Actionable node issue text (V-Gate3): real planners could not converge on
    bare "cannot execute" / "does not match" messages. Field locations, catalog
    reasons and allowed models are appended; submitted values are never echoed."""
    base = getattr(error, "message", "Node input or output does not match the executable contract")
    details = []
    if isinstance(error, ValidationError):
        details = [f"{'.'.join(str(part) for part in item.get('loc', ()))}: {item.get('msg', '')}"
                   for item in error.errors(include_url=False, include_context=False, include_input=False)[:6]]
    elif isinstance(error, AppError):
        payload = error.payload if isinstance(error.payload, dict) else {}
        raw = payload.get("errors") or []
        for item in raw[:6]:
            if isinstance(item, dict):
                details.append(f"{'.'.join(str(part) for part in item.get('loc', ()))}: {item.get('msg', '')}")
            elif item and str(item) not in base:
                details.append(str(item))
        if payload.get("allowed_model_ids"):
            details.append("allowed models: " + ", ".join(map(str, payload["allowed_model_ids"][:8])))
    elif isinstance(error, KeyError):
        details = [f"missing key {error}"]
    text = base + (" — " + "; ".join(details) if details else "")
    return text[:600]


def compile_plan(raw, run, *, registry=None, plan_version=1):
    """Compile without writes, launches, LLM calls or any authority mutation."""
    with db.session.no_autoflush:
        return _compile(raw, run, registry=registry, plan_version=plan_version)


def _compile(raw, run, *, registry, plan_version):
    if registry is None:
        from app.tools import build_v3_registry
        registry = build_v3_registry()
    issues, estimates, validated, outputs, cache = [], [], {}, {}, {}
    dag = {"order": [], "dependencies": {}, "children": {}}
    def issue(code, message, node_id=None):
        issues.append({"code": code, "node_id": node_id, "message": message})
    editable = {}
    try:
        editable = finite_json(authoring_plan(raw))
        plan = PlanDraft.model_validate(editable).model_dump(mode="json")
        if type(plan_version) is not int or plan_version < 1:
            raise ValueError("Invalid server plan version")
    except (ValidationError, AppError, ValueError) as error:
        issue(getattr(error, "code", "INVALID_PLAN"), "Plan does not match the authoring schema")
        return {"plan": editable, "issues": issues, "estimates": PlanEstimates().model_dump(), "experimental": True,
                "dag": dag, "validated_inputs": {}, "output_metadata": {}, "source_artifact_ids": [], "input_artifact_metadata": {}}
    try:
        request_spec = request_spec_for_run(run)
    except (AppError, ValidationError) as error:
        request_spec = None
        issue(getattr(error, "code", "INVALID_BRIEF"), "A valid Run requirement brief is required")
    verified_origin = _provenance(plan, run)
    nodes = {node["id"]: node for node in plan["nodes"]}
    stages = {stage["id"] for stage in plan["stages"]}
    dependencies = {node_id: set() for node_id in nodes}
    for node_id, node in nodes.items():
        if node["stage"] is not None and node["stage"] not in stages:
            issue("UNKNOWN_STAGE", "Node refers to an unknown stage", node_id)
        if len(set(node["depends_on"])) != len(node["depends_on"]):
            issue("DUPLICATE_DEPENDENCY", "Node dependencies must be unique", node_id)
        dependencies[node_id].update(node["depends_on"])
        try:
            dependencies[node_id].update(source for source, _field in _refs(node["inputs"]))
        except AppError as error:
            issue(error.code, error.message, node_id)
        for source in sorted(dependencies[node_id] - set(nodes)):
            issue("UNKNOWN_NODE_REFERENCE", "Node refers to an unknown predecessor", node_id)
        dependencies[node_id] &= set(nodes)
    children = {node_id: set() for node_id in nodes}
    for target, sources in dependencies.items():
        for source in sources:
            children[source].add(target)
    pending, depth = set(nodes), {}
    while pending:
        ready = [node_id for node_id in nodes if node_id in pending and not (dependencies[node_id] & pending)]
        if not ready:
            issue("PLAN_CYCLE", "Plan dependencies contain a cycle")
            break
        for node_id in ready:
            dag["order"].append(node_id)
            depth[node_id] = max((depth[item] for item in dependencies[node_id]), default=0) + 1
            pending.remove(node_id)
    dag["dependencies"] = {key: sorted(value) for key, value in dependencies.items()}
    dag["children"] = {key: sorted(value) for key, value in children.items()}
    for node_id in nodes:
        if depth.get(node_id, 0) > 30:
            issue("PLAN_DEPTH_LIMIT", "Plan depth exceeds 30", node_id)
        if len(children[node_id]) > 50:
            issue("PLAN_FANOUT_LIMIT", "Node fan-out exceeds 50", node_id)
    for node_id in dag["order"]:
        node = nodes[node_id]
        try:
            if node["tool"] not in PLAN_TOOLS:
                raise AppError("PLAN_TOOL_FORBIDDEN", "Tool is not in the Plan executable vocabulary", 422)
            spec = registry.get(node["tool"])
            if not spec.plan_executable:
                raise AppError("PLAN_TOOL_FORBIDDEN", "Tool is not Plan executable", 422)
            payload, input_metadata = _typed_inputs(node, spec, outputs, run, cache, plan_version)
            if node["tool"] in GENERATION_TOOLS and payload.get("model_id") is None:
                # A model ID is required by the execution schema, but defaults
                # are resolved only after validating all author-supplied inputs.
                payload["model_id"] = "compiler_pending_model"
            payload = spec.input_model.model_validate(payload).model_dump(mode="json")
            estimate = {"node_id": node_id, "estimated_cost": 0, "input_video_seconds": 0, "output_video_seconds": 0}
            if node["tool"] in GENERATION_TOOLS:
                if request_spec is None:
                    continue
                estimate = _generation(node, payload, input_metadata, request_spec, run)
                payload, input_metadata = _typed_inputs(node, spec, outputs, run, cache, plan_version)
                payload = spec.input_model.model_validate(payload).model_dump(mode="json")
            output = _output_metadata(node, spec, payload, input_metadata, estimate)
            if (node["gate"] == "choice") != (node["tool"] == "select_image"):
                raise AppError("INVALID_CHOICE_GATE", "select_image requires a choice gate, and only select_image may use it", 422)
            if node["gate"] and not any(info["type"] in {"image", "image[]"} for info in output.values()):
                raise AppError("INVALID_PREVIEW_GATE", "Preview gates require an image-producing node", 422)
            if node["tool"] == "compose_video" and payload.get("compress_output") and request_spec and not request_spec["constraints"]["compress_output"]:
                raise AppError("COMPRESSION_NOT_REQUESTED", "Compression requires an explicit user request", 422)
            validated[node_id], outputs[node_id] = payload, output
            estimates.append(estimate)
        except (AppError, ValidationError, KeyError, TypeError, ValueError) as error:
            issue(getattr(error, "code", "INVALID_NODE_INPUT"), _issue_message(error), node_id)
    ancestors = {}
    for node_id in dag["order"]:
        ancestors[node_id] = set(dependencies[node_id]).union(*(ancestors.get(source, set()) for source in dependencies[node_id]))
        node = nodes[node_id]
        if node["tool"] == "package_story":
            compressed = node["inputs"].get("compressed_artifact_id")
            if compressed is not None:
                if not request_spec or not request_spec["constraints"]["compress_output"]:
                    issue("COMPRESSION_NOT_REQUESTED", "Compression requires an explicit user request", node_id)
                source = node["inputs"].get("artifact_id")
                match = (_REF.fullmatch(source["ref"]) if isinstance(source, dict) and set(source) == {"ref"}
                         and isinstance(source["ref"], str) else None)
                source_node, source_field = match.groups() if match else (None, None)
                if (source_field != "artifact_id" or nodes.get(source_node, {}).get("tool") != "compose_video"
                        or not validated.get(source_node, {}).get("compress_output")
                        or compressed != {"ref": f"{source_node}.compressed_artifact_id"}):
                    issue("INVALID_COMPRESSED_COPY", "Packaged compressed copy must come from the same compressed composition as the master", node_id)
            matching = [source for source in ancestors[node_id] if nodes[source]["tool"] == "qc_video"
                        and nodes[source]["inputs"].get("artifact_id") == node["inputs"].get("artifact_id")]
            if not matching:
                issue("QC_REQUIRED", "Packaging requires a QC predecessor for the same video", node_id)
    total_seconds = 0.0
    counted_videos = set()
    for target in plan["deliverables"]:
        metadata = outputs.get(target["node_id"], {}).get(target["output"])
        if metadata is None:
            issue("INVALID_DELIVERABLE", "Deliverable output is unavailable", target["node_id"])
        elif metadata["type"] not in ({"image", "image[]"} if target["kind"] == "image" else {target["kind"]}):
            issue("INVALID_DELIVERABLE_TYPE", "Deliverable kind does not match its output", target["node_id"])
        elif target["kind"] == "video":
            try:
                identity = (target["node_id"], target["output"])
                if identity not in counted_videos:
                    total_seconds += _seconds(metadata.get("duration_sec"))
                    counted_videos.add(identity)
            except AppError as error:
                issue(error.code, error.message, target["node_id"])
        elif target["kind"] == "package":
            try:
                source = nodes[target["node_id"]]["inputs"].get("artifact_id")
                if isinstance(source, dict) and set(source) == {"ref"}:
                    source_node, source_field = _REF.fullmatch(source["ref"]).groups()
                    identity = (source_node, source_field)
                    seconds = _seconds(outputs[source_node][source_field].get("duration_sec"))
                else:
                    source_id = source.get("artifact") if isinstance(source, dict) else source
                    identity = ("artifact", source_id)
                    seconds = _seconds(_artifact_info(source_id, run, cache).get("duration_sec"))
                if identity not in counted_videos:
                    total_seconds += seconds
                    counted_videos.add(identity)
            except (AppError, AttributeError, KeyError, TypeError) as error:
                issue(getattr(error, "code", "INVALID_DELIVERABLE"), "Packaged video needs a verified duration", target["node_id"])
    generated = sum(item["output_video_seconds"] for item in estimates)
    limit = current_app.config.get("AGENT_V3_MAX_VIDEO_SECONDS", 600)
    if total_seconds > limit or generated > limit:
        issue("PLAN_DURATION_LIMIT", "Delivered or generated video duration exceeds the configured plan limit")
    summary = PlanEstimates(nodes=estimates, total_credits=float(sum(Decimal(str(item["estimated_cost"])) for item in estimates)),
                            video_seconds=total_seconds, generated_video_seconds=generated).model_dump(mode="json")
    experimental = not (verified_origin or _provenance(plan, run))
    plan.update(plan_version=plan_version, estimates=summary, experimental=experimental)
    return {"plan": plan, "issues": issues, "estimates": summary, "experimental": experimental, "dag": dag,
            "validated_inputs": validated, "output_metadata": outputs, "source_artifact_ids": sorted(cache),
            "input_artifact_metadata": deepcopy(cache)}
