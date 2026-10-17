"""Job-backed execution of approved simple recipes; no direct provider calls."""

from copy import deepcopy

from app.agent.recovery import invoke_once, recover_job
from app.api import AppError
from app.models import Artifact, Job, ToolInvocation
from app.services.storage_service import StorageService
from app.skills.spec import ToolContext


def context(state, suffix):
    return ToolContext(
        role="production", approved=state.get("approved", False), budget_scope=state["run_id"],
        budget_limit=state["budget_limit"], idempotency_key=f"{state['run_id']}:simple:{suffix}",
    )


def step_names(plan):
    return [name for name in ("image", "video") if plan.get(name)]


def production(state, registry):
    shots = deepcopy(state.get("shots", {}))
    name = next(name for name in step_names(state["plan"]) if name not in shots)
    step = state["plan"][name]
    if name == "image":
        tool = "generate_image"
        data = {"mode": step["mode"], "model_id": step["model_id"], "prompt": step["prompt"],
                "params": step["params"], "n": step["n"],
                "reference_artifact_ids": step["reference_attachment_ids"]}
    else:
        first_frame = step.get("first_frame_attachment_id")
        if step["first_frame"] == "generated_image":
            images = shots["image"].get("artifacts", [])
            if shots["image"]["status"] != "success" or not images:
                shots["video"] = {"status": "failed", "terminal": True, "artifacts": [],
                                  "error": {"code": "DEPENDENCY_FAILED", "summary": "First frame generation failed"}}
                return {"shots": shots}
            first_frame = images[0]["artifact_id"]
        tool = "animate_shot"
        data = {"model_id": step["model_id"], "prompt": step["prompt"],
                "params": step["params"], "first_frame_artifact_id": first_frame}
    ctx = context(state, name)
    try:
        result = invoke_once(registry, tool, data, ctx)
        shots[name] = {"job_id": result["output"]["job_id"], "invocation_id": result["invocation_id"],
                       "status": "pending", "terminal": False, "artifacts": []}
    except AppError as error:
        previous = ToolInvocation.query.filter_by(idempotency_key=ctx.idempotency_key).first()
        if previous and previous.job:
            shots[name] = {"job_id": previous.job.job_id, "invocation_id": previous.invocation_id,
                           "status": "pending", "terminal": False, "artifacts": []}
        else:
            shots[name] = {"status": "failed", "terminal": True, "artifacts": [],
                           "error": {"code": error.code, "summary": error.message}}
    return {"shots": shots, "status": "producing"}


def _usable_artifacts(refs):
    usable = []
    for ref in refs:
        artifact = Artifact.query.filter_by(artifact_id=ref["artifact_id"]).first()
        path = StorageService.resolve(artifact.file_path) if artifact else None
        if path and path.is_file() and path.stat().st_size:
            usable.append(ref)
    return usable


def results_for(shots, recipe):
    names = ["image"] if recipe in {"image_create", "image_edit"} else ["video"]
    return [{"kind": name, **{key: ref[key] for key in ("artifact_id", "preview_url", "download_url")}}
            for name in names for ref in shots.get(name, {}).get("artifacts", [])]


def collect(state, registry):
    shots = deepcopy(state["shots"])
    for name, shot in shots.items():
        if shot.get("terminal"):
            continue
        try:
            job = Job.query.filter_by(job_id=shot["job_id"]).one()
            recover_job(job, state["run_id"])
            report = registry.invoke("get_task_status", {"job_id": job.job_id}, context(state, "poll"))["output"]
            expected = "first_frame_image" if name == "image" else "i2v_video"
            report["artifacts"] = _usable_artifacts([ref for ref in report["artifacts"]
                                                   if ref["artifact_type"] == expected])
            if report["overdue"] and not report["terminal"]:
                report.update(terminal=True, status="failed",
                              error={"code": "TASK_OVERDUE", "summary": "Inspect the existing Job before retrying"})
            if report["terminal"]:
                count = state["plan"][name]["n"] if name == "image" else 1
                if len(report["artifacts"]) != count:
                    report["status"] = "partial_success" if report["artifacts"] else "failed"
                    report["error"] = {"code": "INCOMPLETE_OUTPUT", "summary": "Expected outputs are missing"}
            shots[name] = {**shot, **report}
        except AppError as error:
            shots[name] = {**shot, "status": "failed", "terminal": True,
                           "error": {"code": error.code, "summary": error.message}}
    names = step_names(state["plan"])
    complete = len(shots) == len(names) and all(shot.get("terminal") for shot in shots.values())
    results = results_for(shots, state["plan"]["recipe"])
    status = ("awaiting_delivery" if results else "failed") if complete else "producing"
    return {"shots": shots, "results": results, "status": status}


def after_collect(state):
    if state["status"] == "failed":
        return "end"
    if state["status"] == "awaiting_delivery":
        return "delivery"
    if any(not shot.get("terminal") for shot in state["shots"].values()):
        return "wait"
    return "produce"


def deliver(state):
    # Individual media are already downloadable. Packaging remains an optional Skill.
    return {"results": results_for(state["shots"], state["plan"]["recipe"]),
            "status": "success" if all(shot["status"] == "success" for shot in state["shots"].values())
            else "partial_success"}
