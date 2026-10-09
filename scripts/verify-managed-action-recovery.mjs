import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const root=mkdtempSync(path.join(tmpdir(),'neyvia-managed-recovery-'));
try {
  const result=spawnSync(resolveNeyviaPython().python,['-c',String.raw`
import json,sys
from pathlib import Path
from grant_agent.neyvia_agent import NeyviaToolGateway
root=Path(sys.argv[1]);count=root/'count';count.write_text('0')
class Package:
 def describe_tool_suite(self,p):return {'executionReady':True,'operations':[{'operationId':'write','permissions':['artifact.write']},{'operationId':'read','permissions':['artifact.read']}]}
 def execute_tool_operation(self,p):
  if p['operationId']=='write':count.write_text(str(int(count.read_text())+1))
  if p['arguments'].get('fail'):raise RuntimeError('effect occurred before lost response')
  return {'ok':True,'status':'completed','value':count.read_text()}
g=NeyviaToolGateway(root,allow_mutations=True,action_scope='managed');g.capabilities=Package()
missing=g.call_managed('fixture','write',{})
first=g.call_managed('fixture','write',{},action_id='one')
h=NeyviaToolGateway(root,allow_mutations=True,action_scope='managed');h.capabilities=Package()
saved=h.call_managed('fixture','write',{},action_id='one')
conflict=h.call_managed('fixture','write',{'different':True},action_id='one')
checks={'missingIdHasNoEffect':missing['status']=='action_id_required' and count.read_text()=='1',
 'postconditionUnverified':first['ok'] and first['operationStatus']=='unverified',
 'restartDoesNotRepeat':saved['duplicateSuppressed'] and count.read_text()=='1',
 'changedIntentRejected':conflict['status']=='action_conflict',
 'readNeedsNoId':h.call_managed('fixture','read',{})['ok']}
failed=h.call_managed('fixture','write',{'fail':True},action_id='lost')
again=h.call_managed('fixture','write',{'fail':True},action_id='lost')
checks['uncertainDoesNotRepeat']=failed['status']=='action_uncertain' and again['status']=='action_uncertain' and count.read_text()=='2'
checks['recoveryInspectable']=bool(h.recoveries.list()) and bool(h.actions.inspect('lost'))
readonly=NeyviaToolGateway(root,action_scope='readonly');readonly.capabilities=Package()
checks['authorityRetained']=readonly.call_managed('fixture','write',{},action_id='denied')['status']=='approval_required' and count.read_text()=='2'
from grant_agent.neyvia_agent import ModelToolIntelligence
ModelToolIntelligence.resolve_openai_call=lambda *a,**kw:{'requiresApproval':True,'callTarget':'fixture.write','arguments':kw['arguments']}
h._compiled_tool_belt={}
def compiled(p):
 count.write_text(str(int(count.read_text())+1))
 return {'status':'completed','receiptPath':str(count)}
h.capabilities.run_model_tool_plan=compiled
compiled_missing=h.call_compiled('fixture.write',{})
compiled_first=h.call_compiled('fixture.write',{},action_id='compiled')
compiled_saved=h.call_compiled('fixture.write',{},action_id='compiled')
checks['compiledStableAction']=compiled_missing['status']=='action_id_required' and compiled_first['operationStatus']=='unverified' and compiled_saved['duplicateSuppressed'] and count.read_text()=='3'
print(json.dumps(checks))
`,root],{env:{...process.env,PYTHONPATH:path.resolve('src')},encoding:'utf8',timeout:30000});
  assert.equal(result.status,0,result.stderr||result.stdout);
  const checks=JSON.parse(result.stdout);for(const [key,value] of Object.entries(checks))assert.equal(value,true,key);
  console.log(JSON.stringify({status:'verified',checks,boundary:'Real file effects behind a disposable package adapter; no external service call or postcondition-verification claim.'}));
}finally{rmSync(root,{recursive:true,force:true});}
