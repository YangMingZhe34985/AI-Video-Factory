"""Gate6 selective image HTTP boundary (no configuration or execution on import).

Call install only after the existing chat guard and provide the original raw
Session.send captured before that guard. No OSS uploads are authorized here.
"""
from contextlib import contextmanager
from hashlib import sha256
import base64
import ipaddress
import json
import math
import os
import re
import threading
from urllib.parse import urlsplit

from gate6_budget import canonical, digest, ImageGuardError
from safety import CHAT_URL, EvaluationSafetyError

ASYNC_URL='https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation'
SYNC_URL='https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation'
TASK_PREFIX='https://dashscope.aliyuncs.com/api/v1/tasks/'
OSS_HOST=re.compile(r'[a-z0-9][a-z0-9-]{1,100}\.oss-cn-[a-z0-9-]+\.aliyuncs\.com')
MAX_DOWNLOAD=20*1024*1024


def url_hash(value):
    return sha256(value.encode('utf-8')).hexdigest()


def output_urls(data):
    output=data.get('output') or {}
    values=[]
    for item in output.get('results') or []:
        if isinstance(item,dict):
            value=item.get('url') or item.get('image_url') or item.get('image')
            if isinstance(value,str) and value: values.append(value)
    for choice in output.get('choices') or []:
        for block in ((choice.get('message') or {}).get('content') or []) if isinstance(choice,dict) else []:
            if isinstance(block,dict):
                value=block.get('image') or block.get('url')
                if isinstance(value,str) and value: values.append(value)
    return list(dict.fromkeys(values))


def valid_download_url(value):
    if not isinstance(value,str): raise EvaluationSafetyError('Result URL must be a string')
    p=urlsplit(value)
    try: port=p.port
    except ValueError as error: raise EvaluationSafetyError('Malformed result port') from error
    if (p.scheme!='https' or p.username or p.password or port not in (None,443) or p.fragment
            or not p.hostname or not OSS_HOST.fullmatch(p.hostname.lower()) or not p.path or '\\' in value
            or any(ord(c)<32 for c in value)):
        raise EvaluationSafetyError('Unreviewed result host or unsafe result URL')
    return value


def numeric_usage(data):
    usage=data.get('usage')
    if not isinstance(usage,dict): return {}
    return {k:v for k,v in usage.items() if isinstance(k,str) and re.fullmatch(r'[A-Za-z_]{1,50}',k)
            and type(v) in (int,float) and math.isfinite(v) and v>=0}


class ImageTransport:
    def __init__(self,meter,budget,raw_send,chat_send):
        self.meter,self.budget,self.raw_send,self.chat_send=meter,budget,raw_send,chat_send
        self.local=threading.local()

    @contextmanager
    def permit(self,proof):
        if getattr(self.local,'proof',None) is not None:
            raise EvaluationSafetyError('Nested image dispatch permission')
        self.local.proof=dict(proof)
        try: yield
        finally: self.local.proof=None

    def _proof(self):
        proof=getattr(self.local,'proof',None)
        if not proof: self.meter._block('media','No selected approved image dispatch permit')
        node=self.budget.nodes.get(proof.get('node_id'))
        if not node or proof.get('node_hash')!=node['node_hash'] or proof.get('model')!=node['model']:
            self.meter._block('media','Selected approved node proof changed')
        return proof

    @contextmanager
    def _destination(self,request):
        if getattr(self.local,'destination',None) is not None:
            self.meter._block('network','Nested provider transport')
        p=urlsplit(request.url)
        self.local.destination=(p.hostname.lower(),443)
        self.local.request_token={'method':request.method,'path':p.path+('?' + p.query if p.query else ''),'used':False}
        self.local.ips=set()
        try: yield
        finally:
            self.local.destination=None
            self.local.request_token=None
            self.local.ips=set()

    @contextmanager
    def _exchange(self,session,request,kwargs):
        from urllib3.util.retry import Retry
        if kwargs.get('proxies') and any(kwargs['proxies'].values()):
            self.meter._block('network','Gate6 prohibits provider proxies')
        if kwargs.get('verify') is False:
            self.meter._block('network','Gate6 requires verified TLS')
        for adapter in session.adapters.values():
            adapter.max_retries=Retry(total=0,connect=0,read=0,redirect=0,status=0,other=0)
        kwargs['allow_redirects']=False
        with self._destination(request):
            self.meter._transport_context.allowed=True
            try: yield self.raw_send(session,request,**kwargs)
            finally: self.meter._transport_context.allowed=False

    def _event(self,kind,reservation,request):
        import time
        with self.budget.connect() as db:
            cur=db.execute('INSERT INTO gate6_http_events(kind,reservation_id,url_hash,method,started,status) VALUES(?,?,?,?,?,?)',
                (kind,reservation,url_hash(request.url),request.method,time.time(),'reserved'))
            return cur.lastrowid

    def _end_event(self,identity,response=None,error=None,body=None):
        import time
        with self.budget.connect() as db:
            db.execute('UPDATE gate6_http_events SET finished=?,status=?,http_status=?,response_hash=?,bytes=? WHERE id=? AND finished IS NULL',
                (time.time(),'unknown' if error else 'success' if response.status_code<300 else 'http_error',
                 None if response is None else response.status_code,None if body is None else sha256(body).hexdigest(),
                 None if body is None else len(body),identity))

    def _validate_payload(self,proof,payload):
        if (not isinstance(payload,dict) or payload.get('model')!=proof['model']
                or type((payload.get('parameters') or {}).get('n')) is not int
                or payload['parameters']['n']!=1 or digest(payload)!=proof['payload_hash']):
            self.meter._block('media','Image payload differs from approved single-output dispatch')
        refs=[]
        for msg in (payload.get('input') or {}).get('messages',[]):
            for block in msg.get('content') or []:
                if isinstance(block,dict) and 'image' in block:
                    value=block['image']
                    if not isinstance(value,str) or not value.startswith('data:image/') or ';base64,' not in value:
                        self.meter._block('media','Gate6 image references must be local verified data URLs; uploads are disabled')
                    try: raw=base64.b64decode(value.split(';base64,',1)[1],validate=True)
                    except (TypeError,ValueError): self.meter._block('media','Invalid image reference encoding')
                    refs.append(sha256(raw).hexdigest())
        if refs!=proof['reference_hashes']:
            self.meter._block('media','Reference bytes/order differ from approved real cast images')

    def _row(self,provider_task):
        with self.budget.connect() as db:
            row=db.execute('SELECT * FROM gate6_images WHERE provider_task_id=?',(provider_task,)).fetchone()
        if row is None: self.meter._block('network','Unbound provider task poll')
        return dict(row)

    def _terminal(self,reservation,data,http_status,raw):
        urls=output_urls(data)
        status=(data.get('output') or {}).get('task_status')
        failed=http_status>=300 or status in {'FAILED','CANCELED'}
        terminal='unknown' if status=='UNKNOWN' else 'http_error' if failed else 'success'
        if not failed and len(urls)==1:
            valid_download_url(urls[0])
        self.budget.finish(reservation,status=terminal,actual_images=len(urls),
            response_hash=sha256(raw).hexdigest(),request_id=data.get('request_id'),http_status=http_status,
            provider_usage=numeric_usage(data),output_url_hash=url_hash(urls[0]) if len(urls)==1 else None)
        if terminal=='unknown': raise ImageGuardError('Provider task status is unknown; stop without retry')

    def send(self,session,request,**kwargs):
        if request.url==CHAT_URL:
            with self._destination(request):
                response=self.chat_send(session,request,**kwargs)
            if self.meter.phase()['phase']=='identity':
                raw=response.content
                evidence={'http_status':response.status_code,'sha256':sha256(raw).hexdigest(),
                    'raw_body_base64':base64.b64encode(raw).decode('ascii'),'bytes':len(raw)}
                try:
                    data=response.json()
                    evidence['raw_response']=data
                    choices=data.get('choices') if isinstance(data,dict) else None
                    first=choices[0] if isinstance(choices,list) and choices and isinstance(choices[0],dict) else {}
                    message=first.get('message')
                    evidence['content']=message.get('content') if isinstance(message,dict) else None
                    evidence['finish_reason']=first.get('finish_reason')
                except (TypeError,ValueError,AttributeError):
                    evidence['text']=raw.decode('utf-8',errors='replace')
                path=self.meter.path.parent/'identity-provider-response.json'
                with path.open('x',encoding='utf-8') as stream:
                    json.dump(evidence,stream,ensure_ascii=False,indent=2); stream.flush(); os.fsync(stream.fileno())
            return response
        proof=self._proof()
        if request.method=='POST' and request.url in {ASYNC_URL,SYNC_URL}:
            if request.url!=proof['endpoint']: self.meter._block('media','Image endpoint differs from selected adapter')
            try: payload=json.loads(request.body)
            except (TypeError,ValueError,UnicodeDecodeError): self.meter._block('media','Invalid image JSON')
            self._validate_payload(proof,payload)
            reservation=self.budget.reserve(attempt_key=proof['attempt_key'],node_id=proof['node_id'],
                model=proof['model'],node_hash=proof['node_hash'],request_hash=proof['payload_hash'],n=1)
            self.budget.mark_transport(reservation,inputs_hash=proof['inputs_hash'],job_id=proof['job_id'],invocation_id=proof['invocation_id'])
            event=self._event('image_submit',reservation,request)
            try:
                with self._exchange(session,request,kwargs) as response:
                    raw=response.content
                self._end_event(event,response,body=raw)
                data=response.json()
                if not isinstance(data,dict): raise ValueError('Non-object provider response')
                task=(data.get('output') or {}).get('task_id')
                if 200<=response.status_code<300 and request.url==ASYNC_URL and task:
                    self.budget.bind_task(reservation,task)
                else: self._terminal(reservation,data,response.status_code,raw)
                self._end_event(event,response,body=raw)
                return response
            except BaseException as error:
                with self.budget.connect() as db:
                    row=db.execute('SELECT status,provider_task_id FROM gate6_images WHERE id=?',(reservation,)).fetchone()
                if row['status']=='reserved' and row['provider_task_id'] is None:
                    self.budget.finish(reservation,status='unknown',actual_images=0,response_hash=sha256(type(error).__name__.encode()).hexdigest())
                self._end_event(event,error=error)
                raise
        if request.method=='GET' and request.url.startswith(TASK_PREFIX):
            task_id=request.url[len(TASK_PREFIX):]
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',task_id): self.meter._block('network','Malformed task poll URL')
            row=self._row(task_id)
            if row['node_id']!=proof['node_id'] or row['model']!=proof['model'] or row['status']!='reserved':
                self.meter._block('network','Poll does not match selected active image')
            event=self._event('image_poll',row['id'],request)
            try:
                with self._exchange(session,request,kwargs) as response:
                    raw=response.content
                self._end_event(event,response,body=raw)
                data=response.json()
                state=(data.get('output') or {}).get('task_status')
                if response.status_code>=300 or state in {'SUCCEEDED','FAILED','CANCELED','UNKNOWN'}:
                    self._terminal(row['id'],data,response.status_code,raw)
                self._end_event(event,response,body=raw)
                return response
            except BaseException as error:
                with self.budget.connect() as db:
                    current=db.execute('SELECT status FROM gate6_images WHERE id=?',(row['id'],)).fetchone()
                if current['status']=='reserved':
                    self.budget.finish(row['id'],status='unknown',actual_images=0,response_hash=sha256(type(error).__name__.encode()).hexdigest())
                self._end_event(event,error=error); raise
        if request.method=='GET':
            valid_download_url(request.url)
            if any(k.lower() in {'authorization','proxy-authorization','cookie'} for k in request.headers):
                self.meter._block('network','No credentials or cookies may accompany result downloads')
            with self.budget.connect() as db:
                row=db.execute("SELECT * FROM gate6_images WHERE node_id=? AND output_url_hash=? AND status='success' AND actual_images=1",
                    (proof['node_id'],url_hash(request.url))).fetchone()
            if row is None: self.meter._block('network','Result URL is not the exact selected provider result')
            event=self._event('image_download',row['id'],request)
            try:
                kwargs['stream']=True
                with self._exchange(session,request,kwargs) as response:
                    chunks=[]; count=0
                    for chunk in response.iter_content(1024*1024):
                        count+=len(chunk)
                        if count>MAX_DOWNLOAD:
                            self._end_event(event,response,error=True,body=b''.join(chunks)+chunk)
                            raise EvaluationSafetyError('Image download exceeds 20 MiB; response evidence is partial')
                        chunks.append(chunk)
                response._content=b''.join(chunks); response._content_consumed=True
                self._end_event(event,response,body=response.content)
                if not 200<=response.status_code<300: raise EvaluationSafetyError('Image download failed; redirects are forbidden')
                return response
            except BaseException as error:
                self._end_event(event,error=error); raise
        self.meter._block('network','Gate6 endpoint/method is outside the exact allowlist; uploads/video are forbidden')

    def install(self):
        import requests
        import socket
        from urllib3.connection import HTTPConnection,HTTPSConnection
        def guarded_send(session,request,**kwargs):
            return self.send(session,request,**kwargs)
        self.meter._patch(requests.Session,'send',guarded_send)
        original_dns=socket.getaddrinfo
        guard=self
        def dns(host,port,*args,**kwargs):
            name=host.decode('ascii') if isinstance(host,bytes) else host
            if getattr(guard.local,'destination',None)!=(str(name).lower(),int(port)):
                guard.meter._block('network','DNS outside active approved transport')
            values=original_dns(host,port,*args,**kwargs)
            addresses={item[4][0] for item in values}
            if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
                guard.meter._block('network','Provider DNS resolved to nonpublic addresses')
            guard.local.ips=addresses
            return values
        self.meter._patch(socket,'getaddrinfo',dns)
        original_connect=socket.socket.connect
        def connect(sock,address):
            dest=getattr(guard.local,'destination',None)
            if not dest or not isinstance(address,tuple) or address[0] not in guard.local.ips or address[1]!=443:
                guard.meter._block('network','Socket outside the exact provider destination')
            return original_connect(sock,address)
        self.meter._patch(socket.socket,'connect',connect)
        original_sendto=socket.socket.sendto
        def sendto(sock,*args,**kwargs):
            guard.meter._block('network','Datagrams are not part of Gate6')
        self.meter._patch(socket.socket,'sendto',sendto)
        previous_requests={cls:cls.request for cls in (HTTPConnection,HTTPSConnection)}
        for cls in (HTTPConnection,HTTPSConnection):
            previous=previous_requests[cls]
            def http_request(connection,*args,_previous=previous,**kwargs):
                if getattr(guard.local,'destination',None)!=(str(connection.host).lower(),int(connection.port or 443)):
                    guard.meter._block('network','Unaudited or redirected HTTP destination')
                token=getattr(guard.local,'request_token',None)
                method=args[0] if args else kwargs.get('method')
                path=args[1] if len(args)>1 else kwargs.get('url')
                if not token or token['used'] or (method,path)!=(token['method'],token['path']):
                    guard.meter._block('network','HTTP request token already used or method/path changed')
                token['used']=True
                return _previous(connection,*args,**kwargs)
            self.meter._patch(cls,'request',http_request)
        return self
