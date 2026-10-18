"""Freeze Agent output choices independently from the classic global switch."""
from app.models import AgentRun


def for_submission(ctx):
    if ctx.plan_node_task_id is not None or ctx.plan_preview_id is not None:
        return {"compress_output": False}
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
    constraints = ((run.snapshot or {}).get("request_spec") or {}).get("constraints") or {} if run else {}
    # Story clips remain originals; an explicitly requested compressed final
    # is produced separately by Editor after composition.
    return {"compress_output": ctx.shot_task_id is None and constraints.get("compress_output") is True}


def compression_enabled(job):
    config = job.config or {}
    if config.get("agent_story_production") or config.get("agent_plan"):
        return False
    if config.get("skill"):
        return (config.get("agent_output_policy") or {}).get("compress_output") is True
    return None
