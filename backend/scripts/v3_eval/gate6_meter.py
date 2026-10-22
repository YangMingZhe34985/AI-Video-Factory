"""Gate6 text/vision admission on the existing durable physical-call ledger.

This module does not load configuration or start a run. Image transport remains
blocked by default; the separate selective image dispatcher must be reviewed.
"""
from __future__ import annotations

from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from safety import CallMeter, EvaluationSafetyError, TEXT_MODEL, VISION_MODEL, CHAT_URL

MARKER={'round':'V13-Gate6','call_limit':120,'real_image_limit':6,'real_video_limit':0,
        'media_mode':'identity_sample'}


class Gate6Meter(CallMeter):
    def __init__(self, work):
        super().__init__(work,max_calls=120)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS gate6_phase(id INTEGER PRIMARY KEY CHECK(id=1),phase TEXT NOT NULL,identity_hashes TEXT)')
            db.execute("INSERT OR IGNORE INTO gate6_phase VALUES(1,'planning',NULL)")
            db.execute('CREATE TABLE IF NOT EXISTS gate6_identity_inputs(id INTEGER PRIMARY KEY CHECK(id=1),records TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS gate6_identity_request(id INTEGER PRIMARY KEY CHECK(id=1),call_id INTEGER NOT NULL)')
            if db.execute('SELECT max_calls FROM limits WHERE id=1').fetchone()[0]!=120:
                raise EvaluationSafetyError('Gate6 cannot adopt an altered text/vision ceiling')

    @contextmanager
    def _connect(self):
        db=sqlite3.connect(self.path,timeout=30)
        try:
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def phase(self):
        with self._connect() as db:
            return dict(db.execute('SELECT phase,identity_hashes FROM gate6_phase WHERE id=1').fetchone())

    def begin_execution(self):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT phase FROM gate6_phase WHERE id=1').fetchone()[0]!='planning':
                raise EvaluationSafetyError('Execution may start only once after fixed planning samples')
            db.execute("UPDATE gate6_phase SET phase='execution' WHERE id=1")

    def bind_identity_inputs(self,records):
        from gate6_views import MAX_IMAGE_BYTES,MAX_TOTAL_BYTES,TRANSFORM
        if not isinstance(records,list) or len(records)!=4:
            raise EvaluationSafetyError('Exactly four bounded display inputs required')
        if len({r['sha256'] for r in records})!=4 or sum(r['bytes'] for r in records)>MAX_TOTAL_BYTES:
            raise EvaluationSafetyError('Display input identity/size mismatch')
        from gate6_selective import managed_file
        for record in records:
            for field,hash_field in (('path','sha256'),('source_path','source_sha256')):
                path=managed_file(record.get(field,''),self.path.parent)
                if hashlib.sha256(path.read_bytes()).hexdigest()!=record.get(hash_field):
                    raise EvaluationSafetyError('Display input or original file hash changed')
            if (type(record.get('bytes')) is not int or not 0<record['bytes']<=MAX_IMAGE_BYTES
                    or any(record.get('transform',{}).get(k)!=v for k,v in TRANSFORM.items())):
                raise EvaluationSafetyError('Display input transformation is not the fixed evaluation policy')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT phase FROM gate6_phase WHERE id=1').fetchone()[0]!='execution':
                raise EvaluationSafetyError('Display input binding requires deterministic execution')
            db.execute('INSERT INTO gate6_identity_inputs VALUES(1,?)',(json.dumps(records,ensure_ascii=False),))

    def begin_identity(self, ordered_hashes):
        if (not isinstance(ordered_hashes,list) or len(ordered_hashes)!=4 or len(set(ordered_hashes))!=4
                or any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in ordered_hashes)):
            raise EvaluationSafetyError('Identity review requires four distinct exact image hashes')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT phase FROM gate6_phase WHERE id=1').fetchone()[0]!='execution':
                raise EvaluationSafetyError('Identity phase cannot be restarted')
            rows=db.execute('''SELECT i.node_id,i.status,i.actual_images,d.sha256
                FROM gate6_images i JOIN gate6_image_downloads d ON d.reservation_id=i.id
                WHERE i.status='success' AND i.actual_images=1''').fetchall()
            manifest=json.loads(db.execute('SELECT manifest FROM gate6_image_policy WHERE id=1').fetchone()[0])
            expected=[n['node_id'] for n in manifest['nodes']]
            if len(rows)!=4 or len({r['node_id'] for r in rows})!=4 or set(expected)!={r['node_id'] for r in rows}:
                raise EvaluationSafetyError('Four real selected outputs are not complete')
            actual={r['node_id']:r['sha256'] for r in rows}
            record=db.execute('SELECT records FROM gate6_identity_inputs WHERE id=1').fetchone()
            views=json.loads(record['records']) if record else []
            if (len(views)!=4 or [r.get('source_sha256') for r in views]!=[actual[n] for n in expected]
                    or ordered_hashes!=[r.get('sha256') for r in views]):
                raise EvaluationSafetyError('Four display inputs are not bound to exact original selected outputs')
            if db.execute('SELECT 1 FROM gate6_image_violations LIMIT 1').fetchone():
                raise EvaluationSafetyError('Image anomaly prevents identity review')
            db.execute("UPDATE gate6_phase SET phase='identity',identity_hashes=? WHERE id=1",(json.dumps(ordered_hashes),))

    def complete_identity(self):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT c.status FROM calls c JOIN gate6_identity_request i ON i.call_id=c.id').fetchone()
            if not row or row['status']!='success':
                raise EvaluationSafetyError('Identity physical completion is not successful')
            db.execute("UPDATE gate6_phase SET phase='complete' WHERE id=1")

    def _reserve(self, model, request_hash):
        if model not in {TEXT_MODEL,VISION_MODEL}:
            raise EvaluationSafetyError('Unapproved Gate6 model')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            phase=db.execute('SELECT phase FROM gate6_phase WHERE id=1').fetchone()[0]
            if phase not in {'planning','identity'}:
                raise EvaluationSafetyError('No LLM/vision call is allowed during deterministic execution')
            if phase=='identity' and model!=VISION_MODEL:
                raise EvaluationSafetyError('Identity review allows only qwen3.7-plus')
            previous=db.execute("SELECT id FROM calls WHERE request_hash=? AND status IN ('reserved','unknown') LIMIT 1",(request_hash,)).fetchone()
            if previous:
                raise EvaluationSafetyError('Ambiguous Gate6 request cannot be resubmitted')
            count=db.execute('SELECT COUNT(*) FROM calls').fetchone()[0]
            limit=119 if phase=='planning' else 120
            if count>=limit:
                raise EvaluationSafetyError('Gate6 call ceiling or final-vision reservation reached')
            if phase=='identity' and db.execute('SELECT 1 FROM gate6_identity_request').fetchone():
                raise EvaluationSafetyError('Identity review is one physical request, never a per-image retry')
            cursor=db.execute('''INSERT INTO calls(label,model,kind,request_hash,process_id,started,status)
                VALUES(?,?,?,?,?,?,?)''',(self.label,model,'vision' if model==VISION_MODEL else 'text',
                                         request_hash,os.getpid(),time.time(),'reserved'))
            call_id=int(cursor.lastrowid)
            if phase=='identity':
                db.execute('INSERT INTO gate6_identity_request VALUES(1,?)',(call_id,))
            return call_id

    def check_identity_payload(self, payload):
        if self.phase()['phase']!='identity':
            return
        if payload.get('model')!=VISION_MODEL:
            raise EvaluationSafetyError('Wrong identity model')
        images=[]
        for message in payload.get('messages',[]):
            for block in message.get('content',[]) if isinstance(message.get('content'),list) else []:
                if isinstance(block,dict) and block.get('type')=='image_url':
                    value=(block.get('image_url') or {}).get('url','')
                    if not isinstance(value,str) or not value.startswith('data:image/') or ';base64,' not in value:
                        raise EvaluationSafetyError('Identity review accepts only the four local image byte payloads')
                    try: raw=base64.b64decode(value.split(';base64,',1)[1],validate=True)
                    except (ValueError,TypeError) as error: raise EvaluationSafetyError('Malformed identity image') from error
                    images.append(hashlib.sha256(raw).hexdigest())
        if images!=json.loads(self.phase()['identity_hashes']):
            raise EvaluationSafetyError('Identity request is not exactly the four approved images in order')

    def install(self):
        super().install()
        import requests
        original=requests.Session.send
        meter=self
        def guarded_send(session,request,**kwargs):
            if request.url==CHAT_URL:
                try: payload=json.loads(request.body)
                except (ValueError,TypeError,UnicodeDecodeError) as error:
                    raise EvaluationSafetyError('Malformed chat payload') from error
                meter.check_identity_payload(payload)
            return original(session,request,**kwargs)
        self._patch(requests.Session,'send',guarded_send)
        return self

    def snapshot(self):
        value=super().snapshot()
        value['phase']=self.phase()['phase']
        with self._connect() as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gate6_images'").fetchone()
            rows=[dict(r) for r in db.execute('SELECT * FROM gate6_images ORDER BY id')] if exists else []
            downloads=list(db.execute('SELECT * FROM gate6_image_downloads')) if exists else []
        value.update(real_image_calls=sum(r['transport_started'] is not None for r in rows),
                     reserved_image_units=sum(r['requested'] for r in rows),
                     real_images_returned=sum(r['actual_images'] or 0 for r in rows),
                     real_images_downloaded=len(downloads),image_limit=6)
        return value
