"""The only entry point through which agents (or operators) execute tools.

invoke() enforces, in order: input schema -> caller role -> approval ->
budget -> idempotency -> handler -> output schema -> ledger. Nothing an LLM
produces reaches a service without passing every step.
"""

import hashlib
import json
import time
import uuid

from flask import current_app
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError

from app.api import AppError
from app.extensions import db
from app.models import Job, ToolInvocation
from app.skills.budget import BudgetGuard
from app.skills.spec import ToolContext, ToolSpec
from app.utils.time_utils import as_utc, utc_now

REPLAYABLE_STATUSES = {"pending", "running", "success", "partial_success"}
TERMINAL_JOB_STATUSES = {"success", "partial_success", "failed", "cancelled"}
DELIVERY_TOOLS = frozenset({"compose_video", "probe_media", "qc_video", "package_story"})


def _delivery_module(name):
    from importlib import import_module
    return import_module(f"app.skills.tools.{name}")


def idempotency_key_for(tool_name: str, data: BaseModel) -> str:
    canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(f"{tool_name}\n{canonical}".encode("utf-8")).hexdigest()
    return f"{tool_name}:{digest}"


def sync_invocation_from_job(invocation: ToolInvocation) -> None:
    """Mirror the linked job's outcome onto a job-backed invocation."""
    job = invocation.job
    if job is None or invocation.status not in {"pending", "running"}:
        return
    if job.status not in TERMINAL_JOB_STATUSES:
        return
    # A rerun started through the thread runner leaves the previous terminal
    # status in place until the worker picks it up; ignore it until then.
    started_at = as_utc(invocation.started_at)
    if started_at and job.updated_at and as_utc(job.updated_at) < started_at:
        return
    if job.status == "success":
        invocation.status = "success"
    elif job.status == "partial_success":
        invocation.status = "partial_success"
    else:
        invocation.status = "failed"
        invocation.error_code = "JOB_FAILED" if job.status == "failed" else "JOB_CANCELLED"
        invocation.error_message = job.error_summary
    invocation.finished_at = utc_now()


class ToolRegistry:
    def __init__(self):
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise AppError("TOOL_NOT_FOUND", f"Unknown tool: {name}", 404)
        return spec

    def names(self) -> list[str]:
        return sorted(self._specs)

    def describe_all(self) -> list[dict]:
        return [self._specs[name].describe() for name in self.names()]

    def invoke(self, name: str, raw_input: dict | None, ctx: ToolContext) -> dict:
        ctx._delivery_authorization = None
        try:
            return self._invoke(name, raw_input, ctx)
        finally:
            ctx._delivery_authorization = None

    def _invoke(self, name: str, raw_input: dict | None, ctx: ToolContext) -> dict:
        spec = self.get(name)
        data = self._validate_input(spec, raw_input or {})
        self._authorize(spec, ctx)
        ctx.tool_name = spec.name
        from app.agent.production_policy import require_task_authorization
        require_task_authorization(spec.name, ctx)
        from app.agent.transform_policy import require_tool_authorization
        require_tool_authorization(spec.name, ctx)
        if spec.name == "transform_video":
            from app.agent.transform_policy import validate_submission
            validate_submission(data, ctx)
        if spec.name == "capture_reference_page":
            from app.skills.tools.capture_reference_page import validate_source
            validate_source(data, ctx)
        if ctx.shot_task_id is not None:
            from app.agent.production_policy import validate_submission
            validate_submission(data, ctx)
        if spec.name == "extract_frame":
            from app.skills.tools.extract_frame import validate_source
            validate_source(data, ctx)
        if spec.name in DELIVERY_TOOLS:
            from app.agent.delivery_policy import require_delivery_authorization
            require_delivery_authorization(ctx, getattr(data, "plan_version", None))
            _delivery_module(spec.name).validate_sources(data, ctx)
        if spec.permission == "external" or spec.name == "analyze_image":
            from app.agent.search.scope import require_run
            require_run(ctx, getattr(data, "run_id", None))
        if not spec.uses_ledger:
            output = self._run_handler(spec, data, ctx)
            return self._result(spec, None, output, replayed=False)
        return self._invoke_with_ledger(spec, data, ctx)

    # -- pipeline steps -------------------------------------------------

    @staticmethod
    def _validate_input(spec: ToolSpec, raw_input: dict) -> BaseModel:
        try:
            return spec.input_model.model_validate(raw_input)
        except ValidationError as error:
            raise AppError(
                "INVALID_INPUT",
                f"Invalid input for tool {spec.name}",
                422,
                payload={"errors": error.errors(include_url=False, include_context=False)},
            ) from error

    @staticmethod
    def _authorize(spec: ToolSpec, ctx: ToolContext) -> None:
        if ctx.role not in spec.allowed_roles:
            raise AppError(
                "TOOL_FORBIDDEN",
                f"Role '{ctx.role}' may not call tool {spec.name}",
                403,
                payload={"allowed_roles": sorted(spec.allowed_roles)},
            )
        if spec.requires_approval and not ctx.approved:
            raise AppError(
                "APPROVAL_REQUIRED",
                f"Tool {spec.name} submits billed work and requires explicit approval",
                403,
            )

    def _invoke_with_ledger(self, spec: ToolSpec, data: BaseModel, ctx: ToolContext) -> dict:
        scoped = spec.permission == "external" or spec.name in {"analyze_image", "extract_frame"} | DELIVERY_TOOLS or ctx.shot_task_id is not None or spec.name == "transform_video"
        generated_key = idempotency_key_for(spec.name, data)
        if scoped:
            generated_key = f"{ctx.budget_scope}:tool:{hashlib.sha256(generated_key.encode()).hexdigest()[:32]}"
        key = ctx.idempotency_key or (
            generated_key if spec.dedupe else f"{spec.name}:{uuid.uuid4().hex}"
        )
        invocation = ToolInvocation.query.filter_by(idempotency_key=key).first()

        if invocation is not None:
            self._check_scoped_replay(spec, invocation, data, ctx)
            if invocation.tool_name != spec.name:
                raise AppError(
                    "IDEMPOTENCY_KEY_CONFLICT",
                    f"Idempotency key already used by tool {invocation.tool_name}",
                    409,
                )
            if spec.name in {"generate_image", "animate_shot"} and invocation.budget_scope != ctx.budget_scope:
                from app.models import AgentRun
                if AgentRun.query.filter(AgentRun.run_id.in_([ctx.budget_scope, invocation.budget_scope])).first():
                    raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Agent tool key belongs to a different session", 409)
            if spec.name in {"produce_shot", "remix_shot", "generate_video", "animate_shot", "rerun_node"}:
                from app.agent.model_policy import scope_policy, validate_job_policy
                policy = scope_policy(ctx.budget_scope)
                if policy:
                    if invocation.budget_scope != ctx.budget_scope:
                        raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Agent tool key belongs to a different session", 409)
                    if invocation.job:
                        validate_job_policy(invocation.job, policy)
            if invocation.job is not None:
                db.session.refresh(invocation.job)
            sync_invocation_from_job(invocation)
            recovering_download = spec.name in {"download_reference", "extract_frame"} and invocation.status in {"pending", "running"}
            if spec.name == "extract_frame" and invocation.status == "success":
                from app.models import Artifact
                from app.skills.tools.extract_frame import cached_frame_is_valid
                output_artifact = Artifact.query.filter_by(artifact_id=(invocation.output_payload or {}).get("artifact_id")).first()
                recovering_download = not cached_frame_is_valid(output_artifact)
            if spec.name in DELIVERY_TOOLS:
                recovering_download = invocation.status in {"pending", "running"}
                if invocation.status == "success":
                    recovering_download = (spec.name in {"probe_media", "qc_video"}
                        or not _delivery_module(spec.name).cached_output_is_valid(invocation))
            if spec.name == "capture_reference_page" and invocation.status == "success":
                from app.skills.tools.capture_reference_page import cached_output_is_valid
                if not cached_output_is_valid(invocation):
                    raise AppError("TRANSFORM_INPUT_CHANGED", "Stored page snapshot is missing or changed; automatic refetch stopped", 409)
            if invocation.status in REPLAYABLE_STATUSES and not recovering_download:
                if scoped and invocation.status in {"pending", "running"} and invocation.job is None:
                    raise AppError("RECOVERY_REQUIRED", "Research call outcome is unknown; automatic repeat stopped", 409)
                db.session.commit()
                return self._result(spec, invocation, invocation.output_payload, replayed=True)
            if (invocation.status == "failed" and spec.name == "animate_shot"
                    and (ctx.shot_task_id is not None or (invocation.job is not None
                         and (invocation.job.config or {}).get("agent_story_production")))):
                raise AppError("UNSAFE_RETRY", "Failed production attempts require the repair policy and a new task", 409)
            if recovering_download:
                # Free local tools have durable receipts and atomic outputs.
                # Paid external calls never re-enter this recovery branch.
                ctx.previous = invocation
            elif invocation.status == "failed":
                if invocation.input_payload != data.model_dump(mode="json"):
                    raise AppError(
                        "IDEMPOTENCY_KEY_CONFLICT",
                        "A failed invocation must be retried with its original input",
                        409,
                    )
                if invocation.attempt >= 1 + spec.max_retries:
                    raise AppError(
                        "RETRY_LIMIT_EXCEEDED",
                        f"Tool {spec.name} already failed {invocation.attempt} time(s); "
                        f"retry limit is {spec.max_retries}",
                        409,
                        payload={"invocation_id": invocation.invocation_id},
                    )
                ctx.previous = invocation
                cost = float(spec.cost_fn(data, ctx))
                # Refuse without touching the failed record: its spent cost stays counted.
                BudgetGuard.check(ctx.budget_scope, ctx.budget_limit, cost)
                invocation.attempt += 1
                invocation.estimated_cost += cost
            else:  # "rejected": nothing ran, evaluate again from scratch
                cost = float(spec.cost_fn(data, ctx))
                self._check_budget(invocation, ctx, cost)
                invocation.estimated_cost = cost
            invocation.status = "pending"
            invocation.error_code = None
            invocation.error_message = None
            invocation.finished_at = None
            db.session.commit()
        else:
            cost = float(spec.cost_fn(data, ctx))
            invocation = ToolInvocation(
                tool_name=spec.name,
                idempotency_key=key,
                caller_role=ctx.role,
                budget_scope=ctx.budget_scope,
                input_payload=data.model_dump(mode="json"),
                estimated_cost=cost,
            )
            # Check before adding the row so its own cost is not counted as spent.
            self._check_budget(invocation, ctx, cost, record_new=True)
            db.session.add(invocation)
            try:
                db.session.commit()
            except IntegrityError:
                # A concurrent call claimed the same key first: replay it.
                db.session.rollback()
                existing = ToolInvocation.query.filter_by(idempotency_key=key).one()
                self._check_scoped_replay(spec, existing, data, ctx)
                if scoped and existing.status not in {"success", "partial_success"}:
                    raise AppError("RECOVERY_REQUIRED", "Concurrent research call has not completed", 409)
                return self._result(spec, existing, existing.output_payload, replayed=True)

        ctx.invocation_id = invocation.invocation_id
        invocation.started_at = utc_now()
        db.session.commit()
        started = time.monotonic()
        try:
            output = self._run_handler(spec, data, ctx)
        except Exception as error:
            db.session.rollback()
            invocation = db.session.get(ToolInvocation, invocation.id)
            # A client error raised before any job was launched means nothing
            # ran: record it as rejected so it costs no budget and no retry.
            nothing_ran = (
                invocation.job_id is None
                and isinstance(error, AppError)
                and 400 <= int(error.status_code) < 500
                and not error.payload.get("response_validation")
            )
            invocation.status = "rejected" if nothing_ran else "failed"
            invocation.error_code = getattr(error, "code", None) or "TOOL_FAILED"
            invocation.error_message = getattr(error, "message", None) or str(error)
            invocation.duration_ms = int((time.monotonic() - started) * 1000)
            invocation.finished_at = utc_now()
            db.session.commit()
            if isinstance(error, AppError):
                raise
            raise AppError("TOOL_FAILED", f"Tool {spec.name} failed: {error}", 500) from error

        invocation.duration_ms = int((time.monotonic() - started) * 1000)
        if invocation.duration_ms > spec.timeout_sec * 1000:
            current_app.logger.warning(
                "Tool %s exceeded its %ss soft timeout (%sms)",
                spec.name,
                spec.timeout_sec,
                invocation.duration_ms,
            )
        invocation.output_payload = output
        job_public_id = output.get("job_id")
        job = Job.query.filter_by(job_id=job_public_id).first() if job_public_id else None
        if job is not None:
            # Job-backed: the outcome is the job's, resolved now or on later syncs.
            invocation.job = job
            invocation.status = "running"
            sync_invocation_from_job(invocation)
        else:
            invocation.status = "success"
            invocation.finished_at = utc_now()
        db.session.commit()
        return self._result(spec, invocation, output, replayed=False)

    @staticmethod
    def _check_scoped_replay(spec, invocation, data, ctx):
        if spec.permission == "external" or spec.name in {"analyze_image", "extract_frame"} | DELIVERY_TOOLS or ctx.shot_task_id is not None or spec.name == "transform_video":
            if (invocation.tool_name != spec.name or invocation.budget_scope != ctx.budget_scope
                    or invocation.input_payload != data.model_dump(mode="json")):
                raise AppError("IDEMPOTENCY_KEY_CONFLICT", "Tool key belongs to different input or Run", 409)

    @staticmethod
    def _check_budget(
        invocation: ToolInvocation, ctx: ToolContext, cost: float, record_new: bool = False
    ) -> None:
        try:
            BudgetGuard.check(ctx.budget_scope, ctx.budget_limit, cost)
        except AppError as error:
            invocation.status = "rejected"
            invocation.error_code = error.code
            invocation.error_message = error.message
            if record_new:
                db.session.add(invocation)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
            raise

    @staticmethod
    def _run_handler(spec: ToolSpec, data: BaseModel, ctx: ToolContext) -> dict:
        result = spec.handler(data, ctx)
        payload = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
        try:
            return spec.output_model.model_validate(payload).model_dump(mode="json")
        except ValidationError as error:
            raise AppError(
                "TOOL_OUTPUT_INVALID",
                f"Tool {spec.name} returned output that does not match its schema",
                500,
                payload={"errors": error.errors(include_url=False, include_context=False)},
            ) from error

    @staticmethod
    def _result(spec: ToolSpec, invocation: ToolInvocation | None, output: dict, replayed: bool) -> dict:
        return {
            "tool": spec.name,
            "invocation_id": invocation.invocation_id if invocation else None,
            "status": invocation.status if invocation else "success",
            "attempt": invocation.attempt if invocation else 1,
            "estimated_cost": invocation.estimated_cost if invocation else 0.0,
            "replayed": replayed,
            "output": output,
        }
