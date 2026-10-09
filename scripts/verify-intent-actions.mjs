import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=resolveNeyviaPython(repo).python; const root=mkdtempSync(path.join(tmpdir(),'neyvia-intent-'));
try {
 const result=spawnSync(python,['-c',String.raw`
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys,json,time
from grant_agent.intent_actions import IntentAction
stamp=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(); rows=[{'id':'save-1','semanticTarget':'save','state':'idle','observedAt':stamp}]; calls=[]
a=IntentAction(observe=lambda:rows,gateway=lambda p:calls.append(p) or {'accepted':True})
r=a.execute({'semanticTarget':'save','acceptableIds':['save-1'],'action':'save','expectedTransition':{'state':'saved'}},authority={'granted':True}); checks={'postcondition':r['status']=='postcondition_failed' and len(calls)==1}
rows[0]['state']='saved'; checks['stalePostRefused']=a.execute({'semanticTarget':'save','acceptableIds':['save-1'],'action':'save','expectedTransition':{'state':'saved'}},authority={'granted':True})['status']=='postcondition_failed'
def fresh():
 time.sleep(0.002)
 return [{**row,'observedAt':datetime.now(timezone.utc).isoformat()} for row in rows]
a.observe=fresh
checks['verified']=a.execute({'semanticTarget':'save','acceptableIds':['save-1'],'action':'save','expectedTransition':{'state':'saved'}},authority={'granted':True})['status']=='verified'
rows[:]=[{'id':'a','semanticTarget':'save','observedAt':stamp},{'id':'b','semanticTarget':'save','observedAt':stamp}]; checks['ambiguous']=a.resolve({'semanticTarget':'save'})['status']=='ambiguous_target'
a.observe=lambda:rows
rows[:]=[{'id':'save-1','semanticTarget':'save','observedAt':(datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat()}]; checks['stale']=a.resolve({'semanticTarget':'save','maxAgeSeconds':30})['status']=='target_not_found'
rows[:]=[{'id':'save-1','semanticTarget':'save','state':'saved','observedAt':stamp}]
from grant_agent.verified_operations import VerifiedOperationStore
s=VerifiedOperationStore(Path(sys.argv[1]),'intent'); first=IntentAction(observe=fresh,gateway=lambda p:{'ok':True},verified_store=s).execute({'semanticTarget':'save','action':'save','expectedTransition':{'state':'saved'}},operation_id='op-1',authority={'granted':True}); checks['durableVerified']=first['status']=='verified'
second=IntentAction(observe=fresh,gateway=lambda p:(_ for _ in ()).throw(AssertionError('replayed')),verified_store=s).execute({'semanticTarget':'save','action':'save','expectedTransition':{'state':'saved'}},operation_id='op-1',authority={'granted':True}); checks['duplicate']=second['status']=='duplicate_suppressed'
print(json.dumps(checks,separators=(',',':')))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:90000});
 assert.equal(result.status,0,result.stderr||result.stdout); const checks=JSON.parse(result.stdout.trim()); for(const [name,value] of Object.entries(checks)) assert.equal(value,true,name); console.log(JSON.stringify({status:'verified',checks}));
} finally {rmSync(root,{recursive:true,force:true});}
