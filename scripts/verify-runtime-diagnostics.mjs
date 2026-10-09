import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const root=mkdtempSync(path.join(tmpdir(),'neyvia-runtime-diagnostics-'));
try {
  const process_=spawnSync(resolveNeyviaPython(process.cwd()).python,['-c',String.raw`
import json,sys,hashlib
from pathlib import Path
from grant_agent.native_tools import NativeToolRegistry,ReusablePlaywrightRuntime
from grant_agent.runtime_diagnostics import failure_record,context_observation,completion_evidence
from grant_agent.adaptive_work import AdaptiveWorkStore
root=Path(sys.argv[1]);r=NativeToolRegistry(root)
missing=r.call('host.launch',{'executable':str(root/'missing.exe')})
invalid=r.call('preview.inspect',{})
unknown=failure_record(RuntimeError('blocked by policy'),tool='external',phase='execution',mutability='process_execute')
os_error=failure_record(PermissionError('access denied'),tool='external',phase='execution',mutability='read')
preflight=r.call('runtime.preflight',{'tools':['host.programs','no-such-tool']})
success=r.call('host.programs',{})
evidence=r.call('runtime.evidence',{'limit':20})
checkpoint=root/'proof'/'semantic-primitives'/'operating-checkpoint.json'
checkpoint.parent.mkdir(parents=True)
source=root/'source.txt';source.write_text('original')
payload={'schema':'neyvia.operating_checkpoint.v1','files':[{'path':'source.txt','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}],'gates':[{'name':'Browser journey','status':'pending','evidence':'Not observed'}]}
checkpoint.write_text(json.dumps(payload))
fresh=r.call('runtime.completion',{})
source.write_text('changed')
stale=completion_evidence(root)
payload['files'][0]['path']='../outside.txt';checkpoint.write_text(json.dumps(payload))
outside=completion_evidence(root)
checkpoint.write_text('[]');malformed=completion_evidence(root)
work=AdaptiveWorkStore(root,'constraints')
for i in range(20):work.record_constraint(('Preserve this user decision '+str(i)+' ')*12,source='user')
packet=work.packet(token_budget=180)
class Context:
 def new_page(self):return object()
 def close(self):pass
class Browser:
 def __init__(self,fail):self.fail=fail
 def new_context(self,**kwargs):
  if self.fail:raise ConnectionError('detached before page')
  return Context()
runtime=ReusablePlaywrightRuntime(root); attempts=[]; actions=[]
def ensure():
 attempts.append(1);return Browser(len(attempts)==1),False
runtime._ensure_browser=ensure;runtime._browser_is_connected=lambda:False;runtime.close=lambda:None
try:
 with runtime.page(width=800,height=600):
  actions.append(1);raise ConnectionError('failed after action')
except ConnectionError:pass
print(json.dumps({'fresh':fresh,'stale':stale,'outside':outside,'malformed':malformed,'missing':missing,'invalid':invalid,'unknown':unknown,'os':os_error,'preflight':preflight,'evidence':evidence,'packet':packet,'totalConstraints':len(work.snapshot()['constraints']),'attempts':len(attempts),'actions':len(actions),'context':context_observation(root)}))
`,root],{encoding:'utf8',timeout:30000,env:{...process.env,PYTHONPATH:path.resolve('src')}});
  assert.equal(process_.status,0,process_.stderr);
  const result=JSON.parse(process_.stdout);
  assert.equal(result.missing.ok,false);
  assert.equal(result.fresh.result.status,'current');
  assert.equal(result.fresh.result.claimVerification,'not_independently_verified');
  assert.equal(result.fresh.result.gates[0].reportedStatus,'pending');
  assert.equal(result.stale.status,'stale');
  assert.equal(result.outside.status,'stale');
  assert.equal(result.outside.files[0].matches,false);
  assert.equal(result.malformed.status,'unreadable');
  assert.equal(result.missing.failure.sideEffects,'uncertain');
  assert.equal(result.invalid.failure.stage,'validation');
  assert.equal(result.invalid.failure.kind,'invalid_arguments');
  assert.equal(result.unknown.kind,'unknown');
  assert.equal(result.unknown.policyOwner,null);
  assert.equal(result.unknown.automaticRetry,false);
  assert.equal(result.os.kind,'operating_system_access');
  assert.equal(result.preflight.result.configurationReady,false);
  assert.equal(result.preflight.result.executionReady,false);
  assert.equal(result.evidence.result.tokenCost,null);
  assert(result.evidence.result.tools.some(row=>row.tool==='host.programs'&&row.successfulCalls===1));
  assert.equal(result.packet.executionReady,false);
  assert(result.packet.requiredConstraintsOmitted>0);
  assert.equal(result.packet.nextAction.tool,'work.state');
  assert.equal(result.totalConstraints,20);
  assert(JSON.stringify(result.packet).length<=720);
  assert.equal(result.attempts,2,'reconnect only before exposing the page');
  assert.equal(result.actions,1,'never replay the body after an uncertain action');
  assert.equal(result.context.executionVerified,false);
  assert(result.context.unavailableTools.includes('no-such-tool'));
  console.log('PASS: failure provenance, unknown policy ownership, conservative retry, configuration boundary, real receipt metrics, protected-constraint retrieval and budget');
} finally {rmSync(root,{recursive:true,force:true});}
