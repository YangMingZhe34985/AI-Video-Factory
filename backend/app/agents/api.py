"""Owner-scoped v3 projections and durable command admission."""

import hashlib
import json
import re
from copy import deepcopy
from typing import Literal

from flask import current_app
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.clarify import Answer
from app.agent.plan_versions import _lock_run
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentStep, ToolInvocation
from app.tools.budget import BudgetGuard
from app.utils.ids import new_id
from app.utils.time_utils import isoformat


class RuntimeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["answer", "reject", "resume", "approve_plan", "approve_gate", "approve_results"]
    request_key: str = Field(min_length=1, max_length=128)
    card_id: str | None = Field(default=None, min_length=1, max_length=80)
    answers: list[Answer] = Field(default_factory=list, max_length=3)
    use_defaults: bool = False
    plan_version: int | None = Field(default=None, ge=1, strict=True)
    repair_budget_credits: float = Field(default=0, ge=0, allow_inf_nan=False)
    gate_node_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "answer" and self.card_id is None:
            raise ValueError("An answer needs card_id")
        fields = {"answer": {"card_id", "answers", "use_defaults"},
            "approve_plan": {"plan_version", "repair_budget_credits"},
            "approve_gate": {"plan_version", "gate_node_id"}, "approve_results": {"plan_version"}}
        if self.model_fields_set - {"action", "request_key"} - fields.get(self.action, set()):
            raise ValueError("Fields do not match the selected action")
        if self.action.startswith("approve_") and self.plan_version is None:
            raise ValueError("Approval requires an exact plan_version")
        if self.action == "approve_gate" and self.gate_node_id is None:
            raise ValueError("Gate approval requires gate_node_id")
        return self


def safe_text(value, limit=160):
    value = str(value or "")
    value = re.sub(r"(?i)(?:bearer\s+\S+|sk-[A-Za-z0-9_-]+|https?://\S+)", "[已隐藏]", value)
    value = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+", r"\1=[已隐藏]", value)
    return value[:limit]


def step_page(run, page=1, per_page=30):
    query = AgentStep.query.filter_by(run_id=run.run_id)
    items = query.order_by(AgentStep.id).offset((page - 1) * per_page).limit(per_page).all()
    labels = {"llm": "完成一次规划回合", "tool": "调用受控工具", "delegate": "创建子委派", "ask": "请求用户澄清"}
    return {"items": [{"agent": item.agent, "kind": item.kind, "tool": item.tool,
                       "summary": labels.get(item.kind, "运行步骤"), "credits": item.credits,
                       "at": isoformat(item.created_at)} for item in items],
            "page": page, "per_page": per_page, "total": query.count()}


def public_view(run):
    from app.api.agent import attachment_metadata
    delegations = AgentDelegation.query.filter_by(run_id=run.run_id).order_by(AgentDelegation.id).all()
    spent = {}
    for row in ToolInvocation.query.filter_by(budget_scope=run.run_id).filter(
            ToolInvocation.status != "rejected", ToolInvocation.caller_agent.is_not(None)).all():
        spent[row.delegation_id] = spent.get(row.delegation_id, 0.0) + row.estimated_cost
    root = next((item for item in delegations if item.parent_id is None), None)
    limit = root.credits_limit if root else min(run.request["budget_limit"], current_app.config["AGENT_V3_PLANNING_CREDITS"])
    snapshot = run.snapshot or {}
    output = root.output or {} if root else {}
    # Explicit projection: never serialize persisted prompts, messages or workspace payloads.
    from app.plans.views import public_plan
    return {"run_id": run.run_id, "schema_version": 3, "status": run.status,
            "text": run.request["text"], "attachments": attachment_metadata(run),
            "created_at": isoformat(run.created_at), "updated_at": isoformat(run.updated_at),
            "estimated_spent": BudgetGuard.spent(run.run_id), "budget_limit": run.request["budget_limit"],
            "planning_budget": {"limit": limit, "spent": sum(spent.values())},
            "agents": [{"delegation_id": item.id, "parent_id": item.parent_id, "agent": item.agent,
                        "status": item.status, "task_summary": safe_text(item.task),
                        "credits": spent.get(item.id, 0.0), "steps": item.steps} for item in delegations],
            "steps": step_page(run)["items"],
            "pending_card": snapshot.get("pending_card") if run.status == "awaiting_input" else None,
            "message": safe_text(output.get("message") or output.get("reason"), 4000) if root and root.agent == "producer" else None,
            "error": {"code": safe_text((run.error or {}).get("code"), 80),
                      "message": "规划已停止，请检查步骤记录。"} if run.error else None,
            **public_plan(run), "patches": [],
            "mock": current_app.config.get("MODEL_ADAPTER_MODE") == "mock"}


def admit_action(run, data):
    from app.agents.tools import validate_answers
    run = _lock_run(run)
    body = data.model_dump(mode="json", exclude={"request_key"})
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    snapshot = deepcopy(run.snapshot or {})
    receipts = snapshot.setdefault("v3_action_receipts", {})
    existing = receipts.get(data.request_key)
    if existing:
        if existing["digest"] != digest:
            raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Action key belongs to another request", 409)
        db.session.commit()
        return
    interrupted_command = deepcopy(run.command)
    if run.command is not None and not (run.status == "attention" and data.action in {"resume", "reject"}):
        raise AppError("INVALID_AGENT_STATE", "An action is already pending", 409)
    if data.action == "answer":
        if run.status != "awaiting_input" or not snapshot.get("pending_card"):
            raise AppError("INVALID_AGENT_STATE", "No pending clarification", 409)
        validate_answers(snapshot["pending_card"], {key: body[key] for key in ("card_id", "answers", "use_defaults")})
    elif data.action == "resume":
        if run.status != "attention" or run.resume_count >= 2:
            raise AppError("INVALID_AGENT_STATE", "Recovery is not available", 409)
        run.resume_count += 1
    elif data.action.startswith("approve_"):
        from app.agent.plan_versions import require_current_version
        require_current_version(run, data.plan_version)
        expected = {"approve_plan": "awaiting_plan_review", "approve_gate": "awaiting_gate",
                    "approve_results": "awaiting_result_review"}[data.action]
        if run.status != expected:
            raise AppError("INVALID_AGENT_STATE", "The selected approval is not available", 409)
    elif run.status in {"success", "partial_success", "failed", "cancelled"}:
        raise AppError("INVALID_AGENT_STATE", "This run has already ended", 409)
    command_id = new_id("v3cmd")
    receipts[data.request_key] = {"digest": digest, "command_id": command_id}
    run.snapshot = snapshot
    # A worker exception preserves its inbox. Explicit recovery retries that
    # exact accepted command, including the original idempotency receipt.
    run.command = interrupted_command if data.action == "resume" and interrupted_command else {**body, "command_id": command_id}
    if data.action in {"resume", "reject"} and run.status == "attention":
        run.status = "understanding"
    db.session.commit()
