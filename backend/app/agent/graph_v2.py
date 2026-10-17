"""Version-two graph: understanding, clarification and the shortest approved recipe."""

from flask import current_app
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from app.agent.clarify import ClarifyState, clarify_gate, queue_questions
from app.agent.director_lite import director_lite
from app.agent.graph import AgentState, in_app_context, pipeline_nodes
from app.agent.intake import IntakeState, analyze_attachments, intake
from app.agent.model_selection import video_policy_for_request
from app.agent.planning import SPECS
from app.agent.recipes import complete_transition_draft, prepare_transition, validate_transition_plan
from app.agent.simple_plan import approval_request_spec, validate_simple_plan
from app.agent import simple_execution
from app.api import AppError
from app.extensions import db
from app.models import AgentRun
from app.skills import build_default_registry


class AgentStateV2(AgentState, IntakeState, ClarifyState, total=False):
    results: list[dict]


def _publish_understanding(state):
    """Publish validated intent for Job/budget guards before any generation."""
    row = AgentRun.query.filter_by(run_id=state["run_id"]).one()
    spec = state["request_spec"]
    policy = video_policy_for_request(spec) if spec["deliverable"] == "video" else None
    row.snapshot = {**(row.snapshot or {}), "request_spec": spec, "video_model_policy": policy}
    db.session.commit()
    return {"video_model_policy": policy}


UNRESOLVED_INTAKE_NOTE = "提问次数已用完，需求中仍有不确定之处，已按当前理解继续；请在审核计划时确认。"


def _queue(state, result, asked_by, resume_status):
    questions = result.get("open_questions", [])
    if questions and any(record["card"]["asked_by"] == asked_by and record.get("asked") is False
                         for record in state.get("clarifications", [])):
        if asked_by == "intake":
            # The round limit is spent and the understanding itself is valid:
            # continue on it rather than failing the run; plan review follows.
            assumptions = list(dict.fromkeys([*state.get("assumptions", []), UNRESOLVED_INTAKE_NOTE]))
            return {**result, "open_questions": [], "assumptions": assumptions}
        raise AppError("INVALID_CLARIFICATION", "The Agent did not resolve its final clarification answers", 422)
    return {**result, **queue_questions({**state, **result}, asked_by, questions, resume_status)}


def _plan_issue(error):
    if isinstance(error, ValidationError):
        return {"code": "INVALID_PLAN", "message": "Plan schema validation failed",
                "errors": error.errors(include_url=False, include_context=False, include_input=False)}
    return {"code": error.code, "message": error.message, **error.payload}


def build_graph(checkpointer, registry=None):
    registry = registry or build_default_registry()
    for spec in SPECS:
        if spec.name not in registry.names():
            registry.register(spec)
    legacy = pipeline_nodes(registry)

    def understand(state):
        result = intake(state, registry)
        result.update(_publish_understanding({**state, **result}))
        return _queue(state, result, "intake", "understanding")

    def direct(state):
        result = director_lite(state, registry)
        spec = result.get("request_spec") or state["request_spec"]
        result["request_spec"] = spec
        result.update(_publish_understanding({**state, **result}))
        return _queue(state, result, "director", "planning")

    def prepare(state):
        result = prepare_transition(state)
        result.update(_publish_understanding({**state, **result}))
        return _queue(state, result, "director", "planning")

    def checked_simple(state, raw, *, edited=False):
        row = AgentRun.query.filter_by(run_id=state["run_id"]).one()
        spec = approval_request_spec(state["request_spec"], state.get("plan"), raw) if edited else state["request_spec"]
        return spec, validate_simple_plan(raw, spec, owner_id=row.owner_id,
                                         budget_scope=state["run_id"], budget_limit=state["budget_limit"])

    def simple_validate(state):
        try:
            _spec, plan = checked_simple(state, state["plan"])
        except (AppError, ValidationError) as error:
            return {"plan_issues": [_plan_issue(error)], "status": "awaiting_approval"}
        assumptions = list(dict.fromkeys([*plan["assumptions"], *state.get("assumptions", [])]))
        plan["assumptions"] = assumptions[:10]
        threshold = current_app.config.get("AGENT_AUTO_APPROVE_CREDITS", 0)
        auto = threshold > 0 and plan["estimated_cost"] <= threshold
        return {"plan": plan, "plan_issues": [], "approved": auto, "shots": {},
                "status": "producing" if auto else "awaiting_approval"}

    def simple_approval(state):
        decision = interrupt({"kind": "approval", "plan": state["plan"],
                              "estimated_credits": state["plan"].get("estimated_cost")})
        if decision.get("action") == "reject":
            return {"approved": False, "status": "cancelled", "last_command_id": decision.get("command_id")}
        if decision.get("action") != "approve":
            raise AppError("INVALID_ACTION", "Explicit plan approval required", 409)
        spec, plan = checked_simple(state, decision.get("plan") or state["plan"], edited=bool(decision.get("plan")))
        update = {"request_spec": spec, "plan": plan, "approved": True, "shots": {}, "plan_issues": [],
                  "status": "producing", "last_command_id": decision.get("command_id")}
        return {**update, **_publish_understanding({**state, **update})}

    def simple_delivery_approval(_state):
        decision = interrupt({"kind": "delivery"})
        if decision.get("action") != "deliver":
            raise AppError("INVALID_ACTION", "Delivery must be requested explicitly", 409)
        return {"status": "delivering", "last_command_id": decision.get("command_id")}

    def create_story(state):
        result = legacy["creative"](state)
        result["plan"] = complete_transition_draft(result["plan"], state)
        return result

    def check_story(state):
        try:
            plan = validate_transition_plan(state["plan"], state, enforce_duration=True)
        except (AppError, ValidationError) as error:
            return {"plan_issues": [_plan_issue(error)], "status": "awaiting_approval"}
        return {"plan": plan, "plan_issues": [], "status": "awaiting_approval"}

    def story_approval(state):
        decision = interrupt({"kind": "approval", "plan": state["plan"]})
        if decision.get("action") == "reject":
            return {"approved": False, "status": "cancelled", "last_command_id": decision.get("command_id")}
        if decision.get("action") != "approve":
            raise AppError("INVALID_ACTION", "Explicit plan approval required", 409)
        plan = validate_transition_plan(decision.get("plan") or state["plan"], state,
                                        enforce_duration=not bool(decision.get("plan")))
        return {"plan": plan, "approved": True, "plan_issues": [], "shots": {}, "status": "producing",
                "last_command_id": decision.get("command_id")}

    def story_collect(state):
        result = legacy["collect"](state)
        result["results"] = [
            {"kind": "video", **{key: ref[key] for key in ("artifact_id", "preview_url", "download_url")}}
            for shot in state["plan"]["shots"]
            for ref in result["shots"].get(shot["shot_id"], {}).get("artifacts", [])
            if ref["artifact_type"] in {"i2v_video", "retained_video"}
        ]
        return result

    def route(state):
        return "simple_director" if state["request_spec"]["recipe_hint"] in {
            "image_edit", "image_create", "single_clip",
        } else "prepare_story"

    def wait_analysis(_state):
        interrupt({"kind": "analysis"})
        return {}

    nodes = {
        "analyze_attachments": lambda state: analyze_attachments(state, registry),
        "wait_analysis": wait_analysis,
        "intake": understand,
        "intake_clarify": clarify_gate,
        "simple_director": direct,
        "director_clarify": clarify_gate,
        "simple_validate": simple_validate,
        "simple_approval": simple_approval,
        "simple_production": lambda state: simple_execution.production(state, registry),
        "simple_collect": lambda state: simple_execution.collect(state, registry),
        "simple_wait": legacy["wait_tasks"],
        "simple_delivery_approval": simple_delivery_approval,
        "simple_deliver": simple_execution.deliver,
        "prepare_story": prepare,
        "story_clarify": clarify_gate,
        "story_director": legacy["director"],
        "story_creative": create_story,
        "story_validate": check_story,
        "story_approval": story_approval,
        "story_production": legacy["production"],
        "story_collect": story_collect,
        "story_wait": legacy["wait_tasks"],
        "story_delivery_approval": legacy["delivery_approval"],
        "story_deliver": legacy["deliver"],
    }
    builder = StateGraph(AgentStateV2)
    for name, fn in nodes.items():
        builder.add_node(name, in_app_context(fn))
    builder.add_edge(START, "analyze_attachments")
    builder.add_conditional_edges("analyze_attachments", lambda s: "intake" if s["attachments_ready"] else "wait_analysis")
    builder.add_edge("wait_analysis", "analyze_attachments")
    builder.add_edge("intake", "intake_clarify")
    builder.add_conditional_edges("intake_clarify", lambda s: "intake" if s.get("open_questions") else route(s))
    builder.add_edge("simple_director", "director_clarify")
    builder.add_conditional_edges("director_clarify", lambda s: "simple_director" if s.get("open_questions") else "simple_validate")
    builder.add_conditional_edges("simple_validate", lambda s: "simple_production" if s.get("approved") else "simple_approval")
    builder.add_conditional_edges("simple_approval", lambda s: "simple_production" if s["approved"] else END)
    builder.add_edge("simple_production", "simple_collect")
    # CONTRACTS A.11: simple results are individually downloadable, so delivery
    # needs no extra approval. simple_delivery_approval stays registered only so
    # runs checkpointed at that interrupt by earlier builds can still resume.
    builder.add_conditional_edges("simple_collect", simple_execution.after_collect,
                                  {"end": END, "delivery": "simple_deliver", "wait": "simple_wait",
                                   "produce": "simple_production"})
    builder.add_edge("simple_wait", "simple_collect")
    builder.add_edge("simple_delivery_approval", "simple_deliver")
    builder.add_edge("simple_deliver", END)
    builder.add_edge("prepare_story", "story_clarify")
    builder.add_conditional_edges("story_clarify", lambda s: "prepare_story" if s.get("open_questions") else "story_director")
    builder.add_edge("story_director", "story_creative")
    builder.add_edge("story_creative", "story_validate")
    builder.add_edge("story_validate", "story_approval")
    builder.add_conditional_edges("story_approval", lambda s: "story_production" if s["approved"] else END)
    builder.add_conditional_edges("story_production", lambda s: "story_production" if len(s["shots"]) < len(s["plan"]["shots"]) else "story_collect")
    builder.add_conditional_edges("story_collect", lambda s: {"producing": "story_wait", "awaiting_delivery": "story_delivery_approval", "failed": END}[s["status"]])
    builder.add_edge("story_wait", "story_collect")
    builder.add_conditional_edges("story_delivery_approval", lambda s: "story_production" if s["status"] == "producing" else "story_deliver")
    builder.add_edge("story_deliver", END)
    return builder.compile(checkpointer=checkpointer)
