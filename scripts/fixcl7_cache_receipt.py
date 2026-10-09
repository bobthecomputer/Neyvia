"""Measure unchanged regeneration and execute a bounded C7 CL contract case."""
from pathlib import Path
import json
import subprocess
import sys
import time
import hashlib

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO/'scripts'),str(REPO/'src')]
start = time.monotonic()
command = [sys.executable,str(REPO/'scripts/fixcl7_regenerate.py'),'--port','48781']
run = subprocess.run(command,cwd=REPO,capture_output=True,text=True,
    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
records = [json.loads(line) for line in run.stdout.splitlines() if line.startswith('{')]
from fixcl7_regenerate import PROBES
report = {'schema':'neyvia.FIXCL7.cache.v1','command':command,'seconds':round(time.monotonic()-start,3),
    'exitCode':run.returncode,'records':records,
    'allProbesCached':{row.get('probe') for row in records if row.get('status') == 'current'} == set(PROBES),
    'auditCached':any(row.get('audit') == 'current' for row in records)}
output = REPO/'scripts/evidence/FIXCL7-cache-proof.json'
output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
root = REPO/'.agent_control/proofs'/('FIXCL7-cache-contract-'+str(time.time_ns())); root.mkdir(parents=True,exist_ok=True)
witness = root/'measured-cache.json'; witness.write_bytes(output.read_bytes())
source = 'G: matches(workspace.read(path='+json.dumps(str(witness))+')["content"], '+json.dumps({
    'type':'string','allOf':[{'pattern':'"'+key+'"\\s*:\\s*true'} for key in ('allProbesCached','auditCached')]
})+')\ndone()'
from fixcl_verify import environment, guards
environment(root,48781); guards(root)
from grant_agent.proof_credential_guard import prepare_broker_fixture
prepare_broker_fixture(root)
from grant_agent.neyvia_agent import NeyviaToolGateway
from grant_agent.cl.protocol import Protocol
gateway = NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL7-cache-contract',permission_mode='workspace')
answer = Protocol(gateway).run(source,action_id='FIXCL7-cache-contract',scope_tools=['workspace.read'])
case = {'schema':'neyvia.FIXCL7.C7.contract-cases.v1','cases':[{'name':'unchanged-receipts-are-cached',
    'source':source,'result':answer,'measuredReceiptSha256':hashlib.sha256(output.read_bytes()).hexdigest(),
    'boundary':'One unchanged command, all 31 compiled workers reused and current 185-cell assessment reused. No full C7/C8 matrix claim.'}]}
(REPO/'scripts/evidence/FIXCL7-C7-cases.json').write_text(json.dumps(case,indent=2)+'\n',encoding='utf-8')
print(json.dumps({key:report[key] for key in ('seconds','exitCode','allProbesCached','auditCached')}|{'contractPassed':answer.get('ok') is True}))
raise SystemExit(0 if run.returncode == 0 and answer.get('ok') is True else 1)
