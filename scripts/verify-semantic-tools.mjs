import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'); const python=resolveNeyviaPython(repo).python; const root=mkdtempSync(path.join(tmpdir(),'neyvia-semantic-tools-'));
try {
 const result=spawnSync(python,['-c',String.raw`
import hashlib,json,sys
from pathlib import Path
from grant_agent.native_tools import NativeToolRegistry
root=Path(sys.argv[1]); fixture=root/'journey.txt'; fixture.write_text('observed upload result',encoding='utf-8'); digest=hashlib.sha256(fixture.read_bytes()).hexdigest(); reg=NativeToolRegistry(root)
catalog=reg.list_tools(include_schemas=True); names={row['name'] for row in catalog}
recovery=reg.call('semantic.recovery.create',{'failedOperation':{'operationId':'upload-1','intent':'upload fixture'},'operationId':'upload-1','uncertainEffects':[{'effect':'upload may have completed'}],'retrySafety':'requires_reconciliation','requiredAuthority':['workspace.write']})
rid=recovery['result']['recoveryId']; read=reg.call('semantic.recovery.read',{'recoveryId':rid})
proof=reg.call('semantic.proof.create',{'claim':'Preview upload works','build':{'revision':'fixture'},'environment':{'runtime':'test'},'startingState':{'route':'/preview'},'journey':[{'step':'upload'}],'actions':[{'intent':'choose file','observed':'fixture accepted'}],'artifacts':[{'path':'journey.txt','sha256':digest}],'result':{'status':'passed'},'limitations':[],'reproduction':{'command':'fixture'}})
pid=proof['result']['proofId']; verified=reg.call('semantic.proof.verify',{'proofId':pid}); failed=reg.call('semantic.proof.verify',{'proofId':'missing-proof'})
reg.semantic.memory_project({'sessionId':'semantic-session'})
from grant_agent.working_memory import WorkingMemoryStore
state=WorkingMemoryStore(root,'semantic-session').record_observation('upload.state','complete',source='receipt')
record_id=state['observations'][-1]['recordId']
found=reg.call('semantic.memory.find',{'sessionId':'semantic-session','query':'upload.state'}); recovered=reg.call('semantic.memory.retrieve',{'sessionId':'semantic-session','recordId':record_id})
memory=reg.call('semantic.memory.project',{'sessionId':'semantic-session','query':'','tokenBudget':500}); mission=reg.call('semantic.mission.create',{'missionId':'semantic-mission','desiredOutcome':'Verify semantic tools','acceptanceGates':['A proof exists']})
print(json.dumps({'names':sorted(names),'recovery':recovery,'read':read,'verified':verified,'failed':failed,'memory':memory,'found':found,'recovered':recovered,'recordId':record_id,'mission':mission},default=str))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:30000});
 assert.equal(result.status,0,result.stderr||result.stdout||result.error?.message); const output=JSON.parse(result.stdout); const required=['semantic.recovery.create','semantic.recovery.read','semantic.proof.create','semantic.proof.verify','semantic.memory.project','semantic.memory.read','semantic.memory.find','semantic.memory.retrieve','semantic.mission.create']; for (const name of required) assert(output.names.includes(name),`missing ${name}`); assert.equal(output.read.result.recovery.recoveryId,output.recovery.result.recoveryId); assert.equal(output.verified.result.verification.claimProven,false); assert.equal(output.verified.result.verification.semanticClaimStatus,'artifact_integrity_only'); assert.equal(output.verified.result.verification.artifactsVerified,true); assert.notEqual(output.failed.result.status,'completed'); assert.equal(output.memory.result.schema,'neyvia.working_memory_projection.v1'); assert(output.found.result.handles.some(item=>item.recordId===output.recordId)); assert.equal(output.recovered.result.record.recordId,output.recordId); assert.equal(output.mission.result.missionId,'semantic-mission'); console.log(JSON.stringify({status:'verified',evidence:'SEMANTIC_TOOLS_VERIFIED: discoverable bounded recovery/proof/memory/mission tools, durable find/retrieve, independent artifact verification, and truthful semantic-claim boundary',sha256:createHash('sha256').update(result.stdout).digest('hex')}));
} finally { rmSync(root,{recursive:true,force:true}); }
