"""Scoped Patch proposals and independent Director review receipts."""
from copy import deepcopy
from typing import Literal

from pydantic import Field, RootModel, model_validator

from app.agent.plan_versions import _lock_run, inputs_hash, require_current_version
from app.agent.request_spec import StrictModel
from app.agents.schemas import finite_json
from app.agents.workspace import require_context, validate_artifact_references
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentWorkspaceItem, PlanNodeTask
from app.plans.patch_schemas import PatchDraft
from app.tools.spec import ToolSpec
from app.utils.ids import new_id


class ProposeInput(StrictModel):
    draft: PatchDraft


class ReviewInput(StrictModel):
    patch_id: str = Field(min_length=1, max_length=80)
    verdict: Literal["approve", "revise", "reject"]
    reason: str = Field(min_length=1, max_length=2000)
    revised_draft: PatchDraft | None = None

    @model_validator(mode="after")
    def revision_matches_verdict(self):
        if (self.verdict == "revise") != (self.revised_draft is not None):
            raise ValueError("Only a revise verdict requires a replacement draft")
        return self


class Output(RootModel[dict]):
    pass


INPUTS = {"propose_patch": ProposeInput, "review_patch": ReviewInput}


def validate_evidence(draft, ctx):
    from app.agents.workspace import resolve_workspace_ref
    run, _delegation = require_context(ctx)
    for evidence in draft.get("evidence_refs", []):
        if "task_id" in evidence and PlanNodeTask.query.filter_by(
                id=evidence["task_id"], run_id=run.run_id, plan_version=draft["base_version"]).first() is None:
            raise AppError("INVALID_PATCH_EVIDENCE", "Failure evidence must belong to this Run and base version", 422)
        if "workspace_ref" in evidence:
            resolve_workspace_ref(evidence["workspace_ref"], ctx)
    validate_artifact_references(draft, ctx, plan_refs=True)


def _key(ctx):
    if not isinstance(ctx.idempotency_key, str) or not 1 <= len(ctx.idempotency_key) <= 128:
        raise AppError("INVALID_AGENT_CONTEXT", "Patch mutations require a server request key", 403)
    return ctx.idempotency_key


def _receipt(run, name, data, ctx):
    receipt = (run.snapshot or {}).get("v3_patch_tool_receipts", {}).get(_key(ctx))
    if receipt is None:
        return None
    if (receipt["name"] != name or receipt["input_hash"] != inputs_hash(data)
            or receipt["delegation_id"] != ctx.delegation_id or receipt["agent"] != ctx.caller_agent):
        raise AppError("IDEMPOTENCY_CONFLICT", "Patch tool key belongs to different inputs", 409)
    return deepcopy(receipt["output"])


def recover_receipt(name, data, ctx):
    if name not in INPUTS:
        return None
    run, _delegation = require_context(ctx)
    return _receipt(run, name, INPUTS[name].model_validate(data).model_dump(mode="json"), ctx)


def _active(ctx, name, normalized):
    run, delegation = require_context(ctx)
    run = _lock_run(run)
    old = _receipt(run, name, normalized, ctx)
    if old is not None:
        return run, delegation, None, old
    from app.agents.repair_flow import active_flow
    flow = active_flow(run)
    if (not flow or run.status != "understanding" or delegation.status not in {"pending", "running"}
            or flow.get("base_version") != normalized.get("draft", {}).get("base_version", flow["base_version"])):
        raise AppError("PATCH_FLOW_REQUIRED", "Patch tools require the active assigned repair phase", 409)
    require_current_version(run, flow["base_version"])
    return run, delegation, flow, None


def _workspace(run, delegation, key, draft, ctx):
    artifact_ids = validate_artifact_references(draft, ctx, plan_refs=True)
    row = AgentWorkspaceItem(run_id=run.run_id, key=key, version=1, kind="patch", payload=draft,
        artifact_ids=artifact_ids, author_agent=delegation.agent, delegation_id=delegation.id,
        request_key=_key(ctx), inputs_hash=inputs_hash({"key": key, "kind": "patch", "payload": draft}))
    db.session.add(row)
    return {"key": key, "version": 1}


def _save(run, flow, record, name, normalized, ctx, output):
    snapshot = deepcopy(run.snapshot or {})
    snapshot.setdefault("v3_patches", {})[record["patch_id"]] = record
    snapshot["v3_repair_flows"][flow["flow_id"]] = flow
    snapshot.setdefault("v3_patch_tool_receipts", {})[_key(ctx)] = {"name": name,
        "input_hash": inputs_hash(normalized), "delegation_id": ctx.delegation_id,
        "agent": ctx.caller_agent, "output": deepcopy(output)}
    run.snapshot = snapshot
    db.session.commit()
    return output


def propose_patch(data, ctx):
    from app.plans.patches import normalize_patch
    normalized = data.model_dump(mode="json")
    finite_json(normalized)
    run, delegation, flow, old = _active(ctx, "propose_patch", normalized)
    if old is not None:
        db.session.commit()
        return old
    if delegation.agent not in {"repair", "director"} or flow.get("author_delegation_id") != delegation.id or flow["stage"] != "author_running":
        raise AppError("TOOL_FORBIDDEN", "Only the assigned Patch author may propose this change", 403)
    draft = normalize_patch(normalized["draft"])
    validate_evidence(draft, ctx)
    patch_id = new_id("patch")
    proposal_ref = _workspace(run, delegation, f"patch.{patch_id}.proposal", draft, ctx)
    record = {"patch_id": patch_id, "draft": draft, "proposed_by": delegation.agent,
        "proposal_ref": proposal_ref, "author_delegation_id": delegation.id,
        "status": "proposed", "director_review": None, "review_delegation_id": None,
        "flow_id": flow["flow_id"], "trigger": deepcopy(flow["trigger"]), "return_status": flow["return_status"]}
    flow.update(stage="review_pending", patch_id=patch_id)
    delegation.status = "completed"
    delegation.output = {"kind": "completed", "patch_ref": proposal_ref, "diagnosis": draft["reason"]}
    output = {"patch_id": patch_id, "patch_ref": proposal_ref, "status": "review_pending"}
    return _save(run, flow, record, "propose_patch", normalized, ctx, output)


def review_patch(data, ctx):
    from app.plans.patches import normalize_patch, patch_digest
    normalized = data.model_dump(mode="json")
    finite_json(normalized)
    run, delegation, flow, old = _active(ctx, "review_patch", normalized)
    if old is not None:
        db.session.commit()
        return old
    record = deepcopy((run.snapshot or {}).get("v3_patches", {}).get(data.patch_id))
    if (not record or delegation.agent != "director" or flow.get("patch_id") != data.patch_id
            or flow["stage"] != "review_running" or record.get("review_delegation_id") != delegation.id
            or flow.get("review_delegation_id") != delegation.id or record["author_delegation_id"] == delegation.id):
        raise AppError("TOOL_FORBIDDEN", "Patch review requires its independently assigned Director", 403)
    draft = normalize_patch(normalized["revised_draft"] if data.verdict == "revise" else record["draft"])
    validate_evidence(draft, ctx)
    if draft["base_version"] != flow["base_version"]:
        raise AppError("PLAN_VERSION_CONFLICT", "Review cannot change the Patch base version", 409)
    review_ref = _workspace(run, delegation, f"patch.{data.patch_id}.review", draft, ctx)
    record.update(draft=draft, status="rejected" if data.verdict == "reject" else "reviewed", director_review={
        "verdict": data.verdict, "reason": data.reason, "delegation_id": delegation.id, "review_ref": review_ref,
        "draft_hash": patch_digest(draft), "request_key": _key(ctx), "base_version": flow["base_version"]})
    flow["stage"] = "review_rejected" if data.verdict == "reject" else "quote_pending"
    delegation.status = "completed"
    delegation.output = {"kind": "completed", "patch_ref": review_ref, "verdict": data.verdict, "rationale": data.reason}
    return _save(run, flow, record, "review_patch", normalized, ctx,
        {"patch_id": data.patch_id, "review_ref": review_ref, "status": record["status"]})


def register_patch_tools(registry):
    registry.register(ToolSpec(name="propose_patch", description="Submit a local Patch draft for independent Director review; never grants generation approval.",
        input_model=ProposeInput, output_model=Output, handler=propose_patch, permission="write",
        allowed_roles=frozenset({"repair", "director"}), agent_visible=True, max_retries=0))
    registry.register(ToolSpec(name="review_patch", description="Assigned Director approves, revises or rejects one exact Patch; this review does not authorize paid execution.",
        input_model=ReviewInput, output_model=Output, handler=review_patch, permission="write",
        allowed_roles=frozenset({"director"}), agent_visible=True, max_retries=0))
