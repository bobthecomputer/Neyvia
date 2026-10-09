"""Actual CL command completion and corrupt-journal refusal; no model needed."""
import hashlib
import json
from pathlib import Path
import sys
import time
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from grant_agent.cl.protocol import Protocol
from grant_agent.cl.terminal_receipts import observe
from grant_agent.neyvia_agent import NeyviaToolGateway

def main():
    root=REPO/'.agent_control/c4'/f'c4c-terminal-{time.time_ns()}'
    root.mkdir(parents=True);(root/'answer.txt').write_text('acceptance',encoding='utf-8')
    gateway=NeyviaToolGateway(root,allow_mutations=True,permission_mode='full-access',action_scope='c4c-terminal')
    protocol=Protocol(gateway);protocol.host.observation_mode='diff'
    protocol.run('G: "acceptance" in workspace.read(path="answer.txt")["content"]',action_id='goal')
    args={'command':'print("C4c actual terminal 739")','shell':'python','cwd':str(root),'timeoutMs':3000}
    completed=protocol.run('terminal.exec('+','.join(k+'='+repr(v) for k,v in args.items())+')',action_id='real-command')
    assert completed['ok'], completed
    assert 'C4c actual terminal 739' in completed['text'] and '+native-command-receipt' in completed['text']
    actions=gateway.actions.list()['actions']
    row=next(r for r in actions if r['toolId']=='terminal.exec')
    record_path=gateway.actions._path(row['actionId'])
    result_path=record_path.with_suffix('.result')
    saved=json.loads(result_path.read_text(encoding='utf-8'))
    raw={**saved,'actionId':row['actionId'],'duplicateSuppressed':False,'actionReceiptPath':str(record_path)}
    assert observe(gateway,raw,args)['exitCode']==0
    original=result_path.read_bytes()
    result_path.write_text('{}',encoding='utf-8')
    assert observe(gateway,raw,args) is None
    result_path.write_bytes(original)
    failed=protocol.run('terminal.exec(command="raise SystemExit(7)",shell="python",cwd='+repr(str(root))+',timeoutMs=3000)',action_id='nonzero')
    assert not failed['ok']
    done=protocol.run('done()',action_id='done')
    assert done['ok']
    report={'passed':True,'checks':['actual system-Python stdout and exitCode exposed through CL',
            'saved action/result independently reread and hash verified','corrupt result refused',
            'actual exit7 preserved as failure','observer goal and done still enforced'],
            'completed':completed,'failed':failed,'root':str(root),
            'sourceSha256':{p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in
                           [Path(__file__),REPO/'src/grant_agent/cl/integration.py',REPO/'src/grant_agent/cl/terminal_receipts.py']}}
    (REPO/'scripts/evidence/C4c-terminal.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'checks':report['checks']}))
if __name__=='__main__':main()
