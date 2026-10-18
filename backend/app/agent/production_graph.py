"""Persistent production interrupts; historical storyboard approvals stay inert."""

from typing import TypedDict

from langgraph.types import interrupt

from app.agent.production_engine import tick_production
from app.models import AgentRun


class ProductionState(TypedDict, total=False):
    production_command: dict | None


def nodes(registry):
    def tick(state):
        from app.agent.production_actions import apply_command
        run = AgentRun.query.filter_by(run_id=state["run_id"]).one()
        command = state.get("production_command")
        result = {}
        if command:
            result.update(apply_command(run, command, registry))
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
