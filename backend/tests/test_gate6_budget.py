"""Pure standard-library tests; no app import and all databases are temporary."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

_budget_path=Path(__file__).with_name('gate6_budget.py')
if not _budget_path.is_file(): _budget_path=Path(__file__).resolve().parents[1]/'scripts/v3_eval/gate6_budget.py'
SPEC = importlib.util.spec_from_file_location('budget', _budget_path)
budget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(budget)


def manifest():
    return {'run_id':'agent_offline', 'plan_version':1, 'plan_hash':'a'*64,
            'nodes':[{'node_id':f'n{i}', 'kind':'cast' if i<2 else 'keyframe',
                      'model':'wan2.6-image' if i<2 else 'qwen-image-3.0',
                      'node_hash':str(i)*64, 'n':1} for i in range(4)]}


class Tests(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory(prefix='cc-g6-budget-pure-')
        self.addCleanup(self.area.cleanup)
        self.path = Path(self.area.name)/'audit.sqlite'
        self.manifest = manifest()
        self.meter = budget.ImageBudget(self.path, self.manifest)

    def reserve(self, index=0, key=None, retry_of=None, **override):
        node = self.manifest['nodes'][index]
        args={'attempt_key':key or f'node-{index}', 'node_id':node['node_id'], 'model':node['model'],
              'node_hash':node['node_hash'], 'request_hash':str(index)*64, 'n':1, 'retry_of':retry_of}
        args.update(override)
        return self.meter.reserve(**args)

    def finish(self, identity, status='success', count=1):
        self.meter.finish(identity,status=status,actual_images=count,response_hash='f'*64,request_id='stub')

    def test_commit_before_transport_visible_to_second_connection(self):
        identity=self.reserve()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT id,status FROM gate6_images').fetchall(),[(identity,'reserved')])

    def test_four_independent_nodes(self):
        for i in range(4): self.finish(self.reserve(i))
        self.assertEqual(self.meter.snapshot()['requested_image_units'],4)
        self.assertEqual(self.meter.snapshot()['actual_images'],4)

    def test_n_cannot_hide_multiple_outputs(self):
        for n in (0,2,6,True,'1',None,1.0):
            with self.subTest(n=n), self.assertRaises(budget.ImageGuardError): self.reserve(n=n)
        self.assertEqual(self.meter.snapshot()['requested_image_units'],0)

    def test_failure_consumes_and_no_automatic_retry(self):
        identity=self.reserve()
        self.finish(identity,'http_error',0)
        with self.assertRaises(budget.ImageGuardError): self.reserve(key='new-attempt')
        self.assertEqual(self.meter.snapshot()['requested_image_units'],1)

    def test_explicit_confirmed_retry_consumes_another_unit(self):
        identity=self.reserve(); self.finish(identity,'http_error',0)
        again=self.reserve(key='explicit-2',retry_of=identity)
        self.finish(again)
        self.assertEqual(self.meter.snapshot()['requested_image_units'],2)

    def test_unknown_stops_other_nodes(self):
        identity=self.reserve(); self.finish(identity,'unknown',0)
        with self.assertRaises(budget.ImageGuardError): self.reserve(1)
        self.assertEqual(self.meter.snapshot()['requested_image_units'],1)

    def test_restart_keeps_pending_and_cannot_repeat(self):
        self.reserve()
        self.meter=budget.ImageBudget(self.path,self.manifest)
        with self.assertRaises(budget.ImageGuardError): self.reserve()
        with self.assertRaises(budget.ImageGuardError): self.reserve(key='new-key')
        self.assertEqual(self.meter.snapshot()['unknown_or_reserved'],1)

    def test_concurrent_cap_never_permits_seventh_request(self):
        previous=[]
        for i in range(4):
            identity=self.reserve(i); self.finish(identity,'http_error',0); previous.append(identity)
        barrier=threading.Barrier(4)
        def attempt(i):
            barrier.wait()
            try: return self.reserve(i,key=f'retry-{i}',retry_of=previous[i])
            except budget.ImageGuardError: return None
        with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(attempt,range(4)))
        self.assertEqual(sum(x is not None for x in results),2)
        self.assertEqual(self.meter.snapshot()['requested_image_units'],6)

    def test_duplicate_attempt_concurrently_reserves_only_once(self):
        barrier=threading.Barrier(2)
        def attempt(_):
            barrier.wait()
            try: return self.reserve()
            except budget.ImageGuardError: return None
        with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(x is not None for x in result),1)

    def test_limit_cannot_be_raised_after_restart(self):
        budget.ImageBudget(self.path,self.manifest,image_limit=2)
        self.meter=budget.ImageBudget(self.path,self.manifest,image_limit=6)
        self.assertEqual(self.meter.snapshot()['limit'],2)

    def test_manifest_identity_cannot_change(self):
        for field,value in [('run_id','agent_other'),('plan_version',2),('plan_hash','b'*64)]:
            changed=deepcopy(self.manifest); changed[field]=value
            with self.subTest(field=field),self.assertRaises(budget.ImageGuardError): budget.ImageBudget(self.path,changed)

    def test_node_model_input_hash_and_payload_proof(self):
        for field,value in [('node_id','unselected'),('model','wan3.0-video'),('node_hash','e'*64),('request_hash','oops')]:
            with self.subTest(field=field),self.assertRaises(budget.ImageGuardError): self.reserve(**{field:value})
        self.assertEqual(self.meter.snapshot()['requested_image_units'],0)

    def test_overproduction_persists_anomaly_and_stops_round(self):
        identity=self.reserve()
        with self.assertRaises(budget.ImageGuardError): self.finish(identity,count=2)
        state=self.meter.snapshot()
        self.assertEqual((state['requested_image_units'],state['actual_images']),(1,2))
        self.assertEqual(len(state['violations']),1)
        with self.assertRaises(budget.ImageGuardError): self.reserve(1)
        with self.assertRaises(budget.ImageGuardError): self.finish(identity,count=2)

    def test_success_with_zero_images_is_not_accepted(self):
        identity=self.reserve()
        with self.assertRaises(budget.ImageGuardError): self.finish(identity,count=0)
        self.assertEqual(len(self.meter.snapshot()['violations']),1)

    def test_final_evidence_is_idempotent_but_immutable(self):
        identity=self.reserve(); self.finish(identity); self.finish(identity)
        with self.assertRaises(budget.ImageGuardError): self.finish(identity,'unknown',0)
        self.assertEqual(self.meter.snapshot()['actual_images'],1)

    def test_manifest_exactly_two_cast_and_two_keyframes_n1(self):
        for change in ('extra','role','n','badmodel'):
            value=manifest()
            if change=='extra': value['nodes'].append(deepcopy(value['nodes'][0]))
            if change=='role': value['nodes'][0]['kind']='keyframe'
            if change=='n': value['nodes'][0]['n']=2
            if change=='badmodel': value['nodes'][0]['model']='happyhorse-1.0-i2v'
            with self.subTest(change=change), self.assertRaises(budget.ImageGuardError): budget.checked_manifest(value)


if __name__ == '__main__':
    unittest.main(verbosity=2)
