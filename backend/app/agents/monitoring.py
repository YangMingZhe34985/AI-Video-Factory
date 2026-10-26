"""Read-only v3 operational metrics from the durable ledger (D-064).

Planning, execution and repair figures for one Run, and an owner-scoped
aggregate for rollout decisions (DEFAULT_ON_PLAN section 5). Credits are the
demonstration estimates used everywhere else, not a provider bill.
"""
from collections import Counter
from datetime import timedelta
from statistics import median

from app.models import AgentDelegation, AgentPlanVersion, AgentRun, AgentStep, PlanNodeTask, ToolInvocation
from app.plans.compiler import GENERATION_TOOLS
from app.utils.time_utils import as_utc, utc_now

PEAK_ALERT_TOKENS = 80_000
FINAL = {"success", "partial_success", "failed", "cancelled"}


def _usage(row):
    usage = (row.output_payload or {}).get("usage") or {}
    return (int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            int(usage.get("completion_tokens") or usage.get("output_tokens") or 0))


def _error_code(value):
    return value.get("code") if isinstance(value, dict) else None


def v3_run_metrics(run):
    ledger = ToolInvocation.query.filter_by(budget_scope=run.run_id).all()
    turns = [row for row in ledger if row.tool_name == "agent_llm_turn" and row.status == "success"]
    usage = [_usage(row) for row in turns]
    spent = [row for row in ledger if row.status != "rejected"]
    planning_credits = sum(float(row.estimated_cost or 0) for row in spent if row.caller_agent is not None)
    media_credits = sum(float(row.estimated_cost or 0) for row in spent if row.tool_name in GENERATION_TOOLS)
    asks = AgentStep.query.filter_by(run_id=run.run_id, kind="ask").count()
    agents = sorted({row.agent for row in AgentDelegation.query.filter_by(run_id=run.run_id).all()})
    first = AgentPlanVersion.query.filter_by(run_id=run.run_id).order_by(AgentPlanVersion.version).first()
    latest = AgentPlanVersion.query.filter_by(run_id=run.run_id).order_by(AgentPlanVersion.version.desc()).first()
    tasks = PlanNodeTask.query.filter_by(run_id=run.run_id, plan_version=latest.version).all() if latest else []
    patches = list(((run.snapshot or {}).get("v3_patches") or {}).values())
    failed_codes = Counter(_error_code(task.error) for task in tasks if task.status == "failed" and _error_code(task.error))
    peak = max((item[0] for item in usage), default=0)
    alerts = []
    if peak > PEAK_ALERT_TOKENS:
        alerts.append("PEAK_INPUT_OVER_80K")
    if run.status == "attention":
        alerts.append("ATTENTION")
    if failed_codes:
        alerts.append("NODE_FAILED")
    return {
        "planning": {
            "llm_rounds": len(turns), "input_tokens": sum(item[0] for item in usage),
            "output_tokens": sum(item[1] for item in usage), "peak_input_tokens": peak,
            "usage_missing": sum(1 for item in usage if item == (0, 0)),
            "credits": round(planning_credits, 5), "questions": asks, "agents": agents,
            "reached_plan": first is not None,
            "seconds_to_first_plan": (as_utc(first.created_at) - as_utc(run.created_at)).total_seconds() if first else None,
        },
        "execution": {
            "plan_version": latest.version if latest else None,
            "node_status": dict(Counter(task.status for task in tasks)),
            "failed_node_codes": dict(failed_codes),
            "media_credits": round(media_credits, 5),
            "run_error_code": _error_code(run.error),
        },
        "patches": {
            "total": len(patches), "by_status": dict(Counter(item.get("status") for item in patches)),
            "auto_applied": sum(1 for item in patches if item.get("status") == "applied" and item.get("auto_approved")),
            "manual_applied": sum(1 for item in patches if item.get("status") == "applied" and not item.get("auto_approved")),
        },
        "alerts": alerts,
        "cost_basis": "demonstration_credits_not_provider_bill",
    }


def _median(values):
    values = [value for value in values if value is not None]
    return round(median(values), 2) if values else None


def v3_aggregate(owner_id, days=7):
    since = utc_now() - timedelta(days=days)
    runs = [run for run in AgentRun.query.filter(AgentRun.owner_id == owner_id, AgentRun.created_at >= since).all()
            if (run.request or {}).get("schema_version") == 3]
    rows = [(run, v3_run_metrics(run)) for run in runs]
    planning = [item["planning"] for _run, item in rows]
    reasons = Counter()
    for run, item in rows:
        if run.status == "attention":
            codes = item["execution"]["failed_node_codes"] or {item["execution"]["run_error_code"] or "UNKNOWN": 1}
            reasons.update(codes.keys())
    total = len(rows)
    return {
        "window_days": days, "runs": total,
        "by_status": dict(Counter(run.status for run, _item in rows)),
        "reached_plan_rate": round(sum(item["reached_plan"] for item in planning) / total, 3) if total else None,
        "asked_rate": round(sum(1 for item in planning if item["questions"]) / total, 3) if total else None,
        "median_llm_rounds": _median([item["llm_rounds"] for item in planning]),
        "median_seconds_to_first_plan": _median([item["seconds_to_first_plan"] for item in planning]),
        "median_planning_credits": _median([item["credits"] for item in planning]),
        "peak_over_80k_runs": sum(1 for item in planning if item["peak_input_tokens"] > PEAK_ALERT_TOKENS),
        "attention_runs": sum(1 for run, _item in rows if run.status == "attention"),
        "attention_reasons": dict(reasons),
        "media_credits": round(sum(item["execution"]["media_credits"] for _run, item in rows), 5),
        "patches": {"manual_applied": sum(item["patches"]["manual_applied"] for _run, item in rows),
                    "auto_applied": sum(item["patches"]["auto_applied"] for _run, item in rows)},
        "cost_basis": "demonstration_credits_not_provider_bill",
    }
