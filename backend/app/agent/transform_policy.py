"""Server-owned approval, immutable Job bindings and one-shot transform dispatch."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ApiTask, ToolInvocation

_dispatch_permit = ContextVar("transform_dispatch", default=None)
PAID_TOOLS = {"generate_image", "generate_video", "animate_shot", "produce_shot", "remix_shot"}


def invocation_key(run_id, plan_hash):
    return f"{run_id}:transform:{plan_hash}"


def approve(run, plan):
    from app.agent.transform_plan import execution_hash, validate_transform_plan
    previous = (run.snapshot or {}).get("transform") or {}
    if previous:
        previous = _receipt(run)
        if (execution_hash(plan) == previous["plan_hash"] and plan.get("plan_hash") == previous["plan_hash"]
                and plan.get("quote_id") == previous["quote_id"]):
            return deepcopy(previous)
        raise AppError("UNSAFE_RETRY", "An approved transform cannot be replaced by another paid attempt", 409)
    checked = validate_transform_plan(plan, (run.snapshot or {})["request_spec"], run=run, require_quote=True)
    receipt = {"approved": True, "plan_hash": checked["plan_hash"], "quote_id": checked["quote_id"],
               "plan": deepcopy(checked), "request_spec": deepcopy(run.snapshot["request_spec"]), "invocation_key": invocation_key(run.run_id, checked["plan_hash"])}
    run.snapshot = {**(run.snapshot or {}), "transform": receipt}
    db.session.commit()
    return receipt


def _receipt(run):
    receipt = (run.snapshot or {}).get("transform") or {}
    plan = receipt.get("plan") or {}
    if (not receipt.get("approved") or not receipt.get("plan_hash") or not receipt.get("quote_id")
            or plan.get("recipe") != "video_transform" or receipt["plan_hash"] != plan.get("plan_hash")
            or receipt["quote_id"] != plan.get("quote_id")
            or receipt.get("invocation_key") != invocation_key(run.run_id, receipt["plan_hash"])):
        raise AppError("APPROVAL_REQUIRED", "Transform requires a server-owned approved quote", 403)
    from app.agent.transform_plan import execution_hash
    if execution_hash(plan) != plan["plan_hash"]:
        raise AppError("TRANSFORM_APPROVAL_MISMATCH", "Frozen transform execution hash is invalid", 409)
    return receipt


def require_tool_authorization(name, ctx):
    if name not in PAID_TOOLS:
        return
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
    if run and ((run.snapshot or {}).get("request_spec") or {}).get("recipe_hint") == "video_transform":
        raise AppError("UNSAFE_RETRY", "Transform generation must use its approved transform_video invocation", 409)


def approved_plan(ctx):
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
    if not run:
        raise AppError("APPROVAL_REQUIRED", "Transform requires an Agent Run", 403)
    receipt = _receipt(run)
    if not ctx.transform_hash or ctx.transform_hash != receipt["plan_hash"]:
        raise AppError("APPROVAL_REQUIRED", "Transform context must be issued by the server", 403)
    if ctx.idempotency_key != receipt["invocation_key"]:
        raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Transform invocation key differs from approval", 409)
    return run, deepcopy(receipt["plan"])


def validate_submission(data, ctx):
    run, plan = approved_plan(ctx)
    if data.plan_hash != plan["plan_hash"]:
        raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Transform input differs from approval", 409)
    previous = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).first()
    if previous:
        if (previous.tool_name != "transform_video" or previous.budget_scope != run.run_id
                or previous.input_payload != {"plan_hash": plan["plan_hash"]}):
            raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Transform invocation belongs to other inputs", 409)
        if previous.job:
            validate_job(previous.job)
            # Already accepted provider tasks may be polled/downloaded even if
            # model availability or current rates changed after submission.
            if ApiTask.query.filter_by(job_id=previous.job_id).filter(ApiTask.provider_task_id.is_not(None)).first():
                return
    from app.agent.transform_plan import validate_transform_plan
    validate_transform_plan(plan, (run.snapshot or {})["request_spec"], run=run,
                            require_quote=True, check_budget=False)


def job_marker(ctx):
    run, plan = approved_plan(ctx)
    return {"run_id": run.run_id, "plan_hash": plan["plan_hash"], "quote_id": plan["quote_id"]}


def validate_job(job):
    config = job.config or {}
    marker, skill = config.get("agent_transform") or {}, config.get("skill") or {}
    run = AgentRun.query.filter_by(run_id=marker.get("run_id")).first()
    if not run:
        raise AppError("APPROVAL_REQUIRED", "Transform Job has no owning Run", 403)
    receipt = _receipt(run)
    invocation = ToolInvocation.query.filter_by(invocation_id=skill.get("invocation_id"),
        budget_scope=run.run_id, tool_name="transform_video").first()
    plan = receipt["plan"]
    if (not invocation or invocation.job_id != job.id or skill.get("budget_scope") != run.run_id
            or skill.get("tool_name") != "transform_video" or invocation.idempotency_key != receipt["invocation_key"]
            or invocation.input_payload != {"plan_hash": plan["plan_hash"]}
            or marker != {"run_id": run.run_id, "plan_hash": plan["plan_hash"], "quote_id": plan["quote_id"]}
            or (config.get("node_models") or {}) != {"submit_r2v_flash": plan["model_id"]}
            or (config.get("node_model_params") or {}) != {"submit_r2v_flash": plan["params"]}):
        raise AppError("TRANSFORM_APPROVAL_MISMATCH", "Transform Job differs from its approved receipt", 409)
    enabled = set((job.node_overrides or {}).get("enabled_nodes") or [])
    if enabled != {"submit_r2v_flash", "poll_r2v_flash", "export_manifest"}:
        raise AppError("TRANSFORM_APPROVAL_MISMATCH", "Transform workflow differs from approval", 409)
    from app.services.prompt_service import PromptService
    from app.services.job_run_state_service import JobRunStateService
    prompt = PromptService.get_active_for_template(job.template, "r2v_flash", job_id=job.id)
    if not prompt or prompt.content != plan["prompt"] or JobRunStateService.prompt_policy(job) == "template_first":
        raise AppError("TRANSFORM_APPROVAL_MISMATCH", "Transform prompt differs from approval", 409)
    return run, deepcopy(plan)


def submission_inputs(job):
    from app.agent.transform_media import resolved_media
    run, plan = validate_job(job)
    return {"prompt": plan["prompt"], "media": resolved_media(plan["media"], run=run, expected_manifest=plan["manifest"])}


def validate_before_submit(job, model, inputs, params, *, operation="submit_r2v_flash", adapter_name=None):
    if not job or not (job.config or {}).get("agent_transform"):
        return
    run, plan = validate_job(job)
    from app.agent.transform_plan import validate_transform_plan
    validate_transform_plan(plan, (run.snapshot or {})["request_spec"], run=run,
                            require_quote=True, check_budget=False)
    if (operation != "submit_r2v_flash" or model.model_id != plan["model_id"]
            or adapter_name not in (None, model.adapter_name) or params != plan["params"]
            or inputs != submission_inputs(job)):
        raise AppError("TRANSFORM_APPROVAL_MISMATCH", "Queued transform payload differs from approval", 409)


@contextmanager
def authorized_job_dispatch(job, run_type, node_key=None, *, force=False, restart=False):
    if run_type != "run_full" or node_key is not None or force or restart:
        raise AppError("UNSAFE_RETRY", "Transform permits cannot force a paid retry", 409)
    token = _dispatch_permit.set((job.job_id, run_type, node_key, force, restart))
    try:
        yield
    finally:
        _dispatch_permit.reset(token)


def validate_dispatch(job, run_type, node_key, force, restart):
    if (job.config or {}).get("agent_transform"):
        if _dispatch_permit.get() != (job.job_id, run_type, node_key, force, restart):
            raise AppError("UNSAFE_RETRY", "Transform Jobs cannot be manually rerun or restarted", 409)
        validate_job(job)
