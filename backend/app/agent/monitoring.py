"""Read-only operational metrics derived from the existing durable ledger."""

from collections import Counter, defaultdict

from app.models import ApiTask, ToolInvocation
from app.utils.time_utils import as_utc, utc_now


def run_metrics(run):
    invocations = ToolInvocation.query.filter_by(budget_scope=run.run_id).all()
    by_tool = defaultdict(lambda: {"calls": 0, "attempts": 0, "estimated_credits": 0.0})
    by_status = Counter()
    for item in invocations:
        by_status[item.status] += 1
        row = by_tool[item.tool_name]
        row["calls"] += 1
        row["attempts"] += item.attempt
        if item.status != "rejected":
            row["estimated_credits"] += item.estimated_cost
    spent = sum(row["estimated_credits"] for row in by_tool.values())
    job_ids = {item.job_id for item in invocations if item.job_id is not None}
    tasks = ApiTask.query.filter(ApiTask.job_id.in_(job_ids)).all() if job_ids else []
    shots = list((run.snapshot or {}).get("shots", {}).values())
    alerts = []
    limit = run.request["budget_limit"]
    if spent > limit:
        alerts.append("BUDGET_EXCEEDED")
    elif spent >= limit * 0.8:
        alerts.append("BUDGET_NEAR_LIMIT")
    if run.status == "needs_attention":
        alerts.append("RECOVERY_REQUIRED")
    if any(item.get("status") == "failed" for item in shots):
        alerts.append("SHOT_FAILED")
    return {
        "run_id": run.run_id, "status": run.status,
        "cost_basis": "estimated_reserved_credits_not_provider_bill",
        "budget_limit": limit, "estimated_spent": spent, "remaining": max(0, limit - spent),
        "by_tool": dict(by_tool), "invocation_statuses": dict(by_status),
        "provider_tasks_by_model": dict(Counter(task.model_id for task in tasks)),
        "provider_task_count": len(tasks),
        "provider_task_note": "Persisted generation tasks only; excludes planning/analysis and is not an HTTP call counter",
        "resume_count": run.resume_count,
        "shot_revision_count": sum((run.snapshot or {}).get("shot_revisions", {}).values()),
        "plan_issue_count": len((run.snapshot or {}).get("plan_issues", [])),
        "elapsed_seconds_including_human_wait": max(0, ((as_utc(run.updated_at) if run.status in {
            "success", "partial_success", "failed", "cancelled"} else utc_now()) - as_utc(run.created_at)).total_seconds()),
        "alerts": alerts,
    }
