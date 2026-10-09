"""Real native JSON admission, refusal receipts and owned stdio user path."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.port not in range(48741,48750):parser.error('Explicit assigned port required')
    output=args.output.resolve();output.relative_to(REPO/'scripts/evidence')
    root=REPO/'.agent_control/proofs'/('c7d-admission-'+uuid.uuid4().hex);root.mkdir()
    for key in ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA','CODEX_HOME','TEMP','TMP'):
        path=root/'home'/key.lower();path.mkdir(parents=True);os.environ[key]=str(path)
    os.environ.update(NEYVIA_NAS_ROOT=str(root),NEYVIA_C7_PORT=str(args.port),NEYVIA_COORDINATOR_AUTOSTART='0',FLUXIO_WATCHDOG_AUTOSTART='0',NEYVIA_TOOL_AUTO_UPDATE='0',PYTHONPATH=str(REPO/'src'),PYTHONIOENCODING='utf-8')
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.edge_journeys import run
    from grant_agent.proof_contracts import source_digest
    names=['scripts/prove_C7d_admission.py','src/grant_agent/native_tools.py','src/grant_agent/native_arguments.py','src/grant_agent/native_tool_worker.py','src/grant_agent/proofs_d_native.py','src/grant_agent/edge_journeys.py']
    bindings={n:source_digest(REPO/n) for n in names}
    rows=run(root/'journeys')
    if not rows or any(r['status']!='passed' for r in rows):raise AssertionError(rows)
    worker_root=root/'stdio';worker_root.mkdir()
    requests=[{'id':'invalid-content','tool':'workspace.write','arguments':{'path':'rejected-content/file.txt','content':'\ud800'}},
        {'id':'invalid-path','tool':'workspace.write','arguments':{'path':'rejected-\ud800/file.txt','content':'safe'}},
        {'id':'valid-unicode','tool':'workspace.write','arguments':{'path':'owned-雪.txt','content':'Exact 雪🙂 e\u0301\r\nbytes'}},
        {'id':'shutdown','command':'shutdown'}]
    env={**os.environ,'NEYVIA_BROWSER_OWNER_COOKIE':'neyvia_session=generated-unused-fixture','NEYVIA_BROWSER_CONTEXT_URL':f'http://127.0.0.1:{args.port}/owned'}
    child=subprocess.run([sys.executable,'-m','grant_agent.native_tool_worker','--root',str(worker_root),'--browser-transport','neyvia','--browser-port',str(args.port)],
        cwd=REPO,env=env,input=''.join(json.dumps(r)+'\n' for r in requests),capture_output=True,text=True,encoding='utf8',timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    values=[json.loads(line) for line in child.stdout.splitlines()]
    if child.returncode or len(values)!=4 or not all(r.get('ok') for r in values):raise AssertionError({'exit':child.returncode,'responses':values,'stderr':child.stderr[-1000:]})
    receipts=[]
    for response in values[:3]:
        receipt=response['data'];path=Path(receipt['receipt_path']);path.relative_to(worker_root)
        if json.loads(path.read_text(encoding='utf8'))!={k:v for k,v in receipt.items() if k!='worker'}:raise AssertionError('Stdio receipt differs from durable JSON')
        if receipt['worker']['browserStarts'] or receipt['worker']['contextsCreated']:raise AssertionError('Workspace admission started a browser')
        if response['id'].startswith('invalid'):
            if receipt['ok'] or receipt['proofs']['phase']!='validation' or receipt['arguments']!={}:raise AssertionError('Malformed Unicode reached an effect or admitted snapshot')
        elif not receipt['ok'] or (worker_root/'owned-雪.txt').read_bytes()!=requests[2]['arguments']['content'].encode('utf8'):raise AssertionError('Valid Unicode changed')
        receipts.append({'requestId':response['id'],'ok':receipt['ok'],'phase':receipt['proofs']['phase'],'snapshot':receipt['arguments'],'receiptPath':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'receiptHash':receipt['receiptHash']})
    if (worker_root/'rejected-content').exists() or (worker_root/'rejected-\ud800').exists():raise AssertionError('Rejected path was created')
    if bindings!={n:source_digest(REPO/n) for n in names}:raise AssertionError('Admission sources changed')
    prior=REPO/'.agent_control/proofs/c7d-mesh-loader-after.json'
    before=json.loads(prior.read_text(encoding='utf8'))['failures']
    report={'schema':'neyvia.c7d-native-admission.v1','ok':True,'explicitPort':args.port,'root':str(root),'sourceBindings':bindings,'sourceStable':True,
        'beforeFailedCases':before,'beforeReceipt':str(prior),'beforeSha256':hashlib.sha256(prior.read_bytes()).hexdigest(),
        'journeys':rows,'actualStdioReceipts':receipts,'workerExit':child.returncode,'noBrowserContextCreated':True,
        'boundary':'Actual native call and persistent stdio JSON transport: invalid Unicode refused before effects; durable failure JSON remains usable and valid Unicode bytes are exact. No rendered or provider claim.'}
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'ok':True,'journeysPassed':len(rows),'actualStdioCalls':3}))

if __name__=='__main__':main()
