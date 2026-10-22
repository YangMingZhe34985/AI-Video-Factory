"""Fail-closed local execution/SQLite guard for the Gate6 evaluation process."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import threading
from urllib.parse import urlsplit,unquote

from gate6_budget import require



def checked_sqlite(value,work):
    if value==':memory:': return
    work=Path(work).resolve()
    if value.startswith('file:'):
        parsed=urlsplit(value)
        require(parsed.scheme=='file' and not parsed.netloc and not parsed.fragment and parsed.query=='mode=ro','Only exact read-only audit SQLite URI accepted')
        raw=unquote(parsed.path)
        if os.name=='nt' and re.match(r'^/[A-Za-z]:/',raw): raw=raw[1:]
        require(not raw.startswith(('\\\\','//')) and '\\' not in raw,'Unsafe SQLite URI path')
        path=Path(raw).resolve()
        require(path in {work/'eval.db',work/'real_call_audit.sqlite'},'Read-only URI outside the two evaluation databases')
        return
    require(not value.startswith(('\\\\','//','\\/','/\\')) and not re.match(r'^[A-Za-z]:[^\\/]',value),'Network/device/drive-relative SQLite path forbidden')
    require(Path(value).resolve().is_relative_to(work),'SQLite outside unique Gate6 work directory')


def install_guard(root,work,ffmpeg,transport_getter):
    root,work,ffmpeg=map(lambda p:Path(p).resolve(),(root,work,ffmpeg))
    git=Path(shutil.which('git') or '').resolve()
    require(git.is_file() and ffmpeg.is_file(),'Fixed Git and FFmpeg binaries required')
    original=subprocess.Popen
    local=threading.local()
    def blocked(reason):
        transport=transport_getter()
        if transport is not None: transport.meter._block('network',reason)
        raise RuntimeError(reason)
    def validate(argv,shell=False,executable=None):
        require(shell is False and isinstance(argv,(list,tuple)) and argv and all(isinstance(a,(str,os.PathLike)) for a in argv),'Only explicit argv without shell is accepted')
        argv=list(map(os.fspath,argv)); first=argv[0]
        if first.lower() in {'git','git.exe'} or Path(first).resolve()==git:
            require(argv[1:3]==['-C',str(root)],'Wrong Git repository')
            require(argv[3:] in [['rev-parse','HEAD'],['branch','--show-current'],['ls-files','--cached','--others','--exclude-standard','-z'],
                ['status','--porcelain=v1','--untracked-files=all','--','backend','frontend-vue','factory_prompts','docs']],'Git operation not allowlisted')
            program=git
        elif Path(first).resolve()==ffmpeg:
            program=ffmpeg
            for arg in argv[1:]:
                # Block remote protocols even inside a concat/filter expression.
                require(not re.search(r'(?i)(https?|rtsp|rtmp|ftp|sftp|smb|tcp|udp|tls|file|crypto|srt):',arg)
                    and not arg.startswith(('\\\\','//','\\/','/\\')),'Remote FFmpeg access is forbidden')
        else: raise RuntimeError('Only fixed FFmpeg and read-only Git are allowed')
        require(executable is None or Path(executable).resolve()==program,'Executable override changed')
        argv[0]=str(program)
        return argv,program
    class GuardedPopen(original):
        def __init__(self,*positional,**keywords):
            require(len(positional)<=1 and not(positional and 'args' in keywords),'Ambiguous subprocess invocation')
            argv,program=validate(positional[0] if positional else keywords.pop('args',None),keywords.get('shell',False),keywords.get('executable'))
            require(getattr(local,'token',None) is None,'Nested subprocess call')
            token={'argv':argv,'executable':program,'command_line':subprocess.list2cmdline(argv),'seen':False}
            local.token=token
            try:
                super().__init__(argv,**{**keywords,'shell':False,'executable':str(program)})
                require(token['seen'],'Subprocess audit did not correlate')
            finally: local.token=None
    def audit(event,args):
        if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            raw=os.fsdecode(args[0]); name=Path(raw).name.casefold()
            if raw.startswith(('\\\\','//','\\/','/\\')) or name=='.env' or name.startswith('.env.') or name=='ai_video_factory_technical_notes_cn.md':
                blocked('Private configuration or network filesystem access')
        if event=='sqlite3.connect':
            checked_sqlite(str(args[0]),work)
        if event in {'os.system','os.startfile','os.startfile/2'}: blocked('Shell/external program access')
        if event=='subprocess.Popen':
            token=getattr(local,'token',None)
            require(token is not None and not token['seen'],'No exact subprocess token')
            require(args[0] is not None and Path(os.fsdecode(args[0])).resolve()==token['executable'],'Subprocess executable mismatch')
            require(args[1]==token['command_line'] if isinstance(args[1],str) else list(args[1])==token['argv'],'Subprocess argv mismatch')
            token['seen']=True
        if event.startswith('socket.'):
            transport=transport_getter()
            dest=getattr(transport.local,'destination',None) if transport else None
            if event=='socket.getaddrinfo':
                name=args[0].decode() if isinstance(args[0],bytes) else str(args[0])
                if dest!=(name.lower(),int(args[1])): blocked('DNS outside exact provider request')
            elif event in {'socket.connect','socket.connect_ex'}:
                address=args[1]
                if not dest or not isinstance(address,tuple) or address[0] not in transport.local.ips or address[1]!=443:
                    blocked('Socket outside exact provider request')
            elif event in {'socket.sendto','socket.sendmsg','socket.gethostbyname','socket.gethostbyaddr'}:
                blocked('Unaudited socket operation')
    subprocess.Popen=GuardedPopen
    sys.addaudithook(audit)
    return {'popen_class':GuardedPopen,'validate_command':validate}
