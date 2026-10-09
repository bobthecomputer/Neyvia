import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-working-memory-'));
try {
  const result = spawnSync(python, ['-c', String.raw`
import json,sys,subprocess
from pathlib import Path
from grant_agent.working_memory import WorkingMemoryStore
from grant_agent.context_engine import DurableContextEngine
root=Path(sys.argv[1]); m=WorkingMemoryStore(root,'mission-alpha')
m.set_objective('Ship a recoverable release with user-visible proof.',source='user')
m.record_decision('Preserve the previous release until verification passes.',source='user',scope='deployment')
m.record_hypothesis('The stale browser session caused the failed upload.',confidence=.7)
m.record_failure('upload-timeout',diagnosis='session detached',attempted='repeat click',recovery='create replacement tab')
first=m.record_observation('browser.session','detached',source='runtime'); second=m.record_observation('browser.session','attached',source='runtime')
other=m.record_observation('browser.session','unknown',source='human',source_ref='field-note')
m.add_evidence('artifacts/upload-receipt.json',sha256='a'*64,source='test',retrieval_path='artifacts/upload-receipt.json')
state=m.snapshot(); old=next(r for r in state['observations'] if r['recordId']==first['observations'][-1]['recordId']); projection=m.project('browser upload',token_budget=600)
latest=next(r for r in state['observations'] if r['recordId']==second['observations'][-1]['recordId']); human=next(r for r in state['observations'] if r['recordId']==other['observations'][-1]['recordId'])
found=m.find('browser.session',limit=10); retrieved=m.retrieve(human['recordId'])
probe='from grant_agent.working_memory import WorkingMemoryStore; import json,sys; print(json.dumps(WorkingMemoryStore(sys.argv[1],"mission-alpha").project("browser upload",token_budget=600)))'
reopened=json.loads(subprocess.check_output([sys.executable,'-c',probe,str(root)],text=True))
e=DurableContextEngine(root,'engine-mission',max_context_tokens=2048,reserve_tokens=128); e.append('user','Ship the release',kind='goal'); e.append('user','Preserve rollback',kind='decision'); e.append('tool','upload observed',kind='observation'); b=e.build_bundle('release',token_budget=900)
print(json.dumps({'stale':old['status']=='stale' and old['contradictedBy']==second['observations'][-1]['recordId'],'crossSourcePreserved':latest['status']=='active' and human['status']=='active' and human['recordId'] in latest['conflictsWith'],'findAndRetrieve':any(x['recordId']==human['recordId'] for x in found['handles']) and retrieved['recordSha256']==human['recordSha256'],'omittedHandles':all(x.get('recordId') and x.get('recordSha256') and x.get('retrievalPath') for x in projection['omitted']),'bounded':projection['omittedCount']>0,'freshRevision':reopened['revision']==projection['revision'],'freshHash':reopened['integritySha256']==projection['integritySha256'],'bundleMemory':'workingMemory' in b and 'workingMemoryRetrieval' in b},separators=(',',':')))
`, root], {cwd: repo, env: {...process.env, PYTHONPATH: path.join(repo, 'src')}, encoding: 'utf8', timeout: 30000});
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  const checks = JSON.parse(result.stdout.trim());
  for (const [name, value] of Object.entries(checks)) assert.equal(value, true, name);
  const evidence = 'WORKING_MEMORY_VERIFIED: ' + Object.keys(checks).join(', ');
  console.log(JSON.stringify({status:'verified', evidence, sha256:createHash('sha256').update(evidence).digest('hex')}));
} finally { rmSync(root, {recursive: true, force: true}); }
