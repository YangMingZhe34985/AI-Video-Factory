"""Pure Gate6 boundary tests; no app, provider credentials or HTTP dispatch."""
import base64
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import sys
_eval_scripts=Path(__file__).resolve().parents[1]/'scripts/v3_eval'
if _eval_scripts.is_dir(): sys.path.insert(0,str(_eval_scripts))

from gate6_budget import ImageBudget, ImageGuardError, digest
from gate6_meter import Gate6Meter
from gate6_selective import selected_plan, managed_file
from gate6_transport import ImageTransport, ASYNC_URL, TASK_PREFIX, numeric_usage, output_urls, valid_download_url, url_hash
from safety import EvaluationSafetyError, TEXT_MODEL, VISION_MODEL, CHAT_URL


def manifest():
    return {'run_id':'agent_test','plan_version':1,'plan_hash':'f'*64,'nodes':[
      {'node_id':name,'kind':'cast' if index<2 else 'keyframe','model':'qwen-image-3.0','node_hash':str(index)*64,'n':1}
      for index,name in enumerate(('cast_a','cast_b','kf_a','kf_b'))]}


def response(data,status=200):
    import requests
    value=requests.Response(); value.status_code=status
    value._content=json.dumps(data).encode(); value._content_consumed=True
    return value


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='cinecrew-gate6-pure-')
        self.work=Path(self.tmp.name)
        self.meter=Gate6Meter(self.work)
        self.budget=ImageBudget(self.meter.path,manifest())
        self.proof={'node_id':'cast_a','model':'qwen-image-3.0','node_hash':'0'*64,
           'attempt_key':'agent_test:1:cast_a:1','inputs_hash':'a'*64,'job_id':'job_a','invocation_id':'inv_a',
           'endpoint':ASYNC_URL,'reference_hashes':[]}
        self.payload={'model':'qwen-image-3.0','input':{'messages':[{'role':'user','content':[{'text':'test'}]}]},'parameters':{'n':1}}
        self.proof['payload_hash']=digest(self.payload)
    def tearDown(self):
        self.meter.uninstall(); self.tmp.cleanup()
    def request(self,url=ASYNC_URL,method='POST',payload=None):
        import requests
        return requests.Request(method,url,json=self.payload if payload is None and method=='POST' else payload).prepare()
    def transport(self,fn):
        return ImageTransport(self.meter,self.budget,fn,lambda *a,**kw:None)
    def test_bind_and_download_evidence(self):
        rid=self.budget.reserve(attempt_key='first',node_id='cast_a',model='qwen-image-3.0',node_hash='0'*64,request_hash='a'*64,n=1)
        self.budget.mark_transport(rid,inputs_hash='b'*64,job_id='job_a',invocation_id='inv_a')
        self.budget.bind_task(rid,'task_a')
        self.budget.finish(rid,status='success',actual_images=1,response_hash='c'*64,output_url_hash='d'*64)
        self.budget.record_download(rid,url_hash='d'*64,sha256_value='e'*64,byte_count=100)
        self.assertEqual(self.budget.snapshot()['downloaded_images'],1)
        with self.assertRaises(ImageGuardError): self.budget.record_download(rid,url_hash='d'*64,sha256_value='f'*64,byte_count=100)
    def test_mark_transport_once(self):
        rid=self.budget.reserve(attempt_key='first',node_id='cast_a',model='qwen-image-3.0',node_hash='0'*64,request_hash='a'*64,n=1)
        self.budget.mark_transport(rid,inputs_hash='b'*64,job_id='job_a',invocation_id='inv_a')
        with self.assertRaises(ImageGuardError): self.budget.mark_transport(rid,inputs_hash='b'*64,job_id='job_a',invocation_id='inv_a')
    def test_planning_reserves_final_slot_without_lowering_limit(self):
        for index in range(119): self.meter._reserve(TEXT_MODEL,str(index))
        with self.assertRaises(EvaluationSafetyError): self.meter._reserve(TEXT_MODEL,'120')
        self.assertEqual(self.meter.snapshot()['call_limit'],120)
        self.assertEqual(self.meter.snapshot()['real_calls'],119)
    def test_execution_phase_forbids_llm(self):
        self.meter.begin_execution()
        for model in (TEXT_MODEL,VISION_MODEL):
            with self.assertRaises(EvaluationSafetyError): self.meter._reserve(model,'new')
        self.assertEqual(self.meter.snapshot()['real_calls'],0)
    def test_identity_needs_four_real_downloads(self):
        self.meter.begin_execution()
        with self.assertRaises(EvaluationSafetyError): self.meter.begin_identity(['a'*64,'b'*64,'c'*64,'d'*64])
    def identity_ready(self):
        self.meter.begin_execution(); hashes=[]
        for index,node in enumerate(manifest()['nodes']):
            rid=self.budget.reserve(attempt_key=node['node_id'],node_id=node['node_id'],model=node['model'],node_hash=node['node_hash'],request_hash='a'*64,n=1)
            self.budget.mark_transport(rid,inputs_hash='b'*64,job_id='job_'+str(index),invocation_id='inv_'+str(index))
            raw=f'image {index}'.encode(); h=sha256(raw).hexdigest(); hashes.append(h)
            self.budget.finish(rid,status='success',actual_images=1,response_hash='c'*64,output_url_hash='d'*64)
            self.budget.record_download(rid,url_hash='d'*64,sha256_value=h,byte_count=len(raw))
        from gate6_views import TRANSFORM
        records=[]
        for index,h in enumerate(hashes):
            path=self.work/(str(index)+'.png'); raw=f'image {index}'.encode(); path.write_bytes(raw)
            records.append({'path':str(path),'source_path':str(path),'sha256':h,'source_sha256':h,'bytes':len(raw),'transform':TRANSFORM})
        self.meter.bind_identity_inputs(records)
        self.meter.begin_identity(hashes)
        return hashes
    def test_identity_exact_four_byte_payloads(self):
        self.identity_ready()
        payload={'model':VISION_MODEL,'messages':[{'role':'user','content':[
          {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(f'image {i}'.encode()).decode()}} for i in range(4)]}]}
        self.meter.check_identity_payload(payload)
        payload['messages'][0]['content'].reverse()
        with self.assertRaises(EvaluationSafetyError): self.meter.check_identity_payload(payload)
    def test_identity_one_physical_reservation(self):
        self.identity_ready(); self.meter._reserve(VISION_MODEL,'vision')
        with self.assertRaises(EvaluationSafetyError): self.meter._reserve(VISION_MODEL,'vision-again')
        self.assertEqual(self.meter.snapshot()['real_calls'],1)
    def test_unknown_call_is_not_reposted(self):
        self.meter._reserve(TEXT_MODEL,'same')
        with self.assertRaises(EvaluationSafetyError): self.meter._reserve(TEXT_MODEL,'same')
    def test_retry_and_redirect_disabled_before_raw_transport(self):
        import requests
        from urllib3.util.retry import Retry
        session=requests.Session()
        for adapter in session.adapters.values(): adapter.max_retries=Retry(total=2)
        calls=[]
        def raw(s,r,**kw):
            calls.append(1); self.assertIs(kw['allow_redirects'],False)
            self.assertTrue(all(a.max_retries.total==0 and a.max_retries.connect==0 and a.max_retries.read==0 and a.max_retries.status==0 for a in s.adapters.values()))
            return response({'output':{'task_id':'task_one'}})
        transport=self.transport(raw)
        with transport.permit(self.proof): transport.send(session,self.request())
        self.assertEqual(calls,[1]); self.assertEqual(self.budget.snapshot()['image_post_attempts'],1)
    def test_failed_post_consumes_slot(self):
        import requests
        def fail(*a,**kw): raise TimeoutError('stub')
        transport=self.transport(fail)
        with transport.permit(self.proof),self.assertRaises(TimeoutError): transport.send(requests.Session(),self.request())
        self.assertEqual(self.budget.snapshot()['requested_image_units'],1)
        self.assertEqual(self.budget.snapshot()['rows'][0]['status'],'unknown')
        with transport.permit(self.proof),self.assertRaises(ImageGuardError): transport.send(requests.Session(),self.request())
    def test_overproduction_preserves_response_and_stops(self):
        import requests
        payload={'output':{'results':[{'url':'https://one.oss-cn-beijing.aliyuncs.com/1.png'},{'url':'https://one.oss-cn-beijing.aliyuncs.com/2.png'}]}}
        self.proof['endpoint']='https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation'
        transport=self.transport(lambda *a,**k:response(payload))
        with transport.permit(self.proof),self.assertRaises(ImageGuardError):
            transport.send(requests.Session(),self.request(self.proof['endpoint']))
        self.assertEqual(self.budget.snapshot()['actual_images'],2)
        with self.budget.connect() as db: event=dict(db.execute('SELECT * FROM gate6_http_events').fetchone())
        self.assertEqual(event['http_status'],200); self.assertIsNotNone(event['response_hash'])
    def test_no_permit_or_upload_endpoint(self):
        import requests
        transport=self.transport(lambda *a,**kw:self.fail('Network reached'))
        with self.assertRaises(EvaluationSafetyError): transport.send(requests.Session(),self.request())
        with transport.permit(self.proof),self.assertRaises(EvaluationSafetyError): transport.send(requests.Session(),self.request('https://dashscope.aliyuncs.com/api/v1/uploads','GET'))
    def test_references_must_be_exact_data_bytes(self):
        transport=self.transport(None)
        payload=json.loads(json.dumps(self.payload)); payload['input']['messages'][0]['content'].append({'image':'https://example.com/a.png'})
        self.proof['payload_hash']=digest(payload)
        with self.assertRaises(EvaluationSafetyError): transport._validate_payload(self.proof,payload)
    def test_result_host_credential_redirect_targets_rejected(self):
        good='https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/path.png?signature=demo'
        self.assertEqual(valid_download_url(good),good)
        for value in ('http://'+good[8:],good.replace('aliyuncs.com','aliyuncs.com.evil'),good.replace('https://','https://user:pw@'), 'https://127.0.0.1/a','https://169.254.169.254/a',good+'#x'):
            with self.subTest(value=value),self.assertRaises(EvaluationSafetyError): valid_download_url(value)
    def test_one_lowlevel_method_path_token(self):
        import requests
        from urllib3.connection import HTTPConnection,HTTPSConnection
        with patch.object(HTTPConnection,'request',lambda *a,**k:None),patch.object(HTTPSConnection,'request',lambda *a,**k:None):
            transport=self.transport(None).install(); req=self.request()
            conn=SimpleNamespace(host='dashscope.aliyuncs.com',port=443)
            with transport._destination(req):
                HTTPConnection.request(conn,'POST','/api/v1/services/aigc/image-generation/generation')
                with self.assertRaises(EvaluationSafetyError): HTTPConnection.request(conn,'POST','/api/v1/services/aigc/image-generation/generation')
            self.meter.uninstall()
    def test_wrong_lowlevel_path_rejected(self):
        from urllib3.connection import HTTPConnection,HTTPSConnection
        with patch.object(HTTPConnection,'request',lambda *a,**k:None),patch.object(HTTPSConnection,'request',lambda *a,**k:None):
            transport=self.transport(None).install()
            with transport._destination(self.request()),self.assertRaises(EvaluationSafetyError):
                HTTPConnection.request(SimpleNamespace(host='dashscope.aliyuncs.com',port=443),'POST','/api/v1/other')
            self.meter.uninstall()
    def test_only_numeric_usage_is_saved(self):
        self.assertEqual(numeric_usage({'usage':{'image_count':1,'credentials':'secret','bad':float('inf'),'flag':True}}),{'image_count':1})
    def test_url_shapes_deduplicated(self):
        self.assertEqual(output_urls({'output':{'results':[{'url':'one'}],'choices':[{'message':{'content':[{'image':'one'},{'image':'two'}]}}]}}),['one','two'])
    def test_managed_file_does_not_resolve_unc(self):
        for path in ('\\\\server\\share\\a.png','//server/share/a.png','https://example.com/a.png','C:relative.png','file:///C:/a.png','../outside.png'):
            with self.subTest(path=path),self.assertRaises(ImageGuardError): managed_file(path,self.work,must_exist=False)
    def test_managed_relative_file(self):
        target=self.work/'jobs'/'image.png'; target.parent.mkdir(); target.write_bytes(b'demo')
        self.assertEqual(managed_file('jobs/image.png',self.work),target.resolve())


    def test_https_inherited_method_consumes_one_token(self):
        from urllib3.connection import HTTPConnection,HTTPSConnection
        calls=[]
        with patch.object(HTTPConnection,'request',lambda *a,**k:calls.append(1)):
            self.assertNotIn('request',HTTPSConnection.__dict__)
            transport=self.transport(None).install()
            connection=SimpleNamespace(host='dashscope.aliyuncs.com',port=443)
            with transport._destination(self.request()):
                HTTPSConnection.request(connection,'POST','/api/v1/services/aigc/image-generation/generation')
                self.assertEqual(calls,[1])
                with self.assertRaises(EvaluationSafetyError): HTTPSConnection.request(connection,'POST','/api/v1/services/aigc/image-generation/generation')
            self.meter.uninstall()
    def test_nonjson_submit_preserves_http_evidence(self):
        import requests
        for code in (200,502):
            with self.subTest(code=code):
                # A fresh selected node keeps this test independent of the first unknown latch.
                local=tempfile.TemporaryDirectory(prefix='cinecrew-gate6-nonjson-')
                try:
                    meter=Gate6Meter(local.name); budget=ImageBudget(meter.path,manifest())
                    value=requests.Response(); value.status_code=code; value._content=b'not-json'; value._content_consumed=True
                    transport=ImageTransport(meter,budget,lambda *a,**k:value,None)
                    with transport.permit(self.proof),self.assertRaises(ValueError): transport.send(requests.Session(),self.request())
                    with budget.connect() as db: row=dict(db.execute('SELECT * FROM gate6_http_events').fetchone())
                    self.assertEqual(row['http_status'],code); self.assertEqual(row['response_hash'],sha256(b'not-json').hexdigest())
                    self.assertEqual(budget.snapshot()['rows'][0]['status'],'unknown')
                finally: local.cleanup()
    def test_unknown_provider_task_stops_round(self):
        import requests
        replies=iter([response({'output':{'task_id':'task_one'}}),response({'output':{'task_status':'UNKNOWN'}})])
        transport=self.transport(lambda *a,**k:next(replies))
        with transport.permit(self.proof):
            transport.send(requests.Session(),self.request())
            with self.assertRaises(ImageGuardError): transport.send(requests.Session(),self.request(TASK_PREFIX+'task_one','GET'))
        self.assertEqual(self.budget.snapshot()['rows'][0]['status'],'unknown')
    def test_readonly_sqlite_uris_are_exact(self):
        from gate6_process import checked_sqlite
        for name in ('eval.db','real_call_audit.sqlite'):
            checked_sqlite((self.work/name).as_uri()+'?mode=ro',self.work)
        for value in ((self.work/'other.db').as_uri()+'?mode=ro',(self.work/'eval.db').as_uri()+'?mode=rw',
                      (self.work/'eval.db').as_uri()+'?mode=ro&cache=shared','file://server/share/eval.db?mode=ro',r'\\server\share\eval.db','C:eval.db'):
            with self.subTest(value=value),self.assertRaises(ImageGuardError): checked_sqlite(value,self.work)
    def test_fixed_display_preserves_original_and_aspect(self):
        from PIL import Image
        from gate6_views import make_view,TRANSFORM,maximum_credit_reserve
        source=self.work/'original.png'; Image.new('RGBA',(2000,1000),(20,80,130,128)).save(source)
        original=source.read_bytes(); view=make_view(source,self.work/'view.jpg')
        self.assertEqual(source.read_bytes(),original); self.assertEqual(view['size'],[1024,512])
        self.assertEqual(view['source_sha256'],sha256(original).hexdigest())
        self.assertLess(view['bytes'],512*1024); self.assertFalse(view['transform']['crop'])
        with Image.open(view['path']) as image: self.assertEqual(image.mode,'RGB')
        self.assertLess(maximum_credit_reserve(.02),60)
    def test_display_never_overwrites_existing_file(self):
        from PIL import Image
        from gate6_views import make_view
        source=self.work/'original.png'; target=self.work/'view.jpg'
        Image.new('RGB',(64,64)).save(source); target.write_bytes(b'old')
        with self.assertRaises(FileExistsError): make_view(source,target)
        self.assertEqual(target.read_bytes(),b'old')


    def test_malformed_identity_choices_always_preserve_raw_body(self):
        self.identity_ready()
        data={'id':'vision_stub','choices':{'x':{}},'usage':{'prompt_tokens':1,'completion_tokens':1}}
        reply=response(data)
        transport=ImageTransport(self.meter,self.budget,None,lambda *a,**k:reply)
        import requests
        transport.send(requests.Session(),self.request(CHAT_URL))
        saved=json.loads((self.work/'identity-provider-response.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['raw_response'],data)
        self.assertEqual(saved['sha256'],sha256(reply.content).hexdigest())
        self.assertEqual(base64.b64decode(saved['raw_body_base64']),reply.content)
        self.assertIsNone(saved['content'])


    def test_selected_wait_allows_slow_provider_without_reposting(self):
        from gate6_entry import wait_selected
        clock=[0]; calls=[]
        class Harness:
            def observe(self): return {'status':'executing'}
            def tasks(self): return {'kf':{'status':'success' if clock[0]>=180 else 'running'}}
            def gates(self,_view): pass
            def advance(self): calls.append('poll')
        view=wait_selected(Harness(),{'kf'},clock=lambda:clock[0],sleep=lambda _s:clock.__setitem__(0,clock[0]+30))
        self.assertEqual(view['status'],'executing'); self.assertEqual(len(calls),6)
    def test_selected_wait_stops_at_wallclock_bound(self):
        from gate6_entry import wait_selected
        clock=[0]
        harness=SimpleNamespace(observe=lambda:{'status':'executing'},tasks=lambda:{'kf':{'status':'running'}},gates=lambda _v:None,advance=lambda:None)
        with self.assertRaisesRegex(RuntimeError,'1200 seconds'):
            wait_selected(harness,{'kf'},clock=lambda:clock[0],sleep=lambda _s:clock.__setitem__(0,clock[0]+60))
        self.assertEqual(clock[0],1200)


if __name__=='__main__': unittest.main(verbosity=2)
