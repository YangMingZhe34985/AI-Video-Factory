"""Offline integrated selected adapter/Registry proof with an in-memory HTTP Stub."""
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import sys

import pytest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/v3_eval'))
from gate6_budget import ImageBudget,digest
from gate6_meter import Gate6Meter
from gate6_selective import SelectiveMedia,capture_originals
from gate6_transport import ImageTransport,ASYNC_URL,TASK_PREFIX,CHAT_URL
from gate6_identity import invoke_identity

pytestmark=pytest.mark.config(AGENT_MODE_ENABLED=True,AGENT_V3_ENABLED=True,T2V_ENABLED=True)


def test_approved_four_node_identity_sample_uses_real_adapter_paths_with_http_stub(app_ctx,monkeypatch,tmp_path):
    import requests
    from PIL import Image
    from app import adapters
    from app.agent import plan_versions
    from app.extensions import db
    from app.plans import runtime
    from app.plans.compiler import compile_plan
    from app.plans.dry_run import dry_run
    from app.models import ToolInvocation
    from app.services.job_run_service import JobRunService
    from app.tools import build_v3_registry
    from tests.test_v3_plan_compiler import make_run
    import mock_media
    run=make_run(deliverable='image')
    run.request={**run.request,'budget_limit':300}
    nodes=[]
    for node_id,role in [('cast_a','hero_a'),('cast_b','hero_b')]:
        nodes.append({'id':node_id,'tool':'generate_image','model_id':'wan2.6-image','params':{'n':1},
            'inputs':{'mode':'t2i','prompt':'Original test character '+role},'characters':[role],'gate':'preview',
            'origin':{'agent':'director','skills':[]},'rationale':'One identity'})
    for node_id in ('kf_a','kf_b'):
        nodes.append({'id':node_id,'tool':'generate_image','model_id':'qwen-image-3.0','params':{'n':1},
            'inputs':{'mode':'i2i','prompt':'Both test characters in scene '+node_id,
                'reference_artifact_ids':[{'ref':'cast_a.image'},{'ref':'cast_b.image'}]},'characters':['hero_a','hero_b'],
            'origin':{'agent':'director','skills':[]},'rationale':'Two references'})
    nodes.append({'id':'other','tool':'generate_image','model_id':'wan2.6-image','params':{'n':1},
        'inputs':{'mode':'t2i','prompt':'An empty background'},'characters':[],
        'origin':{'agent':'director','skills':[]},'rationale':'Unselected Mock'})
    draft={'title':'Gate6 offline fixture','goal':'Test selected dispatch','nodes':nodes,
        'character_references':{'hero_a':[{'ref':'cast_a.image'}],'hero_b':[{'ref':'cast_b.image'}]},
        'deliverables':[{'kind':'image','node_id':n['id'],'output':'image'} for n in nodes]}
    registry=build_v3_registry()
    checked=compile_plan(draft,run,registry=registry,plan_version=1)
    assert not checked['issues'],json.dumps(checked['issues'],ensure_ascii=False)
    checked['dry_run']=dry_run(checked,registry=registry)
    assert checked['dry_run']['passed']
    version=plan_versions.create_version(run,checked['plan'],{},checked,author='system')
    run.status='awaiting_plan_review'; db.session.commit()
    selected=version.plan['nodes'][:4]
    manifest={'run_id':run.run_id,'plan_version':version.version,'plan_hash':plan_versions.inputs_hash(version.plan),
        'nodes':[{'node_id':node['id'],'kind':'cast' if index<2 else 'keyframe','model':node['model_id'],'node_hash':digest(node),'n':1} for index,node in enumerate(selected)]}
    from gate6_views import preflight_budget
    preflight=preflight_budget(run,version.plan,manifest)
    assert preflight['can_cover_selected_and_vision'] and preflight['can_cover_full_plan_and_vision']
    assert preflight['approved_plan_estimate']==version.plan['estimates']['total_credits']
    assert preflight['required_including_remaining_mock']>=preflight['required_before_remaining_mock']
    # Stub before guard installation, so each adapter follows its production
    # payload/submit/poll/download path but no socket or provider is involved.
    calls=[]; tasks={}; images={}
    def result(data):
        response=requests.Response(); response.status_code=200
        response._content=json.dumps(data).encode(); response._content_consumed=True
        return response
    def raw_send(session,request,**kwargs):
        calls.append((request.method,request.url))
        if request.method=='POST' and request.url==ASYNC_URL:
            payload=json.loads(request.body); task='task_'+str(len(tasks)+1); tasks[task]=payload
            out=io.BytesIO(); Image.new('RGB',(1024,1024),(25*len(tasks),80,120)).save(out,format='PNG'); images[task]=out.getvalue()
            return result({'request_id':'req_'+task,'output':{'task_id':task}})
        if request.method=='GET' and request.url.startswith(TASK_PREFIX):
            task=request.url[len(TASK_PREFIX):]
            return result({'request_id':'req_'+task,'output':{'task_status':'SUCCEEDED',
                'results':[{'url':f'https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/{task}.png'}]},'usage':{'image_count':1}})
        if request.method=='GET' and request.url.startswith('https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/'):
            task=Path(request.url).stem; response=requests.Response(); response.status_code=200
            response._content=images[task]; response._content_consumed=True; return response
        if request.method=='POST' and request.url==CHAT_URL:
            body={'comparisons':[{'character':role,'keyframe_node':frame,'verdict':'uncertain',
                'visible_traits':'Stub color rectangle','differences':'No actual character quality evaluated'}
                for role in ('hero_a','hero_b') for frame in ('kf_a','kf_b')],
                'limitations':'Offline Stub only; no actual vision or generation quality tested'}
            return result({'id':'stub_identity_once','choices':[{'message':{'content':json.dumps(body)},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}})
        pytest.fail('Unexpected HTTP stub request: '+request.url)
    monkeypatch.setattr(requests.Session,'send',raw_send)
    monkeypatch.setattr(mock_media,'CONTROLLER',None)
    for name in mock_media.MEDIA_NAMES: monkeypatch.setitem(adapters.ADAPTERS,name,adapters.ADAPTERS[name])
    originals=capture_originals()
    meter=Gate6Meter(tmp_path).install(); budget=ImageBudget(meter.path,manifest)
    transport=ImageTransport(meter,budget,raw_send,requests.Session.send).install()
    controller=SelectiveMedia(budget,transport,originals,tmp_path/'mock-media.jsonl'); controller.install()
    app_ctx.config.update(MODEL_ADAPTER_MODE='real',DASHSCOPE_API_KEY='OFFLINE_STUB_NOT_A_KEY',AGENT_WORKER_ACTIVE=True,
        AGENT_V3_DEFAULT_VISION_MODEL='qwen3.7-plus',AGENT_VISION_MODEL='qwen3.7-plus')
    monkeypatch.setattr(JobRunService,'start',JobRunService.run_inline)
    meter.set_label('04-identity:'+run.run_id); meter.begin_execution()
    try:
        runtime.begin(run,version,registry=registry)
        approved=set()
        for _ in range(20):
            runtime.advance(run,registry)
            tasks_now=runtime.latest_tasks(run)
            for node_id in ('cast_a','cast_b'):
                task=tasks_now[node_id]
                if task.status=='success' and node_id not in approved:
                    runtime.approve_gate(run,version.version,node_id)
                    approved.add(node_id)
            if all(tasks_now[n['id']].status=='success' for n in selected): break
        assert all(runtime.latest_tasks(run)[n['id']].status=='success' for n in selected),[(t.node_id,t.status,t.error) for t in runtime.latest_tasks(run).values()]
        assert budget.snapshot()['downloaded_images']==4
        assert len(tasks)==4
        assert mock_media.CONTROLLER.summary()['mock_images_written']==1
        assert tasks['task_3']['model']=='qwen-image-3.0' and tasks['task_4']['model']=='qwen-image-3.0'
        for task in ('task_3','task_4'):
            refs=[b['image'] for b in tasks[task]['input']['messages'][0]['content'] if 'image' in b]
            assert len(refs)==2 and all(ref.startswith('data:image/') for ref in refs)
        report=invoke_identity(budget,meter)
        assert report['tool_receipt']['status']=='success' and report['product_visual_qc'] is False
        assert len(report['display_inputs'])==4 and all(Path(i['path']).is_file() for i in report['images'])
        assert report['provider_response']['finish_reason']=='stop'
        assert 'Offline Stub only' in report['provider_response']['content']
        assert all(item['transform']['max_edge']==1024 for item in report['display_inputs'])
        assert sum(item['bytes'] for item in report['display_inputs'])<=2*1024*1024
        assert meter.snapshot()['real_calls']==1 and meter.snapshot()['vision_calls']==1
        assert meter.snapshot()['real_image_calls']==4 and meter.snapshot()['real_video_calls']==0
        assert not meter.snapshot()['blocked_network_attempts'] and not meter.snapshot()['blocked_media_attempts']
        assert len([u for m,u in calls if m=='POST' and u==CHAT_URL])==1
        row=ToolInvocation.query.filter_by(tool_name='gate6_identity_review',budget_scope=run.run_id).one()
        assert row.status=='success' and row.output_payload['usage']['prompt_tokens']+row.output_payload['usage']['completion_tokens']==20
        assert row.estimated_cost>0
    finally: meter.uninstall()
