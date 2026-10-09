import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'); const python=resolveNeyviaPython(repo).python; const root=mkdtempSync(path.join(tmpdir(),'neyvia-adapter-'));
try { const result=spawnSync(python,['-c',String.raw`
from pathlib import Path
import json,sys
from grant_agent.neyvia_agent import NeyviaToolGateway
root=Path(sys.argv[1]); args={'applicationId':'adapter_app','source':{'path':'src/app.ts'},'buildRecipe':{'command':'npm run build'}}
g=NeyviaToolGateway(root,allow_mutations=True,action_scope='adapter',allowed_mutation_tools={'semantic.application.register'})
first=g.call_native('semantic.application.register',args,action_id='register-1'); assert first['ok'] and first['operationStatus']=='verified'
path=root/'.agent_control'/'living_applications'/'adapter_app.json'; assert path.is_file()
fresh=NeyviaToolGateway(root,allow_mutations=True,action_scope='adapter',allowed_mutation_tools={'semantic.application.register'}); second=fresh.call_native('semantic.application.register',args,action_id='register-1'); assert second['duplicateSuppressed']
value=json.loads(path.read_text()); value['source']={'path':'tampered'}; path.write_text(json.dumps(value))
third=fresh.call_native('semantic.application.register',{**args,'buildRecipe':{'command':'changed'}},action_id='register-2'); assert third['status'] in {'failed','action_uncertain'} and third.get('operationStatus') in {'failed','unknown_side_effects'}
print('OPERATION_ADAPTER_VERIFIED: semantic application registration postcondition hash, duplicate suppression, altered artifact refusal')
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:90000}); assert.equal(result.status,0,result.stderr||result.stdout); console.log(result.stdout.trim()); } finally {rmSync(root,{recursive:true,force:true});}
