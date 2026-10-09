import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=resolveNeyviaPython(repo).python;
const root=mkdtempSync(path.join(tmpdir(),'neyvia-adapters-'));
const result=spawnSync(python,['-c',String.raw`
import hashlib,json,shutil,sys,uuid
from pathlib import Path
from grant_agent.neyvia_agent import NeyviaToolGateway
target=Path.home()/'.codex'/'skills'/('_neyvia_adapter_'+uuid.uuid4().hex[:8]); target.mkdir(parents=True)
path=target/'SKILL.md'; original='---\nname: adapter-fixture\ndescription: fixture\n---\nOriginal instructions.\n'; updated='---\nname: adapter-fixture\ndescription: fixture\n---\nUpdated instructions.\n'; path.write_text(original)
try:
 g=NeyviaToolGateway(Path(sys.argv[1]),allow_mutations=True,action_scope='expanded',allowed_mutation_tools={'skill.live.iterate'})
 args={'path':str(path),'content':updated,'sessionId':'fixture'}
 first=g.call_native('skill.live.iterate',args,action_id='skill-1'); after=path.read_bytes(); receipt=json.loads(Path(first['operationReceiptPath']).read_text()); expected=receipt['result']['after']['sha256']
 failed=g.call_native('skill.live.iterate',{'path':str(path.parent/'escape'/'SKILL.md'),'content':updated,'sessionId':'fixture'},action_id='skill-bad')
 print(json.dumps({'firstOk':first.get('ok') is True,'operationStatus':first.get('operationStatus'),'contentMatches':path.read_text()==updated,'hashMatches':expected==hashlib.sha256(after).hexdigest(),'confinedFailure':failed.get('status') in {'failed','action_uncertain'}}))
finally: shutil.rmtree(target,ignore_errors=True)
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:90000});
assert.equal(result.status,0,result.stderr||result.stdout); const proof=JSON.parse(result.stdout.trim());
console.log(JSON.stringify(proof)); assert.equal(proof.firstOk,true); assert.equal(proof.operationStatus,'verified'); assert.equal(proof.contentMatches,true); assert.equal(proof.hashMatches,true); assert.equal(proof.confinedFailure,true); console.log(JSON.stringify({status:'verified',proof})); rmSync(root,{recursive:true,force:true});
