"""Read-only production board projection; relational tasks remain authoritative."""

from app.agent import plan_versions as versions
from app.agent.production_state import dependencies, enabled, latest_tasks, remaining_video_cost, shot_cost, usable_artifact
from app.api import AppError
from app.models import ToolInvocation
from app.skills.budget import BudgetGuard


def public_production(run):
    version = versions.current_version(run)
    if version is None:
        return None
    metadata = (run.snapshot or {}).get("production", {})
    repairs = (run.snapshot or {}).get("production_repairs", {})
    tasks = latest_tasks(run, version)
    deps = dependencies(version)
    output = []
    editable = run.status in {"production_attention", "awaiting_video_review"} and enabled()
    for shot in version.plan["shots"]:
        sid = shot["shot_id"]
        task = tasks.get(sid)
        artifact = usable_artifact(task)
        status = task.status if task else "pending"
        if task and status == "success" and not artifact:
            status = "stale"
        if not task and deps[sid]:
            parent = tasks.get(deps[sid][0])
            status = "blocked" if parent and parent.status in {"failed", "stale", "cancelled"} else "waiting_dependency"
        error = task.error if task else None
        if error and "category" not in error:
            error = {**error, "category": "permanent", "stage": "local", "submission_state": "unknown",
                     "provider_task_id": None, "recovery_action": "stop"}
        unsafe = bool(error and error.get("category") == "submit_unknown")
        try:
            cost = shot_cost(run, shot)
        except AppError:
            cost = None
        output.append({"shot_id": sid, "order": shot["order"], "duration_sec": shot["duration_sec"],
            "model_id": shot["motion"]["model_id"], "depends_on": deps[sid], "status": status,
            "attempt": task.attempt if task else 0, "artifact_id": artifact.artifact_id if artifact else None,
            "preview_url": f"/api/artifacts/{artifact.artifact_id}/preview" if artifact else None,
            "download_url": f"/api/artifacts/{artifact.artifact_id}/download" if artifact else None,
            "error": error, "estimated_credits": cost,
            "repair_count": sum(1 for item in repairs.values() if item.get("shot_id") == sid),
            "can_retry": editable and run.status == "production_attention" and status in {"failed", "stale"} and not unsafe,
            "can_redo": editable and status in {"success", "failed", "stale"} and not unsafe,
            "retained": sid in metadata.get("retained_sources", {})})
    spent = BudgetGuard.spent(run.run_id)
    invocations = ToolInvocation.query.filter_by(budget_scope=run.run_id).all()
    video_spent = sum(item.estimated_cost for item in invocations if item.tool_name == "animate_shot" and item.status != "rejected")
    repair_invocations = {item.get("invocation_id") for item in repairs.values()}
    repair_tasks = {item.get("replacement_task_id") for item in repairs.values()}
    from app.models import AgentShotTask
    for task in AgentShotTask.query.filter_by(run_id=run.run_id).all():
        if task.id in repair_tasks:
            repair_invocations.add(task.invocation_id)
    repair_spent = sum(item.estimated_cost for item in invocations
                       if item.invocation_id in repair_invocations and item.status != "rejected")
    try:
        remaining = remaining_video_cost(run, version)
    except AppError:
        remaining = None
    estimates = {"video_credits": sum(item["estimated_credits"] for item in output) if all(
        item["estimated_credits"] is not None for item in output) else None,
        "remaining_credits": remaining, "remaining_budget": max(0, run.request["budget_limit"] - spent),
        "video_spent_credits": video_spent, "repair_spent_credits": repair_spent, "spent_credits": spent}
    retained = list(metadata.get("retained_sources", {}))
    return {"enabled": enabled(), "plan_version": version.version, "approved_version": metadata.get("approved_version"),
            "status": run.status, "shots": output, "estimates": estimates,
            "repair_budget_credits": metadata.get("repair_budget_credits", 0),
            "kept_downstream": retained, "warnings": ["保留的下游片段仍使用原版本尾帧，衔接可能变化。"] if retained else []}
