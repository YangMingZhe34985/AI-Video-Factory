"""Credential launch policy with fake keys only; never reads a configuration file."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

scripts=Path(__file__).resolve().parents[1]/'scripts/v3_eval'
if scripts.is_dir(): sys.path.insert(0,str(scripts))
from gate6_launch import child_environment,child_command


class LaunchPolicyTests(unittest.TestCase):
    def test_existing_key_never_reads_file_or_mutates_parent(self):
        parent={'DASHSCOPE_API_KEY':'stub-existing'}
        def forbidden(*_args): raise AssertionError('Reader must not run')
        env=child_environment(parent,Path('unused'),forbidden)
        self.assertEqual(env['DASHSCOPE_API_KEY'],'stub-existing')
        self.assertEqual(parent,{'DASHSCOPE_API_KEY':'stub-existing'})
        self.assertEqual(env['PYTHON_DOTENV_DISABLED'],'1')
    def test_missing_key_reads_only_allowlisted_provider_value(self):
        seen=[]
        def reader(path,wanted):
            seen.append((path.name,wanted)); return {'DASHSCOPE_API_KEY':'stub-key'}
        env=child_environment({},Path('unused'),reader)
        self.assertEqual(seen,[('.env',{'DASHSCOPE_API_KEY'})])
        self.assertEqual(env['DASHSCOPE_API_KEY'],'stub-key')
        self.assertEqual(env['DASHSCOPE_API_BASE_URL'],'https://dashscope.aliyuncs.com/api/v1')
    def test_unapproved_reader_output_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'unapproved'):
            child_environment({},Path('unused'),lambda *_:{'DATABASE_URL':'must-not-use'})
    def test_missing_credential_stops_before_child(self):
        with self.assertRaisesRegex(RuntimeError,'unavailable'):
            child_environment({},Path('unused'),lambda *_:{})
    def test_command_contains_no_key_and_pins_utf8_isolated_interpreter(self):
        args=SimpleNamespace(work='work',label='01-c3-1',expected_commit='a'*40,
            full_evidence='evidence',manifest=None,approve_manifest_sha256=None)
        command=child_command(args,Path('gate6_entry.py'))
        self.assertEqual(command[1:5],['-X','utf8','-I','-B'])
        self.assertEqual(command[-1],'--execute')
        self.assertFalse(any('KEY' in item for item in command))


class SelectionArchiveTests(unittest.TestCase):
    def record(self,label='03-c7'):
        from gate6_entry import SAMPLES
        return {'run_id':'agent_selected','audit_label':label+':agent_selected','case':SAMPLES[label],
            'phase':'planning','round':'V13-Gate6','status':'awaiting_plan_review'}
    def test_each_fixed_planning_label_is_eligible(self):
        from gate6_entry import require_selected_archive
        for label in ('01-c3-1','02-c3-2','03-c7'):
            row=self.record(label); self.assertEqual(require_selected_archive([row],'agent_selected'),row)
    def test_external_run_is_rejected(self):
        from gate6_entry import require_selected_archive
        with self.assertRaises(RuntimeError): require_selected_archive([self.record()],'agent_external')
    def test_forged_label_case_phase_or_round_is_rejected(self):
        from gate6_entry import require_selected_archive
        for field,value in [('audit_label','outside:agent_selected'),('case','c1_photo'),('phase','identity_sample'),('round','V12-Gate5b')]:
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                require_selected_archive([{**self.record(),field:value}],'agent_selected')
    def test_clarification_plan_cannot_be_approved(self):
        from gate6_entry import require_selected_archive
        with self.assertRaises(RuntimeError):
            require_selected_archive([{**self.record(), 'status':'awaiting_input'}],'agent_selected')
    def test_duplicate_same_run_archive_is_rejected(self):
        from gate6_entry import require_selected_archive
        with self.assertRaises(RuntimeError): require_selected_archive([self.record(),self.record()],'agent_selected')


if __name__=='__main__': unittest.main()
