"""Owner-facing Plan state, without private compiler data or Agent messages."""
from copy import deepcopy

from app.agent.plan_versions import current_version
from app.models import AgentPlanVersion, Artifact
from app.plans.runtime import latest_tasks
from app.tools.specs.package_story import _safe
from app.utils.time_utils import isoformat


def public_patches(run):
    from app.agents.api import safe_text
    result = []
    for patch_id, record in (run.snapshot or {}).get("v3_patches", {}).items():
        draft = record.get("draft") or {}
        review = record.get("director_review") or {}
        base = AgentPlanVersion.query.filter_by(run_id=run.run_id, version=draft.get("base_version")).first()
        originals = {node["id"]: node for node in base.plan.get("nodes", [])} if base else {}
        changes = []
        upgrade = draft.get("identity_upgrade")
        if upgrade is not None:
            source = base.plan if base else {}
            before = {"character_references": source.get("character_references", {}),
                      "story_ref": source.get("story_ref")}
            after = {"character_references": upgrade.get("character_references", {}),
                     "story_ref": upgrade.get("story_ref") or source.get("story_ref")}
            changes.append({"op": "identity_upgrade", "node_id": None,
                            "before": _safe(before), "after": _safe(after)})
        for op in draft.get("ops", []):
            node_id = op.get("node_id", (op.get("node") or {}).get("id"))
            original = originals.get(node_id)
            before, after = original, op.get("node")
            if op.get("op") == "update_inputs":
                after = op.get("inputs", {})
                before = {key: (original or {}).get("inputs", {}).get(key) for key in after}
            changes.append({"op": op.get("op"), "node_id": node_id, "before": _safe(before), "after": _safe(after)})
        result.append({"patch_id": patch_id, "status": record.get("status"),
            "base_version": draft.get("base_version"), "scope": draft.get("scope", "only"),
            "author": record.get("proposed_by"), "reason": safe_text(_safe(draft.get("reason")), 2000),
            "diff_summary": ([{"op": "identity_upgrade", "node_id": None,
                              "fields": ["character_references", "story_ref"]}] if upgrade is not None else []) + [{"op": op.get("op"), "node_id": op.get("node_id", (op.get("node") or {}).get("id")),
                "fields": sorted((op.get("inputs") or {}).keys()) if op.get("op") == "update_inputs" else []}
                for op in draft.get("ops", [])],
            "diff_preview": changes,
            "review": {"verdict": review.get("verdict"), "reason": safe_text(_safe(review.get("reason")), 2000)} if review else None,
            "auto_approved": bool(record.get("auto_approved")),
            "approved_version": record.get("approved_version"),
            "quote": _safe(record.get("quote"))})
    return result


def repair_budget(run):
    state = (run.snapshot or {}).get("v3_repair", {})
    limit = state.get("budget_limit", (run.snapshot or {}).get("v3_execution", {}).get("repair_budget_credits", 0))
    reserved = sum(item.get("credits", 0) for item in state.get("repair_claims", {}).values() if item.get("automatic"))
    return {"limit": limit, "committed": reserved, "remaining": max(0, limit - reserved)}


def public_plan(run):
    from app.plans.choices import public_choice
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
            "choice": public_choice(run, version, node, task),
            "artifacts": artifacts, "error": _safe(task.error) if task else None,
            "reused_from_task_id": task.reused_from_task_id if task and hasattr(task, "reused_from_task_id") else (task.state or {}).get("reused_from") if task else None,
            "retained": bool((task.state or {}).get("retained_by_only")) if task else False,
            "source_plan_version": (task.state or {}).get("source_plan_version") if task else None,
            "depends_on": version.check.get("dag", {}).get("dependencies", {}).get(node["id"], node.get("depends_on", [])),
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
