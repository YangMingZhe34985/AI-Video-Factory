"""Owner-facing Plan state, without private compiler data or Agent messages."""
from copy import deepcopy

from app.agent.plan_versions import current_version
from app.models import Artifact
from app.plans.runtime import latest_tasks
from app.tools.specs.package_story import _safe
from app.utils.time_utils import isoformat


def public_plan(run):
    version = current_version(run)
    if version is None:
        return {"plan": None, "plan_issues": _safe((run.snapshot or {}).get("plan_issues", [])), "estimates": None, "experimental": False,
                "nodes": [], "results": [], "summary": {"steps_total": 0, "steps_success": 0, "steps_failed": 0}}
    tasks = latest_tasks(run, version)
    approvals = (run.snapshot or {}).get("v3_execution", {}).get("approved_gates", [])
    nodes = []
    for node in version.plan.get("nodes", []):
        task = tasks.get(node["id"])
        artifacts = []
        for key in task.artifact_ids if task else []:
            artifact = Artifact.query.filter_by(artifact_id=key).first()
            if artifact:
                artifacts.append({"artifact_id": key, "mime_type": artifact.mime_type,
                    "preview_url": f"/api/artifacts/{key}/preview", "download_url": f"/api/artifacts/{key}/download"})
        nodes.append({"node_id": node["id"], "tool": node["tool"], "stage": node["stage"],
            "status": task.status if task else "pending", "attempt": task.attempt if task else 0,
            "job_id": task.job_id if task else None, "estimated_cost": task.estimated_cost if task else 0,
            "gate": node.get("gate"), "gate_approved": node["id"] in approvals,
            "artifacts": artifacts, "error": _safe(task.error) if task else None,
            "reused_from_task_id": task.reused_from_task_id if task and hasattr(task, "reused_from_task_id") else (task.state or {}).get("reused_from") if task else None,
            "updated_at": isoformat(task.updated_at) if task else None})
    results = []
    for delivery in version.plan.get("deliverables", []):
        task = tasks.get(delivery["node_id"])
        if task is None or task.status != "success":
            continue
        value = task.output.get(delivery["output"])
        for key in value if isinstance(value, list) else [value]:
            if key not in task.artifact_ids:
                continue
            results.append({**deepcopy(delivery), "artifact_id": key,
                "preview_url": f"/api/artifacts/{key}/preview", "download_url": f"/api/artifacts/{key}/download"})
    return {"plan": _safe(version.plan), "plan_issues": _safe(version.check.get("issues", [])),
        "estimates": deepcopy(version.check.get("estimates", version.plan.get("estimates"))),
        "experimental": bool(version.plan.get("experimental")), "nodes": nodes, "results": results,
        "summary": {"steps_total": len(nodes), "steps_success": sum(item["status"] == "success" for item in nodes),
                    "steps_failed": sum(item["status"] == "failed" for item in nodes)}}
