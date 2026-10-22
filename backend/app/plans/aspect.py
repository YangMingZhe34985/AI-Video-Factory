"""Deterministic v3 output geometry, independent of prompts and node names."""

from copy import deepcopy
from math import ceil, floor, gcd, sqrt
import re

from app.api import AppError

ASPECTS = frozenset({"16:9", "9:16", "1:1", "4:3", "3:4"})
VIDEO_GENERATORS = frozenset({"animate_shot", "generate_video", "transform_video"})


def dimensions(size):
    match = re.fullmatch(r"([1-9][0-9]{0,7})\*([1-9][0-9]{0,7})", str(size or ""))
    return tuple(map(int, match.groups())) if match else None


def ratio_for(width, height):
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        return None
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def geometry(size):
    value = dimensions(size)
    return {"width": value[0], "height": value[1], "aspect_ratio": ratio_for(*value)} if value else {}


def display_ratio(width, height, sar):
    match = re.fullmatch(r"([1-9][0-9]{0,7}):([1-9][0-9]{0,7})", str(sar or ""))
    if match and type(width) is int and type(height) is int:
        return ratio_for(width * int(match[1]), height * int(match[2]))
    return None


def video_geometry(media):
    width, height = media.get("width"), media.get("height")
    if not ratio_for(width, height):
        return {}
    sar = (media.get("video") or {}).get("sar") if not media.get("display_transform_unverified") else None
    value = display_ratio(width, height, sar)
    result = {"width": width, "height": height, "aspect_ratio": value,
              "sample_aspect_ratio": sar if value else None}
    if value is None:
        result["geometry_unverified"] = True
    return result


def fit_display_canvas(media, width, height):
    """Fit the measured display shape into an even square-pixel canvas."""
    aspect = video_geometry(media).get("aspect_ratio")
    if aspect is None:
        raise AppError("INVALID_SOURCE", "Explicit canvas normalization requires a verified sample aspect ratio", 422)
    source_width, source_height = map(int, aspect.split(":"))
    if width * source_height <= height * source_width:
        return width, max(2, 2 * ((width * source_height // source_width) // 2))
    return max(2, 2 * ((height * source_width // source_height) // 2)), height


def target_size(aspect, short_edge=720):
    width, height = map(int, aspect.split(":"))
    factor = ceil(short_edge / min(width, height))
    if factor % 2:
        factor += 1
    return f"{width * factor}*{height * factor}"


def valid_target(aspect, size):
    value = dimensions(size)
    return (aspect in ASPECTS and value is not None and all(2 <= item <= 8192 and item % 2 == 0 for item in value)
            and ratio_for(*value) == aspect)


def _fail(code, node, field, current, expected):
    valid_literal = isinstance(current, str) and (dimensions(current) is not None
        or re.fullmatch(r"[1-9][0-9]{0,15}:[1-9][0-9]{0,15}", current) is not None)
    catalog_id = (code == "PLAN_ASPECT_RATIO_UNSUPPORTED" and isinstance(current, str)
                  and re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", current) is not None)
    if not valid_literal and not catalog_id:
        current = "unverified geometry" if code == "PLAN_ASPECT_RATIO_UNKNOWN" else "invalid " + type(current).__name__
    detail = {"node_id": node["id"], "tool": node["tool"], "field": field,
              "current": current, "expected": expected}
    raise AppError(code, f"Node {node['id']} field {field}: current {current!r}; expected {expected}.",
                   422, payload=detail)


def _refs(value):
    if isinstance(value, list):
        for item in value:
            yield from _refs(item)
    elif isinstance(value, dict) and set(value) == {"ref"} and isinstance(value["ref"], str):
        parts = value["ref"].split(".")
        if len(parts) == 2:
            yield tuple(parts)


def _auxiliary_cast_roots(plan, deliverable):
    nodes = {node["id"]: node for node in plan["nodes"]}
    cast_roots = set()
    if deliverable == "video":
        for character, references in (plan.get("character_references") or {}).items():
            for reference in references:
                for source, output in _refs(reference):
                    node = nodes.get(source, {})
                    count = (node.get("params") or {}).get("n", (node.get("inputs") or {}).get("n"))
                    count = 1 if count is None else count
                    if (output == "image" and node.get("tool") == "generate_image" and count == 1
                            and node.get("gate") == "preview" and node.get("characters") == [character]):
                        cast_roots.add(source)
    return cast_roots


def constrained_nodes(plan, *, deliverable=None):
    """Follow output use only. Generation reference inputs are not frame inputs."""
    nodes = {node["id"]: node for node in plan["nodes"]}
    cast_roots = _auxiliary_cast_roots(plan, deliverable)
    pending = [(item["node_id"], item["output"]) for item in plan["deliverables"]
               if not (item["kind"] == "image" and item["node_id"] in cast_roots)]
    seen, constrained = set(), set()
    while pending:
        key = pending.pop()
        if key in seen or key[0] not in nodes:
            continue
        seen.add(key)
        node = nodes[key[0]]
        tool, inputs = node["tool"], node["inputs"]
        if tool == "generate_image":
            if key[1] in {"image", "images"}:
                constrained.add(node["id"])
            continue
        if tool in VIDEO_GENERATORS:
            if key[1] == "video":
                constrained.add(node["id"])
                for field in ("first_frame_artifact_id", "last_frame_artifact_id"):
                    pending.extend(_refs(inputs.get(field)))
            continue
        if tool in {"compose_video", "qc_video"}:
            constrained.add(node["id"])
        fields = {"compose_video": ("video_artifact_ids",), "qc_video": ("artifact_id",),
                  "package_story": ("artifact_id",), "probe_media": ("artifact_id",),
                  "retain_video_segment": ("video_artifact_id",), "extract_frame": ("video_artifact_id",),
                  "select_image": ("candidate_artifact_ids",)}.get(tool, ())
        for field in fields:
            pending.extend(_refs(inputs.get(field)))
    packaged_sources = [nodes[source]["inputs"].get("artifact_id") for source, _output in seen
                        if nodes[source]["tool"] == "package_story"]
    for node in plan["nodes"]:
        source = node["inputs"].get("artifact_id")
        if node["tool"] == "qc_video" and (any(reference in seen for reference in _refs(source))
                                            or source in packaged_sources):
            constrained.add(node["id"])
    return constrained


def delivery_geometry_issues(plan, outputs, aspect, *, deliverable=None, known_artifacts=None):
    """Existing segments and direct choices need output proof too."""
    if not aspect:
        return []
    nodes = {node["id"]: node for node in plan["nodes"]}
    exempt = _auxiliary_cast_roots(plan, deliverable)
    issues = []
    for target in plan["deliverables"]:
        node_id = target["node_id"]
        if target["kind"] not in {"image", "video", "package"} or (target["kind"] == "image" and node_id in exempt):
            continue
        metadata = outputs.get(node_id, {}).get(target["output"])
        field = "output." + target["output"]
        if target["kind"] == "package":
            source = nodes[node_id]["inputs"].get("artifact_id")
            references = list(_refs(source))
            if references:
                source_id, source_field = references[0]
                metadata = outputs.get(source_id, {}).get(source_field)
            else:
                source_id = source.get("artifact") if isinstance(source, dict) else source
                metadata = (known_artifacts or {}).get(source_id) if isinstance(source_id, str) else None
            field = "inputs.artifact_id"
        if metadata is None:
            continue  # The compiler reports missing or mistyped outputs separately.
        items = metadata.get("items", []) if metadata.get("type") == "image[]" else [metadata]
        for item in items:
            actual = item.get("aspect_ratio")
            if actual == aspect:
                continue
            try:
                _fail("PLAN_ASPECT_RATIO_UNKNOWN" if actual is None else "PLAN_ASPECT_RATIO_MISMATCH",
                      nodes[node_id], field, actual, aspect)
            except AppError as error:
                issues.append({"code": error.code, "node_id": node_id, "message": error.message})
            break
    return issues


def _image_default(model, aspect):
    schema = model.parameter_schema or {}
    size_rule = schema.get("size", {})
    for size in size_rule.get("enum", size_rule.get("presets", [])):
        if geometry(size).get("aspect_ratio") == aspect:
            return size
    if size_rule.get("format") == "image_size":
        width, height = map(int, aspect.split(":"))
        if not size_rule["min_aspect_ratio"] <= width / height <= size_rule["max_aspect_ratio"]:
            return None
        minimum = 2 * ceil(sqrt(size_rule["min_pixels"] / (width * height)) / 2)
        maximum = 2 * floor(sqrt(size_rule["max_pixels"] / (width * height)) / 2)
        default_size = ((getattr(model, "default_params", None) or {}).get("size") or size_rule.get("default"))
        default = dimensions(default_size)
        desired_area = default[0] * default[1] if default else size_rule["min_pixels"]
        factor = max(minimum, min(maximum, 2 * round(sqrt(desired_area / (width * height)) / 2)))
        if minimum <= maximum:
            return f"{width * factor}*{height * factor}"
    return None


def generation_params(node, model, params, aspect, mode, inputs):
    """Supply supported defaults only; never replace conflicting author intent."""
    result = deepcopy(params)
    if not aspect:
        return result
    for field in ("ratio", "size"):
        if field in result:
            value = geometry(result[field]).get("aspect_ratio") if field == "size" else result[field]
            if value != aspect:
                _fail("PLAN_ASPECT_RATIO_MISMATCH", node, "params." + field, result[field], aspect)
    if mode == "i2v":
        for field in ("first_frame_artifact_id", "last_frame_artifact_id"):
            if field not in inputs:
                continue
            info = inputs[field]
            actual = info.get("aspect_ratio")
            if actual is None:
                _fail("PLAN_ASPECT_RATIO_UNKNOWN", node, "inputs." + field, "unverified geometry", aspect)
            if actual != aspect:
                _fail("PLAN_ASPECT_RATIO_MISMATCH", node, "inputs." + field, actual, aspect)
    schema = model.parameter_schema or {}
    if "ratio" in schema:
        if aspect not in schema["ratio"].get("enum", []):
            _fail("PLAN_ASPECT_RATIO_UNSUPPORTED", node, "params.ratio", model.model_id, aspect)
        result.setdefault("ratio", aspect)
    if "size" in schema:
        if "size" not in result:
            size = _image_default(model, aspect)
            if size is None:
                _fail("PLAN_ASPECT_RATIO_UNSUPPORTED", node, "params.size", model.model_id, aspect)
            result["size"] = size
    if "ratio" not in schema and "size" not in schema and mode != "i2v":
        _fail("PLAN_ASPECT_RATIO_UNSUPPORTED", node, "params", model.model_id, aspect)
    return result


def output_geometry(node, payload, inputs, outputs):
    """Attach geometric intent/provenance without claiming provider execution."""
    tool, params = node["tool"], node["params"]
    value = geometry(params.get("size"))
    if params.get("ratio") in ASPECTS:
        value["aspect_ratio"] = params["ratio"]
    if tool in VIDEO_GENERATORS:
        if not value.get("aspect_ratio") and (tool == "animate_shot" or payload.get("mode") == "i2v"):
            value.update({key: item for key, item in inputs.get("first_frame_artifact_id", {}).items()
                          if key in {"width", "height", "aspect_ratio"}})
        if value.get("aspect_ratio") and "size" not in params:
            resolution = re.fullmatch(r"([1-9][0-9]{2,3})P", str(params.get("resolution", "")))
            if resolution:
                value.update(geometry(target_size(value["aspect_ratio"], int(resolution[1]))))
        outputs["video"].update(value)
        if value.get("aspect_ratio"):
            outputs["video"]["sample_aspect_ratio"] = "1:1"
    elif tool == "generate_image":
        outputs["image"].update(value)
        for item in outputs["images"]["items"]:
            item.update(value)
    elif tool == "select_image":
        candidates = inputs["candidate_artifact_ids"]
        common = {}
        for field in ("aspect_ratio", "width", "height"):
            values = [item.get(field) for item in candidates]
            if values and values[0] is not None and all(item == values[0] for item in values):
                common[field] = values[0]
        outputs["image"].update(common)
    elif tool in {"retain_video_segment", "extract_frame"}:
        value = {key: item for key, item in inputs["video_artifact_id"].items()
                 if key in {"width", "height", "aspect_ratio", "sample_aspect_ratio", "geometry_unverified"}}
        if tool == "extract_frame":
            # PNG decoding does not promise square-pixel normalization for an
            # anamorphic/unknown source. Require normalization or a measured PNG.
            value = ({key: item for key, item in value.items() if key != "sample_aspect_ratio"}
                     if value.get("sample_aspect_ratio") == "1:1" else {"geometry_unverified": True})
        for info in outputs.values():
            if info["type"] in {"image", "video"}:
                info.update(value)
    elif tool == "compose_video" and payload.get("target_size"):
        for info in outputs.values():
            if info["type"] == "video":
                info.update(geometry(payload["target_size"]))
                info["sample_aspect_ratio"] = "1:1"


def delivery_inputs(node, metadata, aspect):
    if node["tool"] not in {"compose_video", "qc_video"}:
        return
    inputs = node["inputs"]
    explicit = inputs.get("target_aspect_ratio")
    target = aspect or (explicit if isinstance(explicit, str) and explicit in ASPECTS else None)
    sources = ([metadata.get("artifact_id", {})] if node["tool"] == "qc_video"
               else metadata.get("video_artifact_ids", []))
    if target and any(source.get("geometry_unverified") for source in sources):
        field = "inputs.artifact_id" if node["tool"] == "qc_video" else "inputs.video_artifact_ids"
        _fail("PLAN_ASPECT_RATIO_UNKNOWN", node, field, None, target)
    if not aspect:
        # A ratio-only authoring input has one deterministic D-048 canvas.
        # Keep explicit pairs and invalid/missing ratios on the strict path.
        if isinstance(explicit, str) and explicit in ASPECTS and inputs.get("target_size") is None:
            aspect = explicit
        else:
            return
    for field in ("target_aspect_ratio", "target_size"):
        if inputs.get(field) is not None:
            current = geometry(inputs[field]).get("aspect_ratio") if field == "target_size" else inputs[field]
            if current != aspect:
                _fail("PLAN_ASPECT_RATIO_MISMATCH", node, "inputs." + field, inputs[field], aspect)
    # QC inherits the exact approved composition canvas; it cannot silently
    # accept a different size even where both sizes have the requested ratio.
    source = metadata.get("artifact_id", {}) if node["tool"] == "qc_video" else (metadata.get("video_artifact_ids") or [{}])[0]
    inherited = (f"{source['width']}*{source['height']}" if source.get("width") and source.get("height")
                 and source.get("aspect_ratio") == aspect else None)
    size = inherited if valid_target(aspect, inherited) else target_size(aspect)
    if node["tool"] == "qc_video" and inputs.get("target_size") not in {None, size}:
        _fail("PLAN_ASPECT_RATIO_MISMATCH", node, "inputs.target_size", inputs["target_size"], size)
    inputs["target_aspect_ratio"] = aspect
    if inputs.get("target_size") is None:
        inputs["target_size"] = size


def delivery_checks(media, aspect, size):
    if not aspect:
        return []
    actual_size = f"{media.get('width')}*{media.get('height')}"
    actual_ratio = video_geometry(media).get("aspect_ratio")
    return [{"code": "MASTER_SIZE", "passed": actual_size == size, "summary": "主片像素尺寸符合批准画布"},
            {"code": "MASTER_ASPECT_RATIO", "passed": actual_ratio == aspect, "summary": "主片显示比例符合用户明确要求"}]
