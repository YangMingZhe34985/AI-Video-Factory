"""One paid transform, conservative recovery and direct original-file delivery."""
from copy import deepcopy

from langgraph.types import interrupt

from app.agent.recovery import invoke_once, recover_job
from app.agent.simple_execution import _usable_artifacts
from app.agent.transform_policy import invocation_key
from app.api import AppError
from app.models import Job, ToolInvocation
from app.skills.spec import ToolContext


def context(state):
    return ToolContext(role="production", approved=state.get("approved", False), budget_scope=state["run_id"],
        budget_limit=state["budget_limit"], transform_hash=state["plan"]["plan_hash"],
        idempotency_key=invocation_key(state["run_id"], state["plan"]["plan_hash"]))


def produce(state, registry):
    ctx = context(state)
    try:
        result = invoke_once(registry, "transform_video", {"plan_hash": state["plan"]["plan_hash"]}, ctx)
        shot = {"job_id": result["output"]["job_id"], "invocation_id": result["invocation_id"],
                "status": "pending", "terminal": False, "artifacts": []}
    except AppError as error:
        previous = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).first()
        if previous and previous.job and error.code not in {"TRANSFORM_APPROVAL_MISMATCH", "IDEMPOTENCY_KEY_CONFLICT"}:
            shot = {"job_id": previous.job.job_id, "invocation_id": previous.invocation_id,
                    "status": "pending", "terminal": False, "artifacts": []}
        else:
            shot = {"status": "failed", "terminal": True, "artifacts": [],
                    "error": {"code": error.code, "summary": error.message}}
    return {"shots": {"transform": shot}, "status": "producing"}


def collect(state, registry):
    shot = deepcopy(state["shots"]["transform"])
    if not shot.get("terminal"):
        try:
            job = Job.query.filter_by(job_id=shot["job_id"]).one()
            recover_job(job, state["run_id"])
            report = registry.invoke("get_task_status", {"job_id": job.job_id}, context(state))["output"]
            report["artifacts"] = _usable_artifacts([ref for ref in report["artifacts"]
                                                     if ref["artifact_type"] == "r2v_flash_video"])
            if report["overdue"] and not report["terminal"]:
                report.update(terminal=True, status="failed", error={"code": "TASK_OVERDUE",
                              "summary": "Inspect the existing provider task; automatic resubmission is disabled"})
            if report["terminal"] and len(report["artifacts"]) != 1:
                report.update(status="failed", error={"code": "INCOMPLETE_OUTPUT", "summary": "Expected video is missing"})
            shot = {**shot, **report}
        except AppError as error:
            shot.update(status="failed", terminal=True, error={"code": error.code, "summary": error.message})
    status = ("awaiting_delivery" if shot["status"] == "success" else "failed") if shot["terminal"] else "producing"
    return {"shots": {"transform": shot}, "status": status, "transform_error": shot.get("error")}


def after_collect(state):
    return {"failed": "end", "awaiting_delivery": "delivery"}.get(state["status"], "wait")


def deliver(state):
    refs = state["shots"]["transform"]["artifacts"]
    return {"status": "success", "transform_error": None,
            "results": [{"kind": "video", **{key: ref[key] for key in ("artifact_id", "preview_url", "download_url")}}
                        for ref in refs]}


def wait(state):
    interrupt({"kind": "tasks", "run_id": state["run_id"]})
    return {}


def nodes(registry):
    return {"transform_production": lambda state: produce(state, registry),
            "transform_collect": lambda state: collect(state, registry),
            "transform_wait": wait, "transform_delivery": deliver}
