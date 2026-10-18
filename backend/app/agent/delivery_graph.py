"""Checkpoint bridge into the deterministic local Editor."""
from typing import TypedDict
from langgraph.types import interrupt
from app.agent import delivery
from app.api import AppError
from app.models import AgentRun

class DeliveryState(TypedDict, total=False):
    delivery_command: dict | None
    delivery_error: dict | None


def nodes(registry):
    def tick(state):
        row = AgentRun.query.filter_by(run_id=state["run_id"]).one()
        command = state.get("delivery_command")
        result = {}
        if command:
            try:
                result.update(delivery.apply_command(row, command))
            except AppError as error:
                delivery.update(row, stage="failed", error={"code": error.code, "message": error.message})
                result["status"] = "delivery_attention"
            result["last_command_id"] = command.get("command_id")
        if result.get("status", "editing") == "editing":
            result["status"] = delivery.tick(row, registry)
        result["delivery_error"] = (row.snapshot or {}).get("delivery", {}).get("error")
        return {**result, "delivery_command": None}
    def wait(_state):
        interrupt({"kind": "delivery_tasks"})
        return {}
    def review(_state):
        return {"delivery_command": interrupt({"kind": "delivery_review"})}
    return {"delivery_v2_tick": tick, "delivery_v2_wait": wait, "delivery_v2_review": review}
