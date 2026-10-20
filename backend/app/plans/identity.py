"""Pure structural identity evidence for an already typed v3 Plan.

No prompt inference, database access or execution authority is introduced here.
Every catalog reference is required. Evidence is tracked per named media output,
with alternative images and concatenated clips using their common evidence.
"""

GENERATORS = frozenset({"generate_image", "animate_shot", "generate_video", "transform_video"})
VISUAL = frozenset({"image", "image[]", "video", "video[]"})


def _reference(value):
    if isinstance(value, dict) and set(value) == {"artifact"} and isinstance(value["artifact"], str):
        return ("artifact", value["artifact"])
    if isinstance(value, dict) and set(value) == {"ref"} and isinstance(value["ref"], str):
        parts = value["ref"].split(".")
        if len(parts) == 2 and all(parts):
            return ("ref", parts[0], parts[1])
    return None


def _common(items):
    return set.intersection(*(set(item) for item in items)) if items else set()


def validate_identity(plan, *, order, output_metadata, known_artifacts, media_fields):
    """Return blocking issues without changing the Plan or compiler metadata.

    The caller performs schema validation, Story binding, normal media typing,
    ownership checks and DAG validation. Only validated named outputs are usable
    here. ``media_fields`` contains each node's ToolSpec.io_types.inputs.
    """
    nodes = {node["id"]: node for node in plan.get("nodes", [])}
    catalog = plan.get("character_references") or {}
    issues, required, root_roles = [], {}, {}
    valid_roots, invalid_roles = set(), set()
    available = set(order)

    def issue(code, message, node_id=None):
        issues.append({"code": code, "node_id": node_id, "message": message})

    for character, references in catalog.items():
        anchors = required.setdefault(character, set())
        for value in references:
            anchor = _reference(value)
            if anchor is None:
                invalid_roles.add(character)
                issue("PLAN_INVALID_CHARACTER_REFERENCE", f"Character {character} requires a pure single-image artifact or ref.")
                continue
            anchors.add(anchor)
            if anchor[0] == "artifact":
                if known_artifacts.get(anchor[1], {}).get("type") != "image":
                    invalid_roles.add(character)
                    issue("PLAN_INVALID_CHARACTER_REFERENCE", f"Character {character} requires a verified Run-owned image artifact.")
                continue
            _kind, source, field = anchor
            node = nodes.get(source, {})
            metadata = output_metadata.get(source, {})
            count = metadata.get("images", {}).get("count", node.get("params", {}).get("n", 1))
            valid = (field == "image" and node.get("tool") == "generate_image"
                     and source in available and metadata.get("image", {}).get("type") == "image"
                     and type(count) is int and count == 1 and node.get("gate") == "preview"
                     and node.get("characters") == [character])
            if not valid:
                invalid_roles.add(character)
                issue("PLAN_INVALID_CHARACTER_REFERENCE",
                      f"Character {character} needs a single-image generate_image.image preview root declaring only that character.", source)
                continue
            previous = root_roles.get(source)
            if previous is not None and previous != character:
                invalid_roles.update({previous, character})
                valid_roots.discard(source)
                issue("PLAN_INVALID_CHARACTER_REFERENCE", "A generated identity root cannot define multiple characters.", source)
            else:
                root_roles[source] = character
                valid_roots.add(source)
        if not anchors:
            invalid_roles.add(character)
            issue("PLAN_INVALID_CHARACTER_REFERENCE", f"Character {character} requires at least one identity reference.")

    for node_id, node in nodes.items():
        characters = node.get("characters")
        if node.get("tool") not in GENERATORS:
            if characters is not None:
                issue("PLAN_INVALID_CHARACTER_REFERENCE", "Only generation nodes may declare characters.", node_id)
            continue
        if catalog and characters is None:
            issue("PLAN_CHARACTERS_REQUIRED", "Declare this generation node's characters; use [] only for an intentional empty shot.", node_id)
        unknown = sorted(set(characters or []) - set(catalog))
        if unknown:
            issue("PLAN_UNKNOWN_CHARACTER", "Characters are absent from the identity catalog: " + ", ".join(unknown), node_id)

    # Each scalar output owns one evidence set; an image/video array owns one
    # independent set per item. Never flatten alternatives into a union here.
    evidence = {}

    def visual(value, expected):
        anchor = _reference(value)
        if anchor and anchor[0] == "ref":
            _kind, source, field = anchor
            if output_metadata.get(source, {}).get(field, {}).get("type") != expected:
                return [] if expected.endswith("[]") else set()
            found = evidence.get((source, field))
            if expected.endswith("[]"):
                return [set(item) for item in found] if isinstance(found, list) else [set()]
            return set(found) if isinstance(found, set) else set()
        if expected.endswith("[]"):
            if not isinstance(value, list):
                return []
            return [visual(item, expected[:-2]) for item in value]
        if isinstance(value, str):
            anchor = ("artifact", value)
        if anchor and anchor[0] == "artifact" and known_artifacts.get(anchor[1], {}).get("type") == expected:
            return {anchor}
        return set()

    def assign(node_id, field, kind, anchors):
        metadata = output_metadata.get(node_id, {}).get(field, {})
        if metadata.get("type") != kind:
            return
        if kind.endswith("[]"):
            count = metadata.get("count", len(metadata.get("items") or []))
            if type(count) is int and count >= 1:
                evidence[node_id, field] = [set(anchors) for _ in range(count)]
        else:
            evidence[node_id, field] = set(anchors)

    for node_id in order:
        node = nodes.get(node_id)
        if node is None or node_id not in output_metadata:
            continue
        tool, inputs = node.get("tool"), node.get("inputs") or {}
        if tool in GENERATORS:
            incoming = set()
            for field, kind in media_fields.get(node_id, {}).items():
                if kind not in VISUAL or inputs.get(field) is None:
                    continue
                found = visual(inputs[field], kind)
                if kind.endswith("[]"):
                    incoming.update(*(found or [set()]))
                else:
                    incoming.update(found)
            if tool == "transform_video":
                for item in inputs.get("media") or []:
                    kind = {"reference_image": "image", "reference_video": "video"}.get(item.get("type"))
                    if kind:
                        incoming.update(visual(item.get("artifact_id"), kind))
            kept = set()
            for character in node.get("characters") or []:
                anchors = required.get(character, set())
                if node_id in valid_roots and root_roles[node_id] == character:
                    # A root can seed its own atomic reference. Additional views
                    # remain separate required anchors for downstream generation.
                    kept.add(("ref", node_id, "image"))
                    kept.update(incoming & anchors)
                elif character in invalid_roles or not anchors or not anchors <= incoming:
                    if character in catalog:
                        issue("PLAN_CHARACTER_REFERENCE_MISSING",
                              f"Character {character} is missing required visual identity references; add all references or a multi-reference keyframe. depends_on is not a visual input.", node_id)
                else:
                    kept.update(anchors)
            if tool == "generate_image":
                assign(node_id, "image", "image", kept)
                assign(node_id, "images", "image[]", kept)
            else:
                assign(node_id, "video", "video", kept)
        elif tool == "select_image":
            candidates = visual(inputs.get("candidate_artifact_ids"), "image[]")
            assign(node_id, "image", "image", _common(candidates))
        elif tool == "compose_video":
            clips = visual(inputs.get("video_artifact_ids"), "video[]")
            common = _common(clips)
            assign(node_id, "artifact_id", "video", common)
            assign(node_id, "compressed_artifact_id", "video", common)
        elif tool in {"extract_frame", "retain_video_segment"}:
            source = visual(inputs.get("video_artifact_id"), "video")
            assign(node_id, "artifact_id", "image" if tool == "extract_frame" else "video", source)
        # Reports, packages and unknown tools intentionally have no evidence.
    return issues
