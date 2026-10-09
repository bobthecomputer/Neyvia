import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'); const python=resolveNeyviaPython(repo).python; const root=mkdtempSync(path.join(tmpdir(),'neyvia-adaptive-'));
try { const result=spawnSync(python,['-c',String.raw`
import json,sys
from pathlib import Path
from grant_agent.adaptive_work import AdaptiveWorkStore
from grant_agent.context_engine import DurableContextEngine
root=Path(sys.argv[1]); s=AdaptiveWorkStore(root,'mission'); s.change_focus('reconcile upload proof',source='user'); s.record_constraint('Never publish current',source='user'); s.record_problem('Upload receipt is missing',source='user'); s.record_dependency('Preview runtime',source='user'); s.record_evidence('upload complete',status='verified',identity='receipt-1',sha256='a'*64); s.record_evidence('upload complete',status='failed',identity='receipt-2'); s.record_evidence('second claim',status='reported'); p=s.packet(token_budget=700); fresh=AdaptiveWorkStore(root,'mission'); e=DurableContextEngine(root,'mission2',max_context_tokens=2048,reserve_tokens=128); e.append('user','Need inspect blocker',kind='blocker'); b=e.build_bundle(token_budget=900); corrupt=root/'.agent_control'/'adaptive_work'/'corrupt.json'; corrupt.write_text('{bad',encoding='utf8'); corruptFails=False
try: AdaptiveWorkStore(root,'corrupt').snapshot()
except ValueError: corruptFails=True
print(json.dumps({'focus':p['focus']['text']=='reconcile upload proof','constraint':p['constraints'][0]['text']=='Never publish current','contradiction':any(x.get('status')=='contradicted' for x in fresh.snapshot()['evidence']),'reportedUnverified':any(x.get('status')=='unverified' for x in fresh.snapshot()['evidence']),'nextAction':p['nextAction']['kind']=='test','reload':fresh.snapshot()['revision']==s.snapshot()['revision'],'bounded':len(json.dumps(p,separators=(',',':')))<=2800,'corruptFailsClosed':corruptFails,'bundle': 'adaptiveWork' in b and b['adaptiveWork']['nextAction']['kind']=='inspect'},separators=(',',':')))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:30000}); assert.equal(result.status,0,result.stderr||result.stdout); const checks=JSON.parse(result.stdout.trim()); for(const [name,value] of Object.entries(checks)) assert.equal(value,true,name); console.log(JSON.stringify({status:'verified',checks})); } finally {rmSync(root,{recursive:true,force:true});}
