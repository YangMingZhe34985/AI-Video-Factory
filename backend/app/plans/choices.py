"""User-bound image choices, never an Agent-authored or implicit first candidate."""
from copy import deepcopy

from pydantic import ValidationError

from app.agent import plan_versions as versions
from app.api import AppError
from app.extensions import db
from app.models import PlanNodeTask


def _error(message="The preview candidates changed; review the current choice"):
    return AppError("CHOICE_CHANGED", message, 409)


def _source(task):
    """Follow verified carry-forward links, not an author-supplied lineage flag."""
    current, seen = task, set()
    while current.state.get("reused_from"):
        if current.id in seen or len(seen) >= 200:
            raise _error()
        seen.add(current.id)
        previous = db.session.get(PlanNodeTask, current.state["reused_from"])
        if (previous is None or previous.run_id != task.run_id
                or previous.status != "success" or previous.inputs_hash != current.inputs_hash
                or previous.inputs != current.inputs or previous.state.get("tool") != current.state.get("tool")
                or previous.output != current.output
                or previous.state.get("output_fingerprints") != current.state.get("output_fingerprints")):
            raise _error()
        current = previous
    return {"task_id": task.id, "root_task_id": current.id, "inputs_hash": task.inputs_hash,
            "inputs_digest": versions.inputs_hash({"inputs": task.inputs,
                "input_fingerprints": task.state.get("input_fingerprints", {})}),
            "output": deepcopy(task.output), "fingerprints": deepcopy(task.state.get("output_fingerprints", {}))}


def candidate_proof(run, version, node, task, tasks, *, require_ready=True, rebinding=False):
    from app.plans import execution, runtime
    from app.plans.compiler import _refs, node_inputs, resolve_inputs
    from app.plans.node_tools import SelectImageInput
    if node.get("tool") != "select_image" or node.get("gate") != "choice" or task is None:
        raise AppError("INVALID_GATE", "The selected node is not an image choice gate", 409)
    dag = version.check.get("dag", {})
    dependencies = dag.get("dependencies", {}).get(node["id"], [])
    if require_ready:
        approval = (run.snapshot or {}).get("v3_execution", {})
        gates = {item["id"] for item in version.plan["nodes"] if item.get("gate")
                 and item["id"] not in approval.get("approved_gates", [])}
        if runtime._gate_blocks(node["id"], dag, gates):
            raise AppError("INVALID_GATE", "An upstream gate must be approved first", 409)
    def usable(source):
        if rebinding and source.state.get("tool") == "select_image":
            original = db.session.get(PlanNodeTask, source.state.get("reused_from"))
            return bool(original and original.run_id == run.run_id and original.node_id == source.node_id
                and original.plan_version < version.version and source.status == "success"
                and source.inputs == original.inputs and source.output == original.output
                and source.state.get("output_fingerprints") == original.state.get("output_fingerprints")
                and execution.usable(run, original))
        return execution.usable(run, source)
    if any(key not in tasks or not usable(tasks[key]) for key in dependencies):
        raise AppError("INVALID_GATE", "All choice predecessors must have valid completed outputs", 409)
    outputs = {key: item.output for key, item in tasks.items() if item.status == "success"}
    raw = resolve_inputs(node_inputs(node, plan_version=version.version), outputs)
    try:
        data = SelectImageInput.model_validate(raw)
    except ValidationError as error:
        raise AppError("INVALID_CHOICE", "Resolved choice candidates must be 2 to 20 unique images", 409) from error
    candidates = data.candidate_artifact_ids
    try:
        fingerprints = {key: execution.fingerprint(run, key, "image") for key in candidates}
    except AppError as error:
        if error.code not in {"PLAN_ARTIFACT_UNAVAILABLE", "PLAN_OUTPUT_TYPE_MISMATCH", "ATTACHMENT_NOT_FOUND", "ARTIFACT_NOT_FOUND"}:
            raise
        raise _error("A choice candidate is missing or its media type changed") from error
    source_nodes = sorted({source for source, _field in _refs(node["inputs"])})
    proof = {"run_id": run.run_id, "plan_version": version.version, "node_id": node["id"], "task_id": task.id,
        "node_hash": versions.inputs_hash(node), "candidates": list(candidates), "fingerprints": fingerprints,
        "sources": {key: _source(tasks[key]) for key in source_nodes}}
    proof["choice_digest"] = versions.inputs_hash(proof)
    return proof


def _semantic(proof):
    return {"node_hash": proof["node_hash"], "candidates": proof["candidates"],
        "fingerprints": proof["fingerprints"], "sources": {key: {name: value for name, value in item.items()
            if name != "task_id"} for key, item in proof["sources"].items()}}


def prepare(run, version, node, task, tasks):
    """Freeze the exact options while leaving the node pending and uninvoked."""
    proof = candidate_proof(run, version, node, task, tasks)
    old = task.state.get("choice_pending")
    if old is not None and old != proof:
        raise _error()
    if old is None:
        task.state = {**task.state, "choice_pending": proof}
        db.session.commit()
    return proof


def pending(run, version, node_id):
    from app.plans import runtime
    runtime._frozen(run, version)
    tasks = runtime.latest_tasks(run, version)
    node = next((item for item in version.plan["nodes"] if item["id"] == node_id), {})
    task = tasks.get(node_id)
    if task is None or task.status != "pending" or node_id in (run.snapshot or {}).get("v3_execution", {}).get("approved_gates", []):
        raise AppError("INVALID_GATE", "The image choice is not awaiting user selection", 409)
    proof = candidate_proof(run, version, node, task, tasks)
    if task.state.get("choice_pending") != proof:
        raise _error()
    return task, proof


def validate_action(run, version, node_id, selected_artifact_id, choice_digest):
    task, proof = pending(run, version, node_id)
    if not selected_artifact_id or not choice_digest or proof["choice_digest"] != choice_digest:
        raise _error()
    if selected_artifact_id not in proof["candidates"]:
        raise AppError("INVALID_CHOICE", "Select one of this gate's current candidate images", 422)
    return task, proof


def receipt_for_task(run, task, _seen=None):
    """Validate persisted user authority and every immutable source, also in history."""
    from app.plans import runtime
    if task is None:
        raise _error()
    seen = set(_seen or ())
    if task.id in seen or len(seen) >= 200:
        raise _error("The image approval chain is invalid or exceeds the supported history depth")
    seen.add(task.id)
    version = versions.get_version(run, task.plan_version)
    approval = (run.snapshot or {}).get("v3_execution", {})
    if approval.get("approved_version") != task.plan_version:
        approval = (run.snapshot or {}).get("v3_execution_history", {}).get(str(task.plan_version), {})
    record = approval.get("choice_receipts", {}).get(task.node_id)
    if (approval.get("approval_hash") != versions.inputs_hash(version.plan)
            or task.node_id not in approval.get("approved_gates", []) or not record
            or record.get("task_id") != task.id or record.get("plan_version") != task.plan_version):
        raise _error("The image selection has no matching user approval")
    node = next(item for item in version.plan["nodes"] if item["id"] == task.node_id)
    proof = candidate_proof(run, version, node, task, runtime.latest_tasks(run, version), require_ready=False)
    if any(record.get(key) != value for key, value in proof.items()) or record.get("selected_artifact_id") not in proof["candidates"]:
        raise _error()
    if task.status == "success" and (task.inputs.get("selected_artifact_id") != record["selected_artifact_id"]
            or task.output != {"image": record["selected_artifact_id"]}):
        raise _error()
    inherited = record.get("inherited_from")
    if inherited:
        # Each rebind is server-created; require an actual older successful
        # task with identical frozen selection, not a freely editable flag.
        source = db.session.get(PlanNodeTask, inherited.get("task_id"))
        if (source is None or source.run_id != run.run_id or source.plan_version >= task.plan_version
                or source.node_id != task.node_id or source.status != "success"):
            raise _error()
        parent = receipt_for_task(run, source, seen)
        if (parent["choice_digest"] != inherited.get("choice_digest")
                or parent["selected_artifact_id"] != record["selected_artifact_id"]
                or _semantic(parent) != _semantic(record)):
            raise _error()
    return deepcopy(record)


def approve(run, version, node_id, selected_artifact_id, choice_digest):
    from app.plans import runtime
    run = versions._lock_run(run)
    version = versions.require_current_version(run, version)
    approval = runtime._frozen(run, version)
    previous = approval.get("choice_receipts", {}).get(node_id)
    if previous is not None:
        task = runtime.latest_tasks(run, version).get(node_id)
        record = receipt_for_task(run, task)
        if record["selected_artifact_id"] != selected_artifact_id or record["choice_digest"] != choice_digest:
            raise _error("Changing an accepted image choice requires a reviewed Patch")
        return run.status
    if run.status not in runtime.ACTIVE:
        raise AppError("INVALID_AGENT_STATE", "No choice gate is awaiting approval", 409)
    _task, proof = validate_action(run, version, node_id, selected_artifact_id, choice_digest)
    records = deepcopy(approval.get("choice_receipts", {}))
    records[node_id] = {**proof, "selected_artifact_id": selected_artifact_id}
    return runtime._update(run, status="executing", choice_receipts=records,
        approved_gates=list(dict.fromkeys([*approval.get("approved_gates", []), node_id]))).status


def resolved_selection(run, node, version, data, fingerprints, *, receipt=None):
    from app.plans import runtime
    if receipt is None:
        task = runtime.latest_tasks(run, version).get(node["id"])
        receipt = receipt_for_task(run, task)
    if (receipt["node_hash"] != versions.inputs_hash(node)
            or receipt["candidates"] != data["candidate_artifact_ids"]
            or receipt["fingerprints"] != fingerprints):
        raise _error()
    return receipt["selected_artifact_id"]


def validate_execution(run, task, node, payload):
    record = receipt_for_task(run, task)
    if (payload.get("selected_artifact_id") != record["selected_artifact_id"]
            or payload.get("candidate_artifact_ids") != record["candidates"]
            or versions.inputs_hash(node) != record["node_hash"]):
        raise _error()


def select_image(data, ctx):
    from app.plans.policy import task_context
    run, task, _version, node = task_context(ctx)
    validate_execution(run, task, node, data.model_dump(mode="json"))
    return {"image": data.selected_artifact_id}


def rebind(run, version, node, task, tasks, source):
    previous = receipt_for_task(run, source)
    proof = candidate_proof(run, version, node, task, tasks, require_ready=False, rebinding=True)
    if _semantic(previous) != _semantic(proof):
        raise _error()
    return {**proof, "selected_artifact_id": previous["selected_artifact_id"],
            "inherited_from": {"task_id": source.id, "choice_digest": previous["choice_digest"]}}


def public_choice(run, version, node, task):
    if node.get("tool") != "select_image":
        return None
    result = {"ready": False, "choice_digest": None, "candidates": [], "selected_artifact_id": None}
    if task is None:
        return result
    try:
        if node["id"] in (run.snapshot or {}).get("v3_execution", {}).get("approved_gates", []):
            record = receipt_for_task(run, task)
            result["selected_artifact_id"] = record["selected_artifact_id"]
        else:
            _task, record = pending(run, version, node["id"])
            result["ready"] = True
        result["choice_digest"] = record["choice_digest"]
        result["candidates"] = [{"artifact_id": key, "mime_type": record["fingerprints"][key]["mime_type"],
            "preview_url": f"/api/artifacts/{key}/preview", "download_url": f"/api/artifacts/{key}/download"}
            for key in record["candidates"]]
    except (AppError, KeyError, ValueError):
        pass
    return result
