"""Bounded, schema-derived diagnostics; no Plan mutation or authority."""
from pydantic import ValidationError

from app.api import AppError

RESERVED = frozenset({"model_id", "params", "plan_version", "template_id"})
MEDIA_REFERENCE_TYPES = frozenset({"image", "video", "audio", "document", "package",
                                  "image[]", "video[]", "audio[]", "document[]", "package[]"})


def _field(value):
    # Echo field locations, never submitted text, paths or artifact values.
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str) or len(value) > 100:
        return "<field>"
    return value if value.isascii() and all(c.isalnum() or c in "_.[]" for c in value) else "<field>"


def issue_details(error, node, spec):
    fields, hints = [], []
    code = getattr(error, "code", "INVALID_NODE_INPUT")
    payload = error.payload if isinstance(error, AppError) and isinstance(error.payload, dict) else {}
    if isinstance(payload.get("field"), str):
        fields.append(_field(payload["field"]))
    raw = error.errors(include_url=False, include_context=False, include_input=False) if isinstance(error, ValidationError) else payload.get("errors", [])
    if isinstance(raw, list):
        for item in raw[:8]:
            if isinstance(item, dict) and isinstance(item.get("loc"), (tuple, list)):
                location = [_field(part) for part in item["loc"][:8]]
                if location:
                    # Pydantic validates the resolved tool payload: only model/params
                    # stay at node level; all other author-supplied fields use inputs.
                    path = ".".join(location)
                    fields.append(path if location[0] in RESERVED else "inputs." + path)
    if code == "INVALID_NODE_MODEL":
        if node.get("model_id") is not None:
            fields.append("model_id")
        if node.get("params"):
            fields.append("params")
            for key in list(node["params"])[:8]:
                if spec and key in spec.input_model.model_fields and key not in RESERVED:
                    hints.append({"from": "params." + _field(key), "to": "inputs." + _field(key)})
    if code == "RESERVED_INPUT":
        for key in sorted(set(node.get("inputs") or {}) & RESERVED):
            fields.append("inputs." + key)
    declared = spec.io_types.get("inputs", {}) if spec else {}
    reference_inputs = sorted(key for key, kind in declared.items() if kind in MEDIA_REFERENCE_TYPES)
    if node.get("tool") == "transform_video":
        reference_inputs = sorted(set(reference_inputs) | {"media[].artifact_id", "source_artifact_id"})
    server_owned = RESERVED | ({"selected_artifact_id"} if node.get("tool") == "select_image" else set())
    details = {"node_id": node["id"], "tool": node["tool"],
               "fields": list(dict.fromkeys(fields))[:8],
               "allowed_reference_inputs": reference_inputs,
               "allowed_input_fields": sorted(key for key in spec.input_model.model_fields if key not in server_owned) if spec else []}
    if hints:
        details["field_hints"] = hints
    if code == "INVALID_NODE_MODEL":
        details["hint"] = "Local tools accept options in inputs, not model_id or params; only the listed input fields are valid."
    elif code == "UNTYPED_REFERENCE":
        details["hint"] = "Use a declared reference input; output names are not aliases for input names."
    elif code == "RESERVED_INPUT" and node.get("tool") == "select_image" and "selected_artifact_id" in node.get("inputs", {}):
        details["hint"] = "The selected image is supplied only by the user choice gate, never authored in Plan inputs."
    elif code == "RESERVED_INPUT":
        details["hint"] = "model_id and params belong at node level; template_id and plan_version cannot be authored inside inputs."
    return details
