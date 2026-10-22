"""Incomplete context views cannot become saved or executable Plan/Patch inputs."""
from copy import deepcopy
import json

import pytest

from app.agents.schemas import PlanDraft, PlanDraftNode, WorkspaceRef, validate_payload
from app.api import AppError
from app.extensions import db
from app.models import AgentPlanVersion, AgentWorkspaceItem, Job, PlanNodeTask, ToolInvocation
from app.plans.compiler import compile_plan
from app.plans.patch_schemas import PatchDraft, UpdateInputs
from app.plans.projection_input import reject_context_projection
from app.plans.tools import AppendInput, CheckInput
from tests.test_v3_plan_compiler import make_run, node, plan
from tests.test_v3_plan_tools import context, invoke, registry, save


def marker(key='draft', version=1):
    return {'context_projection': {'not_executable': True, 'reread': [
        {'tool': 'read_workspace', 'arguments': {'key': key, 'version': version}}]}}


def patch(op=None):
    return {'base_version': 1, 'reason': 'update cat poster', 'ops': [op or {
        'op': 'update_inputs', 'node_id': 'image', 'inputs': {'prompt': 'cat in rain'}}]}


def error_from(call):
    with pytest.raises(AppError) as caught:
        call()
    assert caught.value.code == 'PLAN_CONTEXT_PROJECTION'
    assert caught.value.status_code == 422
    assert caught.value.payload['repair_guidance']
    return caught.value


@pytest.mark.parametrize('model,value', [
    (PlanDraft, marker()),
    (PlanDraft, {**plan(), **marker()}),
    (PlanDraft, plan([{**node(), 'inputs': marker()}])),
    (PlanDraftNode, {**node(), **marker()}),
    (PlanDraftNode, {**node(), 'params': marker()}),
    (CheckInput, marker()),
    (CheckInput, {'plan_ref': {'key': 'draft', 'version': 1}, **marker()}),
    (CheckInput, {'plan': marker()}),
    (AppendInput, {'plan_ref': {'key': 'draft', 'version': 1}, 'nodes': [node()], **marker()}),
    (AppendInput, {'plan_ref': {'key': 'draft', 'version': 1}, 'nodes': [{**node(), 'inputs': marker()}]}),
    (PatchDraft, {**patch(), **marker()}),
    (PatchDraft, patch({'op': 'update_inputs', 'node_id': 'image', 'inputs': marker()})),
    (PatchDraft, patch({'op': 'replace_node', 'node_id': 'image', 'node': {**node(), 'inputs': marker()}})),
    (PatchDraft, patch({'op': 'insert_node', 'node': {**node('another'), 'inputs': marker()}})),
])
def test_before_validation_retains_special_error_and_original_input(model, value):
    original = deepcopy(value)
    error = error_from(lambda: model.model_validate(value))
    assert error.payload['reread'] == marker()['context_projection']['reread']
    assert value == original


@pytest.mark.parametrize('value', [None, False, 'literal', [], {}, {'reread': 'wrong'}])
def test_any_structural_marker_is_rejected_even_malformed(value):
    error = error_from(lambda: reject_context_projection({'context_projection': value}))
    assert error.payload['reread'] == []


def test_plain_text_and_typed_nested_inputs_preserve_existing_parsing():
    typed_node = PlanDraftNode.model_validate(node(inputs={'prompt': 'draw the text context_projection {"context_projection": true}'}))
    typed = PlanDraft.model_validate({**plan(), 'nodes': [typed_node]})
    assert typed.nodes[0] is typed_node
    assert CheckInput.model_validate({'plan': typed}).plan is typed
    ref = WorkspaceRef(key='draft', version=1)
    appended = AppendInput.model_validate({'plan_ref': ref, 'nodes': [typed_node]})
    assert appended.plan_ref is ref and appended.nodes[0] is typed_node
    operation = UpdateInputs(op='update_inputs', node_id='image', inputs={'prompt': 'context_projection'})
    assert PatchDraft.model_validate({**patch(), 'ops': [operation]}).ops[0] is operation
    data = {'model': typed, 'reference': ref}
    assert reject_context_projection(data) is data


def test_typed_nested_operations_do_not_hide_a_marker():
    operation = UpdateInputs(op='update_inputs', node_id='image', inputs=marker())
    error_from(lambda: PatchDraft.model_validate({**patch(), 'ops': [operation]}))


def test_unmarked_deep_and_cyclic_objects_are_not_recursively_serialized():
    root, current = {}, None
    current = root
    for _ in range(1000):
        current['next'] = {}
        current = current['next']
    current['cycle'] = root
    assert reject_context_projection(root) is root
    current.update(marker())
    error_from(lambda: reject_context_projection(root))


def test_reread_is_exact_allowlisted_deduplicated_and_bounded():
    safe = lambda key, version=1: {'tool': 'read_workspace', 'arguments': {'key': key, 'version': version}}
    candidates = [
        {'tool': 'generate_image', 'arguments': {'prompt': 'paid'}},
        safe('https://secret.invalid/path'), safe('../private'), safe(' draft '),
        safe('draft', True), safe('draft', '1'), safe('draft', 0),
        {'tool': 'read_workspace', 'arguments': {'key': 'draft', 'version': 1, 'run_id': 'other'}},
        {'tool': 'read_workspace', 'arguments': {'key': 'draft', 'version': 1}, 'extra': 'secret'},
        safe('one'), safe('one'), safe('two'), safe('three'), safe('four'),
    ]
    value = {'context_projection': {'reread': candidates, 'omitted_secret': 'must-not-echo'}}
    error = error_from(lambda: reject_context_projection(value))
    assert error.payload['reread'] == [safe('one'), safe('two'), safe('three')]
    serialized = json.dumps(error.payload)
    assert 'secret' not in serialized and 'generate_image' not in serialized and 'run_id' not in serialized


@pytest.mark.parametrize('kind,data', [('plan_draft', marker()), ('patch', {**patch(), **marker()})])
def test_workspace_validation_keeps_special_error(kind, data):
    error_from(lambda: validate_payload(kind, data))


@pytest.mark.parametrize('shape,code', [('size', 'WORKSPACE_PAYLOAD_TOO_LARGE'), ('depth', 'INVALID_WORKSPACE_PAYLOAD')])
def test_unmarked_workspace_keeps_original_size_depth_limits(shape, code):
    value = plan()
    if shape == 'size':
        value['nodes'][0]['inputs']['prompt'] = 'x' * (256 * 1024)
    else:
        current = value['nodes'][0]['inputs']
        for _ in range(70):
            current['next'] = {}
            current = current['next']
    original = deepcopy(value)
    with pytest.raises(AppError) as caught:
        validate_payload('plan_draft', value)
    assert caught.value.code == code and value == original


def counts():
    return (AgentWorkspaceItem.query.count(), AgentPlanVersion.query.count(),
            Job.query.count(), PlanNodeTask.query.count())


@pytest.mark.parametrize('name,kind', [('check_plan', None), ('append_plan_nodes', None),
                                     ('write_workspace', 'plan_draft'), ('write_workspace', 'patch'),
                                     ('propose_patch', None), ('review_patch', None)])
def test_actual_registry_rejects_without_workspace_plan_job_or_charge(app_ctx, name, kind):
    run = make_run()
    ref = save(run, plan())
    payloads = {
        'check_plan': {'plan': marker()},
        'append_plan_nodes': {'plan_ref': ref, 'nodes': [node('second')], **marker()},
        'write_workspace': {'key': 'newdraft', 'kind': kind, 'payload': marker()},
        'propose_patch': {'draft': {**patch(), **marker()}},
        'review_patch': {'patch_id': 'unused', 'verdict': 'revise', 'reason': 'review',
                         'revised_draft': {**patch(), **marker()}},
    }
    ctx = context(run, 'blocked', 'director')
    before, snapshot = counts(), deepcopy(run.snapshot)
    error_from(lambda: registry().invoke(name, payloads[name], ctx))
    db.session.refresh(run)
    assert counts() == before and run.snapshot == snapshot and run.status == 'queued'
    assert all(row.estimated_cost == 0 for row in ToolInvocation.query.all())
    assert not ToolInvocation.query.filter(ToolInvocation.tool_name.in_(
        ['agent_llm_turn', 'generate_image', 'animate_shot', 'generate_video'])).count()


def test_compile_exposes_only_safe_reread_and_never_changes_saved_version(app_ctx):
    run = make_run()
    ref = save(run, plan())
    value = plan([{**node(), 'inputs': marker(ref['key'], ref['version'])}])
    value['nodes'][0]['inputs']['context_projection']['private'] = 'hidden-provider-secret'
    original, before = deepcopy(value), counts()
    result = compile_plan(value, run)
    assert [item['code'] for item in result['issues']] == ['PLAN_CONTEXT_PROJECTION']
    issue = result['issues'][0]
    assert issue['details']['reread'] == marker(ref['key'], ref['version'])['context_projection']['reread']
    assert 'Reread' in issue['message'] and 'hidden-provider-secret' not in json.dumps(issue)
    assert not result['dag']['order'] and result['validated_inputs'] == {}
    assert value == original and counts() == before
    output = invoke(registry(), 'read_workspace', ref, run, 'reread')
    assert output['items'][0]['payload']['nodes'][0]['inputs'] == {'prompt': 'cat'}
    checked = invoke(registry(), 'check_plan', {'plan_ref': ref}, run, 'check-original')
    assert checked['issues'] == [] and counts() == before


def test_reread_metadata_does_not_grant_other_run_access(app_ctx):
    source = make_run()
    ref = save(source, plan(), key='only_source')
    other = make_run()
    error = error_from(lambda: CheckInput.model_validate({'plan': marker(ref['key'], ref['version'])}))
    before = counts()
    with pytest.raises(AppError) as caught:
        invoke(registry(), 'read_workspace', error.payload['reread'][0]['arguments'], other, 'foreign')
    assert caught.value.code != 'PLAN_CONTEXT_PROJECTION' and counts() == before


@pytest.mark.parametrize('name', ['write_workspace', 'append_plan_nodes', 'read_workspace', 'check_plan'])
def test_historical_projected_inputs_are_conservatively_retained(name):
    from app.agents.context import project_messages
    from tests.test_v9_context import batch
    payload = marker()
    ref = {'key': 'draft', 'version': 1}
    item = {'workspace_ref': ref, 'key': 'draft', 'version': 1, 'kind': 'plan_draft', 'payload': payload}
    arguments, output = {
        'write_workspace': ({'key': 'draft', 'kind': 'plan_draft', 'payload': payload}, item),
        'append_plan_nodes': ({'plan_ref': ref, 'nodes': [{**node(), 'inputs': payload}]}, {**item, 'version': 2}),
        'read_workspace': (ref, {'items': [item]}),
        'check_plan': ({'plan': payload}, {'issues': []}),
    }[name]
    messages = batch(name, arguments, output, 'one')
    original = deepcopy(messages)
    projected, _metrics = project_messages(messages)
    assert messages == original
    assert projected[0]['tool_calls'] == original[0]['tool_calls']


def test_context_malformed_deep_json_stays_unchanged():
    from app.agents.context import project_messages
    from tests.test_v9_context import batch
    messages = batch('check_plan', {}, {'issues': []}, 'deep')
    messages[0]['tool_calls'][0]['function']['arguments'] = '{"a":' * 2000 + '0' + '}' * 2000
    original = deepcopy(messages)
    projected, _metrics = project_messages(messages)
    assert messages == original and projected[0]['tool_calls'] == original[0]['tool_calls']
