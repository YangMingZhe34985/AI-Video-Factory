"""SQL-only visibility and current-attempt queries for the read-only task center."""
from sqlalchemy import and_, case, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import aliased

from app.models import AgentPlanVersion, AgentRun, AgentShotTask, ApiTask, Job, JobNodeRun, Template, ToolInvocation

STATES = ("queued", "running", "waiting", "attention", "completed", "cancelled")
WAITING = ("storyboard_approved", "characters_approved", "videos_approved", "paused", "pending")
ATTENTION = ("failed", "partial_success", "needs_attention", "production_attention", "delivery_attention")


def state_expression(status, unknown=None):
    checks = [(unknown, "attention")] if unknown is not None else []
    return case(*checks,
        (status == "queued", "queued"),
        (or_(status.in_(WAITING), status.like("awaiting_%")), "waiting"),
        (status.in_(ATTENTION), "attention"),
        (status.in_(("success", "completed")), "completed"),
        (status == "cancelled", "cancelled"), else_="running")


def linked_to_run(run_id=None):
    query = select(ToolInvocation.id).where(ToolInvocation.job_id == Job.id)
    if run_id is None:
        query = query.join(AgentRun, AgentRun.run_id == ToolInvocation.budget_scope)
    else:
        query = query.where(ToolInvocation.budget_scope == run_id).correlate(Job, AgentRun)
    return query.exists()


def shared_workflow():
    # Missing/malformed/orphan ownership metadata never falls back to shared.
    private = or_(
        Job.strategy == "agent_upload",
        Job.strategy.like("skill:%"),
        Job.config["agent_upload_owner"].as_string().is_not(None),
        Job.config["agent_story_preview"].as_string().is_not(None),
        Job.config["agent_story_production"].as_string().is_not(None),
        Job.config["skill"].as_string().is_not(None),
        exists(select(Template.id).where(Template.id == Job.template_id, Template.template_id == "agent_workspace")),
        exists(select(ToolInvocation.id).where(ToolInvocation.job_id == Job.id)),
        exists(select(AgentShotTask.id).where(AgentShotTask.job_id == Job.job_id)),
    )
    # JSON objects are compared through extraction of the object, not a run_id.
    return ~private


def visible_job(owner):
    own_link = exists(select(ToolInvocation.id).join(
        AgentRun, AgentRun.run_id == ToolInvocation.budget_scope).where(
        ToolInvocation.job_id == Job.id, AgentRun.owner_id == owner))
    markers = [
        Job.config["agent_story_preview"]["run_id"].as_string(),
        Job.config["agent_story_production"]["run_id"].as_string(),
    ]
    marker_checks = []
    for marker in markers:
        marker_checks.append(or_(marker.is_(None), exists(select(AgentRun.id).where(
            AgentRun.run_id == marker, AgentRun.owner_id == owner,
            Job.config["skill"]["budget_scope"].as_string() == AgentRun.run_id))))
    foreign_link = exists(select(ToolInvocation.id).join(
        AgentRun, AgentRun.run_id == ToolInvocation.budget_scope).where(
        ToolInvocation.job_id == Job.id, AgentRun.owner_id != owner))
    return or_(shared_workflow(), and_(own_link, ~foreign_link, *marker_checks,
        Job.strategy != "agent_upload"))


def parent_query(owner):
    agent_title = func.coalesce(
        AgentRun.snapshot["story_package"]["title"].as_string(),
        AgentRun.snapshot["plan"]["title"].as_string(),
        AgentRun.snapshot["brief"]["title"].as_string(), AgentRun.run_id)
    agent = select(literal("agent").label("source"), AgentRun.run_id.label("task_id"),
        AgentRun.id.label("pk"), agent_title.label("title"),
        state_expression(AgentRun.status, exists(select(Job.id).where(
            linked_to_run(AgentRun.run_id), current_agent_job(AgentRun.run_id, AgentRun.snapshot), unknown_submission()
        ).correlate(AgentRun))).label("state"),
        AgentRun.created_at.label("created_at"), AgentRun.updated_at.label("updated_at")).where(AgentRun.owner_id == owner)
    workflow = select(literal("workflow").label("source"), Job.job_id.label("task_id"),
        Job.id.label("pk"), func.coalesce(Job.job_name, Job.job_id).label("title"),
        state_expression(Job.status, unknown_submission()).label("state"), Job.created_at.label("created_at"),
        Job.updated_at.label("updated_at")).where(shared_workflow())
    return union_all(agent, workflow).subquery()


def latest_shots(run_id, version):
    newer = aliased(AgentShotTask)
    return AgentShotTask.query.filter(
        AgentShotTask.run_id == run_id, AgentShotTask.plan_version == version,
        ~exists(select(newer.id).where(
            newer.run_id == AgentShotTask.run_id, newer.plan_version == AgentShotTask.plan_version,
            newer.target_type == AgentShotTask.target_type, newer.target_id == AgentShotTask.target_id,
            newer.attempt > AgentShotTask.attempt)))


def current_node_filter(job_model=Job):
    current = job_model.config["current_run"]["run_id"].as_string()
    return or_(current.is_(None), JobNodeRun.input_snapshot["run_id"].as_string() == current)


def latest_nodes(job_ids):
    newer = aliased(JobNodeRun)
    return JobNodeRun.query.join(Job, Job.id == JobNodeRun.job_id).filter(
        JobNodeRun.job_id.in_(job_ids), current_node_filter(),
        ~exists(select(newer.id).where(
            newer.job_id == JobNodeRun.job_id, newer.node_key == JobNodeRun.node_key,
            or_(Job.config["current_run"]["run_id"].as_string().is_(None),
                newer.input_snapshot["run_id"].as_string() == Job.config["current_run"]["run_id"].as_string()),
            newer.id > JobNodeRun.id)))


def same_sample(left, right):
    a, b = left.request_payload["test_index"].as_integer(), right.request_payload["test_index"].as_integer()
    return or_(a == b, and_(a.is_(None), b.is_(None)))


def current_api_query(job_ids):
    current = Job.config["current_run"]["run_id"].as_string()
    node_ids = latest_nodes(job_ids).with_entities(JobNodeRun.id).statement
    newer = aliased(ApiTask)
    # A branch has one current provider operation (old retry attempts are history).
    return ApiTask.query.join(Job, Job.id == ApiTask.job_id).filter(
        ApiTask.job_id.in_(job_ids),
        or_(current.is_(None), ApiTask.request_payload["_run_id"].as_string() == current),
        or_(ApiTask.node_run_id.is_(None), ApiTask.node_run_id.in_(node_ids)),
        ~exists(select(newer.id).where(
            newer.job_id == ApiTask.job_id, newer.branch_key == ApiTask.branch_key, same_sample(newer, ApiTask),
            or_(newer.node_run_id == ApiTask.node_run_id,
                and_(newer.node_run_id.is_(None), ApiTask.node_run_id.is_(None))), newer.id > ApiTask.id,
            or_(current.is_(None), newer.request_payload["_run_id"].as_string() == current))))


def current_version(run):
    return AgentPlanVersion.query.filter_by(run_id=run.run_id).order_by(AgentPlanVersion.version.desc()).first()



def current_agent_job(run_id, snapshot=None):
    version = select(func.max(AgentPlanVersion.version)).where(
        AgentPlanVersion.run_id == run_id).correlate(AgentRun).scalar_subquery()
    newer = aliased(AgentShotTask)
    active = exists(select(AgentShotTask.id).where(
        AgentShotTask.job_id == Job.job_id, AgentShotTask.run_id == run_id,
        AgentShotTask.plan_version == version,
        ~exists(select(newer.id).where(
            newer.run_id == AgentShotTask.run_id, newer.plan_version == AgentShotTask.plan_version,
            newer.target_type == AgentShotTask.target_type, newer.target_id == AgentShotTask.target_id,
            newer.attempt > AgentShotTask.attempt))).correlate(Job, AgentRun))
    markers = [Job.config[key]["plan_version"].as_integer()
               for key in ("agent_story_production", "agent_story_preview")]
    if snapshot is None:
        snapshot = select(AgentRun.snapshot).where(AgentRun.run_id == run_id).scalar_subquery()
    shot_id = Job.config["shot"]["shot_id"].as_string()
    path = literal('$.' + '"shots"' + '.') + func.json_quote(shot_id) + literal('."job_id"')
    selected_job = snapshot[path].as_string()
    # Legacy produce_shot/remix_shot revisions have no AgentShotTask rows.
    legacy_current = or_(version.is_not(None), shot_id.is_(None), selected_job == Job.job_id)
    return and_(legacy_current,
                or_(~exists(select(AgentShotTask.id).where(AgentShotTask.job_id == Job.job_id)), active),
                *(or_(marker.is_(None), marker == version) for marker in markers))


def unknown_submission():
    """Use the same current-round/latest-operation rule in SQL parent counts."""
    task, newer = aliased(ApiTask), aliased(ApiTask)
    node, later_node = aliased(JobNodeRun), aliased(JobNodeRun)
    current = Job.config["current_run"]["run_id"].as_string()
    valid_node = exists(select(node.id).where(node.id == task.node_run_id, node.job_id == Job.id,
        or_(current.is_(None), node.input_snapshot["run_id"].as_string() == current),
        ~exists(select(later_node.id).where(
            later_node.job_id == node.job_id, later_node.node_key == node.node_key,
            later_node.id > node.id,
            or_(current.is_(None), later_node.input_snapshot["run_id"].as_string() == current)))
    ).correlate(Job, task))
    latest = ~exists(select(newer.id).where(
        newer.job_id == task.job_id, newer.branch_key == task.branch_key, same_sample(newer, task), newer.id > task.id,
        or_(newer.node_run_id == task.node_run_id, and_(newer.node_run_id.is_(None), task.node_run_id.is_(None))),
        or_(current.is_(None), newer.request_payload["_run_id"].as_string() == current)
    ).correlate(Job, task))
    return exists(select(task.id).where(
        task.job_id == Job.id, task.queue_phase == "submit_unknown",
        or_(current.is_(None), task.request_payload["_run_id"].as_string() == current),
        or_(task.node_run_id.is_(None), valid_node), latest).correlate(Job))
