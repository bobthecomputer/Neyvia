"""Everyday file tasks in persistent hidden Command Prompt and PowerShell."""
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.cua_guard import ZeroDisturbanceGuard
from run_c11_cohort import write_receipt
from c1_native_benchmark import quantile


class HiddenShell:
    def __init__(self,argv,target,guard):
        argv=[str(Path(argv[0])),*argv[1:]]
        self.argv,self.target,self.guard=argv,target,guard
        self.command_prompt=Path(argv[0]).name.casefold()=='cmd.exe'
        self.finished_pids=[]
        if self.command_prompt:
            self.process=None
            return
        self.process=subprocess.Popen(argv,cwd=target,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW)
        guard.register_pid(self.process.pid)
        self.lines=queue.Queue()
        def read():
            for line in self.process.stdout:self.lines.put(line.rstrip())
        threading.Thread(target=read,daemon=True).start()

    def call(self,command):
        if self.command_prompt:
            batch=self.target/('task-'+uuid.uuid4().hex+'.cmd')
            batch.write_bytes(('@echo off\r\n'+command.replace('\n','\r\n')+'\r\n').encode('utf-8'))
            process=subprocess.Popen([*self.argv,'/c',str(batch)],cwd=self.target,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.guard.register_pid(process.pid)
            output=process.communicate(timeout=10)[0]
            self.finished_pids.append(process.pid)
            if process.returncode:raise RuntimeError('Disposable command failed: '+output[:300])
            return output.splitlines()
        marker='END_'+uuid.uuid4().hex
        self.process.stdin.write(command+'\necho '+marker+'\n');self.process.stdin.flush()
        output=[];deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            value=self.lines.get(timeout=max(.01,deadline-time.monotonic()))
            # cmd's prompt and echoed completion command may share a line.
            # It reaches that command only after the requested command finishes;
            # every task independently reads the resulting file immediately.
            if marker in value:return output
            output.append(value)
        raise TimeoutError('Hidden shell command did not return its completion marker')

    def close(self):
        if self.command_prompt:return {'processExited':True,'pids':self.finished_pids,'mode':'one CREATE_NO_WINDOW process per call; startup included in atomic timing'}
        if self.process.poll() is None:
            try:self.process.stdin.write('exit\n');self.process.stdin.flush()
            except OSError:pass
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=5)
        return {'processExited':self.process.poll() is not None,'pid':self.process.pid}


def run():
    token=uuid.uuid4().hex;target=ROOT/'.agent_control/c11f-shell'/token;target.mkdir(parents=True)
    guard=ZeroDisturbanceGuard().start()
    result={'schema':'neyvia.c11f.shell.v1','token':token,'modelTokens':0,'tasks':[],
            'boundary':'CREATE_NO_WINDOW shells; disposable user files only',
            'timing':'Fresh input listing -> command -> shell readback and independent file check. Cold cmd process startup included per call; persistent PowerShell initialization excluded and reported separately.',
            'sourceSha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                for name in ('scripts/prove_c11f_shell.py','src/grant_agent/cua_guard.py')}}
    scripts=[
        ('Command Prompt','write-note','Write a note to a disposable text file',
         'echo {value}> note.txt',lambda value:(target/'note.txt').read_text().strip()==value),
        ('Command Prompt','copy-note','Copy a note and verify its exact content',
         'echo {value}> source.txt\ncopy /y source.txt copy.txt >nul',lambda value:(target/'copy.txt').read_text().strip()==value),
        ('Command Prompt','rename-note','Rename a disposable draft without losing content',
         'echo {value}> draft.txt\nmove /y draft.txt renamed.txt >nul',lambda value:not (target/'draft.txt').exists() and (target/'renamed.txt').read_text().strip()==value),
        ('Windows PowerShell','write-list','Create a grocery list as a UTF-8 file',
         "Set-Content -LiteralPath './list.txt' -Value '{value}' -Encoding utf8",lambda value:(target/'list.txt').read_text(encoding='utf-8-sig').strip()==value),
        ('Windows PowerShell','search-notes','Find a requested phrase in disposable notes',
         "Set-Content './search.txt' '{value}'; (Select-String -LiteralPath './search.txt' -SimpleMatch '{value}').Line | Set-Content './match.txt'",lambda value:(target/'match.txt').read_text(encoding='utf-8-sig').strip()==value),
        ('Windows PowerShell','archive-notes','Create and reopen a ZIP containing a note',
         "Set-Content './archive-note.txt' '{value}'; Compress-Archive -LiteralPath './archive-note.txt' -DestinationPath './notes.zip' -Force",lambda value:zipfile.ZipFile(target/'notes.zip').read('archive-note.txt').decode('utf-8-sig').strip()==value)]
    for app,argv in [('Command Prompt',['C:/Windows/System32/cmd.exe','/d','/q']),
                     ('Windows PowerShell',['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-Command','-'])]:
        shell=None
        try:
            start=time.perf_counter();shell=HiddenShell(argv,target,guard);shell.call('echo ready')
            startup=(time.perf_counter()-start)*1000
            for name,task_id,goal,command,check in scripts:
                if name!=app:continue
                row={'id':task_id,'app':app,'goal':goal,'startupMs':round(startup,3),'attempts':[],
                     'replay':'deterministic application command; no model calls, not claimed as learned UIA flow'}
                result['tasks'].append(row)
                for i in range(5):
                    value='C11_'+token+'_'+task_id+'_'+str(i)
                    tick=time.perf_counter();before=sorted(p.name for p in target.iterdir())
                    output=shell.call(command.format(value=value));ok=check(value)
                    row['attempts'].append({'passed':ok,'actionSent':True,'atomicMs':round((time.perf_counter()-tick)*1000,3),
                        'inputObservation':before,'applicationOutput':output,'independentFileCheck':ok,'tokens':0})
                row['ok']=all(a['passed'] for a in row['attempts'])
        except Exception as exc:result.setdefault('errors',[]).append({'app':app,'error':type(exc).__name__+': '+str(exc)})
        finally:
            if shell:result.setdefault('cleanup',[]).append(shell.close())
    result['guard']=guard.close()
    result['distinctTasksCompleted']=sum(r['ok'] for r in result['tasks'])
    times=[a['atomicMs'] for r in result['tasks'] for a in r['attempts']]
    result['p50Ms']=quantile(times,.5)
    result['ok']=result['distinctTasksCompleted']==6 and result['guard']['ok'] and not result.get('errors')
    return result

if __name__=='__main__':
    result=run();write_receipt(ROOT/'scripts/evidence/C11f-shell.json',result)
    print(json.dumps({k:result.get(k) for k in ['ok','distinctTasksCompleted','p50Ms','errors']}))
    raise SystemExit(0 if result['ok'] else 2)
