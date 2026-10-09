import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const result = spawnSync(resolveNeyviaPython(process.cwd()).python, ['-c', `
import json
from grant_agent.neyvia_conversations import NeyviaConversationStore as Store
text = 'Complete reply. ' * 2000
receipt = {'route': {'model': 'fixture', 'runtime': 'fixture'}}
row = {'turn_id':'t','conversation_id':'c','role':'assistant','content':text,'detail':text,
 'source':'fixture','turn_kind':'dialogue','meaningful':1,'created_at':'2026-09-28',
 'metadata_json':json.dumps({'runtimeResult':{'runtime':'fixture','route':receipt['route'],
 'compartment':{'turnReceipt':receipt,'messages':[{'text':'snapshot '*1000000}]},'toolTimeline':['trace '*1000000]}})}
projected = Store._history_turn_from_row(row)
assert projected['content'] == text and projected['detail'] == text
assert projected['metadata']['runtimeResult']['compartment']['turnReceipt'] == receipt
assert len(json.dumps(projected)) < 100000
assert len(json.dumps(Store._turn_from_row(row))) > 10000000
print(json.dumps({'passed':True,'historyBytes':len(json.dumps(projected)), 'rawDetailsPreserved':True,'fullTextPreserved':True}))
`], { env: { ...process.env, PYTHONPATH: path.resolve('src') }, encoding:'utf8', timeout:30000 });
assert.equal(result.status, 0, result.stderr);
console.log(result.stdout.trim());
