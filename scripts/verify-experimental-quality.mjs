import assert from 'node:assert/strict';import {spawnSync} from 'node:child_process';import {mkdtempSync,rmSync} from 'node:fs';import {tmpdir} from 'node:os';import path from 'node:path';import {fileURLToPath} from 'node:url';import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),py=resolveNeyviaPython(repo).python,root=mkdtempSync(path.join(tmpdir(),'neyvia-quality-'));
try{const r=spawnSync(py,['-c',String.raw`
import json,sys
from pathlib import Path
from grant_agent.experimental_quality import ExperimentalQuality
r=Path(sys.argv[1]); q=ExperimentalQuality(r); base=r/'base.json'; cand=r/'cand.json'; base.write_text(json.dumps({'score':1})); cand.write_text(json.dumps({'score':9})); q.define_instrument('score',{'kind':'json_numeric','key':'score','max':5}); q.define_holdout('h',{'cases':['x']}); c=q.compare('score',base,cand); pending=q.challenge('h',{'case':'x'}); print(json.dumps({'regression':c['regression'],'rejected':c['status']=='rejected','pending':pending['status']=='pending_operator_promotion'}))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:90000});assert.equal(r.status,0,r.stderr||r.stdout);const p=JSON.parse(r.stdout.trim());assert.equal(p.regression,true);assert.equal(p.rejected,true);assert.equal(p.pending,true);console.log(JSON.stringify({status:'verified',proof:p}));}finally{rmSync(root,{recursive:true,force:true});}
