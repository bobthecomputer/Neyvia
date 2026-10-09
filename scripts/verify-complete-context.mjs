import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-full-context-'));
try {
  const child = spawnSync(resolveNeyviaPython(repo).python, ['-c', String.raw`
import json,sys
from pathlib import Path
from grant_agent.context_engine import estimate_tokens
from grant_agent.context_microkernel import ModelVisibleContext
from grant_agent.workspace_intelligence import WorkspaceIntelligence
root=Path(sys.argv[1]); facade=ModelVisibleContext(root,'complete',max_tokens=12000)
facade.record('user','Keep the dark palette. No animation. Do not deploy.',kind='contract')
facade.engine.working_memory.record_decision('The audience is individual makers.',source='user')
for i in range(20): facade.record('tool','diagnostic '+str(i)+' '+('noise '*500),kind='observation')
bundle=facade.bundle('landing page',token_budget=4000)
same=facade.bundle('landing page',token_budget=4000)
messages=facade.model_messages('landing page',token_budget=4000)
intelligence=WorkspaceIntelligence(root,'complete')
intelligence.configure_collaboration({'clarification':'thorough'},operator_identity='fixture-user',expected_revision=0)
changed=facade.bundle('landing page',token_budget=4000)
tiny=facade.bundle('landing page',token_budget=150)
failure=None
try: facade.model_messages('landing page',token_budget=150)
except ValueError as exc: failure=str(exc)
print(json.dumps({'bundle':bundle,'encodedEstimate':estimate_tokens(json.dumps(bundle,ensure_ascii=False,separators=(',',':'),sort_keys=True)),
                 'messages':messages,'sameKey':same['cache_key'],'changedKey':changed['cache_key'],'tiny':tiny,'failure':failure}))
`, root], {cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:30000});
  assert.equal(child.status,0,child.stderr || child.stdout);
  const result=JSON.parse(child.stdout.trim()); const bundle=result.bundle;
  assert.equal(bundle.estimated_tokens,result.encodedEstimate,'complete serialized estimate');
  assert.ok(bundle.estimated_tokens>bundle.ledger_estimated_tokens,'semantic state and framing counted');
  assert.ok(bundle.estimated_tokens<=bundle.token_budget,'optional observations fit the complete budget');
  assert.equal(bundle.contextBudget.exceeded,false);
  assert.equal(result.sameKey,bundle.cache_key,'clock changes alone must not invalidate the content cache');
  assert.notEqual(result.changedKey,bundle.cache_key,'preference change invalidates the cache');
  assert.ok(result.messages.some(row=>row.content.includes('Keep the dark palette. No animation. Do not deploy.')));
  assert.ok(result.messages.some(row=>row.content.includes('individual makers') && row.content.includes('workingMemory')),'actual model path carries saved semantic state');
  assert.equal(result.tiny.contextBudget.requiresRebudget,true);
  assert.match(result.failure,/Complete context requires/,'no silent small-context fallback');
  console.log(JSON.stringify({status:'verified',wholeBundleEstimatedTokens:bundle.estimated_tokens,ledgerEstimatedTokens:bundle.ledger_estimated_tokens,tokenBudget:bundle.token_budget,
    protectedContract:true,semanticStateDelivered:true,cacheInvalidation:true,overflowRefused:true,providerTokenMeasurement:false}));
} finally {rmSync(root,{recursive:true,force:true});}
