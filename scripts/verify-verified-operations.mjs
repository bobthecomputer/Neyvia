import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-verified-ops-'));
try {
  const result = spawnSync(python, ['-c', String.raw`
import hashlib, json, sys
from pathlib import Path
from grant_agent.verified_operations import VerifiedOperationStore
root=Path(sys.argv[1]); artifact=root/'artifact.txt'; artifact.write_text('verified\n')
store=VerifiedOperationStore(root,'fixture')
checks={'authority':store.execute('denied','fixture',authority={'granted':False})['status']=='authority_required'}
count=root/'count'; count.write_text('0')
def effect(_): count.write_text(str(int(count.read_text())+1)); return {'changed':True,'artifacts':[str(artifact)]}
def before(_): return {'state':'old'}
def after(_): return {'state':'new'}
def verify(ctx): return ctx['after'].get('state')=='new' and ctx['effect'].get('changed') is True
first=store.execute('change-1','fixture',authority={'granted':True,'authorityId':'test'},preconditions=[lambda _: {'ok':True}],before=before,effect=effect,after=after,verify=verify)
checks['verified']=first['ok'] and first['status']=='verified' and count.read_text()=='1'
second=store.execute('change-1','fixture',authority={'granted':True},before=before,effect=lambda _: (_ for _ in ()).throw(AssertionError('replayed')),after=after,verify=verify)
checks['exactlyOnce']=second['status']=='duplicate_suppressed' and second['duplicateSuppressed'] and count.read_text()=='1'
checks['argumentHashConflict']=store.execute('change-1','other',authority={'granted':True})['status']=='operation_conflict'
checks['precondition']=store.execute('blocked','fixture',authority={'granted':True},preconditions=[lambda _: False],effect=effect,verify=verify)['status']=='precondition_failed'
bad=store.execute('bad-artifact','fixture',authority={'granted':True},effect=lambda _: {'changed':True},artifacts=[{'path':str(artifact),'sha256':'0'*64}],verify=lambda _: True)
checks['artifactMismatch']=bad['status']=='unknown_side_effects'
checks['falseHandler']=store.execute('bad-artifact','fixture',authority={'granted':True},effect=lambda _: (_ for _ in ()).throw(AssertionError('retry')),verify=lambda _: True)['status']=='unknown_side_effects'
calls=[]
def type_error_effect(_): calls.append(1); raise TypeError('effect failed')
checks['typeErrorRecovery']=store.execute('type-error','fixture',authority={'granted':True},effect=type_error_effect,verify=lambda _: True)['status']=='unknown_side_effects' and len(calls)==1
record=store.inspect('change-1'); result_path=Path(store._path('change-1')); result_path.write_text(result_path.read_text().replace('"resultHash":', '"resultHash":"tampered", "oldResultHash":', 1))
tampered=False
try: store.inspect('change-1')
except ValueError: tampered=True
checks['tamperRejected']=tampered
checks['revoked']=store.execute('denied-again','fixture',authority={'granted':False})['status']=='authority_required'
print(json.dumps(checks,separators=(',',':')))
`, root], {cwd:repo, env:{...process.env, PYTHONPATH:path.join(repo,'src')}, encoding:'utf8', timeout:90000});
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  const checks=JSON.parse(result.stdout.trim()); for(const [name,value] of Object.entries(checks)) assert.equal(value,true,name); console.log(JSON.stringify({status:'verified',checks}));
} finally { rmSync(root, {recursive:true, force:true}); }
