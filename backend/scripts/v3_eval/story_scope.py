"""Evaluation-only, offline scope audit. Never authorizes or executes a Patch."""
from copy import deepcopy

GENERATORS = {"generate_image", "animate_shot", "generate_video", "transform_video"}
VIDEOS = GENERATORS - {"generate_image"}
DELIVERY = {"compose_video", "probe_media", "qc_video", "package_story"}
METADATA = {"origin", "rationale"}


class ScopeViolation(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ScopeViolation(message)


def _refs(value):
    if isinstance(value, dict):
        if "ref" in value:
            require(set(value) == {"ref"} and isinstance(value["ref"], str)
                    and value["ref"].count(".") == 1, "Malformed typed reference")
            yield value["ref"].split(".", 1)[0]
        else:
            for child in value.values():
                yield from _refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _refs(child)


def _closure(roots, children):
    found, pending = set(roots), list(roots)
    while pending:
        for child in children[pending.pop()]:
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def _execution_shape(node):
    # Provenance/description updates are reported separately; they grant no authority.
    value = deepcopy(node)
    for field in METADATA:
        value.pop(field, None)
    value["inputs"].pop("prompt", None)
    return value


def audit_story_patch_scope(base_plan, record, quote, target):
    """Require a prompt-only third-shot revision against unredacted DB records.

    The reviewed Plan must already have reached review B. Public diff_preview is
    redacted, so it cannot prove unchanged URL/path-bearing inputs. This helper
    consumes the same-run raw base Plan and final reviewed record['draft'].
    Prompt semantics and actual visual identity still require separate review.
    """
    nodes = {node["id"]: node for node in base_plan["nodes"]}
    require(len(nodes) == len(base_plan["nodes"]), "Duplicate base node IDs")
    require(target in nodes and nodes[target]["tool"] in VIDEOS, "Target is not a video node")
    draft = record["draft"]
    require(record["patch_id"] == quote["patch_id"], "Patch identity mismatch")
    require(draft["base_version"] == quote["base_version"] == base_plan["plan_version"], "Patch base version mismatch")
    require(quote["scope"] == "cascade", "This review-B scenario requires cascade quote")
    children = {key: set() for key in nodes}
    for node in nodes.values():
        for parent in set(node.get("depends_on", [])) | set(_refs(node.get("inputs", {}))):
            require(parent in nodes, "Unknown base dependency")
            children[parent].add(node["id"])
    generators = {key for key, node in nodes.items() if node["tool"] in GENERATORS}
    image_deliverables = {item["node_id"] for item in base_plan["deliverables"] if item["kind"] == "image"}
    dedicated_frames = set()
    for field in ("first_frame_artifact_id", "last_frame_artifact_id"):
        reference = nodes[target].get("inputs", {}).get(field)
        if not (isinstance(reference, dict) and set(reference) == {"ref"}
                and isinstance(reference["ref"], str) and reference["ref"].endswith(".image")):
            continue
        frame = reference["ref"].split(".", 1)[0]
        if (frame in nodes and nodes[frame]["tool"] == "generate_image" and frame not in image_deliverables
                and (_closure({frame}, children) - {frame}) & generators == {target}):
            dedicated_frames.add(frame)
    allowed = {target} | dedicated_frames
    changed, metadata = set(), {}
    require(isinstance(draft.get("ops"), list) and draft["ops"], "Missing Patch operations")
    for op in draft["ops"]:
        require(op["op"] in {"update_inputs", "replace_node"}, "Insert/remove operations are outside the requested revision")
        node_id = op["node_id"]
        require(node_id in allowed, "Patch changes an unrelated shot or shared/non-keyframe image")
        require(node_id not in changed, "Duplicate Patch target")
        before = nodes[node_id]
        if op["op"] == "update_inputs":
            require(set(op["inputs"]) == {"prompt"}, "Only inputs.prompt may change")
            after = deepcopy(before)
            after["inputs"].update(op["inputs"])
        else:
            after = op["node"]
        require(_execution_shape(before) == _execution_shape(after), "Model, params, references, structure, gate or another execution field changed")
        prompt = after["inputs"].get("prompt")
        require(isinstance(prompt, str) and prompt.strip() and prompt != before["inputs"].get("prompt"), "Missing or unchanged prompt")
        changed.add(node_id)
        fields = sorted(field for field in METADATA if before.get(field) != after.get(field))
        if fields:
            metadata[node_id] = fields
    affected = _closure(changed, children)
    required_generations = {target} | (changed & dedicated_frames)
    require(affected & generators == required_generations, "Revision would regenerate another shot or shared image")
    required_execute = affected | {key for key, node in nodes.items() if node["tool"] in DELIVERY}
    def ids(field):
        value = quote[field]
        require(isinstance(value, list) and len(value) == len(set(value)) and not set(value) - set(nodes), "Invalid quote node set: " + field)
        return set(value)
    require(ids("affected_node_ids") == affected, "Quote expanded or omitted the actual affected subgraph")
    require(ids("execute_node_ids") == required_execute, "Quote expanded or omitted the required execution scope")
    require(ids("reused_node_ids") == set(nodes) - required_execute, "Unchanged outputs are not all reused")
    require(not ids("kept_node_ids") and not ids("removed_node_ids"), "Quote retained stale outputs or removed nodes")
    return {"target": target, "allowed_prompt_node_ids": sorted(allowed), "changed_prompt_node_ids": sorted(changed),
            "generation_node_ids": sorted(required_generations), "execute_node_ids": sorted(required_execute),
            "reused_node_ids": sorted(set(nodes) - required_execute), "metadata_changes": metadata,
            "audit_source": "same-run unredacted base Plan and final reviewed PatchDraft", "semantic_prompt_review_required": True}
