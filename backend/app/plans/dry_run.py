"""An isolated in-memory typed Stub interpreter, with no production handlers."""

from copy import deepcopy

from pydantic import ValidationError

from app.api import AppError
from app.plans.compiler import _placeholder, node_inputs, resolve_inputs


def dry_run(compiled, *, registry=None):
    """Exercise the entire compiled DAG without touching ledger, files or APIs."""
    if registry is None:
        from app.tools import build_v3_registry
        registry = build_v3_registry()
    issues = deepcopy(compiled.get("issues", []))
    result = {"passed": False, "issues": issues, "order": [], "outputs": {}, "demo": True, "estimated_cost": 0}
    if issues:
        return result
    plan = compiled["plan"]
    nodes = {node["id"]: node for node in plan["nodes"]}
    for node_id in compiled["dag"]["order"]:
        node = nodes[node_id]
        try:
            if not set(compiled["dag"]["dependencies"][node_id]).issubset(result["outputs"]):
                raise AppError("DRY_RUN_ORDER", "A predecessor did not complete before its consumer", 422)
            spec = registry.get(node["tool"])
            inputs = resolve_inputs(node_inputs(node, plan_version=plan["plan_version"]), result["outputs"])
            spec.input_model.model_validate(inputs)
            output = {field: _placeholder(node_id, field, info)
                      for field, info in compiled["output_metadata"][node_id].items()}
            if node["tool"] == "select_image":
                # Exercise a non-first candidate without persisting user
                # authority or invoking the production selector.
                selected = inputs["candidate_artifact_ids"][-1]
                spec.input_model.model_validate({**inputs, "selected_artifact_id": selected})
                output = {"image": selected}
                result.setdefault("simulated_choices", {})[node_id] = selected
            result["outputs"][node_id] = output
            result["order"].append(node_id)
        except (AppError, ValidationError, KeyError, TypeError, ValueError) as error:
            issues.append({"code": getattr(error, "code", "DRY_RUN_INVALID_INPUT"), "node_id": node_id,
                           "message": getattr(error, "message", "Typed Stub execution rejected the node")})
            break
    if not issues and len(result["order"]) != len(nodes):
        issues.append({"code": "DRY_RUN_INCOMPLETE", "node_id": None, "message": "Not all nodes were executed"})
    for target in plan["deliverables"]:
        if not issues and target["output"] not in result["outputs"].get(target["node_id"], {}):
            issues.append({"code": "DRY_RUN_MISSING_OUTPUT", "node_id": target["node_id"], "message": "A deliverable output was not produced"})
    result["passed"] = not issues
    return result
