"""Public Skill/Job routes must not bypass story production approval receipts."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.adapters.mock import MockAdapter
from app.agent.production_state import latest_tasks
from app.agent.production_policy import authorized_job_dispatch, validate_dispatch
from app.api import AppError
from app.extensions import db
from app.models import ToolInvocation
from app.services.job_run_service import JobRunService
from app.skills.budget import BudgetGuard
from tests.test_production_recovery import inline_jobs, prepared, settle, fail_submit_once

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_MAX_SHOT_AUTO_REPAIRS=0)


def production(monkeypatch, *, unknown=False):
    run, version, registry = prepared(allowance=0)
    run.owner_id = 'local'
    db.session.commit()
    if unknown:
        calls = fail_submit_once(monkeypatch, status=None)
    else:
        calls = []
        original = MockAdapter.submit
        monkeypatch.setattr(MockAdapter, 'submit', lambda self, payload: calls.append(payload) or original(self, payload))
    expected = 'production_attention' if unknown else 'awaiting_video_review'
    assert settle(run, registry) == expected
    target = latest_tasks(run, version)['s01']
    invocation = ToolInvocation.query.filter_by(invocation_id=target.invocation_id).one()
    return run, version, target, invocation, calls


def public_call(client, run, name, data, key):
    return client.post(f'/api/skills/{name}/invoke', json={'input': data, 'role': 'production',
        'approved': True, 'budget_scope': run.run_id, 'budget_limit': 500, 'idempotency_key': key})


@pytest.mark.parametrize('fresh_key', [False, True])
def test_public_animate_cannot_retry_unknown_or_escape_with_new_key(app_ctx, client, inline_jobs, monkeypatch, fresh_key):
    run, _version, target, invocation, calls = production(monkeypatch, unknown=True)
    before = (len(calls), BudgetGuard.spent(run.run_id), invocation.attempt, ToolInvocation.query.count())
    key = 'new-public-key' if fresh_key else invocation.idempotency_key
    result = public_call(client, run, 'animate_shot', invocation.input_payload, key)
    assert result.status_code == 409, result.json
    assert result.json['error']['code'] == 'UNSAFE_RETRY'
    assert (len(calls), BudgetGuard.spent(run.run_id), invocation.attempt, ToolInvocation.query.count()) == before
    assert target.status == 'failed'


@pytest.mark.parametrize('unknown', [False, True])
@pytest.mark.parametrize('mode', ['node', 'from'])
def test_public_rerun_skill_cannot_force_production_submit(app_ctx, client, inline_jobs, monkeypatch, unknown, mode):
    run, _version, _target, invocation, calls = production(monkeypatch, unknown=unknown)
    before = (len(calls), BudgetGuard.spent(run.run_id), ToolInvocation.query.count())
    result = public_call(client, run, 'rerun_node', {'job_id': invocation.job.job_id,
        'node_key': 'submit_i2v', 'force': True, 'mode': mode}, 'forced')
    assert result.status_code == 409, result.json
    assert result.json['error']['code'] == 'UNSAFE_RETRY'
    assert (len(calls), BudgetGuard.spent(run.run_id), ToolInvocation.query.count()) == before


@pytest.mark.parametrize('path,payload', [('run-full', {'restart': True}),
    ('run-full', {'force': True}), ('run-from', {'node_key': 'submit_i2v', 'force': True}),
    ('run-node', {'node_key': 'submit_i2v', 'force': True}), ('run-node', {'node_key': 'poll_i2v', 'force': True})])
def test_classic_job_routes_cannot_reexecute_production_even_for_its_owner(app_ctx, client, inline_jobs, monkeypatch, path, payload):
    run, _version, _target, invocation, calls = production(monkeypatch, unknown=True)
    before = (len(calls), BudgetGuard.spent(run.run_id), invocation.job.status, deepcopy(invocation.job.config))
    result = client.post(f'/api/jobs/{invocation.job.job_id}/{path}', json=payload)
    assert result.status_code == 409, result.json
    assert result.json['error']['code'] == 'UNSAFE_RETRY'
    assert (len(calls), BudgetGuard.spent(run.run_id), invocation.job.status, invocation.job.config) == before


def test_classic_non_agent_job_can_still_run_through_public_endpoint(app_ctx, client, inline_jobs, h, source_video):
    job = h.make_job(source_video=source_video)
    response = client.post(f'/api/jobs/{job.job_id}/run-full', json={})
    assert response.status_code == 200, response.json
    assert not (job.config or {}).get('agent_story_production')
    assert job.status == 'success'


def test_owner_patch_cannot_remove_production_marker(app_ctx, client, inline_jobs, monkeypatch):
    run, _version, _target, invocation, calls = production(monkeypatch, unknown=True)
    job = invocation.job
    original = deepcopy(job.config)
    response = client.patch(f'/api/jobs/{job.job_id}', json={
        'job_config': {}, 'config': {}, 'agent_story_production': None, 'skill': None})
    assert response.status_code == 200, response.json
    db.session.refresh(job)
    assert job.config == original
    before = (len(calls), BudgetGuard.spent(run.run_id))
    result = client.post(f'/api/jobs/{job.job_id}/run-full', json={'restart': True})
    assert result.status_code == 409 and result.json['error']['code'] == 'UNSAFE_RETRY'
    assert (len(calls), BudgetGuard.spent(run.run_id)) == before


def test_owner_prompt_edit_is_rejected_by_frozen_recovery_policy(app_ctx, client, inline_jobs, monkeypatch):
    from app.agent.recovery import recover_job
    from app.services.prompt_service import PromptService
    run, _version, _target, invocation, calls = production(monkeypatch)
    job = invocation.job
    prompt = PromptService.get_active_for_template(job.template, 'i2v', job_id=job.id)
    response = client.post(
        f'/api/templates/{job.template.template_id}/prompts/i2v/versions/{prompt.version}/edit',
        json={'job_id': job.job_id, 'content': 'An unapproved replacement motion', 'activate': True})
    assert response.status_code == 201, response.json
    # Simulate a durable recovery after executor loss, not another public run.
    job.status = 'pending'
    db.session.commit()
    before = (len(calls), BudgetGuard.spent(run.run_id))
    with pytest.raises(AppError) as rejected:
        recover_job(job, run.run_id)
    assert rejected.value.code == 'MODEL_PREFERENCE_VIOLATION'
    assert (len(calls), BudgetGuard.spent(run.run_id)) == before


def test_dispatch_permit_is_exact_scoped_and_not_inherited_by_another_context():
    from contextvars import Context
    job = SimpleNamespace(job_id='approved-job', config={'agent_story_production': {'task_id': 1}})
    other = SimpleNamespace(job_id='other-job', config=deepcopy(job.config))
    with authorized_job_dispatch(job, 'run_full'):
        validate_dispatch(job, 'run_full', None, False, False)
        for args in [(other, 'run_full', None, False, False),
                     (job, 'run_full', None, True, False),
                     (job, 'run_full', None, False, True),
                     (job, 'run_node', 'submit_i2v', True, False)]:
            with pytest.raises(AppError) as rejected:
                validate_dispatch(*args)
            assert rejected.value.code == 'UNSAFE_RETRY'
        with pytest.raises(AppError):
            Context().run(validate_dispatch, job, 'run_full', None, False, False)
    with pytest.raises(AppError):
        validate_dispatch(job, 'run_full', None, False, False)
    with pytest.raises(RuntimeError):
        with authorized_job_dispatch(job, 'run_full'):
            raise RuntimeError('interrupted admission')
    with pytest.raises(AppError):
        validate_dispatch(job, 'run_full', None, False, False)


@pytest.mark.parametrize('run_type,node_key,options', [
    ('run_node', 'submit_i2v', {'force': True}),
    ('run_full', None, {'force': True}),
    ('run_full', None, {'restart': True}),
    ('run_from', 'poll_i2v', {})])
def test_server_permit_cannot_authorize_forced_submit_or_restart(run_type, node_key, options):
    job = SimpleNamespace(job_id='approved-job', config={'agent_story_production': {'task_id': 1}})
    with pytest.raises(AppError) as rejected:
        with authorized_job_dispatch(job, run_type, node_key, **options):
            pytest.fail('Unsafe permission was granted')
    assert rejected.value.code == 'UNSAFE_RETRY'
