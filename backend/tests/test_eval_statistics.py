"""Tiny SQLite/JSON fixtures; no application, model or service imports."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.v3_eval.eval_statistics import MARKER, TEXT, VISION, TEMP, checked_work, summarize, ro, markdown, usage


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='cinecrew-v12-stat-fixture-', dir=TEMP))
        (self.work / 'v12-round.json').write_text(json.dumps(MARKER), encoding='utf-8')
        (self.work / 'results').mkdir()
        with sqlite3.connect(self.work / 'eval.db') as db:
            db.executescript('''
            CREATE TABLE agent_runs(id INTEGER PRIMARY KEY,run_id TEXT,status TEXT,error TEXT);
            CREATE TABLE tool_invocations(id INTEGER PRIMARY KEY,invocation_id TEXT,budget_scope TEXT,tool_name TEXT,status TEXT,caller_agent TEXT,delegation_id INTEGER,estimated_cost REAL,output_payload TEXT,error_code TEXT,error_message TEXT);
            CREATE TABLE agent_delegations(id INTEGER PRIMARY KEY,run_id TEXT,parent_id INTEGER,agent TEXT,status TEXT,llm_calls INTEGER,steps INTEGER,state TEXT,error TEXT);
            ''')
            db.execute('INSERT INTO agent_runs VALUES(1,?,?,?)', ('agent_test', 'attention', '{}'))
            state = {'messages': [{'role': 'tool', 'name': 'check_plan', 'tool_call_id': 'check-1',
                'content': json.dumps({'ok': False, 'error': {'code': 'PLAN_CHARACTER_REFERENCE_MISSING', 'message': 'Missing actor2 reference', 'node_id': 'shot2'}})}]}
            db.execute('INSERT INTO agent_delegations VALUES(1,?,NULL,?,?,2,2,?,?)', ('agent_test','producer','completed',json.dumps(state),'{}'))
            for values in [
                (1,'turn1','agent_llm_turn','success',1,{'usage':{'prompt_tokens':100,'completion_tokens':20}}),
                (2,'vision1','analyze_images','success',2,{'usage':{'prompt_tokens':200,'completion_tokens':30}}),
                (3,'submit1','submit_plan','success',0,{'submitted':True,'plan_version':1}),
                (4,'media1','animate_shot','success',8,{}),
                (5,'repair1','agent_llm_turn','success',0.1,{'usage':{'prompt_tokens':10,'completion_tokens':5}}),
            ]:
                ident,invocation,tool,status,cost,output=values
                db.execute('INSERT INTO tool_invocations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (ident,invocation,'agent_test',tool,status,'producer' if ident<5 else 'director',1,cost,json.dumps(output),None,None))
        with sqlite3.connect(self.work / 'real_call_audit.sqlite') as db:
            db.executescript('''
            CREATE TABLE limits(id INTEGER PRIMARY KEY,max_calls INTEGER);
            INSERT INTO limits VALUES(1,150);
            CREATE TABLE calls(id INTEGER PRIMARY KEY,label TEXT,kind TEXT,model TEXT,status TEXT,input_tokens INTEGER,output_tokens INTEGER);
            CREATE TABLE blocked(id INTEGER PRIMARY KEY,label TEXT,kind TEXT,reason TEXT);
            ''')
            db.executemany('INSERT INTO calls VALUES(?,?,?,?,?,?,?)', [
                (1,'c3_story:agent_test','text',TEXT,'success',100,20),
                (2,'c3_story:agent_test','vision',VISION,'success',200,30),
                (3,'V12-failure-intent-agent_test','text',TEXT,'success',10,5)])
        self.archive = {'case':'c3_story','run_id':'agent_test','status':'awaiting_plan_review','spent_total':3,
            'metrics': {'turns':[{'invocation_id':'turn1'}], 'vision_calls':[{'invocation_id':'vision1'}],
                'llm': {'calls':1,'input_tokens_sum':100,'output_tokens_sum':20},
                'vision': {'calls':1,'input_tokens_sum':200,'output_tokens_sum':30}},
            'delegations':[{'id':1,'parent_id':None,'agent':'producer'}], 'final_compile_issue_codes':[],
            'full_plan':{'nodes':[], 'estimates':{'video_seconds':120}}}
        self.write('result_c3_story_agent_test.json',self.archive)
        self.write('result_c3_story.json',self.archive)
        self.write('hybrid_V12-failure-intent-agent_test_agent_test.json', {'scenario':'V12-failure-intent-agent_test',
            'run_id':'agent_test','status':'not_covered','acceptance':{'safe_control_flow':True,
                'manual_intent_path_covered':False,'outcome':'declared_preserved_auto'}})
        self.write('result_c3_story_agent_test_private_profile.json', {'run_id':'agent_test', 'ledger':[{'estimated_cost':999999}]})

    def write(self,name,data):
        (self.work/'results'/name).write_text(json.dumps(data),encoding='utf-8')

    def test_c7_geometry_uses_latest_run_scoped_brief_without_archive_mutation(self):
        from tests.test_eval_aspect_evidence import fixture
        plan, brief = fixture()
        with sqlite3.connect(self.work/'eval.db') as db:
            db.execute('CREATE TABLE agent_workspace_items(id INTEGER PRIMARY KEY,run_id TEXT,key TEXT,version INTEGER,kind TEXT,payload TEXT)')
            db.executemany('INSERT INTO agent_workspace_items VALUES(?,?,?,?,?,?)', [
                (1,'agent_test','brief',1,'brief',json.dumps({**brief,'aspect_ratio':'9:16'})),
                (2,'agent_test','brief',2,'brief',json.dumps(brief)),
                (99,'another_run','brief',99,'brief',json.dumps({**brief,'aspect_ratio':'9:16'}))])
        archive = {**self.archive, 'case':'c7_complete_story','full_plan':plan}
        self.write('result_c7_complete_story_agent_test.json', archive)
        before = {path.name:sha256(path.read_bytes()).hexdigest() for path in (self.work/'results').glob('*.json')}
        db_before = sha256((self.work/'eval.db').read_bytes()).hexdigest()
        case = next(item for item in summarize(self.work)['planning'] if item['label']=='c7_complete_story')
        result = case['plan']['aspect_chain']
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['brief_source']['key'],'brief')
        self.assertEqual(result['brief_source']['version'],2)
        self.assertEqual(result['brief_source']['aspect_ratio'],'16:9')
        canonical = json.dumps(brief,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
        self.assertEqual(result['brief_source']['payload_hash'],sha256(canonical.encode()).hexdigest())
        self.assertEqual(before,{path.name:sha256(path.read_bytes()).hexdigest() for path in (self.work/'results').glob('*.json')})
        self.assertEqual(db_before,sha256((self.work/'eval.db').read_bytes()).hexdigest())
        with sqlite3.connect(self.work/'eval.db') as db:
            db.execute('INSERT INTO agent_workspace_items VALUES(100,?,?,?,?,?)',
                ('agent_test','new_brief_key',1,'brief',json.dumps({**brief,'aspect_ratio':'9:16'})))
        case = next(item for item in summarize(self.work)['planning'] if item['label']=='c7_complete_story')
        self.assertEqual(case['plan']['aspect_chain']['status'],'failed')
        self.assertEqual(case['plan']['aspect_chain']['brief_source']['key'],'new_brief_key')

    def test_c7_missing_persisted_brief_is_not_covered(self):
        from tests.test_eval_aspect_evidence import fixture
        plan, brief = fixture()
        self.write('result_c7_complete_story_agent_test.json', {**self.archive, 'case':'c7_complete_story','full_plan':plan,
                                                             'brief':brief})
        case = next(item for item in summarize(self.work)['planning'] if item['label']=='c7_complete_story')
        self.assertEqual(case['plan']['aspect_chain']['status'],'not_covered')
        self.assertEqual(case['plan']['aspect_chain']['brief_source']['reason'],'persisted_brief_missing')

    def test_dedup_phase_boundary_and_totals(self):
        before = [(name, sha256((self.work/name).read_bytes()).hexdigest()) for name in ('eval.db','real_call_audit.sqlite')]
        result=summarize(self.work)
        self.assertEqual(result['unique_runs'],1)
        self.assertEqual(len(result['planning']),1)
        self.assertEqual(result['totals']['unique_invocations'],5)
        self.assertEqual(result['totals']['accounted_demo_credits'],11.1)
        self.assertEqual(result['totals']['mock_media_demo_credits'],8)
        self.assertEqual(result['physical_audit']['attempts'],3)
        self.assertEqual(result['physical_audit']['by_kind'],{'text':2,'vision':1})
        plan=result['planning'][0]
        self.assertEqual(plan['metrics']['text']['calls'],1)
        self.assertEqual(plan['metrics']['planning_accounted_demo_credits'],3)
        self.assertTrue(plan['physical_slice_verified'])
        self.assertEqual(result['reconciliation']['status'],'passed')
        self.assertFalse(result['hybrid'][0]['manual_intent_path'])
        self.assertEqual(result['hybrid'][0]['coverage'],'not_covered')
        self.assertFalse(any('Repair' in g['name'] for g in result['required_coverage']))
        self.assertEqual(result['runs'][0]['failure_evidence'][0]['code'],'PLAN_CHARACTER_REFERENCE_MISSING')
        self.assertIn('Missing actor2', json.dumps(result['runs'][0]['failure_evidence']))
        self.assertIn('not_covered', markdown(result))
        self.assertEqual(before,[(name, sha256((self.work/name).read_bytes()).hexdigest()) for name,_ in before])

    def test_ro_connection_cannot_write(self):
        with ro(self.work,'eval.db') as db:
            self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0],1)
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('DELETE FROM agent_runs')

    def test_marker_is_mandatory_and_exact(self):
        (self.work/'v12-round.json').write_text(json.dumps({**MARKER,'call_limit':800}),encoding='utf-8')
        with self.assertRaises(ValueError):
            checked_work(self.work)
        with self.assertRaises(ValueError):
            checked_work(TEMP)

    def test_conflicting_alias_is_not_silent_success(self):
        alias=deepcopy(self.archive); alias['status']='failed'
        self.write('result_c3_story.json',alias)
        result=summarize(self.work)
        self.assertIn('ARCHIVE_CONFLICT',[item['code'] for item in result['diagnostics']])
        self.assertEqual(result['planning'][0]['goals'][0]['status'],'not_covered')
        self.assertEqual(result['data_quality_status'],'needs_review')
        self.assertEqual(result['totals']['accounted_demo_credits'],11.1)

    def test_missing_usage_and_mismatched_physical_peak_never_pass(self):
        with sqlite3.connect(self.work/'eval.db') as db:
            db.execute('UPDATE tool_invocations SET output_payload=? WHERE id=1',(json.dumps({'usage':None}),))
        result=summarize(self.work)
        self.assertIsNone(result['planning'][0]['metrics']['text']['input_tokens_max'])
        peak=next(g for g in result['planning'][0]['goals'] if '60000' in g['name'])
        self.assertEqual(peak['status'],'not_covered')
        self.assertEqual(result['reconciliation']['status'],'needs_review')

    def test_unknown_http_and_media_block_are_reported(self):
        with sqlite3.connect(self.work/'real_call_audit.sqlite') as db:
            db.execute("INSERT INTO calls VALUES(4,'unmapped','text',?,'reserved',NULL,NULL)",(TEXT,))
            db.execute("INSERT INTO blocked VALUES(1,'x','media','blocked generation')")
        result=summarize(self.work)
        self.assertEqual(result['physical_audit']['attempts'],4)
        self.assertEqual(result['physical_audit']['unknown_or_reserved_ids'],[4])
        self.assertEqual(result['physical_audit']['unmapped_attempt_ids'],[4])
        self.assertEqual(result['safety']['status'],'failed')

    def test_duplicate_invocation_is_counted_once_and_flagged(self):
        with sqlite3.connect(self.work/'eval.db') as db:
            db.execute('INSERT INTO tool_invocations SELECT 6,invocation_id,budget_scope,tool_name,status,caller_agent,delegation_id,estimated_cost,output_payload,error_code,error_message FROM tool_invocations WHERE id=1')
        result=summarize(self.work)
        self.assertEqual(result['totals']['accounted_demo_credits'],11.1)
        self.assertIn('DUPLICATE_INVOCATION',[item['code'] for item in result['diagnostics']])

    def test_no_current_data_is_not_covered(self):
        with sqlite3.connect(self.work/'eval.db') as db:
            db.execute('DELETE FROM tool_invocations'); db.execute('DELETE FROM agent_delegations'); db.execute('DELETE FROM agent_runs')
        with sqlite3.connect(self.work/'real_call_audit.sqlite') as db:
            db.execute('DELETE FROM calls')
        with patch('scripts.v3_eval.eval_statistics.read_archives',return_value=[]):
            result=summarize(self.work)
        self.assertEqual(result['physical_audit']['attempts'],0)
        self.assertEqual(result['reconciliation']['status'],'not_covered')
        self.assertTrue(all(g['status']=='not_covered' for g in result['required_coverage']))
        self.assertIsNone(result['physical_audit']['usage']['input_tokens_max'])

    def test_real_usage_cap_and_call_budget_fail(self):
        with sqlite3.connect(self.work/'eval.db') as db:
            db.execute('UPDATE tool_invocations SET output_payload=? WHERE id=1', (json.dumps({'usage':{'prompt_tokens':60001,'completion_tokens':20}}),))
        with sqlite3.connect(self.work/'real_call_audit.sqlite') as db:
            db.execute('UPDATE calls SET input_tokens=60001 WHERE id=1')
            db.execute('UPDATE limits SET max_calls=800')
        modified=deepcopy(self.archive); modified['metrics']['llm']['input_tokens_sum']=60001
        self.write('result_c3_story_agent_test.json',modified); self.write('result_c3_story.json',modified)
        result=summarize(self.work)
        peak=next(g for g in result['planning'][0]['goals'] if '60000' in g['name'])
        self.assertEqual(peak['status'],'failed')
        self.assertEqual(result['safety']['status'],'failed')

    def test_cross_kind_usage_swap_cannot_hide_text_peak(self):
        with sqlite3.connect(self.work/'real_call_audit.sqlite') as db:
            db.execute('UPDATE calls SET input_tokens=200,output_tokens=30 WHERE id=1')
            db.execute('UPDATE calls SET input_tokens=100,output_tokens=20 WHERE id=2')
        result=summarize(self.work)
        self.assertEqual(result['reconciliation']['status'],'needs_review')
        self.assertFalse(result['planning'][0]['physical_slice_verified'])
        peak=next(g for g in result['planning'][0]['goals'] if '60000' in g['name'])
        self.assertEqual(peak['status'],'not_covered')

    def test_style_single_n3_is_not_three_independent_candidates(self):
        from scripts.v3_eval.eval_statistics import plan_evidence
        plan={'nodes':[{'id':'posters','tool':'generate_image','params':{'n':3}},
            {'id':'choice','tool':'select_image','gate':'choice','inputs':{'candidate_artifact_ids':{'ref':'posters.images'}}},
            {'id':'video','tool':'animate_shot','inputs':{'first_frame_artifact_id':{'ref':'choice.image'}}}]}
        result=plan_evidence(plan)
        self.assertFalse(result['selectors'][0]['three_independent_n1'])
        self.assertEqual(result['selectors'][0]['animation_node_ids'],['video'])

    def test_planning_budget_and_markdown_include_initial_mock_preview(self):
        with sqlite3.connect(self.work/'eval.db') as db:
            db.execute('INSERT INTO tool_invocations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (0,'preview1','agent_test','request_preview','success','producer',1,18,'{}',None,None))
        modified=deepcopy(self.archive); modified['spent_total']=21
        self.write('result_c3_story_agent_test.json',modified); self.write('result_c3_story.json',modified)
        result=summarize(self.work)
        metrics=result['planning'][0]['metrics']
        self.assertEqual(metrics['planning_accounted_demo_credits'],21)
        self.assertEqual(metrics['llm_demo_credits'],3)
        budget=next(g for g in result['planning'][0]['goals'] if '20 credits' in g['name'])
        self.assertEqual(budget['status'],'failed')
        self.assertEqual(budget['evidence'],21)
        self.assertIn('|21.0|3.0|',markdown(result))
        self.assertEqual(result['totals']['mock_media_demo_credits'],26)

    def test_recorded_truncation_code_and_finish_reason_are_separate_evidence(self):
        with sqlite3.connect(self.work/'eval.db') as db:
            output={'usage':{'prompt_tokens':100,'completion_tokens':20},'finish_reason':'length',
                'tool_call_errors':[{'code':'AGENT_OUTPUT_TRUNCATED','message':'Model output was truncated'}]}
            db.execute('UPDATE tool_invocations SET output_payload=? WHERE id=1',(json.dumps(output),))
        result=summarize(self.work)
        row=result['runs'][0]
        codes=[item['code'] for item in row['failure_evidence']]
        self.assertIn('AGENT_OUTPUT_TRUNCATED',codes)
        self.assertNotIn('MODEL_OUTPUT_TRUNCATED',codes)
        self.assertEqual(row['model_finish_reasons'],[
            {'invocation_id':'turn1','tool':'agent_llm_turn','finish_reason':'length'}])
        self.assertIn('finish_reason=`length`',markdown(result))

    def test_finish_reason_alone_never_fabricates_production_error_code(self):
        with sqlite3.connect(self.work/'eval.db') as db:
            output={'usage':{'prompt_tokens':100,'completion_tokens':20},'finish_reason':'length'}
            db.execute('UPDATE tool_invocations SET output_payload=? WHERE id=1',(json.dumps(output),))
        result=summarize(self.work)
        self.assertTrue(result['runs'][0]['model_finish_reasons'])
        self.assertFalse(any('TRUNCATED' in item['code'] for item in result['runs'][0]['failure_evidence']))


if __name__=='__main__':
    unittest.main()
