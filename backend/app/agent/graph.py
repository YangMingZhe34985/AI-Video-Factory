"""LangGraph creation pipelines. Interrupts yield control, never poll in HTTP."""

from copy import deepcopy
from typing import TypedDict

from flask import current_app
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agent.planning import SPECS
from app.agent.model_policy import request_policy, select_video_model
from app.agent.protocol import validate_plan, validate_shot
from app.agent.plan_spec import PlanSpec, RemixShotSpec
from app.agent.sources import describe_source, source_for_run
from app.agent.recovery import invoke_once, recover_job
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, Artifact, Job, PromptVersion, ToolInvocation
from app.services.storage_service import StorageService
from app.skills import build_default_registry
from app.skills.spec import ToolContext


class AgentState(TypedDict, total=False):
    run_id: str
    goal: str
    shot_count: int
    budget_limit: float
    brief: dict
    plan: dict
    approved: bool
    shots: dict
    packages: list
    package_errors: list
    status: str
    mock: bool
    video_model_policy: dict
    mode: str
    source: dict
    analysis_job_id: str
    analysis: dict
    shot_revisions: dict
    shot_history: dict
    last_command_id: str
    plan_issues: list[dict]


def build_graph(checkpointer):
    app = current_app._get_current_object()
    registry = build_default_registry()
    for spec in SPECS:
        registry.register(spec)

    def call(state, name, data, role, suffix):
        return invoke_once(registry, name, data, ToolContext(
            role=role, approved=state.get("approved", False),
            budget_scope=state["run_id"], budget_limit=state["budget_limit"],
            idempotency_key=f"{state['run_id']}:{suffix}",
        ))

    def analyze(state):
        row = AgentRun.query.filter_by(run_id=state["run_id"]).one()
        source = source_for_run(row)
        result = call(state, "analyze_video", {"source_artifact_id": source.artifact_id}, "creative", "analysis")
        return {"source": describe_source(source), "analysis_job_id": result["output"]["job_id"], "status": "analyzing"}

    def collect_analysis(state):
        job = Job.query.filter_by(job_id=state["analysis_job_id"]).one()
        recover_job(job, state["run_id"])
        report = registry.invoke("get_task_status", {"job_id": job.job_id}, ToolContext(role="creative"))["output"]
        if not report["terminal"]:
            if report["overdue"]:
                raise AppError("TASK_OVERDUE", "Source analysis exceeded its wait limit; inspect the linked Job", 409)
            return {"status": "analyzing"}
        prompt = PromptVersion.query.filter_by(job_id=job.id, prompt_type="t2v", prompt_key="default", is_active=True).first()
        if report["status"] != "success" or not prompt or not prompt.content.strip():
            error = report.get("error") or {}
            raise AppError(error.get("code") or "ANALYSIS_FAILED", error.get("summary") or "Source analysis produced no prompt", 422)
        return {"analysis": {"job_id": job.job_id, "prompt_id": prompt.prompt_id, "content": prompt.content}, "status": "planning"}

    def wait_analysis(_state):
        interrupt({"kind": "analysis"})
        return {}

    def checked_plan(state, plan):
        return validate_plan(plan, state["shot_count"], state["budget_limit"], state.get("video_model_policy"),
                             mode=state.get("mode", "from_scratch"), source_duration=state.get("source", {}).get("duration"))

    def director(state):
        row = AgentRun.query.filter_by(run_id=state["run_id"]).one()
        policy = request_policy(row.request)
        # The MVP produces first-frame -> I2V. Check capability before spending
        # on planning, rather than substituting a different model family.
        if state.get("mode", "from_scratch") == "from_scratch":
            select_video_model(policy, "i2v")
        result = call(state, "agent_director", {"goal": state["goal"], "shot_count": state["shot_count"],
                                              "source_analysis": state.get("analysis", {}).get("content")}, "director", "director")
        return {"brief": result["output"], "status": "planning", "video_model_policy": policy}

    def creative(state):
        result = call(state, "agent_creative", {"brief": state["brief"], "original_goal": state["goal"], "shot_count": state["shot_count"],
                                              "video_model_policy": state.get("video_model_policy"),
                                              "mode": state.get("mode", "from_scratch"),
                                              "source_analysis": state.get("analysis", {}).get("content"),
                                              "source_duration": state.get("source", {}).get("duration"),
                                              "budget_limit": state["budget_limit"]}, "creative", "creative")
        return {"plan": result["output"]}

    def validate(state):
        try:
            plan = checked_plan(state, state["plan"])
        except AppError as error:
            if error.status_code not in {400, 402, 404, 422}:
                raise
            # A structured draft may contain invalid model parameters, ranges
            # or budget choices. Keep it editable; approval still validates it.
            return {"status": "awaiting_approval", "plan_issues": [
                {"code": error.code, "message": error.message, **error.payload}]}
        return {"plan": plan, "status": "awaiting_approval", "plan_issues": []}

    def approval(state):
        decision = interrupt({"kind": "approval", "plan": state["plan"], "estimated_credits": PlanSpec.model_validate(state["plan"]).estimated_cost})
        if decision["action"] == "reject":
            return {"approved": False, "status": "cancelled", "last_command_id": decision.get("command_id")}
        if decision["action"] != "approve":
            raise AppError("INVALID_ACTION", "Explicit plan approval required", 409)
        plan = checked_plan(state, decision.get("plan") or state["plan"])
        return {"approved": True, "plan": plan, "plan_issues": [], "shots": {}, "status": "producing", "last_command_id": decision.get("command_id")}

    def production(state):
        # Each pass submits one shot, then checkpoints. All jobs are queued
        # before waiting, so a slow first frame never blocks other shots.
        shots = deepcopy(state.get("shots", {}))
        shot = next(item for item in state["plan"]["shots"] if item["shot_id"] not in shots)
        shot_id = shot["shot_id"]
        revision = state.get("shot_revisions", {}).get(shot_id, 0)
        suffix = f"shot:{shot_id}" + (f":revision:{revision}" if revision else "")
        tool, payload = "produce_shot", shot
        if state.get("mode") == "remix":
            history = state.get("shot_history", {}).get(shot_id, [])
            tool, payload = "remix_shot", {**shot, "source_artifact_id": state["source"]["artifact_id"],
                                           "analysis_prompt_id": state["analysis"]["prompt_id"],
                                           "parent_job_id": history[-1]["result"].get("job_id") if history else None}
        try:
            launched = call(state, tool, payload, "production", suffix)
            shots[shot_id] = {"job_id": launched["output"]["job_id"], "invocation_id": launched["invocation_id"], "terminal": False, "status": "pending", "artifacts": []}
        except AppError as error:
            invocation = ToolInvocation.query.filter_by(idempotency_key=f"{state['run_id']}:{suffix}").first()
            if invocation and invocation.job:
                shots[shot_id] = {"job_id": invocation.job.job_id, "invocation_id": invocation.invocation_id,
                                  "terminal": False, "status": "pending", "artifacts": [],
                                  "submission_error": {"code": error.code, "summary": error.message}}
            else:
                shots[shot_id] = {"status": "failed", "terminal": True, "artifacts": [], "error": {"code": error.code, "summary": error.message}}
        return {"shots": shots}

    def collect(state):
        shots = deepcopy(state["shots"])
        for shot_id, shot in shots.items():
            if shot.get("terminal") or not shot.get("job_id"):
                continue
            try:
                job = Job.query.filter_by(job_id=shot["job_id"]).first()
                if not job:
                    raise AppError("JOB_NOT_FOUND", "Shot job was deleted", 404)
                recover_job(job, state["run_id"])
                report = registry.invoke("get_task_status", {"job_id": shot["job_id"]}, ToolContext(role="production"))["output"]
                report["artifacts"] = [item for item in report["artifacts"] if item["artifact_type"] != "source_video"]
                report["packable"] = report["terminal"]
                if report["overdue"] and not report["terminal"]:
                    # Bound waiting per shot without blocking successful siblings.
                    # The linked Job/provider can still finish; do not resubmit.
                    report.update(terminal=True, status="failed", error={
                        "code": "TASK_OVERDUE", "summary": "Task exceeded its wait limit; inspect the linked Job"})
                shots[shot_id] = {**shot, **report}
                if report["terminal"]:
                    valid, errors = [], []
                    for ref in report["artifacts"]:
                        artifact = Artifact.query.filter_by(artifact_id=ref["artifact_id"]).first()
                        path = StorageService.resolve(artifact.file_path) if artifact else None
                        if path and path.is_file() and path.stat().st_size:
                            valid.append(ref)
                        else:
                            errors.append(f"Missing or empty artifact: {ref['artifact_id']}")
                    shots[shot_id]["artifacts"] = valid
                    has_video = any(item["artifact_type"] in {"i2v_video", "retained_video"} for item in valid)
                    if not has_video:
                        shots[shot_id]["status"] = "failed"
                        errors.append("No usable video result")
                    elif errors and shots[shot_id]["status"] == "success":
                        shots[shot_id]["status"] = "partial_success"
                    shots[shot_id]["validation"] = {"valid_video": has_video, "errors": errors, "checks": ["file_exists", "non_empty", "expected_video_artifact"]}
            except AppError as error:
                shots[shot_id] = {**shot, "status": "failed", "terminal": True, "error": {"code": error.code, "summary": error.message}}
        terminal = all(item["terminal"] for item in shots.values())
        has_assets = any(item.get("artifacts") and item.get("packable") for item in shots.values())
        return {"shots": shots, "status": ("awaiting_delivery" if has_assets else "failed") if terminal else "producing"}

    def wait_tasks(_state):
        interrupt({"kind": "tasks"})
        return {}

    def delivery_approval(state):
        decision = interrupt({"kind": "delivery"})
        if decision.get("action") == "revise" and state.get("mode") == "remix":
            shot = validate_shot(RemixShotSpec.model_validate(decision["shot"]), state["video_model_policy"],
                                 source_duration=state["source"]["duration"]).model_dump(mode="json")
            shot_id = shot["shot_id"]
            plan, shots = deepcopy(state["plan"]), deepcopy(state["shots"])
            history, revisions = deepcopy(state.get("shot_history", {})), dict(state.get("shot_revisions", {}))
            index = next(i for i, item in enumerate(plan["shots"]) if item["shot_id"] == shot_id)
            history.setdefault(shot_id, []).append({"plan": plan["shots"][index], "result": shots.pop(shot_id),
                                                   "command_id": decision["command_id"], "request_shot": decision["request_shot"]})
            revisions[shot_id] = revisions.get(shot_id, 0) + 1
            plan["shots"][index] = shot
            return {"plan": plan, "shots": shots, "shot_history": history, "shot_revisions": revisions,
                    "status": "producing", "last_command_id": decision["command_id"]}
        if decision.get("action") != "deliver":
            raise AppError("INVALID_ACTION", "Delivery must be requested explicitly", 409)
        return {"status": "delivering", "last_command_id": decision.get("command_id")}

    def deliver(state):
        ordered_shots = [state["shots"][shot["shot_id"]] for shot in state["plan"]["shots"]]
        job_ids = [item["job_id"] for item in ordered_shots if item.get("job_id") and item.get("artifacts") and item.get("packable")]
        result = call(state, "package_project", {"job_ids": job_ids}, "production", "delivery")["output"]
        all_good = all(item["status"] == "success" for item in state["shots"].values())
        return {"packages": result["packages"], "package_errors": result["errors"],
                "status": "success" if all_good and not result["errors"] else "partial_success"}

    def in_context(fn):
        # LangGraph may execute nodes in its executor; Flask contexts are thread-local.
        def wrapped(state):
            with app.app_context():
                try:
                    return fn(state)
                finally:
                    db.session.remove()
        return wrapped

    builder = StateGraph(AgentState)
    for name, fn in {"analyze": analyze, "collect_analysis": collect_analysis, "wait_analysis": wait_analysis,
                     "director": director, "creative": creative, "validate": validate,
                     "approval": approval, "production": production, "collect": collect,
                     "wait_tasks": wait_tasks, "delivery_approval": delivery_approval, "deliver": deliver}.items():
        builder.add_node(name, in_context(fn))
    builder.add_conditional_edges(START, lambda s: "analyze" if s.get("mode") == "remix" else "director")
    builder.add_edge("analyze", "collect_analysis")
    builder.add_conditional_edges("collect_analysis", lambda s: "wait_analysis" if s["status"] == "analyzing" else "director")
    builder.add_edge("wait_analysis", "collect_analysis")
    builder.add_edge("director", "creative")
    builder.add_edge("creative", "validate")
    builder.add_edge("validate", "approval")
    builder.add_conditional_edges("approval", lambda s: "production" if s["approved"] else END)
    builder.add_conditional_edges("production", lambda s: "production" if len(s["shots"]) < len(s["plan"]["shots"]) else "collect")
    builder.add_conditional_edges("collect", lambda s: {"producing": "wait_tasks", "awaiting_delivery": "delivery_approval", "failed": END}[s["status"]])
    builder.add_edge("wait_tasks", "collect")
    builder.add_conditional_edges("delivery_approval", lambda s: "production" if s["status"] == "producing" else "deliver")
    builder.add_edge("deliver", END)
    return builder.compile(checkpointer=checkpointer)
