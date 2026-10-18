"""Persistent production interrupts; historical storyboard approvals stay inert."""

from typing import TypedDict

from langgraph.types import interrupt

from app.agent.production_engine import tick_production
from app.models import AgentRun
from app.api import AppError
from app.extensions import db


class ProductionState(TypedDict, total=False):
    production_command: dict | None
    production_error: dict | None


def nodes(registry):
    def tick(state):
        from app.agent.production_actions import apply_command
        run = AgentRun.query.filter_by(run_id=state["run_id"]).one()
        command = state.get("production_command")
        result = {}
        if command:
            try:
                result.update(apply_command(run, command, registry))
                result["production_error"] = None
            except AppError as error:
                if error.code not in {"PRODUCTION_QUOTE_EXPIRED", "BUDGET_EXCEEDED", "PLAN_VERSION_CONFLICT",
                    "INVALID_PRODUCTION_PLAN", "PRODUCTION_DISABLED", "UNSAFE_RETRY", "VIDEO_INCOMPLETE", "PREVIEW_INCOMPLETE"}:
                    raise
                db.session.rollback()
                from app.agent.production_actions import _save_receipt
                from app.agent.plan_versions import current_version
                current = current_version(run)
                status = state["status"]
                if current.version != state.get("plan_version"):
                    status = "production_attention"
                result = {"status": status, "plan_version": current.version, "plan": current.plan,
                    "story_package": current.story_package,
                    "production_error": {"code": error.code, "message": error.message}}
                _save_receipt(run, command["request_key"], status="completed", result=result)
            result["last_command_id"] = command.get("command_id")
        status = result.get("status", "producing")
        if status == "producing":
            status = tick_production(run, registry)
        return {**result, "status": status, "production_command": None}

    def wait(_state):
        interrupt({"kind": "production_tasks"})
        return {}

    def review(_state):
        command = interrupt({"kind": "production_review"})
        return {"production_command": command}

    return {"production_v2_tick": tick, "production_v2_wait": wait, "production_v2_review": review}
