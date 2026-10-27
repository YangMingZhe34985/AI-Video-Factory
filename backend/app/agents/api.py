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
    action: Literal["answer", "reject", "resume", "approve_plan", "approve_gate", "approve_results",
                    "revise_plan", "approve_patch", "reject_patch"]
    request_key: str = Field(min_length=1, max_length=128)
    card_id: str | None = Field(default=None, min_length=1, max_length=80)
    answers: list[Answer] = Field(default_factory=list, max_length=3)
    use_defaults: bool = False
    plan_version: int | None = Field(default=None, ge=1, strict=True)
    repair_budget_credits: float = Field(default=0, ge=0, allow_inf_nan=False)
    gate_node_id: str | None = Field(default=None, min_length=1, max_length=80)
    selected_artifact_id: str | None = Field(default=None, min_length=1, max_length=100)
    choice_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    message: str | None = Field(default=None, min_length=1, max_length=4000)
    patch_id: str | None = Field(default=None, min_length=1, max_length=128)
    quote_id: str | None = Field(default=None, min_length=1, max_length=128)
    scope: Literal["only", "cascade"] | None = None
    confirm_template_write: bool | None = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "answer" and self.card_id is None:
            raise ValueError("An answer needs card_id")
        fields = {"answer": {"card_id", "answers", "use_defaults"},
            "approve_plan": {"plan_version", "repair_budget_credits", "confirm_template_write"},
            "approve_gate": {"plan_version", "gate_node_id", "selected_artifact_id", "choice_digest"}, "approve_results": {"plan_version"},
            "revise_plan": {"plan_version", "message", "gate_node_id"},
            "approve_patch": {"patch_id", "quote_id", "scope"},
            "reject_patch": {"patch_id", "quote_id", "scope"}}
        if self.model_fields_set - {"action", "request_key"} - fields.get(self.action, set()):
            raise ValueError("Fields do not match the selected action")
        if self.action in {"approve_plan", "approve_gate", "approve_results", "revise_plan"} and self.plan_version is None:
            raise ValueError("Approval requires an exact plan_version")
        if self.action == "approve_gate" and self.gate_node_id is None:
            raise ValueError("Gate approval requires gate_node_id")
        if self.action == "revise_plan" and not (self.message or "").strip():
            raise ValueError("Revision needs a nonempty instruction")
        if self.action in {"approve_patch", "reject_patch"} and not all((self.patch_id, self.quote_id, self.scope)):
            raise ValueError("Patch action requires an exact quote and scope")
        return self


class PatchQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patch_id: str = Field(min_length=1, max_length=128)
    scope: Literal["only", "cascade"] | None = None


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
    from app.plans.views import public_plan, public_patches, repair_budget
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
            **public_plan(run), "patches": public_patches(run), "repair_budget": repair_budget(run),
            "action_pending": run.command is not None, "resume_count": run.resume_count,
            "mock": current_app.config.get("MODEL_ADAPTER_MODE") == "mock"}


def admit_action(run, data):
    from app.agents.tools import validate_answers
    run = _lock_run(run)
    body = data.model_dump(mode="json", exclude={"request_key"})
    # Optional V9 fields must not alter pre-V9 action receipt hashes.
    for field in ("selected_artifact_id", "choice_digest", "confirm_template_write"):
        if body[field] is None:
            body.pop(field)
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
    replay_completed = False
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
    elif data.action in {"approve_patch", "reject_patch"}:
        replay_completed = _validate_patch_action(run, data)
    elif data.action == "revise_plan":
        from app.agent.plan_versions import require_current_version
        from app.plans.patch_execution import assert_patch_idle
        version = require_current_version(run, data.plan_version)
        if run.status not in {"awaiting_plan_review", "awaiting_result_review", "awaiting_gate", "attention"}:
            raise AppError("INVALID_AGENT_STATE", "Revision is not available", 409)
        assert_patch_idle(run)
        if run.status == "awaiting_gate":
            from app.plans.runtime import feedback_gate
            feedback_gate(run, version, data.gate_node_id)
        elif data.gate_node_id is not None:
            raise AppError("INVALID_AGENT_STATE", "Gate feedback needs a pending gate", 409)
    elif data.action in {"approve_plan", "approve_gate", "approve_results"}:
        from app.agent.plan_versions import require_current_version
        version = require_current_version(run, data.plan_version)
        expected = {"approve_plan": "awaiting_plan_review", "approve_gate": "awaiting_gate",
                    "approve_results": "awaiting_result_review"}[data.action]
        if run.status != expected:
            raise AppError("INVALID_AGENT_STATE", "The selected approval is not available", 409)
        if data.action == "approve_plan":
            total = version.check.get("estimates", {}).get("total_credits")
            if total is None:
                raise AppError("INVALID_EXECUTION_PLAN", "Plan estimate is unavailable", 409)
            BudgetGuard.check(run.run_id, run.request["budget_limit"], total + data.repair_budget_credits)
            if version.check.get("template_writes") and data.confirm_template_write is not True:
                raise AppError("TEMPLATE_WRITE_CONFIRMATION_REQUIRED",
                               "Confirm writing prompt versions to the classic template before approval", 422)
        elif data.action == "approve_gate":
            from app.plans.execution import usable
            from app.plans.runtime import latest_tasks
            task = latest_tasks(run, version).get(data.gate_node_id)
            node = next((node for node in version.plan["nodes"] if node["id"] == data.gate_node_id), {})
            if node.get("gate") == "choice":
                from app.plans.choices import validate_action
                validate_action(run, version, data.gate_node_id, data.selected_artifact_id, data.choice_digest)
            elif data.model_fields_set & {"selected_artifact_id", "choice_digest"}:
                raise AppError("INVALID_CHOICE", "Preview approval does not accept a selected candidate", 422)
            elif not node.get("gate") or task is None or task.status != "success" or not usable(run, task) or data.gate_node_id in snapshot.get("v3_execution", {}).get("approved_gates", []):
                raise AppError("INVALID_GATE", "Approve a completed unapproved preview gate", 409)
    elif run.status in {"success", "partial_success", "failed", "cancelled"}:
        raise AppError("INVALID_AGENT_STATE", "This run has already ended", 409)
    command_id = new_id("v3cmd")
    receipts[data.request_key] = {"digest": digest, "command_id": command_id}
    run.snapshot = snapshot
    if replay_completed:
        db.session.commit()
        return
    # A worker exception preserves its inbox. Explicit recovery retries that
    # exact accepted command, including the original idempotency receipt.
    run.command = interrupted_command if data.action == "resume" and interrupted_command else {**body, "command_id": command_id,
        "admitted_from_status": run.status}
    if data.action in {"resume", "reject", "revise_plan", "approve_patch", "reject_patch"} and run.status == "attention":
        run.status = "understanding"
    db.session.commit()


def _validate_patch_action(run, data):
    from app.agent.plan_versions import require_current_version
    from app.plans.patch_execution import assert_patch_idle
    from app.plans.patches import quote_patch
    record = (run.snapshot or {}).get("v3_patches", {}).get(data.patch_id)
    if not record:
        raise AppError("PATCH_NOT_FOUND", "Patch does not belong to this Run", 404)
    terminal = "applied" if data.action == "approve_patch" else "rejected"
    receipt = record.get("approval" if data.action == "approve_patch" else "rejection") or {}
    if record.get("status") == terminal and receipt.get("quote_id") == data.quote_id and receipt.get("scope") == data.scope:
        return True
    if record.get("status") not in {"reviewed", "awaiting_approval"} or run.status not in {"attention", "awaiting_result_review"}:
        raise AppError("INVALID_AGENT_STATE", "Patch is not available for approval", 409)
    require_current_version(run, record["draft"]["base_version"])
    assert_patch_idle(run)
    quote = quote_patch(run, record, scope=data.scope)["quote"]
    if quote["quote_id"] != data.quote_id:
        raise AppError("PATCH_QUOTE_CHANGED", "Patch quote has changed; review it again", 409)
    if data.action == "approve_patch" and not quote.get("manual_can_apply", quote["can_apply"]):
        raise AppError("INVALID_PATCH", "Patch does not pass validation", 422)
    return False
