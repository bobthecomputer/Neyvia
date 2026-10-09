import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '..');
const code = String.raw`
import json
from grant_agent.connected_chat_context import context_from_events
event = {'type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':{'total_tokens':999999},'last_token_usage':{'total_tokens':12000},'model_context_window':200000}}}
print(json.dumps([
 context_from_events('codex',[event]),
 context_from_events('codex',[event,{'type':'compacted'}]),
 context_from_events('claude-code',[{'type':'assistant','message':{'usage':{'input_tokens':100,'cache_read_input_tokens':900,'cache_creation_input_tokens':200,'output_tokens':500}}}]),
 context_from_events('codex',[])
]))
`;
const r = spawnSync(path.join(root,'.venv/Scripts/python.exe'), ['-c',code], {cwd:root,encoding:'utf8',env:{...process.env,PYTHONPATH:path.join(root,'src')}});
assert.equal(r.status,0,r.stderr);
const [codex,compacted,claude,empty] = JSON.parse(r.stdout);
assert.equal(codex.usedTokens,12000); // Not cumulative billing usage.
assert.equal(codex.windowTokens,200000);
assert.equal(codex.compactionThresholdTokens,null);
assert.equal(compacted.usedTokens,null); // Don't show pre-compaction utilization.
assert.equal(claude.usedTokens,1200);
assert.equal(claude.windowTokens,null); // No guessed model window.
assert.equal(empty.usedTokens,null);
console.log('CONNECTED_CONTEXT_OK counters, cache accounting, compaction invalidation, unknown limits');
