import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-wm-continuation-'));
try {
  const result = spawnSync(python, ['-c', String.raw`
import json,sys
from pathlib import Path
from grant_agent.context_engine import DurableContextEngine
from grant_agent.working_memory import WorkingMemoryStore
root=Path(sys.argv[1])
engine=DurableContextEngine(root,'continuation',max_context_tokens=4096,reserve_tokens=128,protect_recent_tokens=128)
goal=engine.append('user','Continue the release mission with exact route constraints.',kind='goal',source='user')
decision=engine.append('user','Use route luna; preserve NAS current and do not publish.',kind='decision',source='user')
correction=engine.append('user','Correction: the browser upload remains unverified; never call it complete.',kind='decision',source='user')
ordinary=engine.append('user','I am thinking aloud about the weather.',kind='message',source='user')
for i in range(50): engine.append('tool','noise '+str(i)+' '+'x'*200,kind='observation')
engine.compact(focus='resume exact constraints',target_ratio=.1)
fresh=DurableContextEngine(root,'continuation',max_context_tokens=4096,reserve_tokens=128,protect_recent_tokens=128)
bundle=fresh.build_bundle('route browser upload',token_budget=1400)
wm=bundle['workingMemory']; decisions=wm['records']['decisions']
all_state=WorkingMemoryStore(root,'continuation').snapshot()
persisted_decisions=all_state['decisions']
print(json.dumps({'goalPersisted':wm['objective']['text']==goal.content,'decisionsPersisted':len(persisted_decisions)>=2,'sourceRefs':all(bool(row.get('sourceRef','').startswith('ctx_')) for row in persisted_decisions),'correctionPersisted':any('remains unverified' in row['text'] for row in persisted_decisions),'ordinaryNotPromoted':all('weather' not in row.get('text','') for row in persisted_decisions),'reloadedRevision':fresh.working_memory.snapshot()['revision']==all_state['revision'],'retrievalPath':bool(wm['retrieval']['statePath']),'bundleMemory':'workingMemory' in bundle},separators=(',',':')))
`, root], {cwd: repo, env: {...process.env, PYTHONPATH: path.join(repo, 'src')}, encoding: 'utf8', timeout: 30000});
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  const checks = JSON.parse(result.stdout.trim());
  for (const [name, value] of Object.entries(checks)) assert.equal(value, true, name);
  console.log(JSON.stringify({status:'verified', checks}));
} finally { rmSync(root, {recursive:true, force:true}); }
