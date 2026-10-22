"""Gate6 image reservation primitive; no app, credentials, transport or network.

Not an execution entry. The trusted selector must prove the approved Plan/Job
before calling reserve. This primitive cannot authorize a tool by itself.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import time

MAX_IMAGES = 6
IMAGE_MODELS = frozenset({'wan2.6-image', 'wan2.7-image', 'wan2.7-image-pro',
                         'qwen-image-3.0', 'qwen-image-3.0-pro'})
HEX = re.compile(r'[0-9a-f]{64}')


class ImageGuardError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode('utf-8')).hexdigest()


def require(value, message):
    if not value:
        raise ImageGuardError(message)


def checked_manifest(value):
    require(isinstance(value, dict) and set(value) == {'run_id', 'plan_version', 'plan_hash', 'nodes'},
            'Manifest requires exact approved identity fields')
    require(isinstance(value['run_id'], str) and bool(re.fullmatch(r'agent_[a-z0-9]{1,64}', value['run_id'])), 'Bad Run ID')
    require(type(value['plan_version']) is int and value['plan_version'] > 0, 'Bad version')
    require(isinstance(value['plan_hash'], str) and HEX.fullmatch(value['plan_hash']), 'Bad approved hash')
    nodes = value['nodes']
    require(isinstance(nodes, list) and len(nodes) == 4, 'Exactly four selected nodes required')
    seen, counts = set(), {'cast': 0, 'keyframe': 0}
    for node in nodes:
        require(isinstance(node, dict) and set(node) == {'node_id', 'kind', 'model', 'node_hash', 'n'}, 'Bad node fields')
        require(isinstance(node['node_id'], str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', node['node_id'])), 'Bad node ID')
        require(node['node_id'] not in seen, 'Duplicate node')
        seen.add(node['node_id'])
        require(node['kind'] in counts, 'Bad selection role')
        counts[node['kind']] += 1
        require(node['model'] in IMAGE_MODELS, 'Unsupported image model')
        require(isinstance(node['node_hash'], str) and HEX.fullmatch(node['node_hash']), 'Bad node hash')
        require(type(node['n']) is int and node['n'] == 1, 'Gate6 requires n=1')
    require(counts == {'cast': 2, 'keyframe': 2}, 'Two cast and two keyframes required')
    return json.loads(canonical(value))


class ImageBudget:
    """Append-only reservations; failures/unknown status never refund image units."""
    def __init__(self, audit_path, manifest, *, image_limit=MAX_IMAGES):
        require(type(image_limit) is int and 0 <= image_limit <= MAX_IMAGES, 'Image limit exceeds authorization')
        self.path = Path(audit_path)
        self.manifest = checked_manifest(manifest)
        self.nodes = {n['node_id']: n for n in self.manifest['nodes']}
        encoded = canonical(self.manifest)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS gate6_image_policy (id INTEGER PRIMARY KEY CHECK(id=1), manifest TEXT NOT NULL, image_limit INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO gate6_image_policy VALUES (1,?,?)', (encoded, image_limit))
            require(db.execute('SELECT manifest FROM gate6_image_policy WHERE id=1').fetchone()[0] == encoded,
                    'Cannot replace the selected approved plan')
            db.execute('UPDATE gate6_image_policy SET image_limit=MIN(image_limit,?) WHERE id=1', (image_limit,))
            db.execute('''CREATE TABLE IF NOT EXISTS gate6_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_key TEXT NOT NULL UNIQUE,
                node_id TEXT NOT NULL, model TEXT NOT NULL, request_hash TEXT NOT NULL,
                requested INTEGER NOT NULL CHECK(requested=1), retry_of INTEGER UNIQUE,
                status TEXT NOT NULL, started REAL NOT NULL, finished REAL,
                response_hash TEXT, actual_images INTEGER, request_id TEXT,
                provider_task_id TEXT UNIQUE, http_status INTEGER, provider_usage TEXT,
                transport_started REAL, inputs_hash TEXT, job_id TEXT, invocation_id TEXT,
                output_url_hash TEXT)''')
            db.execute('CREATE TABLE IF NOT EXISTS gate6_image_downloads (reservation_id INTEGER PRIMARY KEY, url_hash TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, completed_at REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS gate6_http_events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, reservation_id INTEGER, url_hash TEXT NOT NULL, method TEXT NOT NULL, started REAL NOT NULL, finished REAL, status TEXT NOT NULL, http_status INTEGER, response_hash TEXT, bytes INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS gate6_image_violations (id INTEGER PRIMARY KEY AUTOINCREMENT, reservation_id INTEGER, reason TEXT NOT NULL, at REAL NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, *, attempt_key, node_id, model, node_hash, request_hash, n, retry_of=None):
        require(isinstance(attempt_key, str) and bool(re.fullmatch(r'[A-Za-z0-9:_-]{1,180}', attempt_key)), 'Bad attempt key')
        require(type(n) is int and n == 1, 'Gate6 requires explicit n=1')
        node = self.nodes.get(node_id)
        require(node is not None and model == node['model'] and node_hash == node['node_hash'], 'Selected node proof mismatch')
        require(isinstance(request_hash, str) and HEX.fullmatch(request_hash), 'Bad payload hash')
        require(retry_of is None or type(retry_of) is int, 'Bad retry proof')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require(not db.execute('SELECT 1 FROM gate6_image_violations LIMIT 1').fetchone(), 'Image anomaly latched; stop round')
            require(not db.execute("SELECT 1 FROM gate6_images WHERE status='unknown' LIMIT 1").fetchone(), 'Unknown request; stop round')
            require(not db.execute('SELECT 1 FROM gate6_images WHERE attempt_key=?', (attempt_key,)).fetchone(), 'Attempt already reserved; never resend')
            previous = db.execute('SELECT * FROM gate6_images WHERE node_id=? ORDER BY id DESC LIMIT 1', (node_id,)).fetchone()
            if previous is None:
                require(retry_of is None, 'No failed attempt to retry')
            else:
                require(retry_of == previous['id'] and previous['status'] == 'http_error',
                        'Retry requires exact latest confirmed HTTP failure; no automatic retry')
                require(previous['request_hash'] == request_hash, 'Retry payload changed')
            used = db.execute('SELECT COALESCE(SUM(requested),0) FROM gate6_images').fetchone()[0]
            limit = db.execute('SELECT image_limit FROM gate6_image_policy WHERE id=1').fetchone()[0]
            require(used + n <= limit, 'Image reservation ceiling reached')
            row = db.execute('''INSERT INTO gate6_images
                (attempt_key,node_id,model,request_hash,requested,retry_of,status,started)
                VALUES(?,?,?,?,?,?,?,?)''', (attempt_key,node_id,model,request_hash,n,retry_of,'reserved',time.time()))
            result = int(row.lastrowid)
        # The connection context committed before returning to a transport caller.
        return result

    def mark_transport(self, reservation_id, *, inputs_hash, job_id, invocation_id):
        require(isinstance(inputs_hash, str) and HEX.fullmatch(inputs_hash), 'Bad resolved inputs hash')
        for value in (job_id, invocation_id):
            require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value), 'Bad execution binding')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,transport_started FROM gate6_images WHERE id=?', (reservation_id,)).fetchone()
            require(row is not None and row['status']=='reserved' and row['transport_started'] is None,
                    'A reserved image POST can enter transport only once')
            db.execute('UPDATE gate6_images SET transport_started=?,inputs_hash=?,job_id=?,invocation_id=? WHERE id=?',
                       (time.time(),inputs_hash,job_id,invocation_id,reservation_id))

    def bind_task(self, reservation_id, task_id):
        require(isinstance(task_id,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',task_id), 'Bad provider task ID')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT provider_task_id,transport_started,status FROM gate6_images WHERE id=?',(reservation_id,)).fetchone()
            require(row is not None and row['transport_started'] is not None and row['status']=='reserved', 'No active image POST')
            require(row['provider_task_id'] in (None,task_id), 'Provider task binding changed')
            db.execute('UPDATE gate6_images SET provider_task_id=? WHERE id=?',(task_id,reservation_id))

    def record_download(self, reservation_id, *, url_hash, sha256_value, byte_count):
        require(isinstance(url_hash,str) and HEX.fullmatch(url_hash), 'Bad result URL hash')
        require(isinstance(sha256_value,str) and HEX.fullmatch(sha256_value), 'Bad downloaded image hash')
        require(type(byte_count) is int and byte_count>0, 'Empty output download')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status,actual_images,output_url_hash FROM gate6_images WHERE id=?',(reservation_id,)).fetchone()
            require(row is not None and row['status']=='success' and row['actual_images']==1 and row['output_url_hash']==url_hash,
                    'Download is not a successful single-image result')
            old=db.execute('SELECT * FROM gate6_image_downloads WHERE reservation_id=?',(reservation_id,)).fetchone()
            if old:
                require((old['url_hash'],old['sha256'],old['bytes'])==(url_hash,sha256_value,byte_count), 'Download evidence changed')
                return
            db.execute('INSERT INTO gate6_image_downloads VALUES(?,?,?,?,?)',(reservation_id,url_hash,sha256_value,byte_count,time.time()))

    def finish(self, reservation_id, *, status, actual_images, response_hash, request_id=None,
               http_status=None, provider_usage=None, output_url_hash=None):
        require(status in {'success', 'http_error', 'unknown'}, 'Unsupported terminal status')
        require(type(actual_images) is int and actual_images >= 0, 'Bad actual output count')
        require(isinstance(response_hash, str) and HEX.fullmatch(response_hash), 'Bad response hash')
        require(request_id is None or (isinstance(request_id, str) and len(request_id) <= 256), 'Bad request ID')
        require(http_status is None or (type(http_status) is int and 100<=http_status<=599), 'Bad HTTP status')
        require(output_url_hash is None or (isinstance(output_url_hash,str) and HEX.fullmatch(output_url_hash)), 'Bad output URL hash')
        usage = {} if provider_usage is None else provider_usage
        require(isinstance(usage,dict) and all(isinstance(k,str) and re.fullmatch(r'[A-Za-z_]{1,50}',k) and type(v) in (int,float) and v>=0 for k,v in usage.items()), 'Usage must contain only nonnegative numeric counters')
        encoded_usage=canonical(usage)
        violation = None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM gate6_images WHERE id=?', (reservation_id,)).fetchone()
            require(row is not None, 'Unknown reservation')
            if row['status'] != 'reserved':
                require((row['status'],row['actual_images'],row['response_hash'],row['request_id'],row['http_status'],row['provider_usage'],row['output_url_hash']) ==
                    (status,actual_images,response_hash,request_id,http_status,encoded_usage,output_url_hash), 'Cannot rewrite terminal evidence')
                existing = db.execute('SELECT reason FROM gate6_image_violations WHERE reservation_id=? LIMIT 1', (reservation_id,)).fetchone()
                if existing:
                    raise ImageGuardError(existing['reason'])
                return
            db.execute('UPDATE gate6_images SET status=?,actual_images=?,response_hash=?,request_id=?,finished=?,http_status=?,provider_usage=?,output_url_hash=? WHERE id=?',
                       (status,actual_images,response_hash,request_id,time.time(),http_status,encoded_usage,output_url_hash,reservation_id))
            if actual_images > row['requested']:
                violation = 'Provider returned more images than requested; no new dispatch or extra download'
                db.execute('INSERT INTO gate6_image_violations(reservation_id,reason,at) VALUES(?,?,?)',
                           (reservation_id,violation,time.time()))
            elif status == 'success' and actual_images != row['requested']:
                violation = 'Successful image response count mismatch'
                db.execute('INSERT INTO gate6_image_violations(reservation_id,reason,at) VALUES(?,?,?)',
                           (reservation_id,violation,time.time()))
        if violation:
            raise ImageGuardError(violation)

    def snapshot(self):
        with self.connect() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM gate6_images ORDER BY id')]
            limit = db.execute('SELECT image_limit FROM gate6_image_policy WHERE id=1').fetchone()[0]
            violations = [dict(row) for row in db.execute('SELECT * FROM gate6_image_violations ORDER BY id')]
            downloads=[dict(row) for row in db.execute('SELECT * FROM gate6_image_downloads ORDER BY reservation_id')]
        return {'limit':limit, 'image_post_attempts':sum(r['transport_started'] is not None for r in rows), 'downloaded_images':len(downloads), 'downloads':downloads, 'requested_image_units':sum(r['requested'] for r in rows),
                'actual_images':sum(r['actual_images'] or 0 for r in rows),
                'unknown_or_reserved':sum(r['status'] in {'reserved','unknown'} for r in rows),
                'rows':rows, 'violations':violations}
