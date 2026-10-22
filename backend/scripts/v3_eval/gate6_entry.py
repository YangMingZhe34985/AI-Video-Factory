"""Gate6 one scheduled phase. Import is inert; --execute is mandatory.

The operator first reviews the fixed samples, then supplies an exact four-node
manifest for 04-identity. The selected plan is never replanned or rewritten.
"""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import re
import subprocess
import sys
import time

ROOT=Path('C:/Users/MingZheYang/Desktop/项目开发/AI Video Factory').resolve()
TEMP=Path(os.environ.get('TEMP','C:/Users/MingZheYang/AppData/Local/Temp')).resolve()
SCRIPTS=ROOT/'backend/scripts/v3_eval'
HERE=Path(__file__).resolve().parent
SAMPLES={'01-c3-1':'c3_story','02-c3-2':'c3_story','03-c7':'c7_complete_story'}
LABELS=[*SAMPLES,'04-identity']
COMPLETE_STORY = {
    "text": """制作约120秒的二维动画短片《最后一盏灯》。完整情节已经确定，请保留，不需要重新创作故事。
角色是原创拟人机器人小蓝（蓝色短发、白色外套、圆形胸灯）与小橙（橙色短发、深灰工装、方形胸灯）；
角色外观先统一定妆，不引用真实人物，也不需要检索已有IP。
12个情节段各约10秒，依次为：
1. 黄昏，海边灯塔的灯突然熄灭，小蓝在岸边发现远处一艘归船。
2. 小蓝进入灯塔检查，发现主电池耗尽，将空电池展示给刚进门的小橙。
3. 两人在明亮的工具间展开纸质线路图，指向备用发电机的位置。
4. 小橙从储物柜取出工具，小蓝抱起备用电池，一起上楼。
5. 小蓝装好电池，但灯没有亮；小橙发现断开的电缆。
6. 两人一起将电缆安全接好，电表指针恢复，灯仍然不亮。
7. 小蓝抬头看见卡住的遮光叶片，指向灯室顶端。
8. 小橙稳住梯子，小蓝登梯取下卡住叶片的树枝。
9. 灯塔光束重新扫过海面，两人在灯室里松了一口气。
10. 远处归船循着光束慢慢接近港口，画面只有船和海面。
11. 小蓝与小橙并肩站在窗前，看着船安全入港，互相击掌。
12. 夜幕中，两人走出灯塔，回望温暖的光束，镜头拉远结束。
无对白、无字幕，统一温暖动画风格，16:9。可采用清楚的硬切和独立关键帧；请保持两位角色身份，
不要新增情节或删除上述事件。模型沿用服务器默认，成片不额外压缩。先给出可审核的计划，未经批准不生成。""",
    "purpose": "用户已提供完整情节的两分钟长片：应由 Producer/Director 保留故事，不委派 Creative；验证身份输入和分批计划。",
    "budget": 300,
}
ACTIVE_TRANSPORT=None


def require(value,message):
    if not value: raise RuntimeError(message)


def sha(path): return sha256(Path(path).read_bytes()).hexdigest()


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))


def exclusive_json(path,value):
    with Path(path).open('x',encoding='utf-8') as handle:
        json.dump(value,handle,ensure_ascii=False,indent=2,default=str); handle.flush(); os.fsync(handle.fileno())


def source(expected,full):
    require(bool(re.fullmatch('[0-9a-f]{40}',expected)),'Expected full commit SHA required')
    def git(*args):
        return subprocess.run(['git','-C',str(ROOT),*args],check=True,capture_output=True,text=True,encoding='utf-8',timeout=30).stdout.strip()
    require(git('rev-parse','HEAD')==expected,'Frozen HEAD changed')
    branch=git('branch','--show-current')
    require(branch in {'feat/agent-v2','agent-v3/V-Gate6'},'Unexpected Gate6 branch')
    require(not git('status','--porcelain=v1','--untracked-files=all','--','backend','frontend-vue','factory_prompts','docs'),'Runtime/tests/docs must be committed and clean')
    full=Path(full).resolve(); require(full.is_relative_to(TEMP),'Full evidence must be in TEMP')
    summary=read(full/'summary.json'); before=read(full/'source-before.json'); after=read(full/'source-after.json')
    require(summary.get('passed') is True and summary.get('status')=='passed' and summary.get('source_frozen') is True
        and summary.get('processes_passed') is True and summary.get('guard_events')==[]
        and summary.get('mode')=='mock' and summary.get('dotenv_disabled') is True and summary.get('network_guard') is True and before==after,'Completed frozen offline full regression required')
    check=summary.get('verification',{})
    require(check.get('passed') is True and check.get('collected')==check.get('reported') and check.get('collected',0)>0,'Full collection/JUnit verification failed')
    require(all(check.get(k)==[] for k in ('missing','extra','duplicates','failures','skipped','malformed','group_mismatches')),'Full regressions incomplete')
    frontend=[p for p in summary['processes'] if p.get('label')=='frontend']
    require(len(frontend)==1 and frontend[0].get('exit_code')==0,'Final frontend build missing')
    files=after['files']
    listing=subprocess.run(['git','-C',str(ROOT),'ls-files','--cached','--others','--exclude-standard','-z'],check=True,capture_output=True,timeout=30).stdout
    actual_names=set()
    for raw in listing.split(b'\0'):
        if not raw: continue
        path=Path(os.fsdecode(raw))
        if path.parts[0] in {'backend','frontend-vue','factory_prompts'} and not path.name.startswith('.env') and not set(path.parts)&{'node_modules','storage','__pycache__','dist','.vite'}:
            actual_names.add(path.as_posix())
    require(actual_names==set(files),'Source file set differs from passed full regression')
    for name,wanted in files.items():
        path=(ROOT/name).resolve()
        require(path.is_relative_to(ROOT) and path.name!='AI_Video_Factory_Technical_Notes_CN.md' and not path.name.startswith('.env'),'Unexpected source evidence path')
        require(path.is_file() and sha(path)==wanted,'Source differs from passed full: '+name)
    return {'head':expected,'branch':branch,'full_summary_hash':sha(full/'summary.json'),
            'files':files,'entry_files':{p.name:sha(p) for p in HERE.glob('gate6_*.py')}}


def prepare(work,label,freeze):
    from gate6_meter import MARKER
    work=Path(work).resolve()
    require(work!=TEMP and work.is_relative_to(TEMP) and work.name.startswith('cinecrew-v13-gate6-') and not work.is_relative_to(ROOT),'Dedicated unique Gate6 TEMP directory required')
    marker=work/'v13-round.json'
    if marker.exists():
        require(read(marker)==MARKER and read(work/'source-freeze.json')==freeze,'Round source/marker mismatch')
    else:
        require(label==LABELS[0] and (not work.exists() or not any(work.iterdir())),'New round must start with 01-c3-1 in empty work')
        work.mkdir(parents=True,exist_ok=True); exclusive_json(marker,MARKER); exclusive_json(work/'source-freeze.json',freeze)
    for previous in LABELS[:LABELS.index(label)]:
        record=read(work/(previous+'.finished.json'))
        require(record.get('runner_completed') is True and record.get('safety_ok') is True,'Previous scheduled phase has unresolved safety/execution failure')
    require(not (work/(label+'.started.json')).exists(),'Scheduled phase is once-only; preserve failure and inspect, never reset')
    return work


@contextmanager
def once(work,label,freeze):
    lock=work/'.v13-active.lock'
    exclusive_json(lock,{'pid':os.getpid(),'label':label})
    try:
        exclusive_json(work/(label+'.started.json'),{'pid':os.getpid(),'label':label,'started':time.time(),'head':freeze['head'],'entry_files':freeze['entry_files']})
        yield
    finally: lock.unlink()


def counts_ok(meter,*,identity=False):
    counts=meter.snapshot()
    require(counts['call_limit']==120 and counts['real_calls']<=120,'Shared call limit changed')
    require(all(counts[k]==0 for k in ('real_video_calls','blocked_media_attempts','blocked_network_attempts','unknown_or_reserved_calls','usage_missing_calls')),'Safety counters are not clean')
    if identity:
        require(counts['phase']=='complete' and counts['reserved_image_units']<=6 and counts['real_images_returned']==4 and counts['real_images_downloaded']==4,'Four-image phase incomplete')
    else:
        require(counts['real_image_calls']==0 and counts['phase']=='planning','Planning dispatched media or changed phase')
    return counts


def bootstrap(work,label,manifest=None):
    global ACTIVE_TRANSPORT
    require(bool(os.environ.get('DASHSCOPE_API_KEY')),'Inject the existing approved provider key into process environment; this entry never reads dotenv')
    from gate6_process import install_guard
    ffmpeg=ROOT/'.venv/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe'
    os.environ.update(EVAL_WORK_DIR=str(work),EVAL_MAX_REAL_CALLS='120',EVAL_IMAGE_CAP='0',EVAL_MOCK_MEDIA='1',
        PYTHON_DOTENV_DISABLED='1',FLASK_SKIP_DOTENV='1',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',
        DASHSCOPE_API_BASE_URL='https://dashscope.aliyuncs.com/api/v1',DASHSCOPE_OPENAI_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1',
        DEEPSEEK_API_KEY='',OPENAI_API_KEY='',QWEN_API_KEY='',FFMPEG_BINARY=str(ffmpeg))
    os.environ.pop('EVAL_V2',None)
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'): os.environ.pop(key,None)
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(SCRIPTS)); sys.path.insert(0,str(ROOT/'backend'))
    install_guard(ROOT,work,ffmpeg,lambda:ACTIVE_TRANSPORT)
    import safety
    def no_credentials(_path,wanted):
        require(not wanted,'Entry cannot read credentials from dotenv'); return {}
    safety._credential_lines=no_credentials
    def install(work):
        global ACTIVE_TRANSPORT
        import requests
        from gate6_meter import Gate6Meter
        from gate6_transport import ImageTransport
        from gate6_selective import capture_originals,SelectiveMedia
        from gate6_budget import ImageBudget
        originals=capture_originals(); raw_send=requests.Session.send
        meter=Gate6Meter(work).install()
        budget=ImageBudget(meter.path,manifest) if manifest else None
        ACTIVE_TRANSPORT=ImageTransport(meter,budget,raw_send,requests.Session.send).install()
        if manifest:
            controller=SelectiveMedia(budget,ACTIVE_TRANSPORT,originals,work/'mock-media.jsonl')
            controller.install(); meter.image_budget=budget
        else:
            from mock_media import install as install_mock
            install_mock(work/'mock-media.jsonl')
        original_label=meter.set_label
        def set_label(value):
            value=str(value); run=value.split(':',1)[1] if ':' in value else None
            if run: require(bool(re.fullmatch(r'agent_[a-z0-9]+',run)),'Unexpected audit Run label')
            original_label(label+(':'+run if run else ''))
        meter.set_label=set_label
        meter.set_label(label)
        return meter
    safety.install_guards=install
    import eval_v3
    require(eval_v3.METER is ACTIVE_TRANSPORT.meter,'Legacy guards replaced the selected meter')
    return eval_v3


def archive_planning(evaluation,label,case):
    from langgraph.checkpoint.sqlite import SqliteSaver
    from app.agent.graph import build_graph
    from app.agent.graph_v2 import build_graph as build_graph_v2
    from app.agent.worker import AgentWorker
    evaluation.CASES['c7_complete_story']=COMPLETE_STORY
    with evaluation.app.app_context():
        initialized=evaluation.app.test_cli_runner().invoke(args=['init-db'])
        require(initialized.exit_code==0,'Isolated database initialization failed')
        evaluation.app.config.update(FAILURE_AGENT_ENABLED=False,AGENT_WORKER_ACTIVE=True)
        with SqliteSaver.from_conn_string(os.environ['AGENT_CHECKPOINT_PATH']) as saver:
            worker=AgentWorker(build_graph(saver),build_graph_v2(saver),v3_saver=saver)
            result=evaluation.run_case(evaluation.app.test_client(),worker,case,evaluation.CASES[case])
        result.update(audit_label=label+':'+result['run_id'],phase='planning',round='V13-Gate6',safety=evaluation.METER.snapshot())
        path=evaluation.HERE/f"result_{case}_{result['run_id']}.json"
        exclusive_json(path,result)
        from app.models import AgentDelegation,AgentWorkspaceItem,ToolInvocation
        private={'run_id':result['run_id'],'audit_label':result['audit_label'],'archive_sha256':sha(path),
            'delegations':[row.to_dict() for row in AgentDelegation.query.filter_by(run_id=result['run_id']).order_by(AgentDelegation.id)],
            'workspace':[row.to_dict() for row in AgentWorkspaceItem.query.filter_by(run_id=result['run_id']).order_by(AgentWorkspaceItem.id)],
            'ledger':[row.to_dict() for row in ToolInvocation.query.filter_by(budget_scope=result['run_id']).order_by(ToolInvocation.id)]}
        exclusive_json(path.with_name(path.stem+'_private_profile.json'),private)
        return result,path



def wait_selected(harness,selected_ids,*,clock=time.monotonic,sleep=time.sleep):
    deadline=clock()+1200
    while clock()<deadline:
        view=harness.observe()
        tasks=harness.tasks()
        if selected_ids<=tasks.keys() and all(tasks[node]['status']=='success' for node in selected_ids):
            return view
        require(view['status'] not in {'attention','failed','cancelled','awaiting_input','success'},'Selected images stopped before completion')
        if not view.get('action_pending'): harness.gates(view)
        harness.advance(); sleep(0.15)
    raise RuntimeError('Selected image execution exceeded 1200 seconds; reserved attempts are retained')


def execute_identity(evaluation,manifest,label):
    from langgraph.checkpoint.sqlite import SqliteSaver
    from app.agent.graph import build_graph
    from app.agent.graph_v2 import build_graph as build_graph_v2
    from app.agent.worker import AgentWorker
    from app.agent import plan_versions
    from app.models import AgentRun,AgentDelegation,ToolInvocation
    from gate6_selective import selected_plan
    from gate6_identity import invoke_identity
    from hybrid import Harness
    result={'phase':'identity_sample','round':'V13-Gate6','audit_label':label+':'+manifest['run_id'],'run_id':manifest['run_id'],'manifest':manifest,'started':time.time()}
    path=evaluation.HERE/f"identity_{label}_{manifest['run_id']}.json"
    require(not path.exists(),'Identity archive already exists')
    with evaluation.app.app_context():
        run=AgentRun.query.filter_by(run_id=manifest['run_id']).one()
        version=plan_versions.current_version(run)
        require(run.status=='awaiting_plan_review' and version.version==manifest['plan_version'] and plan_versions.inputs_hash(version.plan)==manifest['plan_hash'],'Reviewed selected Plan changed')
        selected_plan(version.plan,manifest)
        from gate6_views import preflight_budget
        result['budget_preflight']=preflight_budget(run,version.plan,manifest)
        exclusive_json(evaluation.WORK/'identity-budget-preflight.json',result['budget_preflight'])
        require(result['budget_preflight']['can_cover_selected_and_vision'],'Same-Run budget cannot cover four approved images plus bounded identity input; stop before first image POST')
        require(result['budget_preflight']['can_cover_full_plan_and_vision'] is True,'Same-Run budget cannot prove coverage of the full approved Plan plus identity input; stop before first image POST')
        require(all(row.status=='completed' for row in AgentDelegation.query.filter_by(run_id=run.run_id)),'Planning is still active')
        frozen_delegations=[row.to_dict() for row in AgentDelegation.query.filter_by(run_id=run.run_id).order_by(AgentDelegation.id)]
        initial_calls=evaluation.METER.snapshot()['real_calls']
        evaluation.METER.begin_execution()
        evaluation.app.config.update(FAILURE_AGENT_ENABLED=False,AGENT_WORKER_ACTIVE=True)
        failure=None
        try:
            with SqliteSaver.from_conn_string(os.environ['AGENT_CHECKPOINT_PATH']) as saver:
                worker=AgentWorker(build_graph(saver),build_graph_v2(saver),v3_saver=saver)
                harness=Harness(evaluation,worker,label,run.run_id)
                # Use the established actions/drive methods; legacy close assumes
                # zero real images and is intentionally not used for this sample.
                harness.path=evaluation.HERE/f"gate6_actions_{run.run_id}.json"
                require(not harness.path.exists(),'Identity actions already archived')
                harness.approve_plan(repair_credits=0)
                wait_selected(harness,{node['node_id'] for node in manifest['nodes']})
                require(evaluation.METER.snapshot()['real_calls']==initial_calls,'Deterministic execution made an LLM request')
                evaluation.METER.set_label(label+':'+run.run_id)
                result['identity']=invoke_identity(evaluation.METER.image_budget,evaluation.METER)
                require(evaluation.METER.snapshot()['real_calls']==initial_calls+1,'Identity review was not exactly one physical request')
                view=harness.drive()
                require(view['status']=='awaiting_result_review','Deterministic Mock delivery did not reach result review')
                require(evaluation.METER.snapshot()['real_calls']==initial_calls+1,'Mock continuation made another LLM request')
                require([row.to_dict() for row in AgentDelegation.query.filter_by(run_id=run.run_id).order_by(AgentDelegation.id)]==frozen_delegations,'Deterministic execution changed planning delegations')
                result.update(review_b=view,tasks=harness.tasks(),actions=harness.result['actions'],status='passed')
        except BaseException as error:
            failure=error; result.update(status='failed',failure={'type':type(error).__name__,'message':str(error)})
        finally:
            result.update(meter=evaluation.METER.snapshot(),images=evaluation.METER.image_budget.snapshot(),finished=time.time())
            provider_path=evaluation.WORK/'identity-provider-response.json'
            if provider_path.is_file():
                result.update(provider_response_path=str(provider_path),provider_response=read(provider_path))
            try:
                from gate6_identity import receipt_images
                result['owned_images']=receipt_images(evaluation.METER.image_budget)[2]
            except Exception:
                result['owned_images_unavailable']=True
            result['ledger']=[{'invocation_id':row.invocation_id,'tool':row.tool_name,'status':row.status,'credits':row.estimated_cost,'usage':(row.output_payload or {}).get('usage')}
                for row in ToolInvocation.query.filter_by(budget_scope=run.run_id).order_by(ToolInvocation.id)]
            exclusive_json(path,result)
        if failure: raise failure
        return result,path


def require_selected_archive(records,run_id):
    matches=[r for r in records if r.get('run_id')==run_id]
    require(len(matches)==1,'Selected Run must have exactly one fixed planning archive')
    record=matches[0]
    label=record.get('audit_label','').split(':',1)[0]
    require(label in SAMPLES and record.get('audit_label')==label+':'+run_id
        and record.get('case')==SAMPLES[label] and record.get('phase')=='planning'
        and record.get('round')=='V13-Gate6' and record.get('status')=='awaiting_plan_review',
        'Select an exact fixed scheduled Plan that reached review; external Runs are forbidden')
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',required=True); parser.add_argument('--label',choices=LABELS,required=True)
    parser.add_argument('--expected-commit',required=True); parser.add_argument('--full-evidence',required=True)
    parser.add_argument('--manifest'); parser.add_argument('--approve-manifest-sha256'); parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if not args.execute: parser.error('No Gate started. Add --execute only after the completed full regression and case/Plan review.')
    sys.path.insert(0,str(SCRIPTS)); sys.path.insert(0,str(HERE))
    freeze=source(args.expected_commit,args.full_evidence)
    work=prepare(args.work,args.label,freeze)
    manifest=None
    if args.label=='04-identity':
        require(args.manifest and not str(args.manifest).startswith(('\\\\','//','\\/','/\\')),'Local selection manifest required')
        selected_path=Path(args.manifest).resolve()
        require(selected_path.is_relative_to(work) and selected_path.name=='selection-manifest.json','Selection manifest must be the exact local round file')
        require(args.approve_manifest_sha256==sha(selected_path),'Explicit exact reviewed manifest hash required')
        from gate6_budget import checked_manifest
        manifest=checked_manifest(read(args.manifest))
        initial=[read(path) for path in (work/'results').glob('result_*_agent_*.json') if not path.name.endswith('_private_profile.json')]
        require_selected_archive(initial,manifest['run_id'])
    else: require(not args.manifest and not args.approve_manifest_sha256,'Planning cannot accept selection/model overrides')
    with once(work,args.label,freeze):
        evaluation=None; completed=False; safe=False; output=None; error=None
        try:
            evaluation=bootstrap(work,args.label,manifest)
            if manifest: output,path=execute_identity(evaluation,manifest,args.label)
            else: output,path=archive_planning(evaluation,args.label,SAMPLES[args.label])
            completed=True
            counts=counts_ok(evaluation.METER,identity=bool(manifest))
            from scripts.v3_eval.eval_statistics import summarize
            statistics=summarize(work,'V13')
            require(statistics['safety']['status']!='failed' and statistics['data_quality_status']=='passed'
                and statistics['reconciliation']['status']=='passed','Stopped-sample statistics/reconciliation failed')
            exclusive_json(work/(args.label+'.statistics.json'),statistics)
            safe=True
            require(source(args.expected_commit,args.full_evidence)==freeze,'Source changed during sample')
            print(json.dumps({'label':args.label,'archive':str(path),'status':output.get('status'),'safety':counts},ensure_ascii=False),flush=True)
        except BaseException as failure:
            safe=False
            error={'type':type(failure).__name__,'message':str(failure)}
            raise
        finally:
            exclusive_json(work/(args.label+'.finished.json'),{'runner_completed':completed,'safety_ok':safe,'error':error,
                'meter':evaluation.METER.snapshot() if evaluation else None,'finished':time.time()})
    return 0


if __name__=='__main__': raise SystemExit(main())
