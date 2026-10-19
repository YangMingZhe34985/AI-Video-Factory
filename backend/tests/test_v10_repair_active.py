"""Repair delegation uses D-038 active time, preserving card limits."""
from copy import deepcopy
from datetime import timedelta

import pytest

from app.agents import repair_flow
from app.agents.cards import get_catalog
from app.extensions import db
from app.models import AgentDelegation, ToolInvocation
from app.utils.time_utils import as_utc, utc_now
from tests.test_v5_repair_flow import assigned, draft, failure, invoke

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)


def prepare(review):
    run, root, task, registry = failure()
    if review:
        author = assigned(run, registry)
        invoke(run, author, registry, 'propose_patch', {'draft': draft(task)}, 'candidate:propose')
        assert repair_flow.active_flow(run)['stage'] == 'review_pending'
    else:
        assert repair_flow.advance_repair_flow(run, registry)
        assert repair_flow.active_flow(run)['stage'] == 'author_pending'
    return run, root, registry


@pytest.mark.parametrize('review', [False, True])
@pytest.mark.parametrize('active,limit', [(0.25, 600), (50.0, 60), (650.0, 900), (None, 600)])
def test_waiting_wall_time_does_not_exhaust_repair_parent(app_ctx, review, active, limit):
    run, root, registry = prepare(review)
    app_ctx.config['AGENT_V3_DELEGATION_ACTIVE_SEC'] = limit
    root.started_at = utc_now() - timedelta(days=2)
    state = deepcopy(root.state or {})
    state.pop('active_seconds', None)
    if active is not None:
        state['active_seconds'] = active
    root.state = state
    db.session.commit()
    started, counters = root.started_at, (root.steps, root.llm_calls)
    children = AgentDelegation.query.filter_by(parent_id=root.id).count()
    assert repair_flow.advance_repair_flow(run, registry)
    child = repair_flow.planning_delegation(run)
    assert child is not None, run.error
    assert child.agent == ('director' if review else 'repair')
    assert AgentDelegation.query.filter_by(parent_id=root.id).count() == children + 1
    assert as_utc(root.started_at) == as_utc(started)
    assert (root.steps, root.llm_calls) == counters
    assert root.state.get('active_seconds') == active
    assert ToolInvocation.query.filter_by(tool_name='agent_llm_turn').count() == 0


@pytest.mark.parametrize('review', [False, True])
@pytest.mark.parametrize('limit', [7, 600, 900])
def test_active_time_limit_applies_to_repair_and_director(app_ctx, review, limit):
    run, root, registry = prepare(review)
    app_ctx.config['AGENT_V3_DELEGATION_ACTIVE_SEC'] = limit
    root.started_at = utc_now()
    root.state = {**(root.state or {}), 'active_seconds': float(limit)}
    db.session.commit()
    before = AgentDelegation.query.count()
    assert repair_flow.advance_repair_flow(run, registry)
    assert run.status == 'attention'
    assert run.error['code'] == 'AGENT_EXECUTION_LIMIT'
    assert repair_flow.active_flow(run) is None
    assert AgentDelegation.query.count() == before
    assert ToolInvocation.query.filter_by(tool_name='agent_llm_turn').count() == 0


@pytest.mark.parametrize('review', [False, True])
@pytest.mark.parametrize('field', ['steps', 'llm_calls'])
def test_card_step_and_llm_limits_remain_enforced(app_ctx, review, field):
    run, root, registry = prepare(review)
    limits = get_catalog().cards['producer'].limits
    setattr(root, field, limits.max_steps if field == 'steps' else limits.max_llm_calls)
    root.state = {**(root.state or {}), 'active_seconds': 0.0}
    db.session.commit()
    before = AgentDelegation.query.count()
    assert repair_flow.advance_repair_flow(run, registry)
    assert run.error['code'] == 'AGENT_EXECUTION_LIMIT'
    assert AgentDelegation.query.count() == before
    assert ToolInvocation.query.filter_by(tool_name='agent_llm_turn').count() == 0
