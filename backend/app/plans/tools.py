"""Read-only checks and atomic planning receipts. Submission is not approval."""

from copy import deepcopy
from hashlib import sha256

from pydantic import Field, RootModel, ValidationError

from app.agent.plan_versions import _lock_run, inputs_hash
from app.agent.request_spec import StrictModel
from app.agents.schemas import PlanDraft, WorkspaceRef, finite_json, validate_payload
from app.agents.workspace import require_context, resolve_workspace_ref, validate_artifact_references
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentPlanVersion, AgentWorkspaceItem
from app.plans.compiler import authoring_plan, compile_plan, plan_digest
from app.plans.dry_run import dry_run
from app.tools.agent_chat import AGENT_ROLES
from app.tools.spec import ToolSpec


class CheckInput(StrictModel):
    plan: PlanDraft


class InstantiateInput(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,79}$")
    params: dict = Field(default_factory=dict)


class SubmitInput(StrictModel):
    plan_ref: WorkspaceRef


class ObjectOutput(RootModel[dict]):
    pass


INPUTS = {"instantiate_blueprint": InstantiateInput, "submit_plan": SubmitInput}
FINISHED = frozenset({"completed", "returned", "failed", "limit", "cancelled", "success"})


def _key(ctx):
    if not isinstance(ctx.idempotency_key, str) or not 1 <= len(ctx.idempotency_key) <= 128:
        raise AppError("INVALID_AGENT_CONTEXT", "Planning mutations require a server request key", 403)
    return ctx.idempotency_key


def _receipt(run, name, normalized, ctx):
    receipt = ((run.snapshot or {}).get("v3_plan_tool_receipts") or {}).get(_key(ctx))
    if receipt is None:
        return None
    if (receipt.get("name") != name or receipt.get("input_hash") != inputs_hash(normalized)
            or receipt.get("agent") != ctx.caller_agent or receipt.get("delegation_id") != ctx.delegation_id):
        raise AppError("IDEMPOTENCY_CONFLICT", "Planning request key belongs to a different operation", 409)
    return deepcopy(receipt["output"])


def recover_receipt(name, data, ctx):
    """Recover the local-commit/Registry-commit gap without repeating a write."""
    if name not in INPUTS:
        return None
    normalized = INPUTS[name].model_validate(data).model_dump(mode="json")
    run, _delegation = require_context(ctx)
    return _receipt(run, name, normalized, ctx)


def _active_locked(ctx):
    run, delegation = require_context(ctx)
    run = _lock_run(run)
    delegation = AgentDelegation.query.populate_existing().filter_by(id=delegation.id, run_id=run.run_id).with_for_update().one()
    return run, delegation


def _assert_active(run, delegation):
    if delegation.status in FINISHED or run.status not in {"queued", "understanding", "attention"}:
        raise AppError("AGENT_NOT_ACTIVE", "Only an active planning phase can create or submit a new plan", 409)


def _save_receipt(run, name, normalized, ctx, output):
    snapshot = deepcopy(run.snapshot or {})
    snapshot.setdefault("v3_plan_tool_receipts", {})[_key(ctx)] = {
        "name": name, "input_hash": inputs_hash(normalized), "agent": ctx.caller_agent,
        "delegation_id": ctx.delegation_id, "output": deepcopy(output)}
    run.snapshot = snapshot


def public_check(compiled):
    return {name: deepcopy(compiled[name]) for name in ("plan", "issues", "estimates", "experimental", "dag")}


def check_plan(data, ctx):
    run, _delegation = require_context(ctx)
    return public_check(compile_plan(data.plan, run))


def instantiate_blueprint(data, ctx):
    """Save draft, provenance and replay receipt in one Run-locked transaction."""
    from app.plans.blueprints import BUILDERS, VERSION
    normalized = data.model_dump(mode="json")
    finite_json(normalized)
    try:
        run, delegation = _active_locked(ctx)
        previous = _receipt(run, "instantiate_blueprint", normalized, ctx)
        if previous is not None:
            db.session.commit()
            return previous
        _assert_active(run, delegation)
        if data.name not in BUILDERS:
            raise AppError("BLUEPRINT_NOT_FOUND", "Unknown registered Blueprint", 404)
        schema, builder = BUILDERS[data.name]
        try:
            params = schema.model_validate(data.params)
        except ValidationError as error:
            raise AppError("INVALID_BLUEPRINT_INPUT", "Blueprint parameters do not match the registered schema", 422) from error
        built = builder(params, run=run, caller_agent=ctx.caller_agent)
        raw = validate_payload("plan_draft", built["plan"])
        compiled = compile_plan(raw, run)
        draft = validate_payload("plan_draft", authoring_plan(compiled["plan"]))
        artifact_ids = validate_artifact_references(draft, ctx, plan_refs=True)
        suffix = sha256(_key(ctx).encode()).hexdigest()[:24]
        key = f"blueprint.{data.name}.{suffix}"
        # This is the same append-only workspace record as write_workspace, but
        # shares this transaction so provenance cannot be lost after a commit.
        existing = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key=key).order_by(AgentWorkspaceItem.version.desc()).first()
        version = existing.version + 1 if existing else 1
        workspace_ref = {"key": key, "version": version}
        item = AgentWorkspaceItem(run_id=run.run_id, key=key, version=version, kind="plan_draft", payload=draft,
            artifact_ids=artifact_ids, author_agent=ctx.caller_agent, delegation_id=ctx.delegation_id,
            request_key=_key(ctx), inputs_hash=inputs_hash({"key": key, "kind": "plan_draft", "payload": draft}))
        db.session.add(item)
        snapshot = deepcopy(run.snapshot or {})
        receipts = snapshot.setdefault("v3_blueprint_receipts", [])
        if not isinstance(receipts, list):
            receipts = list(receipts.values())
            snapshot["v3_blueprint_receipts"] = receipts
        receipts.append({"name": data.name, "version": VERSION, "raw_hash": plan_digest(raw),
            "normalized_hash": plan_digest(draft), "key": _key(ctx), "workspace_ref": workspace_ref})
        run.snapshot = snapshot
        compiled = compile_plan(draft, run)
        output = {"plan": compiled["plan"], "notes": built.get("notes", []), "workspace_ref": workspace_ref,
                  "issues": compiled["issues"], "estimates": compiled["estimates"], "experimental": compiled["experimental"]}
        _save_receipt(run, "instantiate_blueprint", normalized, ctx, output)
        db.session.commit()
        return output
    except Exception:
        db.session.rollback()
        raise


def submit_plan(data, ctx):
    normalized = data.model_dump(mode="json")
    try:
        run, delegation = _active_locked(ctx)
        if ctx.caller_agent != "producer":
            raise AppError("TOOL_FORBIDDEN", "Only Producer can submit a plan for user review", 403)
        previous = _receipt(run, "submit_plan", normalized, ctx)
        if previous is not None:
            db.session.commit()
            return previous
        _assert_active(run, delegation)
        if (run.snapshot or {}).get("v3_execution", {}).get("approved_version"):
            raise AppError("PATCH_REQUIRED", "Approved plans can only change through a reviewed Patch", 409)
        item = resolve_workspace_ref(normalized["plan_ref"], ctx, expected_kind="plan_draft")
        latest = AgentPlanVersion.query.filter_by(run_id=run.run_id).order_by(AgentPlanVersion.version.desc()).first()
        version = (latest.version if latest else 0) + 1
        compiled = compile_plan(item["payload"], run, plan_version=version)
        checked = dry_run(compiled)
        output = {"submitted": False, "plan_ref": normalized["plan_ref"], "plan_version": None,
                  "issues": checked["issues"], "estimates": compiled["estimates"],
                  "experimental": compiled["experimental"], "dry_run": checked}
        if not checked["passed"]:
            snapshot = deepcopy(run.snapshot or {})
            snapshot["plan_issues"] = deepcopy(checked["issues"])
            run.snapshot = snapshot
        else:
            check = {**public_check(compiled), "dry_run": checked,
                     "output_metadata": compiled["output_metadata"]}
            check.pop("plan", None)
            row = AgentPlanVersion(run_id=run.run_id, version=version, author="director",
                parent_version=latest.version if latest else None, plan=compiled["plan"], story_package={}, check=check)
            db.session.add(row)
            snapshot = deepcopy(run.snapshot or {})
            snapshot.update(plan_version=version, plan_issues=[], v3_plan_submission={"plan_ref": normalized["plan_ref"], "plan_version": version})
            run.snapshot, run.status, run.error = snapshot, "awaiting_plan_review", None
            delegation.status = "completed"
            delegation.output = {"kind": "completed", "outcome": "plan_submitted", "plan_ref": normalized["plan_ref"],
                                 "message": "计划已提交，请审核后开始生成。"}
            output.update(submitted=True, plan_version=version)
        _save_receipt(run, "submit_plan", normalized, ctx, output)
        db.session.commit()
        return output
    except Exception:
        db.session.rollback()
        raise


def register_plan_tools(registry):
    for spec in (
        ToolSpec(name="check_plan", description="Check a typed plan, model constraints, data dependencies and demonstration costs without saving or executing it.",
            input_model=CheckInput, output_model=ObjectOutput, handler=check_plan, permission="read",
            allowed_roles=frozenset(AGENT_ROLES), agent_visible=True),
        ToolSpec(name="instantiate_blueprint", description="Instantiate a registered deterministic Blueprint into an immutable workspace draft; this does not approve or execute it.",
            input_model=InstantiateInput, output_model=ObjectOutput, handler=instantiate_blueprint, permission="write",
            allowed_roles=frozenset(AGENT_ROLES), agent_visible=True, max_retries=0),
        ToolSpec(name="submit_plan", description="Producer submits an exact workspace plan version to user review after compilation and zero-cost dry-run. Never grants execution approval.",
            input_model=SubmitInput, output_model=ObjectOutput, handler=submit_plan, permission="write",
            allowed_roles=frozenset({"producer"}), agent_visible=True, max_retries=0),
    ):
        registry.register(spec)
