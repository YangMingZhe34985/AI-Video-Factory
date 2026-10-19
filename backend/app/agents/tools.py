"""Agent coordination tools. Every mutation is invoked through ToolRegistry."""

from copy import deepcopy
from typing import Literal

from flask import current_app
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, model_serializer, model_validator

from app.agent.clarify import AnswerSubmission, Question, max_rounds, resolve_answers
from app.agents.schemas import WorkspaceRef, WorkspaceKey
from app.agents.prompt_scope import PromptScope, PromptUpdate
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation
from app.tools.agent_chat import AGENT_ROLES
from app.tools.spec import ToolSpec
from app.utils.ids import new_id


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Empty(Strict):
    pass


class ObjectOutput(RootModel[dict]):
    pass


class AgentListOutput(RootModel[list[dict]]):
    pass


class ReadInput(Strict):
    key: WorkspaceKey | None = None
    kind: str | None = None
    version: int | None = Field(default=None, ge=1, strict=True)


class WriteInput(Strict):
    key: WorkspaceKey
    kind: str
    payload: dict


class DelegateInput(Strict):
    agent: str
    task: str = Field(min_length=1, max_length=2000)
    context_refs: list[WorkspaceRef] = Field(default_factory=list, max_length=40)
    expected: str = Field(min_length=1, max_length=300)
    planning_credits: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    prompt_scope: PromptScope | None = None

    @model_validator(mode="after")
    def scoped_prompt_target(self):
        if self.agent == "prompt_smith" and self.prompt_scope is None:
            raise ValueError("Prompt Smith delegation requires prompt_scope")
        if self.agent != "prompt_smith" and self.prompt_scope is not None:
            raise ValueError("Only Prompt Smith accepts prompt_scope")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_receipts(self, handler):
        value = handler(self)
        if self.prompt_scope is None:
            value.pop("prompt_scope", None)
        return value


class AskInput(Strict):
    questions: list[Question] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_questions(self):
        if len({q.question_id for q in self.questions}) != len(self.questions):
            raise ValueError("Question identifiers must be unique")
        return self


class ClarificationCardV3(Strict):
    card_id: str = Field(min_length=1, max_length=80)
    asked_by: Literal["producer"] = "producer"
    questions: list[Question] = Field(min_length=1, max_length=3)


def validate_answers(card, submission):
    checked = ClarificationCardV3.model_validate(card)
    # The v2 resolver is pure. Adapt only its old role discriminator locally;
    # never change v2 cards or expose a misleading role in the v3 response.
    value = checked.model_dump(mode="json")
    value["asked_by"] = "intake"
    return resolve_answers(value, AnswerSubmission.model_validate(submission))


class FinishInput(Strict):
    kind: Literal["completed", "returned", "failed"]
    outcome: Literal["answer", "cancelled", "plan_submitted"] | None = None
    message: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, min_length=1, max_length=2000)
    suggestion: str | None = Field(default=None, max_length=2000)
    plan_ref: WorkspaceRef | None = None
    dossier_ref: WorkspaceRef | None = None
    story_ref: WorkspaceRef | None = None
    patch_ref: WorkspaceRef | None = None
    rationale: str | None = Field(default=None, max_length=2000)
    diagnosis: str | None = Field(default=None, max_length=2000)
    updates: list[PromptUpdate] | None = Field(default=None, min_length=1, max_length=200)
    verdict: Literal["pass", "revise"] | None = None
    issues: list[dict] | None = Field(default=None, max_length=200)


class ReviewIssue(Strict):
    node_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,40}$")
    severity: Literal["info", "warning", "error"]
    message: str = Field(min_length=1, max_length=2000)


def _context(ctx):
    from app.agents.budget import TERMINAL
    from app.agents.workspace import require_context
    run, delegation = require_context(ctx)
    if delegation.status in TERMINAL or run.status in {"success", "partial_success", "failed", "cancelled"}:
        raise AppError("AGENT_NOT_ACTIVE", "Finished delegations cannot create new coordination actions", 409)
    return run, delegation


def _delegate(data, ctx):
    from app.agent.plan_versions import _lock_run, inputs_hash
    from app.agents.budget import TERMINAL, allocate
    from app.agents.cards import get_catalog
    from app.agents.workspace import resolve_workspace_ref
    from app.agents.prompt_scope import freeze_scope, validate_delegate_receipt
    run, parent = _context(ctx)
    from app.agents.repair_flow import active_flow
    _lock_run(run)
    run, parent = _context(ctx)
    existing = AgentDelegation.query.filter_by(run_id=run.run_id, request_key=ctx.idempotency_key).first()
    if existing:
        validate_delegate_receipt(data, parent, existing, ctx)
        return {"delegation_id": existing.id, "status": existing.status,
                "output_ref": existing.output, "returned_reason": (existing.output or {}).get("reason")}
    flow = active_flow(run)
    assigned_author = bool(flow and parent.agent == "producer" and flow["stage"] == "author_pending"
        and ctx.idempotency_key == f"{flow['flow_id']}:delegate:author" and data.agent == flow["author_role"])
    assigned_review = bool(flow and parent.agent == "producer" and flow["stage"] == "review_pending"
        and ctx.idempotency_key == f"{flow['flow_id']}:delegate:review" and data.agent == "director")
    if (flow and not (assigned_author or assigned_review)) or (data.agent == "repair" and not assigned_author):
        raise AppError("DELEGATION_FORBIDDEN", "Repair coordination uses server-assigned delegations only", 403)
    catalog = get_catalog()
    card = catalog.cards[parent.agent]
    if data.agent not in card.can_delegate_to:
        raise AppError("DELEGATION_FORBIDDEN", "This Agent cannot delegate to that role", 403)
    if parent.depth >= min(3, int(current_app.config.get("AGENT_V3_MAX_DELEGATION_DEPTH", 3))):
        raise AppError("DELEGATION_DEPTH_EXCEEDED", "Delegation depth limit reached", 422)
    children = AgentDelegation.query.filter_by(run_id=run.run_id, parent_id=parent.id).all()
    if sum(child.status not in TERMINAL for child in children) >= card.limits.max_parallel_delegations:
        raise AppError("DELEGATION_PARALLEL_LIMIT", "Too many live child delegations", 422)
    for ref in data.context_refs:
        resolve_workspace_ref(ref.model_dump(), ctx)
    state = {"delegate_input_hash": inputs_hash(data.model_dump(mode="json"))}
    if data.prompt_scope is not None:
        state["prompt_scope"] = freeze_scope(data.prompt_scope,
            [ref.model_dump(mode="json") for ref in data.context_refs], ctx)
    child = AgentDelegation(run_id=run.run_id, parent_id=parent.id, agent=data.agent,
        task=data.task, expected=data.expected, context_refs=[ref.model_dump() for ref in data.context_refs],
        depth=parent.depth + 1, credits_limit=allocate(parent, data.planning_credits, catalog.cards[data.agent]),
        request_key=ctx.idempotency_key, status="pending", state=state)
    db.session.add(child)
    db.session.commit()
    return {"delegation_id": child.id, "status": child.status}


def _ask(data, ctx):
    from app.agents.workspace import require_artifact, validate_artifact_references, write_workspace
    run, delegation = _context(ctx)
    questions = [question.model_dump(mode="json") for question in data.questions]
    validate_artifact_references({"questions": questions}, ctx)
    for question in data.questions:
        for option in question.options:
            if option.image_artifact_id:
                artifact = require_artifact(option.image_artifact_id, ctx)
                if not artifact.mime_type.startswith("image/"):
                    raise AppError("INVALID_CLARIFICATION", "A choice thumbnail must reference an image", 422)
    state = deepcopy(delegation.state or {})
    receipts = state.setdefault("ask_receipts", {})
    if ctx.idempotency_key in receipts:
        return receipts[ctx.idempotency_key]
    if delegation.agent != "producer":
        delegation.status = "returned"
        delegation.output = {"kind": "returned", "reason": "Clarification requires Producer review",
                             "questions": questions, "suggestion": "Merge questions or answer from known constraints."}
        output = {"status": "returned", "questions": questions}
        receipts[ctx.idempotency_key] = output
        delegation.state = state
        db.session.commit()
        return output
    if state.get("pending_card"):
        return {"status": "awaiting_input", "card": state["pending_card"]}
    if state.get("clarify_rounds", 0) >= max_rounds():
        from hashlib import sha256
        from app.agent.clarify import _fallback, _assumption
        card_id = "card_" + sha256(ctx.idempotency_key.encode()).hexdigest()[:24]
        card = ClarificationCardV3(card_id=card_id, questions=data.questions).model_dump(mode="json")
        resolutions = {question.question_id: _fallback(question) for question in data.questions}
        assumptions = [_assumption(item) for item in resolutions.values()]
        write_workspace(f"clarification.{card_id}", "clarification",
            {"card": card, "answers": resolutions, "asked": False, "assumptions": assumptions}, ctx)
        output = {"status": "resolved", "answers": resolutions, "assumptions": assumptions}
        state["assumptions"] = [*state.get("assumptions", []), *assumptions]
        receipts[ctx.idempotency_key] = output
        delegation.state = state
        db.session.commit()
        return output
    card = ClarificationCardV3(card_id=new_id("card"), questions=data.questions).model_dump(mode="json")
    state["pending_card"] = card
    state["ask_key"] = ctx.idempotency_key
    output = {"status": "awaiting_input", "card": card}
    receipts[ctx.idempotency_key] = output
    delegation.state = state
    delegation.status = "awaiting_input"
    run.status = "awaiting_input"
    db.session.commit()
    return output


def _finish(data, ctx):
    from app.agents.workspace import require_context, resolve_workspace_ref
    from app.agents.budget import submitted_producer
    _run, delegation = require_context(ctx)
    submitted = submitted_producer(_run, delegation)
    if not submitted:
        _run, delegation = _context(ctx)
    elif data.kind != "completed" or data.outcome != "plan_submitted":
        raise AppError("AGENT_NOT_ACTIVE", "Submitted Producer may only acknowledge its submitted Plan", 409)
    output = data.model_dump(mode="json", exclude_none=True)
    from app.agents.repair_flow import active_flow
    flow = active_flow(_run)
    if data.kind == "completed" and flow and delegation.id in {
            flow.get("author_delegation_id"), flow.get("review_delegation_id")}:
        raise AppError("PATCH_TOOL_REQUIRED", "Assigned Patch Agents complete through propose_patch or review_patch", 409)
    fields = set(output) - {"kind"}
    if data.kind in {"returned", "failed"}:
        if not data.reason or fields - {"reason", "suggestion"}:
            raise AppError("INVALID_AGENT_OUTPUT", "Returned/failed output requires only reason and optional suggestion", 422)
    else:
        required = {
            "producer": {"outcome", "message"}, "research": {"dossier_ref"}, "creative": {"story_ref"},
            "director": {"plan_ref", "rationale"}, "prompt_smith": {"updates"},
            "critic": {"verdict", "issues"}, "repair": {"patch_ref", "diagnosis"},
        }[delegation.agent]
        if delegation.agent == "producer" and data.outcome == "plan_submitted":
            required = required | {"plan_ref"}
        if fields != required:
            raise AppError("INVALID_AGENT_OUTPUT", "Completed output does not match this Agent's contract", 422,
                           payload={"field": sorted(fields), "allowed": sorted(required)})
        if delegation.agent == "producer" and data.outcome == "plan_submitted":
            submission = (_run.snapshot or {}).get("v3_plan_submission", {})
            from app.agent.plan_versions import require_current_version
            if not data.plan_ref or submission.get("plan_ref") != data.plan_ref.model_dump():
                raise AppError("PLAN_NOT_SUBMITTED", "Finish must reference the server-submitted Plan", 409)
            require_current_version(_run, submission.get("plan_version"))
        for field, kind in (("dossier_ref", "research_dossier"), ("story_ref", "story"),
                            ("plan_ref", "plan_draft"), ("patch_ref", "patch")):
            if getattr(data, field) is not None:
                resolve_workspace_ref(getattr(data, field).model_dump(), ctx, expected_kind=kind)
        if data.updates is not None:
            from app.agents.prompt_scope import validate_updates
            output["updates"] = validate_updates(data.updates, delegation, ctx)
        if data.issues is not None:
            output["issues"] = [ReviewIssue.model_validate(item).model_dump() for item in data.issues]
    if submitted:
        return {"status": "completed", "output": delegation.output}
    delegation.status = data.kind
    delegation.output = output
    from app.agents.budget import TERMINAL
    from app.agents.runtime import _stop
    for child in AgentDelegation.query.filter_by(run_id=delegation.run_id, parent_id=delegation.id).all():
        if child.status not in TERMINAL:
            _stop(child, "cancelled", "PARENT_FINISHED")
    db.session.commit()
    return {"status": data.kind, "output": output}


def _read(data, ctx):
    from app.agents.workspace import read_workspace
    return read_workspace(ctx, **data.model_dump())


def _write(data, ctx):
    from app.agents.workspace import write_workspace
    if data.kind == "clarification":
        raise AppError("WORKSPACE_KIND_FORBIDDEN", "Clarification answers are written only by the user-answer path", 403)
    return write_workspace(data.key, data.kind, data.payload, ctx)


def register_agent_tools(registry):
    from app.agents.cards import get_catalog
    entries = [
        ("list_agents", Empty, AgentListOutput,
            lambda _data, _ctx: [item for item in get_catalog().describe() if item["name"] != "repair"], "read"),
        ("read_workspace", ReadInput, ObjectOutput, _read, "read"),
        ("write_workspace", WriteInput, ObjectOutput, _write, "write"),
        ("delegate", DelegateInput, ObjectOutput, _delegate, "write"),
        ("ask_user", AskInput, ObjectOutput, _ask, "write"),
        ("finish", FinishInput, ObjectOutput, _finish, "write"),
    ]
    descriptions = {
        "list_agents": "List available collaborator roles and their input/output contracts.",
        "read_workspace": "Read scoped immutable workspace versions or list latest items.",
        "write_workspace": "Append a typed workspace decision; never grants execution approval.",
        "delegate": "Delegate a bounded task using immutable context references and an allocated planning quota.",
        "ask_user": "Ask 1-3 multiple-choice questions; only Producer displays them, other roles return them upward.",
        "finish": "End this delegation with its role-specific completed output, or returned/failed with reason.",
    }
    for name, inputs, outputs, handler, permission in entries:
        registry.register(ToolSpec(name=name, description=descriptions[name], input_model=inputs,
            output_model=outputs, handler=handler, permission=permission, allowed_roles=AGENT_ROLES,
            agent_visible=True, max_retries=0))
