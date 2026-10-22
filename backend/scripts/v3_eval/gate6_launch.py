"""Preflight-only by default; inject only the provider key into one child."""
from pathlib import Path
import argparse
import os
import subprocess
import sys

HERE=Path(__file__).resolve().parent
PYTHON=Path('C:/Users/MingZheYang/anaconda3/envs/video-factory/python.exe')


def child_environment(parent,root,reader=None):
    env=dict(parent)
    if not env.get('DASHSCOPE_API_KEY'):
        if reader is None:
            from safety import _credential_lines
            reader=_credential_lines
        selected=reader(Path(root)/'.env',{'DASHSCOPE_API_KEY'})
        if set(selected)-{'DASHSCOPE_API_KEY'}:
            raise RuntimeError('Credential reader returned an unapproved key')
        env['DASHSCOPE_API_KEY']=selected.get('DASHSCOPE_API_KEY','')
    if not env.get('DASHSCOPE_API_KEY'):
        raise RuntimeError('Provider key is unavailable; no child started')
    env.update(PYTHON_DOTENV_DISABLED='1',FLASK_SKIP_DOTENV='1',
        DASHSCOPE_API_BASE_URL='https://dashscope.aliyuncs.com/api/v1',
        DASHSCOPE_OPENAI_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1',
        DEEPSEEK_API_KEY='',OPENAI_API_KEY='')
    return env


def child_command(args,entry):
    command=[str(PYTHON),'-X','utf8','-I','-B',str(entry),
        '--work',args.work,'--label',args.label,'--expected-commit',args.expected_commit,
        '--full-evidence',args.full_evidence,'--execute']
    if args.manifest: command+=['--manifest',args.manifest]
    if args.approve_manifest_sha256: command+=['--approve-manifest-sha256',args.approve_manifest_sha256]
    return command


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',required=True)
    parser.add_argument('--label',choices=['01-c3-1','02-c3-2','03-c7','04-identity'],required=True)
    parser.add_argument('--expected-commit',required=True); parser.add_argument('--full-evidence',required=True)
    parser.add_argument('--manifest'); parser.add_argument('--approve-manifest-sha256')
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    sys.path.insert(0,str(HERE))
    from gate6_entry import ROOT,SCRIPTS,source,TEMP
    sys.path.insert(0,str(SCRIPTS))
    source(args.expected_commit,args.full_evidence)
    raw=str(args.work)
    if raw.startswith(('\\\\','//','\\/','/\\')):
        raise RuntimeError('Work must be local TEMP')
    work=Path(raw).resolve()
    if not work.is_relative_to(TEMP) or not work.name.startswith('cinecrew-v13-gate6-'):
        raise RuntimeError('Dedicated Gate6 TEMP work required')
    if (work/(args.label+'.started.json')).exists() or (work/'.v13-active.lock').exists():
        raise RuntimeError('Phase already started or round active; never overwrite evidence')
    entry=SCRIPTS/'gate6_entry.py'
    if HERE!=SCRIPTS or not entry.is_file() or not PYTHON.is_file():
        raise RuntimeError('Run only the formally committed Gate6 launcher and fixed conda interpreter')
    if not args.execute:
        print('Gate6 source/full preflight passed; no credentials read and no child started.')
        return 0
    env=child_environment(os.environ,ROOT)
    try:
        return subprocess.run(child_command(args,entry),env=env,cwd=ROOT,
            shell=False,check=False).returncode
    finally:
        env.pop('DASHSCOPE_API_KEY',None)


if __name__=='__main__': raise SystemExit(main())
