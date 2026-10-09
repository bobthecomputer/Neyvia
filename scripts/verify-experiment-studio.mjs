import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'); const python=resolveNeyviaPython(repo).python; const root=mkdtempSync(path.join(tmpdir(),'neyvia-studio-'));
try { const result=spawnSync(python,['-c',String.raw`
import json,sys
from pathlib import Path
from grant_agent.experiment_studio import ExperimentStudio
root=Path(sys.argv[1]); source=root/'source'; source.mkdir(); (source/'app.txt').write_text('v1'); (source/'.env').write_text('secret')
s=ExperimentStudio(root); created=s.create('exp-1',source=source,launch_recipe={'command':'echo launch'},reset_recipe={'command':'echo reset'},evidence_paths=['proof.json']); restored=s.restore('exp-1',root/'.agent_control'/'experiment_restores'/'r1'); (Path(created['snapshotPath'])/'app.txt').write_text('v2'); compared=s.compare('exp-1')
print(json.dumps({'created':created['ok'],'manifest':created['manifest']['sourceSha256'].get('app.txt') is not None,'secretExcluded':'.env' not in created['manifest']['snapshotSha256'],'restored':(Path(restored['restorePath'])/'app.txt').read_text()=='v1','changed':compared['status']=='changed'}))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:90000}); assert.equal(result.status,0,result.stderr||result.stdout); const proof=JSON.parse(result.stdout.trim()); assert.equal(proof.created,true); assert.equal(proof.manifest,true); assert.equal(proof.secretExcluded,true); assert.equal(proof.restored,true); assert.equal(proof.changed,true); console.log(JSON.stringify({status:'verified',proof})); } finally {rmSync(root,{recursive:true,force:true});}
